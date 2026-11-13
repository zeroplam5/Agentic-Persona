"""Big Five persona x Wild Ideas, pilot v2 (DRAFT - see PREREGISTRATION_v2_DRAFT.md).

Changes from v1 (decided 2026-11-12):
  * non-target traits are explicitly "Average" (categorical profile of all five traits)
  * two control conditions: ALL_AVG (all five Average) and CTRL (length/format-matched placebo profile)
  * provider APIs (OpenAI / Gemini) instead of the Claude Code CLI, so temperature and
    reasoning/thinking are set explicitly and recorded
  * representative composite = 100 x (0.5 x norm(novelty) + 0.5 x norm(usefulness)); harmonic is secondary

Subcommands:
  python pilot2.py smoke      # 1 generation + 1 judge call, written to logs/smoke_test.jsonl only (not data)
  python pilot2.py setup | generate | manip | judge | diversity | human
  Analysis/report: PILOT_MODULE=pilot2 ... python ../pilot_v1/report.py  (see README)

API keys are read from the project .env (OPENAI_API_KEY, GEMINI_API_KEY) and never printed or logged.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "prompts"
DATA = ROOT / "data"
LOGS = ROOT / "logs"
RESULTS = ROOT / "results"
HUMAN = ROOT / "human_eval"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SEED = CONFIG["seed"]

TRAITS = {"O": "Openness to Experience", "C": "Conscientiousness", "E": "Extraversion",
          "A": "Agreeableness", "N": "Neuroticism"}
REFERENCE_CONDITIONS = ["BASE", "ALL_AVG", "CTRL"]
CONDITIONS = REFERENCE_CONDITIONS + [f"{t}_{lv}" for t in TRAITS for lv in ("H", "L")]
# report.py uses these: primary reference for trait effects, plus extra contrasts to show
PRIMARY_REF = "ALL_AVG"
EXTRA_CONTRASTS = [("ALL_AVG", "BASE"), ("CTRL", "BASE"), ("ALL_AVG", "CTRL")]

_lock = threading.Lock()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_text(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8").strip("\n")


def load_env() -> dict:
    """Minimal .env reader (tolerates spaces around '=' and quotes). Values are never printed."""
    env = {}
    p = (ROOT / CONFIG["env_file"]).resolve()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = load_env()


# ------------------------------------------------------------------ conditions
def profile_block(cond: str) -> str | None:
    fmt = CONFIG["condition_format"]
    if cond == "BASE":
        return None
    if cond == "CTRL":
        return fmt["placebo_text"]
    levels = {t: "Average" for t in TRAITS}
    if cond != "ALL_AVG":
        t, lv = cond.split("_")
        levels[t] = "High" if lv == "H" else "Low"
    return fmt["template"].format(**levels)


def system_prompt(cond: str) -> str:
    base = read_text("original_system_prompt.txt")
    p = profile_block(cond)
    return base if p is None else f"{p}\n\n{base}"


# ------------------------------------------------------------------ io helpers
def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def append_jsonl(path: Path, rec: dict) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ providers
def _post(url: str, headers: dict, body: dict, timeout=180) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:500]
    except Exception as e:  # network/timeout
        return -1, f"{type(e).__name__}: {str(e)[:300]}"


def call_openai(spec: dict, system: str, user: str) -> dict:
    body = {"model": spec["model"], "temperature": spec["temperature"], "max_tokens": spec["max_output_tokens"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    st, j = _post("https://api.openai.com/v1/chat/completions", {"Authorization": "Bearer " + ENV["OPENAI_API_KEY"]}, body)
    if st != 200 or not isinstance(j, dict):
        return {"ok": False, "error": f"http {st}: {j}", "request_params": {k: v for k, v in body.items() if k != "messages"}}
    ch = j["choices"][0]
    return {"ok": bool(ch["message"].get("content")), "text": (ch["message"].get("content") or "").strip(),
            "finish_reason": ch.get("finish_reason"), "model_returned": j.get("model"),
            "system_fingerprint": j.get("system_fingerprint"), "response_id": j.get("id"), "usage": j.get("usage"),
            "request_params": {k: v for k, v in body.items() if k != "messages"}}


def call_gemini(spec: dict, system: str, user: str) -> dict:
    gen = {"temperature": spec["temperature"], "maxOutputTokens": spec["max_output_tokens"]}
    if "thinking_budget" in spec:
        gen["thinkingConfig"] = {"thinkingBudget": spec["thinking_budget"]}
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": gen}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{spec['model']}:generateContent"
    st, j = _post(url, {"x-goog-api-key": ENV["GEMINI_API_KEY"]}, body)
    if st != 200 or not isinstance(j, dict):
        return {"ok": False, "error": f"http {st}: {j}", "request_params": {"model": spec["model"], **gen}}
    cands = j.get("candidates") or []
    parts = (cands[0].get("content") or {}).get("parts", []) if cands else []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    return {"ok": bool(text), "text": text, "finish_reason": cands[0].get("finishReason") if cands else None,
            "model_returned": j.get("modelVersion"), "response_id": j.get("responseId"), "usage": j.get("usageMetadata"),
            "request_params": {"model": spec["model"], **gen},
            **({} if text else {"error": f"empty response: {json.dumps(j)[:300]}"})}


def call(spec: dict, system: str, user: str, validate=None) -> dict:
    fn = {"openai": call_openai, "gemini": call_gemini}[spec["provider"]]
    attempts = []
    for _ in range(1 + CONFIG["max_retries"]):
        t0 = time.time()
        r = {"started": now(), **fn(spec, system, user)}
        r["elapsed_s"] = round(time.time() - t0, 2)
        if r.get("ok") and validate is not None:
            v = validate(r["text"])
            if v is None:
                r.update(ok=False, error="validation failed (unparseable output)")
            else:
                r["parsed"] = v
        attempts.append(r)
        if r.get("ok"):
            break
        time.sleep(5)
    final = dict(attempts[-1])
    final["provider"] = spec["provider"]
    final["n_attempts"] = len(attempts)
    final["failed_attempts"] = [{k: a.get(k) for k in ("started", "error", "text")} for a in attempts[:-1]]
    return final


def run_pool(tasks, fn, label):
    if not tasks:
        print(f"[{label}] nothing to do")
        return
    print(f"[{label}] {len(tasks)} calls, workers={CONFIG['workers']}", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=CONFIG["workers"]) as ex:
        for fu in as_completed([ex.submit(fn, t) for t in tasks]):
            fu.result()
            done += 1
            if done % 25 == 0 or done == len(tasks):
                print(f"[{label}] {done}/{len(tasks)}", flush=True)


# ------------------------------------------------------------------ parsers (same as v1)
def parse_judge(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
        n, u = int(j["novelty"]), int(j["usefulness"])
    except Exception:
        return None
    if not (1 <= n <= 5 and 1 <= u <= 5):
        return None
    return {"novelty": n, "usefulness": u, "novelty_reason": j.get("novelty_reason"), "usefulness_reason": j.get("usefulness_reason")}


def parse_ipip(text: str):
    d = {}
    for n, v in re.findall(r"(?m)^\s*(\d{1,2})\s*[:.)=-]\s*([1-5])\b", text):
        n = int(n)
        if 1 <= n <= 50 and n not in d:
            d[n] = int(v)
    return d if len(d) == 50 else None


def ipip_user_prompt() -> str:
    ip = json.loads((PROMPTS / "ipip50.json").read_text(encoding="utf-8"))
    lines = [f"{it['n']}. I {it['text'][0].lower()}{it['text'][1:]}" for it in ip["items"]]
    return ("For this one request only, set aside the single-sentence formatting rule and complete a short "
            "self-description questionnaire about yourself.\nRate how accurately each statement describes you on this scale: "
            + ip["scale"] + ".\nAnswer every item. Output only lines of the form `number: rating` (for example `1: 3`), "
            "one per line, nothing else.\n\n" + "\n".join(lines))


# ------------------------------------------------------------------ commands
def cmd_smoke():
    LOGS.mkdir(exist_ok=True)
    out = LOGS / "smoke_test.jsonl"
    g = call(CONFIG["generator"], system_prompt("O_H"), read_text("wild_ideas_user_prompt.txt").replace("[BRAND]", "Lego"))
    append_jsonl(out, {"phase": "smoke-generate", "condition": "O_H", "brand": "Lego", **g})
    print("generate:", g.get("ok"), g.get("model_returned"), g.get("usage"), "|", (g.get("text") or g.get("error"))[:200])
    if g.get("ok"):
        up = read_text("judge_prompt.txt").replace("[BRAND]", "Lego").replace("[IDEA]", g["text"])
        j = call(CONFIG["judge"], read_text("judge_system_prompt.txt"), up, validate=parse_judge)
        append_jsonl(out, {"phase": "smoke-judge", **j})
        print("judge:", j.get("ok"), j.get("model_returned"), j.get("parsed"), j.get("usage"), j.get("error"))
    alt = CONFIG["generator"].get("_alternative")  # optional; none configured after the 2026-11-12 smoke test
    if alt:
        a = call(alt, system_prompt("BASE"), read_text("wild_ideas_user_prompt.txt").replace("[BRAND]", "Lego"))
        append_jsonl(out, {"phase": "smoke-generate-alternative", "condition": "BASE", "brand": "Lego", **a})
        print("alt generate:", a.get("ok"), a.get("model_returned"), a.get("usage"), "|", (a.get("text") or a.get("error"))[:200])


def cmd_setup():
    LOGS.mkdir(exist_ok=True)
    rng = random.Random(SEED)
    cats = CONFIG["brand_table_appendix_A2"]
    chosen = rng.sample(list(cats), CONFIG["n_brands"])
    brands = [{"category": c, "brand": rng.choice(cats[c])} for c in chosen]
    plan = [{"gen_id": f"{b['brand']}|{c}|{r}", "brand": b["brand"], "category": b["category"], "condition": c, "rep": r}
            for b in brands for c in CONDITIONS for r in range(CONFIG["reps"])]
    rng.shuffle(plan)
    (LOGS / "brands.json").write_text(json.dumps(brands, indent=2, ensure_ascii=False), encoding="utf-8")
    (LOGS / "generation_plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    (LOGS / "condition_prompts.json").write_text(json.dumps(
        {c: {"profile_block": profile_block(c), "system_prompt": system_prompt(c)} for c in CONDITIONS}, indent=2, ensure_ascii=False), encoding="utf-8")
    files = [ROOT / "PREREGISTRATION_v2_DRAFT.md", ROOT / "config.json", *sorted(PROMPTS.iterdir())]
    (LOGS / "prereg_hash.txt").write_text(f"recorded_at: {now()}\n" + "".join(
        f"{f.relative_to(ROOT)} sha256: {hashlib.sha256(f.read_bytes()).hexdigest()}\n" for f in files if f.exists()), encoding="utf-8")
    print("brands:", [b["brand"] for b in brands], "| plan:", len(plan), "calls")


def cmd_generate():
    plan = json.loads((LOGS / "generation_plan.json").read_text(encoding="utf-8"))
    out = DATA / "generations.jsonl"
    done = {r["gen_id"] for r in load_jsonl(out) if r.get("ok")}
    tpl = read_text("wild_ideas_user_prompt.txt")
    spec = CONFIG["generator"]

    def work(p):
        sp, up = system_prompt(p["condition"]), tpl.replace("[BRAND]", p["brand"])
        append_jsonl(out, {**p, "phase": "generate", "system_prompt": sp, "user_prompt": up, **call(spec, sp, up)})

    run_pool([p for p in plan if p["gen_id"] not in done], work, "generate")


def cmd_manip():
    out = DATA / "manipulation_check.jsonl"
    done = {r["mc_id"] for r in load_jsonl(out) if r.get("ok")}
    rng = random.Random(SEED + 1)
    tasks = [{"mc_id": f"{c}|{r}", "condition": c, "rep": r} for c in CONDITIONS for r in range(CONFIG["manip_reps"])]
    rng.shuffle(tasks)
    up = ipip_user_prompt()
    spec = {**CONFIG["generator"], "max_output_tokens": 600}

    def work(t):
        sp = system_prompt(t["condition"])
        r = call(spec, sp, up, validate=parse_ipip)
        if "parsed" in r:
            r["parsed"] = {str(k): v for k, v in sorted(r["parsed"].items())}
        append_jsonl(out, {**t, "phase": "manip", "system_prompt": sp, "user_prompt": up, **r})

    run_pool([t for t in tasks if t["mc_id"] not in done], work, "manip")


def cmd_judge():
    gens = {g["gen_id"]: g for g in load_jsonl(DATA / "generations.jsonl") if g.get("ok")}
    out = DATA / "judgments.jsonl"
    done = {(r["gen_id"], r["pass"]) for r in load_jsonl(out) if r.get("ok")}
    rng = random.Random(SEED + 2)
    ids = sorted(gens)
    p1 = ids[:]
    rng.shuffle(p1)
    p2 = rng.sample(ids, round(len(ids) * CONFIG["judge_retest_fraction"]))
    tpl, sp, spec = read_text("judge_prompt.txt"), read_text("judge_system_prompt.txt"), CONFIG["judge"]

    def work(t):
        g = gens[t["gen_id"]]
        up = tpl.replace("[BRAND]", g["brand"]).replace("[IDEA]", g["text"])
        r = call(spec, sp, up, validate=parse_judge)
        append_jsonl(out, {**t, "phase": "judge", "brand": g["brand"], "condition": g["condition"], "rep": g["rep"],
                           "idea": g["text"], "system_prompt": sp, "user_prompt": up, **r})

    run_pool([{"gen_id": i, "pass": 1} for i in p1 if (i, 1) not in done], work, "judge-pass1")
    run_pool([{"gen_id": i, "pass": 2} for i in p2 if (i, 2) not in done], work, "judge-pass2")


STOP = set("a an the and or of to in on for with by at from as is are be it its this that into your you their they them who "
           "what which where when while than then so but not no if every each".split())


def cmd_diversity():
    """TF-IDF here; bge embeddings via ../pilot_v1/embed_bge.py --root pilot_v2 (see README)."""
    import numpy as np
    gens = {g["gen_id"]: g for g in load_jsonl(DATA / "generations.jsonl") if g.get("ok")}
    ids = sorted(gens)
    docs = [[w for w in re.findall(r"[a-z0-9']+", gens[i]["text"].lower()) if w not in STOP] for i in ids]
    vocab = {w: k for k, w in enumerate(sorted({w for d in docs for w in d}))}
    df = np.zeros(len(vocab))
    for d in docs:
        for w in set(d):
            df[vocab[w]] += 1
    T = np.zeros((len(docs), len(vocab)))
    for k, d in enumerate(docs):
        for w in d:
            T[k, vocab[w]] += 1
    T *= np.log((1 + len(docs)) / (1 + df)) + 1
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
    E = None
    ep = DATA / "embeddings_bge_large_en_v1.5.npz"
    if ep.exists():
        z = np.load(ep, allow_pickle=True)
        idx = {k: n for n, k in enumerate(z["ids"].tolist())}
        E = np.stack([z["vectors"][idx[i]] for i in ids])
        E /= np.linalg.norm(E, axis=1, keepdims=True)

    def mpd(V):
        S = V @ V.T
        iu = np.triu_indices(len(V), 1)
        return float(np.mean(1 - S[iu]))

    cells = defaultdict(list)
    for k, i in enumerate(ids):
        cells[(gens[i]["brand"], gens[i]["condition"])].append(k)
    rows = []
    for (b, c), ks in sorted(cells.items()):
        row = {"brand": b, "condition": c, "n": len(ks), "tfidf_div": mpd(T[ks]) if len(ks) > 1 else None}
        if E is not None:
            row["bge_div"] = mpd(E[ks]) if len(ks) > 1 else None
        rows.append(row)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "diversity_cells.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"diversity: {len(rows)} cells; bge {'used' if E is not None else 'missing -> run embed_bge first'}")


def cmd_human():
    """Blinded sample: no condition, no LLM score. Key stored separately."""
    gens = list({g["gen_id"]: g for g in load_jsonl(DATA / "generations.jsonl") if g.get("ok")}.values())
    rng = random.Random(SEED + 3)
    by = defaultdict(list)
    for g in gens:
        by[(g["condition"], g["brand"])].append(g)
    brands = sorted({g["brand"] for g in gens})
    k_per = CONFIG["human_per_condition"]
    items = []
    for c in CONDITIONS:
        pool_b = brands[:]
        rng.shuffle(pool_b)
        picked = [rng.choice(by[(c, b)]) for b in pool_b[:k_per] if by[(c, b)]]
        rng.shuffle(picked)
        items += [{"g": g, "set": "calibration" if n < CONFIG["human_calibration_per_condition"] else "test"} for n, g in enumerate(picked)]
    rng.shuffle(items)
    blind = ROOT.parent.parent / "human_rating_blind_v2"
    keydir = HUMAN / "_key_DO_NOT_OPEN_until_rating_done"
    blind.mkdir(exist_ok=True)
    keydir.mkdir(parents=True, exist_ok=True)
    with (blind / "rating_sheet.csv").open("w", newline="", encoding="utf-8-sig") as f, \
         (keydir / "key.csv").open("w", newline="", encoding="utf-8-sig") as kf:
        w, kw = csv.writer(f), csv.writer(kf)
        w.writerow(["item_id", "set", "brand", "idea", "novelty_1to5", "usefulness_1to5", "new_to_me_yes_no", "comment"])
        kw.writerow(["item_id", "gen_id", "condition", "brand", "rep"])
        for n, it in enumerate(items, 1):
            g = it["g"]
            w.writerow([f"V2-{n:03d}", it["set"], g["brand"], g["text"], "", "", "", ""])
            kw.writerow([f"V2-{n:03d}", g["gen_id"], g["condition"], g["brand"], g["rep"]])
    (blind / "my_prior_ideas.csv").write_text("brand,my_existing_idea_or_known_campaign\n" + "".join(f"{b},\n" for b in brands), encoding="utf-8-sig")
    print(f"human package: {len(items)} items -> {blind} (key -> {keydir})")


# ------------------------------------------------------------------ used by ../pilot_v1/report.py
def bootstrap_brand_diff(per_brand, n_boot=10000, seed=SEED):
    rng = random.Random(seed)
    diffs = [per_brand[b][0] - per_brand[b][1] for b in sorted(per_brand)]
    est = sum(diffs) / len(diffs)
    boots = sorted(sum(diffs[rng.randrange(len(diffs))] for _ in diffs) / len(diffs) for _ in range(n_boot))
    return est, boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1], sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)


def manip_summary() -> dict:
    recs = [r for r in load_jsonl(DATA / "manipulation_check.jsonl") if r.get("ok")]
    if not recs:
        return {}
    ip = json.loads((PROMPTS / "ipip50.json").read_text(encoding="utf-8"))["items"]
    res = defaultdict(lambda: defaultdict(list))
    for r in recs:
        ans = {int(k): v for k, v in r["parsed"].items()}
        for t in TRAITS:
            items = [it for it in ip if it["trait"] == t]
            res[r["condition"]][t].append(sum(ans[it["n"]] if it["key"] == 1 else 6 - ans[it["n"]] for it in items) / len(items))
    out = {c: {t: sum(v) / len(v) for t, v in d.items()} | {"n_runs": len(next(iter(d.values())))} for c, d in res.items()}
    ref = PRIMARY_REF if PRIMARY_REF in out else "BASE"
    for c in out:
        if c in REFERENCE_CONDITIONS:
            continue
        t = c.split("_")[0]
        out[c]["target_change_vs_base"] = out[c][t] - out[ref][t]
        out[c]["mean_abs_offtarget_change_vs_base"] = sum(abs(out[c][o] - out[ref][o]) for o in TRAITS if o != t) / 4
    out["_reference"] = ref
    return out


if __name__ == "__main__":
    cmds = {"smoke": cmd_smoke, "setup": cmd_setup, "generate": cmd_generate, "manip": cmd_manip,
            "judge": cmd_judge, "diversity": cmd_diversity, "human": cmd_human}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]]()
