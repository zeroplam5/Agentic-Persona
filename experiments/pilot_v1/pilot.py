"""Big Five persona x Wild Ideas pilot (v1).

Subcommands (run in order):
  python pilot.py setup       # pick brands, build call plan, hash pre-registration
  python pilot.py generate    # 330 idea generations (resumable)
  python pilot.py manip       # IPIP-50 manipulation check, 33 calls (resumable)
  python pilot.py judge       # blinded LLM judging + 20% retest (resumable)
  python pilot.py diversity   # TF-IDF diversity (+ reads bge embeddings if present)
  python pilot.py analyze     # tables -> results/
  python pilot.py human       # blinded human-rating package -> human_eval/

All model calls go through the Claude Code CLI (`claude -p`) with the system
prompt fully replaced, no tools, no MCP, no session persistence.
See PREREGISTRATION.md for the design.
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
import subprocess
import sys
import tempfile
import threading
import time
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

TRAITS = {
    "O": "Openness to Experience",
    "C": "Conscientiousness",
    "E": "Extraversion",
    "A": "Agreeableness",
    "N": "Neuroticism",
}
CONDITIONS = ["BASE"] + [f"{t}_{lv}" for t in TRAITS for lv in ("H", "L")]

_lock = threading.Lock()
_cost = {"total": 0.0}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_text(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8").strip("\n")


def persona_sentence(cond: str) -> str | None:
    if cond == "BASE":
        return None
    t, lv = cond.split("_")
    level = "High" if lv == "H" else "Low"
    # Kao & Volkova (CEUR Vol-4178 paper6) wording, verbatim.
    return f"You have {level} {TRAITS[t]}."


def system_prompt(cond: str) -> str:
    base = read_text("original_system_prompt.txt")
    p = persona_sentence(cond)
    return base if p is None else f"{p}\n\n{base}"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def append_jsonl(path: Path, rec: dict) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Model call
# --------------------------------------------------------------------------
def call_claude(system: str, user: str, model: str) -> dict:
    """One isolated CLI call. Returns a dict with raw CLI JSON and timing."""
    workdir = Path(CONFIG["isolated_cwd"])
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", dir=workdir) as f:
        f.write(system)
        sys_path = f.name
    cmd = [
        CONFIG["claude_cli"], "-p",
        "--system-prompt-file", sys_path,
        "--tools", "",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--output-format", "json",
        "--model", model,
        "--max-budget-usd", str(CONFIG["per_call_budget_usd"]),
    ]
    env = dict(os.environ)
    env.update(CONFIG["cli_env"])
    t0 = time.time()
    started = now()
    try:
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True,
                              encoding="utf-8", cwd=workdir, env=env, timeout=240)
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, rc = "", "timeout", -1
    finally:
        try:
            os.unlink(sys_path)
        except OSError:
            pass
    rec = {"started": started, "elapsed_s": round(time.time() - t0, 2), "returncode": rc}
    try:
        j = json.loads(stdout)
    except Exception:
        rec.update(ok=False, error=f"non-JSON stdout: {stdout[:300]!r} stderr: {stderr[:300]!r}")
        return rec
    text = (j.get("result") or "").strip()
    err = None
    if j.get("is_error") or text.startswith("API Error") or not text:
        err = f"cli error: subtype={j.get('subtype')} result={text[:300]!r}"
    rec.update(
        ok=err is None,
        error=err,
        text=text,
        stop_reason=j.get("stop_reason"),
        usage=j.get("usage"),
        model_usage=j.get("modelUsage"),
        total_cost_usd=j.get("total_cost_usd"),
        session_id=j.get("session_id"),
    )
    with _lock:
        _cost["total"] += float(j.get("total_cost_usd") or 0.0)
    return rec


def call_with_retry(system: str, user: str, model: str, validate=None) -> dict:
    attempts = []
    for _ in range(1 + CONFIG["max_retries"]):
        if _cost["total"] > CONFIG["total_budget_usd"]:
            attempts.append({"ok": False, "error": "budget cap reached; not called"})
            break
        r = call_claude(system, user, model)
        if r.get("ok") and validate is not None:
            v = validate(r["text"])
            if v is None:
                r["ok"] = False
                r["error"] = "validation failed (unparseable output)"
            else:
                r["parsed"] = v
        attempts.append(r)
        if r.get("ok"):
            break
        time.sleep(3)
    final = dict(attempts[-1])
    final["n_attempts"] = len(attempts)
    final["failed_attempts"] = [
        {k: a.get(k) for k in ("started", "error", "text", "total_cost_usd")} for a in attempts[:-1]
    ]
    final["attempts_cost_usd"] = sum(float(a.get("total_cost_usd") or 0) for a in attempts)
    return final


def run_pool(tasks, fn, label: str) -> None:
    n = len(tasks)
    if n == 0:
        print(f"[{label}] nothing to do")
        return
    print(f"[{label}] {n} calls, workers={CONFIG['workers']}", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=CONFIG["workers"]) as ex:
        futs = [ex.submit(fn, t) for t in tasks]
        for fu in as_completed(futs):
            fu.result()
            done += 1
            if done % 20 == 0 or done == n:
                print(f"[{label}] {done}/{n}  cumulative cost (this process) ${_cost['total']:.3f}", flush=True)


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------
def cmd_setup() -> None:
    LOGS.mkdir(exist_ok=True)
    rng = random.Random(SEED)
    cats = CONFIG["brand_table_appendix_A2"]
    names = list(cats.keys())
    chosen_cats = rng.sample(names, CONFIG["n_brands"])
    brands = [{"category": c, "brand": rng.choice(cats[c])} for c in chosen_cats]
    (LOGS / "brands.json").write_text(json.dumps(brands, indent=2, ensure_ascii=False), encoding="utf-8")

    plan = []
    for b in brands:
        for c in CONDITIONS:
            for r in range(CONFIG["reps"]):
                plan.append({"gen_id": f"{b['brand']}|{c}|{r}", "brand": b["brand"], "category": b["category"],
                             "condition": c, "rep": r})
    rng.shuffle(plan)
    (LOGS / "generation_plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")

    h = hashlib.sha256((ROOT / "PREREGISTRATION.md").read_bytes()).hexdigest()
    ph = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(PROMPTS.iterdir())}
    (LOGS / "prereg_hash.txt").write_text(
        f"recorded_at: {now()}\nPREREGISTRATION.md sha256: {h}\n" +
        "".join(f"prompts/{k} sha256: {v}\n" for k, v in ph.items()), encoding="utf-8")

    cond_prompts = {c: {"persona_sentence": persona_sentence(c), "system_prompt": system_prompt(c)} for c in CONDITIONS}
    (LOGS / "condition_prompts.json").write_text(json.dumps(cond_prompts, indent=2, ensure_ascii=False), encoding="utf-8")
    print("brands:", brands)
    print("plan size:", len(plan))


# --------------------------------------------------------------------------
# generate
# --------------------------------------------------------------------------
def cmd_generate() -> None:
    plan = json.loads((LOGS / "generation_plan.json").read_text(encoding="utf-8"))
    out = DATA / "generations.jsonl"
    done = {r["gen_id"] for r in load_jsonl(out) if r.get("ok")}
    todo = [p for p in plan if p["gen_id"] not in done]
    user_tpl = read_text("wild_ideas_user_prompt.txt")
    model = CONFIG["generator_model"]

    def work(p):
        sp = system_prompt(p["condition"])
        up = user_tpl.replace("[BRAND]", p["brand"])
        r = call_with_retry(sp, up, model)
        rec = {**p, "phase": "generate", "model_requested": model, "system_prompt": sp, "user_prompt": up, **r}
        append_jsonl(out, rec)

    run_pool(todo, work, "generate")


# --------------------------------------------------------------------------
# manipulation check (IPIP-50)
# --------------------------------------------------------------------------
def ipip_user_prompt() -> str:
    ip = json.loads((PROMPTS / "ipip50.json").read_text(encoding="utf-8"))
    lines = [f"{it['n']}. I {it['text'][0].lower()}{it['text'][1:]}" for it in ip["items"]]
    return (
        "For this one request only, set aside the single-sentence formatting rule and complete a short "
        "self-description questionnaire about yourself.\n"
        "Rate how accurately each statement describes you on this scale: " + ip["scale"] + ".\n"
        "Answer every item. Output only lines of the form `number: rating` (for example `1: 3`), "
        "one per line, nothing else.\n\n" + "\n".join(lines)
    )


def parse_ipip(text: str):
    pairs = re.findall(r"(?m)^\s*(\d{1,2})\s*[:.)=-]\s*([1-5])\b", text)
    d = {}
    for n, v in pairs:
        n = int(n)
        if 1 <= n <= 50 and n not in d:
            d[n] = int(v)
    return d if len(d) == 50 else None


def cmd_manip() -> None:
    out = DATA / "manipulation_check.jsonl"
    done = {r["mc_id"] for r in load_jsonl(out) if r.get("ok")}
    rng = random.Random(SEED + 1)
    tasks = [{"mc_id": f"{c}|{r}", "condition": c, "rep": r}
             for c in CONDITIONS for r in range(CONFIG["manip_reps"])]
    rng.shuffle(tasks)
    tasks = [t for t in tasks if t["mc_id"] not in done]
    up = ipip_user_prompt()
    model = CONFIG["generator_model"]

    def work(t):
        sp = system_prompt(t["condition"])
        r = call_with_retry(sp, up, model, validate=parse_ipip)
        if "parsed" in r:
            r["parsed"] = {str(k): v for k, v in sorted(r["parsed"].items())}
        append_jsonl(out, {**t, "phase": "manip", "model_requested": model, "system_prompt": sp, "user_prompt": up, **r})

    run_pool(tasks, work, "manip")


# --------------------------------------------------------------------------
# judge
# --------------------------------------------------------------------------
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
    return {"novelty": n, "usefulness": u,
            "novelty_reason": j.get("novelty_reason"), "usefulness_reason": j.get("usefulness_reason")}


def cmd_judge() -> None:
    gens = [g for g in load_jsonl(DATA / "generations.jsonl") if g.get("ok")]
    gens = {g["gen_id"]: g for g in gens}  # last successful record per id
    out = DATA / "judgments.jsonl"
    done = {(r["gen_id"], r["pass"]) for r in load_jsonl(out) if r.get("ok")}
    rng = random.Random(SEED + 2)
    ids = sorted(gens)
    p1 = ids[:]
    rng.shuffle(p1)
    n_retest = round(len(ids) * CONFIG["judge_retest_fraction"])
    p2 = rng.sample(ids, n_retest)
    rng.shuffle(p2)
    tasks = [{"gen_id": i, "pass": 1} for i in p1] + [{"gen_id": i, "pass": 2} for i in p2]
    tasks = [t for t in tasks if (t["gen_id"], t["pass"]) not in done]
    tpl = read_text("judge_prompt.txt")
    sp = read_text("judge_system_prompt.txt")
    model = CONFIG["judge_model"]

    def work(t):
        g = gens[t["gen_id"]]
        up = tpl.replace("[BRAND]", g["brand"]).replace("[IDEA]", g["text"])
        r = call_with_retry(sp, up, model, validate=parse_judge)
        # The judge never sees the condition; we store it here only for analysis.
        append_jsonl(out, {**t, "phase": "judge", "model_requested": model, "brand": g["brand"],
                           "condition": g["condition"], "rep": g["rep"], "idea": g["text"],
                           "system_prompt": sp, "user_prompt": up, **r})

    # pass-1 first, then pass-2 (so retest is separated in time)
    run_pool([t for t in tasks if t["pass"] == 1], work, "judge-pass1")
    run_pool([t for t in tasks if t["pass"] == 2], work, "judge-pass2")


# --------------------------------------------------------------------------
# helpers for analysis
# --------------------------------------------------------------------------
STOP = set("a an the and or of to in on for with by at from as is are be it its this that into your you their"
           " they them who what which where when while than then so but not no if every each".split())


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in STOP]


def tfidf_vectors(texts: list[str]):
    import numpy as np
    docs = [tokens(t) for t in texts]
    vocab = {w: i for i, w in enumerate(sorted({w for d in docs for w in d}))}
    df = np.zeros(len(vocab))
    for d in docs:
        for w in set(d):
            df[vocab[w]] += 1
    idf = np.log((1 + len(docs)) / (1 + df)) + 1
    M = np.zeros((len(docs), len(vocab)))
    for i, d in enumerate(docs):
        for w in d:
            M[i, vocab[w]] += 1
    M = M * idf
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-12
    return M


def mean_pairwise_cos_dist(V) -> float:
    import numpy as np
    S = V @ V.T
    n = len(V)
    iu = np.triu_indices(n, 1)
    return float(np.mean(1 - S[iu]))


def format_checks(text: str) -> dict:
    words = len(text.split())
    enders = re.findall(r"[.!?]+(?=[\"')\]]*(\s|$))", text)
    return {
        "words": words,
        "under_50_words": words < 50,
        "n_sentence_enders": len(enders),
        "single_sentence": len(enders) <= 1,
        "has_markdown_or_list": bool(re.search(r"(^\s*[-*\d]+[.)]\s)|\*\*|#", text, re.M)),
        "ends_with_punct": bool(re.search(r"[.!?][\"')\]]*$", text)),
    }


def cmd_diversity() -> None:
    import numpy as np
    gens = {g["gen_id"]: g for g in load_jsonl(DATA / "generations.jsonl") if g.get("ok")}
    ids = sorted(gens)
    texts = [gens[i]["text"] for i in ids]
    T = tfidf_vectors(texts)
    emb_path = DATA / "embeddings_bge_large_en_v1.5.npz"
    E = None
    if emb_path.exists():
        z = np.load(emb_path, allow_pickle=True)
        idx = {k: i for i, k in enumerate(z["ids"].tolist())}
        E = np.stack([z["vectors"][idx[i]] for i in ids])
        E = E / np.linalg.norm(E, axis=1, keepdims=True)
    cells = defaultdict(list)
    for k, i in enumerate(ids):
        cells[(gens[i]["brand"], gens[i]["condition"])].append(k)
    rows = []
    for (b, c), ks in sorted(cells.items()):
        row = {"brand": b, "condition": c, "n": len(ks), "tfidf_div": mean_pairwise_cos_dist(T[ks]) if len(ks) > 1 else None}
        if E is not None:
            row["bge_div"] = mean_pairwise_cos_dist(E[ks]) if len(ks) > 1 else None
        rows.append(row)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "diversity_cells.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"diversity: {len(rows)} cells; bge embeddings {'used' if E is not None else 'NOT available (TF-IDF only)'}")


def bootstrap_brand_diff(per_brand: dict[str, tuple[float, float]], n_boot=10000, seed=SEED):
    """per_brand: brand -> (cond_mean, ref_mean). Returns mean diff and 95% percentile CI over brands."""
    rng = random.Random(seed)
    brands = sorted(per_brand)
    diffs = [per_brand[b][0] - per_brand[b][1] for b in brands]
    est = sum(diffs) / len(diffs)
    boots = []
    for _ in range(n_boot):
        s = [diffs[rng.randrange(len(diffs))] for _ in diffs]
        boots.append(sum(s) / len(s))
    boots.sort()
    return est, boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1], sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)


def comp_mean(n: int, u: int) -> float:
    N, U = (n - 1) / 4, (u - 1) / 4
    return 100 * (N + U) / 2


def comp_harm(n: int, u: int) -> float:
    N, U = (n - 1) / 4, (u - 1) / 4
    return 0.0 if N + U == 0 else 100 * 2 * N * U / (N + U)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    xs = [x for x in xs if x is not None]
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else float("nan")


def cmd_analyze() -> None:
    RESULTS.mkdir(exist_ok=True)
    gens_all = load_jsonl(DATA / "generations.jsonl")
    gens = {g["gen_id"]: g for g in gens_all if g.get("ok")}
    judg = [j for j in load_jsonl(DATA / "judgments.jsonl") if j.get("ok")]
    p1 = {j["gen_id"]: j for j in judg if j["pass"] == 1}
    p2 = {j["gen_id"]: j for j in judg if j["pass"] == 2}

    # ---- idea-level table (all raw scores kept)
    rows = []
    for gid, g in sorted(gens.items()):
        fc = format_checks(g["text"])
        j = p1.get(gid)
        r = {"gen_id": gid, "brand": g["brand"], "condition": g["condition"], "rep": g["rep"], "idea": g["text"], **fc,
             "gen_output_tokens": (g.get("usage") or {}).get("output_tokens")}
        if j:
            n, u = j["parsed"]["novelty"], j["parsed"]["usefulness"]
            r.update(novelty=n, usefulness=u, comp_mean=comp_mean(n, u), comp_harm=comp_harm(n, u),
                     floor=(n == 1 or u == 1),
                     novelty_reason=j["parsed"].get("novelty_reason"), usefulness_reason=j["parsed"].get("usefulness_reason"))
        if gid in p2:
            r.update(novelty_retest=p2[gid]["parsed"]["novelty"], usefulness_retest=p2[gid]["parsed"]["usefulness"])
        rows.append(r)
    with (RESULTS / "idea_level_scores.csv").open("w", newline="", encoding="utf-8-sig") as f:
        cols = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0].keys()).index(k) if k in rows[0] else 99)
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    div = json.loads((RESULTS / "diversity_cells.json").read_text(encoding="utf-8")) if (RESULTS / "diversity_cells.json").exists() else []
    div_key = {(d["brand"], d["condition"]): d for d in div}
    div_metric = "bge_div" if div and "bge_div" in div[0] else "tfidf_div"

    metrics = ["novelty", "usefulness", "comp_mean", "comp_harm", "floor"]
    brands = sorted({r["brand"] for r in rows})
    cell = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if "novelty" in r:
            for m in metrics:
                cell[(r["brand"], r["condition"])][m].append(float(r[m]))
    for (b, c), d in div_key.items():
        cell[(b, c)]["diversity"] = [d[div_metric]]
        cell[(b, c)]["tfidf_div"] = [d["tfidf_div"]]
    allm = metrics + ["diversity", "tfidf_div"]
    pooled_sd = {m: sd([r[m] for r in rows if m in r]) for m in metrics}

    # condition means
    summary = {"by_condition": {}, "vs_base": {}, "high_minus_low": {}, "meta": {}}
    for c in CONDITIONS:
        s = {}
        for m in allm:
            vals = [x for b in brands for x in cell[(b, c)].get(m, [])]
            s[m] = mean(vals)
            s[m + "_n"] = len(vals)
        summary["by_condition"][c] = s

    def contrast(c1, c2):
        out = {}
        for m in allm:
            pb = {}
            for b in brands:
                a, z = cell[(b, c1)].get(m), cell[(b, c2)].get(m)
                if a and z:
                    pb[b] = (mean(a), mean(z))
            if len(pb) >= 2:
                est, lo, hi, npos, nneg = bootstrap_brand_diff(pb)
                d = {"diff": est, "ci95": [lo, hi], "brands_pos": npos, "brands_neg": nneg, "n_brands": len(pb)}
                if m in pooled_sd and pooled_sd[m] and pooled_sd[m] == pooled_sd[m]:
                    d["std_diff"] = est / pooled_sd[m]
                out[m] = d
        return out

    for c in CONDITIONS[1:]:
        summary["vs_base"][c] = contrast(c, "BASE")
    for t in TRAITS:
        summary["high_minus_low"][t] = contrast(f"{t}_H", f"{t}_L")

    # judge retest reliability
    pairs = [(p1[g]["parsed"], p2[g]["parsed"]) for g in p2 if g in p1]
    rel = {}
    for k in ("novelty", "usefulness"):
        a = [x[0][k] for x in pairs]
        b = [x[1][k] for x in pairs]
        if a:
            rel[k] = {"n": len(a), "exact": mean([float(x == y) for x, y in zip(a, b)]),
                      "within1": mean([float(abs(x - y) <= 1) for x, y in zip(a, b)]),
                      "pearson": pearson(a, b), "spearman": pearson(rank(a), rank(b))}
    summary["meta"]["judge_retest"] = rel
    summary["meta"]["novelty_usefulness_corr_pass1"] = pearson([r["novelty"] for r in rows if "novelty" in r],
                                                               [r["usefulness"] for r in rows if "novelty" in r])
    summary["meta"]["pooled_sd"] = pooled_sd
    summary["meta"]["diversity_metric"] = div_metric
    summary["meta"]["score_distribution"] = {
        k: {str(v): sum(1 for r in rows if r.get(k) == v) for v in range(1, 6)} for k in ("novelty", "usefulness")}
    summary["meta"]["format"] = {c: {
        "under_50_words": mean([float(r["under_50_words"]) for r in rows if r["condition"] == c]),
        "single_sentence": mean([float(r["single_sentence"]) for r in rows if r["condition"] == c]),
        "mean_words": mean([r["words"] for r in rows if r["condition"] == c])} for c in CONDITIONS}
    summary["meta"]["generation_records"] = {"ok": len(gens), "records_total": len(gens_all),
                                             "planned": len(CONDITIONS) * CONFIG["n_brands"] * CONFIG["reps"]}
    summary["meta"]["judgments"] = {"pass1": len(p1), "pass2": len(p2)}

    # manipulation check
    summary["manipulation_check"] = manip_summary()
    summary["cost_usd_notional"] = cost_summary()
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    write_report(summary, brands)
    print("wrote results/summary.json, results/idea_level_scores.csv, results/report.md")


def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def pearson(a, b):
    if len(a) < 3:
        return float("nan")
    ma, mb = mean(a), mean(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return float("nan")
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


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
            sc = mean([ans[it["n"]] if it["key"] == 1 else 6 - ans[it["n"]] for it in items])
            res[r["condition"]][t].append(sc)
    out = {c: {t: mean(v) for t, v in d.items()} | {"n_runs": len(next(iter(d.values())))} for c, d in res.items()}
    # spillover: for each trait condition, mean abs change in the 4 non-target traits vs BASE
    if "BASE" in out:
        for c in out:
            if c == "BASE":
                continue
            t = c.split("_")[0]
            out[c]["target_change_vs_base"] = out[c][t] - out["BASE"][t]
            out[c]["mean_abs_offtarget_change_vs_base"] = mean([abs(out[c][o] - out["BASE"][o]) for o in TRAITS if o != t])
    return out


def cost_summary() -> dict:
    out = {}
    for name in ("generations", "manipulation_check", "judgments"):
        recs = load_jsonl(DATA / f"{name}.jsonl")
        out[name] = round(sum(float(r.get("attempts_cost_usd") or 0) for r in recs), 4)
    out["total"] = round(sum(out.values()), 4)
    return out


def f2(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def write_report(s: dict, brands: list[str]) -> None:
    L = []
    L.append("# 파일럿 v1 결과 (자동 생성)\n")
    L.append("> 탐색적 파일럿이다. 브랜드 5개, 조건당 30개 아이디어, LLM 평가자 1명. p값을 쓰지 않고, 어떤 차이도 확인된 효과로 해석하지 않는다.\n")
    L.append(f"브랜드: {', '.join(brands)}  \n다양성 지표: `{s['meta']['diversity_metric']}`\n")
    L.append("## 조건별 평균\n")
    L.append("| 조건 | 새로움(1–5) | 유용성(1–5) | 종합-산술(주) | 종합-조화(보조) | 바닥 비율 | 다양성 | TF-IDF 다양성 | n |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for c, d in s["by_condition"].items():
        L.append(f"| {c} | {f2(d['novelty'])} | {f2(d['usefulness'])} | {f2(d['comp_mean'],1)} | {f2(d['comp_harm'],1)} | "
                 f"{f2(d['floor'])} | {f2(d['diversity'],3)} | {f2(d['tfidf_div'],3)} | {d['novelty_n']} |")
    for title, key in (("성격 조건 − BASE (브랜드 내 차이의 평균, 브랜드 부트스트랩 95% 구간, [+브랜드 수/−브랜드 수])", "vs_base"),
                       ("같은 특성의 High − Low", "high_minus_low")):
        L.append(f"\n## {title}\n")
        L.append("| 대비 | 새로움 | 유용성 | 종합-산술 | 종합-조화 | 다양성 |")
        L.append("|---|---|---|---|---|---|")
        for c, d in s[key].items():
            cells = []
            for m, nd in (("novelty", 2), ("usefulness", 2), ("comp_mean", 1), ("comp_harm", 1), ("diversity", 3)):
                x = d.get(m)
                cells.append("—" if not x else f"{x['diff']:+.{nd}f} [{x['ci95'][0]:+.{nd}f}, {x['ci95'][1]:+.{nd}f}] ({x['brands_pos']}/{x['brands_neg']})")
            L.append(f"| {c} | " + " | ".join(cells) + " |")
    mc = s.get("manipulation_check") or {}
    if mc:
        L.append("\n## 조작 확인: IPIP-50 자기보고 특성 점수 (1–5, 조건당 실행 수 표시)\n")
        L.append("| 조건 | O | C | E | A | N | 표적 변화 vs BASE | 표적 외 평균 절대 변화 | 실행 수 |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for c in CONDITIONS:
            if c in mc:
                d = mc[c]
                L.append(f"| {c} | " + " | ".join(f2(d.get(t)) for t in "OCEAN") +
                         f" | {f2(d.get('target_change_vs_base'))} | {f2(d.get('mean_abs_offtarget_change_vs_base'))} | {d['n_runs']} |")
    m = s["meta"]
    L.append("\n## 평가자·형식·비용 점검\n")
    L.append(f"- 평가자 재검사 일치: `{json.dumps(m['judge_retest'], ensure_ascii=False)}`")
    L.append(f"- 새로움–유용성 상관(1차 평가): {f2(m['novelty_usefulness_corr_pass1'])}")
    L.append(f"- 점수 분포: `{json.dumps(m['score_distribution'])}`")
    L.append(f"- 생성 기록: `{json.dumps(m['generation_records'])}`, 평가 기록: `{json.dumps(m['judgments'])}`")
    L.append(f"- 명목 비용(USD, CLI 보고값): `{json.dumps(s['cost_usd_notional'])}`")
    L.append("\n### 형식 준수(조건별)\n")
    L.append("| 조건 | 50단어 미만 | 한 문장 | 평균 단어 수 |")
    L.append("|---|---|---|---|")
    for c, d in m["format"].items():
        L.append(f"| {c} | {f2(d['under_50_words'])} | {f2(d['single_sentence'])} | {f2(d['mean_words'],1)} |")
    (RESULTS / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# human package
# --------------------------------------------------------------------------
def cmd_human() -> None:
    gens = [g for g in load_jsonl(DATA / "generations.jsonl") if g.get("ok")]
    gens = list({g["gen_id"]: g for g in gens}.values())
    rng = random.Random(SEED + 3)
    by = defaultdict(list)
    for g in gens:
        by[(g["condition"], g["brand"])].append(g)
    brands = sorted({g["brand"] for g in gens})
    items = []
    for c in CONDITIONS:
        picked = [rng.choice(by[(c, b)]) for b in brands if by[(c, b)]]
        rest = [g for b in brands for g in by[(c, b)] if g not in picked]
        picked += rng.sample(rest, max(0, CONFIG["human_per_condition"] - len(picked)))
        rng.shuffle(picked)
        for k, g in enumerate(picked):
            items.append({"g": g, "set": "calibration" if k < CONFIG["human_calibration_per_condition"] else "test"})
    rng.shuffle(items)
    HUMAN.mkdir(exist_ok=True)
    keydir = HUMAN / "_key_DO_NOT_OPEN_until_rating_done"
    keydir.mkdir(exist_ok=True)
    with (HUMAN / "rating_sheet.csv").open("w", newline="", encoding="utf-8-sig") as f, \
         (keydir / "key.csv").open("w", newline="", encoding="utf-8-sig") as k:
        w = csv.writer(f)
        kw = csv.writer(k)
        w.writerow(["item_id", "set", "brand", "idea", "novelty_1to5", "usefulness_1to5", "new_to_me_yes_no", "comment"])
        kw.writerow(["item_id", "gen_id", "condition", "brand", "rep"])
        for i, it in enumerate(items, 1):
            g = it["g"]
            iid = f"H{i:03d}"
            w.writerow([iid, it["set"], g["brand"], g["text"], "", "", "", ""])
            kw.writerow([iid, g["gen_id"], g["condition"], g["brand"], g["rep"]])
    (HUMAN / "my_prior_ideas.csv").write_text(
        "brand,my_existing_idea_or_known_campaign\n" + "".join(f"{b},\n" for b in brands), encoding="utf-8-sig")
    print(f"human package: {len(items)} items -> {HUMAN}")


if __name__ == "__main__":
    cmds = {"setup": cmd_setup, "generate": cmd_generate, "manip": cmd_manip, "judge": cmd_judge,
            "diversity": cmd_diversity, "analyze": cmd_analyze, "human": cmd_human}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]]()
