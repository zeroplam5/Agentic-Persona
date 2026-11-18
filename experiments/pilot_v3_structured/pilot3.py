"""Big Five persona x structured ideation, pilot v3 (exploratory). See DESIGN.md and ANALYSIS_PLAN.md.

Separate experiment from the Wild Ideas pilots (v1/v2): different instructions and output format.

Subcommands (run from this folder):
  python pilot3.py setup        # brands/topics, run plan, condition prompts, hash of frozen files
  python pilot3.py smoke        # 1 structured generation + 1 judge call -> logs/smoke.jsonl only
  python pilot3.py generate     # structured runs + NODEDUP split runs (Claude CLI)
  python pilot3.py manip        # Mini-Markers self-report under each condition prompt (Claude CLI)
  python pilot3.py observe      # Gemini observer ratings of Big Five expression in work records
  uv run ... python embed3.py   # embeddings for retrieval (see README)
  python pilot3.py bucket       # MuseScorer-style incremental bucketing (GPT-6-astra)
  python pilot3.py judge        # brand fit / feasibility / logic, one call per dimension (GPT-6-astra)
  python pilot3.py human        # blind human sheets (2 raters), prior-idea sheet, bucket review sheet
  python pilot3.py analyze      # tables + report (human columns used only if filled)

API keys come from the project .env and are never printed or logged.
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
import statistics as stats
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / "prompts"
DATA = ROOT / "data"
LOGS = ROOT / "logs"
RESULTS = ROOT / "results"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SEED = CONFIG["seed"]
HUMAN = ROOT.parent.parent / "human_rating_blind_v3_structured"

TRAIT_NAMES = {"E": "Extraversion", "A": "Agreeableness", "C": "Conscientiousness", "N": "Neuroticism",
               "O": "Openness"}
TARGET = "O"  # pilot trait (see DESIGN.md section 2.4)
STRUCT_CONDITIONS = ["BASE", "SB_AVG", "SB_O_H", "SB_O_L", "LK_AVG", "LK_O_H", "LK_O_L"]
NODEDUP = "NODEDUP"
ALL_RUN_CONDITIONS = STRUCT_CONDITIONS + [NODEDUP]

_lock = threading.Lock()
_cost = defaultdict(float)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_text(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8").strip("\n")


def load_env() -> dict:
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


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def append_jsonl(path: Path, rec: dict) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# =============================================================== persona prompts
BFI2 = json.loads((PROMPTS / "bfi2_items.json").read_text(encoding="utf-8"))
MM = json.loads((PROMPTS / "minimarkers.json").read_text(encoding="utf-8"))

# Huang et al. Table 1 context line is "You are participating in a personality psychology study. You have been
# assigned personality traits." We DROP the first sentence (our task is not a study participation) - modification.
CONTEXT = "### Context ###\nYou have been assigned personality traits."
LIKERT_INSTR = ("### Instruction ###\nEach number below indicates the extent to which you agree or disagree with "
                "that the statement. 1 means `Disagree Strongly', 2 means `Disagree', 3 means `Neutral', and 4 means "
                "`Agree', 5 means `Agree Strongly'.")  # verbatim from Table 1 (including its grammar)


def levels_for(cond: str) -> dict:
    lv = {t: "avg" for t in TRAIT_NAMES}
    if cond.endswith("_H"):
        lv[TARGET] = "high"
    elif cond.endswith("_L"):
        lv[TARGET] = "low"
    return lv


def simple_binary(lv: dict) -> str:
    # Original Simple-Binary: "You are high in X." / "You are low in X." for all five traits (order E, A, C, N, O).
    # Modification: non-target traits get "You are average in X." (no 'average' level exists in the original).
    word = {"high": "high", "low": "low", "avg": "average"}
    body = " ".join(f"You are {word[lv[t]]} in {TRAIT_NAMES[t]}." for t in "EACNO")
    return f"{CONTEXT}\n\n### Your Personality ###\n{body}"


def bfi2_likert(lv: dict) -> str:
    # Original: item responses copied from a real human's BFI-2 answers. Modification: synthetic profile -
    # target-trait items at the extreme (5, or 1 if reverse-keyed; mirrored for low), all other items 3 (Neutral).
    parts = []
    for it in BFI2["items"]:
        level = lv[it["domain"]]
        if level == "avg":
            v = 3
        else:
            hi = (level == "high") != it["reverse"]
            v = 5 if hi else 1
        parts.append(f"{it['text']}: {v}")
    return f"{CONTEXT}\n\n{LIKERT_INSTR}\n\n### Your Personality ###\n" + "; ".join(parts) + "."


def persona_block(cond: str) -> str | None:
    if cond in ("BASE", NODEDUP):
        return None
    lv = levels_for(cond)
    return simple_binary(lv) if cond.startswith("SB_") else bfi2_likert(lv)


def system_prompt(cond: str) -> str:
    base = read_text("common_system.txt")
    p = persona_block(cond)
    return base if p is None else f"{p}\n\n{base}"


# =============================================================== providers
def _post(url: str, headers: dict, body: dict, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:600]
    except Exception as e:
        return -1, f"{type(e).__name__}: {str(e)[:300]}"


def price(model: str, inp: int, out: int) -> float:
    p = CONFIG["price_per_million_usd"].get(model)
    return 0.0 if not p else (inp * p["input"] + out * p["output"]) / 1e6


def call_claude(spec_env: dict, system: str, user: str) -> dict:
    g = CONFIG["generator"]
    workdir = Path(g["isolated_cwd"])
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", dir=workdir) as f:
        f.write(system)
        sys_path = f.name
    cmd = [g["claude_cli"], "-p", "--system-prompt-file", sys_path, "--tools", "", "--no-session-persistence",
           "--strict-mcp-config", "--output-format", "stream-json", "--verbose", "--model", g["model"],
           "--effort", g["effort"], "--max-budget-usd", str(g["per_call_budget_usd"])]
    env = dict(os.environ)
    env.update(spec_env)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8", cwd=workdir,
                              env=env, timeout=600)
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, rc = "", "timeout", -1
    finally:
        try:
            os.unlink(sys_path)
        except OSError:
            pass
    rec = {"elapsed_s": round(time.time() - t0, 2), "returncode": rc,
           "request_params": {"model": g["model"], "effort": g["effort"], **spec_env,
                              "cli_version": g["claude_cli_version"]}}
    blocks, result, msg_models = [], None, set()
    for line in stdout.splitlines():
        try:
            j = json.loads(line)
        except Exception:
            continue
        if j.get("type") == "assistant":
            msg_models.add(j["message"].get("model"))
            for c in j["message"].get("content", []):
                blocks.append(c)
        elif j.get("type") == "result":
            result = j
    if result is None:
        rec.update(ok=False, error=f"no result line; rc={rc} stderr={stderr[:300]!r} stdout_tail={stdout[-300:]!r}")
        return rec
    text = (result.get("result") or "").strip()
    th = [b for b in blocks if b.get("type") in ("thinking", "redacted_thinking")]
    err = None
    if result.get("is_error") or text.startswith("API Error") or not text:
        err = f"cli error: subtype={result.get('subtype')} result={text[:300]!r}"
    usage = result.get("usage") or {}
    rec.update(ok=err is None, error=err, text=text, stop_reason=result.get("stop_reason"),
               model_returned=sorted(m for m in msg_models if m), usage=usage, model_usage=result.get("modelUsage"),
               total_cost_usd=result.get("total_cost_usd"),
               reasoning={"thinking_blocks": len(th),
                          "thinking_text_chars_returned": sum(len(b.get("thinking") or "") for b in th),
                          "thinking_content_available": any((b.get("thinking") or "") for b in th),
                          "output_tokens_total": usage.get("output_tokens"),
                          "visible_text_chars": len(text),
                          "note": "thinking tokens are not reported separately; output_tokens_total includes them"})
    with _lock:
        _cost["claude_nominal"] += float(result.get("total_cost_usd") or 0)
    return rec


def call_openai(spec: dict, system: str, user: str) -> dict:
    body = {"model": spec["model"], "max_output_tokens": spec["max_output_tokens"],
            "reasoning": {"effort": spec["reasoning_effort"]},
            "input": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    params = {k: v for k, v in body.items() if k != "input"}
    st, j = _post("https://api.openai.com/v1/responses", {"Authorization": "Bearer " + ENV["OPENAI_API_KEY"]}, body)
    if st != 200 or not isinstance(j, dict):
        return {"ok": False, "error": f"http {st}: {j}", "request_params": params}
    text = "".join(c.get("text", "") for o in j.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []) if c.get("type") == "output_text").strip()
    u = j.get("usage") or {}
    cost = price(spec["model"], u.get("input_tokens", 0), u.get("output_tokens", 0))
    with _lock:
        _cost["openai"] += cost
    return {"ok": bool(text), "text": text, "status": j.get("status"), "model_returned": j.get("model"),
            "response_id": j.get("id"), "usage": u, "est_cost_usd": round(cost, 6), "request_params": params,
            **({} if text else {"error": f"empty output: status={j.get('status')} {json.dumps(j.get('incomplete_details'))}"})}


def call_gemini(spec: dict, system: str, user: str) -> dict:
    gen = {"temperature": spec["temperature"], "maxOutputTokens": spec["max_output_tokens"],
           "thinkingConfig": {"thinkingBudget": spec["thinking_budget"]}}
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{spec['model']}:generateContent"
    st, j = _post(url, {"x-goog-api-key": ENV["GEMINI_API_KEY"]}, body)
    if st != 200 or not isinstance(j, dict):
        return {"ok": False, "error": f"http {st}: {j}", "request_params": {"model": spec["model"], **gen}}
    cands = j.get("candidates") or []
    parts = (cands[0].get("content") or {}).get("parts", []) if cands else []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    u = j.get("usageMetadata") or {}
    cost = price(spec["model"], u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0))
    with _lock:
        _cost["gemini"] += cost
    return {"ok": bool(text), "text": text, "finish_reason": cands[0].get("finishReason") if cands else None,
            "model_returned": j.get("modelVersion"), "usage": u, "est_cost_usd": round(cost, 6),
            "request_params": {"model": spec["model"], **gen}, **({} if text else {"error": "empty response"})}


def budget_left(kind: str) -> bool:
    return _cost[kind] < CONFIG["budget_usd"][kind]


def call(kind: str, spec, system: str, user: str, validate=None) -> dict:
    """kind: claude | openai | gemini. Retries on failure/validation failure; keeps failed attempts."""
    attempts = []
    for _ in range(1 + CONFIG["max_retries"]):
        bkey = {"claude": "claude_nominal"}.get(kind, kind)
        if not budget_left(bkey):
            attempts.append({"ok": False, "error": f"budget cap reached for {bkey}; not called"})
            break
        started = now()
        if kind == "claude":
            r = call_claude(spec, system, user)
        elif kind == "openai":
            r = call_openai(spec, system, user)
        else:
            r = call_gemini(spec, system, user)
        r["started"] = started
        if r.get("ok") and validate is not None:
            v = validate(r["text"])
            if v is None:
                r.update(ok=False, error="validation failed (unparseable or incomplete output)")
            else:
                r["parsed"] = v
        attempts.append(r)
        if r.get("ok"):
            break
        time.sleep(4)
    final = dict(attempts[-1])
    final["n_attempts"] = len(attempts)
    final["failed_attempts"] = [{k: a.get(k) for k in ("started", "error", "text", "usage", "total_cost_usd", "est_cost_usd")}
                                for a in attempts[:-1]]
    return final


def run_pool(tasks, fn, label, workers=None):
    if not tasks:
        print(f"[{label}] nothing to do")
        return
    workers = workers or CONFIG["workers"]
    print(f"[{label}] {len(tasks)} tasks, workers={workers}", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fu in as_completed([ex.submit(fn, t) for t in tasks]):
            fu.result()
            done += 1
            if done % 10 == 0 or done == len(tasks):
                print(f"[{label}] {done}/{len(tasks)} cost so far: " +
                      ", ".join(f"{k} ${v:.2f}" for k, v in _cost.items()), flush=True)


# =============================================================== parsers
def _json_obj(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def parse_structured(text: str):
    j = _json_obj(text)
    try:
        assert isinstance(j["task_understanding"], dict)
        c = j["candidates"]
        assert isinstance(c, list) and len(c) == CONFIG["n_candidates"]
        assert all(x.get("core_idea") and x.get("title") for x in c)
        ids = [x["id"] for x in c]
        assert j["selection"]["selected_id"] in ids
        assert isinstance(j.get("revisions_after_selection", []), list)
        fp = j["final_proposal"]
        assert fp.get("idea") and fp.get("title") and len(fp.get("follow_up_questions", [])) == 3
    except Exception:
        return None
    return j


def parse_single(text: str):
    j = _json_obj(text)
    try:
        assert j["candidate"].get("core_idea") and j["candidate"].get("title")
        fp = j["final_proposal"]
        assert fp.get("idea") and fp.get("title") and len(fp.get("follow_up_questions", [])) == 3
    except Exception:
        return None
    return j


def parse_mm(text: str):
    j = _json_obj(text)
    if not isinstance(j, dict):
        return None
    norm = {k.strip().lower(): v for k, v in j.items()}
    out = {}
    for it in MM["items"]:
        v = norm.get(it.lower())
        try:
            v = int(v)
        except Exception:
            return None
        if not 1 <= v <= 9:
            return None
        out[it] = v
    return out


def parse_score(text: str):
    j = _json_obj(text)
    try:
        s = int(j["score"])
        assert 1 <= s <= 5
        return {"score": s, "reason": j.get("reason")}
    except Exception:
        return None


def parse_observer(text: str):
    j = _json_obj(text)
    try:
        out = {t: int(j[t]) for t in "OCEAN"}
        assert all(1 <= v <= 9 for v in out.values())
        out["notes"] = j.get("notes")
        return out
    except Exception:
        return None


def parse_bucket(text: str):
    m = re.match(r"\s*(-?\d+)\s*(.*)", text, re.S)
    if not m:
        return None
    return {"id": int(m.group(1)), "reason": m.group(2).strip()}


# =============================================================== setup / generate
def brands_topics():
    return json.loads((LOGS / "brands.json").read_text(encoding="utf-8"))


def cmd_setup():
    LOGS.mkdir(exist_ok=True)
    rng = random.Random(SEED)
    cats = CONFIG["brand_table_appendix_A2"]
    chosen = rng.sample(sorted(cats), CONFIG["n_brands"])
    brands = []
    topics = list(CONFIG["provisional_topics"])
    rng.shuffle(topics)
    for c, tp in zip(chosen, topics):
        pool = [b for b in cats[c] if b not in CONFIG["exclude_brands"]]
        brands.append({"category": c, "brand": rng.choice(pool), "topic": tp, "topic_source": "provisional (Claude placeholder)"})
    plan = []
    for b in brands:
        for c in STRUCT_CONDITIONS:
            for r in range(CONFIG["reps"]):
                plan.append({"gen_id": f"{b['brand']}|{c}|{r}", "run_id": f"{b['brand']}|{c}|{r}", "kind": "structured",
                             "brand": b["brand"], "category": b["category"], "topic": b["topic"], "condition": c, "rep": r})
        for r in range(CONFIG["reps"]):
            for k in range(CONFIG["nodedup_split"]["n_independent_calls"]):
                plan.append({"gen_id": f"{b['brand']}|{NODEDUP}|{r}|k{k}", "run_id": f"{b['brand']}|{NODEDUP}|{r}",
                             "kind": "single", "brand": b["brand"], "category": b["category"], "topic": b["topic"],
                             "condition": NODEDUP, "rep": r, "k": k})
    rng.shuffle(plan)
    (LOGS / "brands.json").write_text(json.dumps(brands, indent=2, ensure_ascii=False), encoding="utf-8")
    (LOGS / "generation_plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    (LOGS / "condition_prompts.json").write_text(json.dumps(
        {c: {"persona_block": persona_block(c), "system_prompt": system_prompt(c)} for c in ALL_RUN_CONDITIONS},
        indent=2, ensure_ascii=False), encoding="utf-8")
    freeze()
    print("brands:", [(b["brand"], b["topic"]) for b in brands], "| plan:", len(plan), "calls")


def freeze():
    files = [ROOT / "DESIGN.md", ROOT / "ANALYSIS_PLAN.md", ROOT / "config.json", ROOT / "pilot3.py",
             *sorted(PROMPTS.iterdir())]
    (LOGS / "freeze_hashes.txt").write_text(f"recorded_at: {now()}\n" + "".join(
        f"{f.relative_to(ROOT).as_posix()} sha256: {hashlib.sha256(f.read_bytes()).hexdigest()}\n"
        for f in files if f.exists()), encoding="utf-8")


def user_prompt(p: dict) -> str:
    tpl = read_text("task_structured_user.txt" if p["kind"] == "structured" else "task_single_user.txt")
    return tpl.replace("[BRAND]", p["brand"]).replace("[CATEGORY]", p["category"]).replace("[TOPIC]", p["topic"])


def gen_env(kind: str) -> dict:
    return CONFIG["generator"]["cli_env"] if kind == "structured" else CONFIG["nodedup_split"]["cli_env"]


def cmd_smoke():
    LOGS.mkdir(exist_ok=True)
    out = LOGS / "smoke.jsonl"
    b = brands_topics()[0]
    p = {"kind": "structured", **b}
    sp, up = system_prompt("LK_O_H"), user_prompt(p)
    g = call("claude", gen_env("structured"), sp, up, validate=parse_structured)
    append_jsonl(out, {"phase": "smoke-generate", "condition": "LK_O_H", **b, "system_prompt": sp, "user_prompt": up, **g})
    print("generate ok:", g.get("ok"), "| usage:", (g.get("usage") or {}).get("output_tokens"), "| reasoning:", g.get("reasoning"),
          "| err:", g.get("error"))
    if g.get("ok"):
        fp = g["parsed"]["final_proposal"]
        up2 = (read_text("judge_logic.txt").replace("[BRAND]", b["brand"]).replace("[TOPIC]", b["topic"])
               .replace("[TITLE]", fp["title"]).replace("[IDEA]", fp["idea"]))
        j = call("openai", CONFIG["judge"], read_text("judge_system.txt"), up2, validate=parse_score)
        append_jsonl(out, {"phase": "smoke-judge", **j})
        print("judge:", j.get("ok"), j.get("parsed"), j.get("usage"), j.get("est_cost_usd"))
    print({k: round(v, 4) for k, v in _cost.items()})


def cmd_generate():
    plan = json.loads((LOGS / "generation_plan.json").read_text(encoding="utf-8"))
    out = DATA / "generations.jsonl"
    done = {r["gen_id"] for r in load_jsonl(out) if r.get("ok")}

    def work(p):
        sp, up = system_prompt(p["condition"]), user_prompt(p)
        r = call("claude", gen_env(p["kind"]), sp, up, validate=parse_structured if p["kind"] == "structured" else parse_single)
        append_jsonl(out, {**p, "phase": "generate", "system_prompt": sp, "user_prompt": up, **r})

    run_pool([p for p in plan if p["gen_id"] not in done], work, "generate")


def cmd_manip():
    out = DATA / "manipulation_check.jsonl"
    done = {r["mc_id"] for r in load_jsonl(out) if r.get("ok")}
    rng = random.Random(SEED + 1)
    tasks = [{"mc_id": f"{c}|{r}", "condition": c, "rep": r} for c in STRUCT_CONDITIONS for r in range(CONFIG["manip_reps"])]
    rng.shuffle(tasks)
    up = read_text("minimarkers_user.txt").replace("[ITEMS]", "\n".join(f"{i + 1}. {w} _" for i, w in enumerate(MM["items"])))

    def work(t):
        sp = system_prompt(t["condition"])
        r = call("claude", gen_env("structured"), sp, up, validate=parse_mm)
        append_jsonl(out, {**t, "phase": "manip_minimarkers", "system_prompt": sp, "user_prompt": up, **r})

    run_pool([t for t in tasks if t["mc_id"] not in done], work, "manip")


# =============================================================== assembled runs
def runs() -> list[dict]:
    """One record per run (structured run, or NODEDUP group of 4 independent single calls).
    Only model-provided fields are copied; NODEDUP has no selection/revision step by design (stored as null)."""
    gens = [g for g in load_jsonl(DATA / "generations.jsonl") if g.get("ok")]
    latest = {g["gen_id"]: g for g in gens}
    out = []
    groups = defaultdict(list)
    for g in latest.values():
        if g["kind"] == "structured":
            P = g["parsed"]
            out.append({"run_id": g["run_id"], "brand": g["brand"], "topic": g["topic"], "condition": g["condition"],
                        "rep": g["rep"], "kind": "structured", "candidates": P["candidates"],
                        "selected_id": P["selection"]["selected_id"], "record": P, "final": P["final_proposal"],
                        "usage": [g.get("usage")], "reasoning": [g.get("reasoning")],
                        "model_returned": g.get("model_returned"), "gen_ids": [g["gen_id"]]})
        else:
            groups[g["run_id"]].append(g)
    k_needed = CONFIG["nodedup_split"]["n_independent_calls"]
    for rid, gs in groups.items():
        if len(gs) < k_needed:
            continue
        gs.sort(key=lambda x: x["k"])
        cands = []
        for g in gs:
            c = dict(g["parsed"]["candidate"])
            c["id"] = f"C{g['k'] + 1}"
            cands.append(c)
        pick = random.Random(f"{SEED}|{rid}").randrange(k_needed)
        g0 = gs[0]
        out.append({"run_id": rid, "brand": g0["brand"], "topic": g0["topic"], "condition": NODEDUP, "rep": g0["rep"],
                    "kind": "nodedup", "candidates": cands, "selected_id": f"C{pick + 1}",
                    "record": {"independent_calls": [g["parsed"] for g in gs], "selection": None,
                               "revisions_after_selection": None, "final_pick_rule": "seeded random"},
                    "final": gs[pick]["parsed"]["final_proposal"], "usage": [g.get("usage") for g in gs],
                    "reasoning": [g.get("reasoning") for g in gs], "model_returned": g0.get("model_returned"),
                    "gen_ids": [g["gen_id"] for g in gs]})
    return sorted(out, key=lambda r: r["run_id"])


def cmd_observe():
    out = DATA / "observer.jsonl"
    done = {r["run_id"] for r in load_jsonl(out) if r.get("ok")}
    spec = CONFIG["observer"]

    def work(r):
        rec = {k: v for k, v in r["record"].items()}
        up = read_text("observer_user.txt").replace("[RECORD]", json.dumps(rec, indent=1, ensure_ascii=False))
        res = call("gemini", spec, "You are a careful personality psychologist.", up, validate=parse_observer)
        append_jsonl(out, {"run_id": r["run_id"], "condition": r["condition"], "brand": r["brand"], "phase": "observer",
                           "user_prompt": up, **res})

    run_pool([r for r in runs() if r["kind"] == "structured" and r["run_id"] not in done], work, "observe")


# =============================================================== bucketing
def bucket_items() -> dict:
    """Per brand two comparison sets: 'final' (one final proposal per run) and 'cand' (all candidates of all runs)."""
    sets = defaultdict(list)
    for r in runs():
        f = r["final"]
        sets[(r["brand"], "final")].append({"item_id": f"{r['run_id']}|final", "run_id": r["run_id"],
                                            "condition": r["condition"], "text": f"{f['title']}: {f['idea']}"})
        for c in r["candidates"]:
            sets[(r["brand"], "cand")].append({"item_id": f"{r['run_id']}|{c['id']}", "run_id": r["run_id"],
                                               "condition": r["condition"], "text": f"{c['title']}: {c['core_idea']}"})
    return sets


def load_emb() -> dict:
    p = DATA / "embeddings.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))  # vectors are L2-normalized


def cmd_bucket():
    emb = load_emb()
    sets = bucket_items()
    missing = [it["item_id"] for v in sets.values() for it in v if it["item_id"] not in emb]
    if missing:
        sys.exit(f"{len(missing)} items have no embedding; run embed3.py first")
    out = DATA / "buckets.jsonl"
    prev = load_jsonl(out)
    done_sets = {(r["brand"], r["set"]) for r in prev if r.get("phase") == "set_done"}
    Kc = CONFIG["bucketing"]["Kc"]
    bt = {b["brand"]: b["topic"] for b in brands_topics()}

    def work(key):
        brand, setname = key
        items = list(sets[key])
        random.Random(f"{SEED}|{brand}|{setname}").shuffle(items)
        codebook = []  # (bucket_id, description, vector)
        assign = {}
        for idx, it in enumerate(items):
            v = emb[it["item_id"]]
            if len(codebook) <= Kc:
                cand = codebook
                sims = {b: round(cos(v, vec), 4) for b, _, vec in codebook}
            else:
                scored = sorted(codebook, key=lambda c: -cos(v, c[2]))[:Kc]
                cand = scored
                sims = {b: round(cos(v, vec), 4) for b, _, vec in scored}
            if not cand:
                bid, res = 0, {"ok": True, "note": "first item: new bucket without LLM call"}
            else:
                comp = {b: d for b, d, _ in cand}
                sp = read_text("bucket_system.txt").replace("[BRAND]", brand).replace("[TOPIC]", bt[brand]).replace("[K]", str(Kc))
                up = read_text("bucket_user.txt").replace("[IDEA]", it["text"]).replace("[COMPARISONS]", repr(comp))
                valid = lambda t: (lambda p: p if p and (p["id"] == -1 or p["id"] in comp) else None)(parse_bucket(t))
                res = call("openai", CONFIG["bucketer"], sp, up, validate=valid)
                if res.get("ok"):
                    bid = res["parsed"]["id"]
                else:
                    bid = -1
                    res["fallback"] = "LLM failed; treated as new bucket"
                if bid == -1:
                    bid = len(codebook)
            if bid == len(codebook):
                codebook.append((bid, it["text"], v))
            assign[it["item_id"]] = bid
            append_jsonl(out, {"phase": "assign", "brand": brand, "set": setname, "order": idx, **it, "bucket": bid,
                               "candidate_sims": sims, "llm": {k: res.get(k) for k in
                               ("ok", "text", "parsed", "usage", "est_cost_usd", "model_returned", "n_attempts",
                                "failed_attempts", "error", "fallback", "note")}})
        append_jsonl(out, {"phase": "set_done", "brand": brand, "set": setname, "n_items": len(items),
                           "n_buckets": len(codebook), "finished": now()})

    keys = [k for k in sets if k not in done_sets]
    # a set interrupted midway is redone from scratch (its partial rows are ignored by readers)
    run_pool(keys, work, "bucket", workers=min(6, len(keys) or 1))


def bucket_assignments() -> dict:
    """{(brand,set): {item_id: bucket}} from the LAST completed pass of each set."""
    rows = load_jsonl(DATA / "buckets.jsonl")
    res, cur = {}, defaultdict(dict)
    for r in rows:
        k = (r["brand"], r["set"])
        if r["phase"] == "assign":
            if r["order"] == 0:
                cur[k] = {}
            cur[k][r["item_id"]] = r
        elif r["phase"] == "set_done":
            res[k] = dict(cur[k])
    return res


def originality(assign_rows: dict) -> dict:
    """MuseScorer metrics with participant = run. m_k = number of distinct runs contributing to bucket k."""
    runs_all = {r["run_id"] for r in assign_rows.values()}
    N = len(runs_all)
    contrib = defaultdict(set)
    for r in assign_rows.values():
        contrib[r["bucket"]].add(r["run_id"])
    out = {}
    for iid, r in assign_rows.items():
        m = len(contrib[r["bucket"]])
        f = m / N
        out[iid] = {"bucket": r["bucket"], "m": m, "N": N, "rarity": 1 - f, "shapley": 1 / m, "unique": int(m == 1),
                    "threshold": 3 if f <= .01 else 2 if f <= .03 else 1 if f <= .10 else 0}
    return out


# =============================================================== judge
DIMS = {"B": "judge_brand_fit.txt", "F": "judge_feasibility.txt", "L": "judge_logic.txt"}


def cmd_judge():
    out = DATA / "judgments.jsonl"
    done = {r["j_id"] for r in load_jsonl(out) if r.get("ok")}
    bt = {b["brand"]: b["topic"] for b in brands_topics()}
    rs = runs()
    rng = random.Random(SEED + 2)
    tasks = [{"j_id": f"{r['run_id']}|{d}|0", "run_id": r["run_id"], "dim": d, "pass": 0} for r in rs for d in DIMS]
    retest = rng.sample(tasks, round(len(tasks) * CONFIG["judge_retest_fraction"]))
    tasks += [{**t, "j_id": t["j_id"][:-1] + "1", "pass": 1} for t in retest]
    rng.shuffle(tasks)
    byid = {r["run_id"]: r for r in rs}

    def work(t):
        r = byid[t["run_id"]]
        up = (read_text(DIMS[t["dim"]]).replace("[BRAND]", r["brand"]).replace("[TOPIC]", bt[r["brand"]])
              .replace("[TITLE]", r["final"]["title"]).replace("[IDEA]", r["final"]["idea"]))
        res = call("openai", CONFIG["judge"], read_text("judge_system.txt"), up, validate=parse_score)
        append_jsonl(out, {**t, "condition": r["condition"], "brand": r["brand"], "phase": "judge", "user_prompt": up, **res})

    run_pool([t for t in tasks if t["j_id"] not in done], work, "judge")


# =============================================================== human sheets
def cmd_human():
    HUMAN.mkdir(exist_ok=True)
    (HUMAN / "_key_DO_NOT_OPEN_until_rating_done").mkdir(exist_ok=True)
    rs = runs()
    k = CONFIG["human_reps_per_condition_per_brand"]
    pick = [r for r in rs if r["rep"] < k]
    rng = random.Random(SEED + 3)
    rng.shuffle(pick)
    key = []
    for rater in ("A", "B"):
        order = pick[:]
        random.Random(f"{SEED}|{rater}").shuffle(order)
        with (HUMAN / f"rating_sheet_rater{rater}.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["item", "brand", "topic", "title", "idea", "follow_up_questions",
                        "S1_satisfaction_1to5", "S2_new_perspective_1to5", "S3_helps_followup_ideas_1to5",
                        "B_brand_fit_1to5_optional", "F_feasibility_1to5_optional", "L_logic_1to5_optional",
                        "new_thoughts_optional"])
            for r in order:
                iid = "H" + hashlib.sha256(r["run_id"].encode()).hexdigest()[:8]
                w.writerow([iid, r["brand"], r["topic"], r["final"]["title"], r["final"]["idea"],
                            " | ".join(r["final"]["follow_up_questions"]), "", "", "", "", "", "", ""])
                if rater == "A":
                    key.append([iid, r["run_id"], r["condition"], r["rep"]])
    with (HUMAN / "_key_DO_NOT_OPEN_until_rating_done" / "key.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item", "run_id", "condition", "rep"])
        w.writerows(sorted(key))
    with (HUMAN / "prior_ideas_BEFORE_viewing.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["rater", "brand", "topic", "your_idea_1", "your_idea_2", "your_idea_3"])
        for rater in ("A", "B"):
            for b in brands_topics():
                w.writerow([rater, b["brand"], b["topic"], "", "", ""])
    # bucket review sheet: every multi-member final bucket + nearest cross-bucket pairs (cosine) for checking
    ba = bucket_assignments()
    emb = load_emb()
    with (HUMAN / "bucket_review.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["review_type", "brand", "set", "bucket_or_pair", "item_a", "text_a", "item_b", "text_b", "cosine",
                    "llm_says_same_idea", "you_agree_Y_N", "comment"])
        for (brand, setname), rows in sorted(ba.items()):
            if setname != "final":
                continue
            byb = defaultdict(list)
            for r in rows.values():
                byb[r["bucket"]].append(r)
            for b, mem in sorted(byb.items()):
                if len(mem) < 2:
                    continue
                rep = min(mem, key=lambda x: x["order"])
                for m in mem:
                    if m is rep:
                        continue
                    w.writerow(["same_bucket", brand, setname, b, "", rep["text"], "", m["text"],
                                round(cos(emb[rep["item_id"]], emb[m["item_id"]]), 3), "Y", "", ""])
            mem = list(rows.values())
            pairs = []
            for i in range(len(mem)):
                for j in range(i + 1, len(mem)):
                    if mem[i]["bucket"] != mem[j]["bucket"]:
                        pairs.append((cos(emb[mem[i]["item_id"]], emb[mem[j]["item_id"]]), mem[i], mem[j]))
            for c, a, b2 in sorted(pairs, key=lambda x: -x[0])[:6]:
                w.writerow(["different_bucket_high_cosine", brand, setname, f"{a['bucket']}/{b2['bucket']}", "", a["text"],
                            "", b2["text"], round(c, 3), "N", "", ""])
    print("human sheets:", len(pick), "items per rater ->", HUMAN)


if __name__ == "__main__":
    cmds = {"setup": cmd_setup, "smoke": cmd_smoke, "generate": cmd_generate, "manip": cmd_manip,
            "observe": cmd_observe, "bucket": cmd_bucket, "judge": cmd_judge, "human": cmd_human}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds and sys.argv[1] != "analyze":
        sys.exit(__doc__)
    if sys.argv[1] == "analyze":
        import analyze3
        analyze3.main()
    else:
        cmds[sys.argv[1]]()
        if _cost:
            print("process cost (estimated):", {k: round(v, 4) for k, v in _cost.items()})
