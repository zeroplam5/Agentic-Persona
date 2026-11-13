"""Novelty measurement v3: rubric revision with Gemini (DEV), final scoring with OpenAI (TEST),
and agreement with the researcher's blind human ratings.

Same ideas, DEV/TEST split and pair design as v2 (../novelty_v2/logs/sample.json); pilot v1
and novelty v2 files are only read. The judges see only brand + idea text.

  python novelty_v3.py estimate
  python novelty_v3.py smoke                 # 1 call each provider -> logs/smoke.jsonl
  python novelty_v3.py dev <rubric_stem>     # Gemini on DEV 55 + human CALIBRATION ideas only
  python novelty_v3.py freeze <rubric_stem>  # hashes prompts/plan/config/sample/human files
  python novelty_v3.py test                  # OpenAI on TEST (refuses if hashes changed)
  python novelty_v3.py analyze               # LLM metrics + human agreement (test rows only)
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "novelty_v2"), str(HERE.parents[1] / "pilot_v2")]
import pilot as P          # noqa: E402  v1 helpers (IO, judge prompt, parse_judge, rank, pearson)
import novelty_study as NS  # noqa: E402  v2 parsers and statistics
import pilot2 as P2        # noqa: E402  OpenAI / Gemini callers (keys read from .env, never printed)

PROMPTS, DATA, LOGS, RESULTS = HERE / "prompts", HERE / "data", HERE / "logs", HERE / "results"
CFG = json.loads((HERE / "study_config.json").read_text(encoding="utf-8"))
SAMPLE = json.loads((HERE / CFG["sample_file"]).read_text(encoding="utf-8"))
DEVJ, TESTJ = CFG["dev_judge"], CFG["test_judge"]
DEV_ABS = DATA / "gemini_dev_abs.jsonl"
T_ABS = DATA / "openai_test_abs.jsonl"
T_PAIR = DATA / "openai_test_pairs.jsonl"
HUMAN_DIR = (HERE / CFG["human_dir"]).resolve()
KEY_DIR = (HERE / CFG["human_key_dir"]).resolve()
CONDS = P.CONDITIONS
_lock = threading.Lock()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def gens():
    return NS.gens()


def cost(rec: dict, spec: dict) -> float:
    u = rec.get("usage") or {}
    pr = spec["price_usd_per_1m"]
    if spec["provider"] == "openai":
        i, o = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    else:
        i = u.get("promptTokenCount", 0)
        o = u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
    return (i * pr["input"] + o * pr["output"]) / 1e6


def spent() -> float:
    tot = 0.0
    for f, spec in ((DEV_ABS, DEVJ), (T_ABS, TESTJ), (T_PAIR, TESTJ), (LOGS / "smoke.jsonl", None)):
        for r in P.load_jsonl(f):
            tot += r.get("est_cost_usd") or 0.0
    return tot


def fill_abs(stem: str, brand: str, idea: str) -> str:
    tpl = (PROMPTS / f"{stem}.txt").read_text(encoding="utf-8")
    fm = (PROMPTS / "familiar_formats.txt").read_text(encoding="utf-8").strip()
    return tpl.replace("[FORMATS]", fm).replace("[BRAND]", brand).replace("[IDEA]", idea)


def human_rows(kind: str, sets=("test",)):
    """kind 'abs' or 'pair'. Joins the rated sheet with the key by item id (texts verified equal)."""
    G = gens()
    if kind == "abs":
        key = {r["item_id"]: r for r in csv.DictReader(open(KEY_DIR / "absolute_key.csv", encoding="utf-8-sig"))}
        rows = list(csv.DictReader(open(HUMAN_DIR / CFG["human_abs_file"], encoding="utf-8-sig")))
        out = []
        for r in rows:
            if r["set"] not in sets:
                continue
            gid = key[r["item_id"]]["gen_id"]
            assert G[gid]["text"] == r["idea"], r["item_id"]
            out.append({"item": r["item_id"], "set": r["set"], "gen_id": gid, "condition": G[gid]["condition"],
                        "novelty": int(r["novelty_1to5"]),
                        "usefulness": int(r["usefulness_1to5"]) if r.get("usefulness_1to5", "").strip() else None})
        return out
    key = {r["pair_item"]: r for r in csv.DictReader(open(KEY_DIR / "pairs_key.csv", encoding="utf-8-sig"))}
    rows = list(csv.DictReader(open(HUMAN_DIR / CFG["human_pair_file"], encoding="utf-8-sig")))
    out = []
    for r in rows:
        if r["set"] not in sets:
            continue
        k = key[r["pair_item"]]
        assert G[k["gen_A"]]["text"] == r["idea_A"] and G[k["gen_B"]]["text"] == r["idea_B"], r["pair_item"]
        out.append({"item": r["pair_item"], "set": r["set"], "pair_id": k["pair_id"], "A": k["gen_A"], "B": k["gen_B"],
                    "verdict": r["more_novel_A_B_SIMILAR"].strip().upper(), "comment": r.get("comment", "")})
    return out


# ------------------------------------------------------------------------------ calling
def run(tasks, spec, out: Path, key, build, validate, label):
    done = {key(r) for r in P.load_jsonl(out) if r.get("ok")}
    tasks = [t for t in tasks if key(t) not in done]
    if not tasks:
        print(f"[{label}] nothing to do")
        return
    print(f"[{label}] {len(tasks)} calls ({spec['provider']} {spec['model']})", flush=True)

    def work(t):
        if spent() > CFG["budget_usd"]:
            return
        system, user, meta = build(t)
        r = P2.call(spec, system, user, validate=validate)
        r["est_cost_usd"] = cost(r, spec)  # last attempt only; failed attempts are rare and logged
        with _lock:
            P.append_jsonl(out, {**t, **meta, "model_requested": spec["model"], "system_prompt": system,
                                 "user_prompt": user, **r})

    n = 0
    with ThreadPoolExecutor(max_workers=CFG["workers"]) as ex:
        for fu in as_completed([ex.submit(work, t) for t in tasks]):
            fu.result()
            n += 1
            if n % 50 == 0 or n == len(tasks):
                print(f"[{label}] {n}/{len(tasks)}  study spend ${spent():.3f}", flush=True)


def abs_builder(G):
    sp = P.read_text("judge_system_prompt.txt")

    def build(t):
        g = G[t["gen_id"]]
        if t["rubric"] == "old_v1":
            up = P.read_text("judge_prompt.txt").replace("[BRAND]", g["brand"]).replace("[IDEA]", g["text"])
        else:
            up = fill_abs(t["rubric"], g["brand"], g["text"])
        return sp, up, {"brand": g["brand"], "condition": g["condition"], "idea": g["text"]}
    return build


def abs_validate(t):
    return P.parse_judge if t["rubric"] == "old_v1" else NS.parse_abs


def run_abs(tasks, spec, out, label):
    G = gens()
    build = abs_builder(G)
    # validator depends on rubric; split by rubric
    for rub in sorted({t["rubric"] for t in tasks}):
        run([t for t in tasks if t["rubric"] == rub], spec, out, lambda r: (r["gen_id"], r["rubric"], r["pass"]),
            build, P.parse_judge if rub == "old_v1" else NS.parse_abs, f"{label}-{rub}")


def run_pairs(tasks, label):
    G = gens()
    sp = P.read_text("judge_system_prompt.txt")
    tpl = (PROMPTS / "novelty_pair_v1.txt").read_text(encoding="utf-8")

    def build(t):
        up = tpl.replace("[BRAND]", t["brand"]).replace("[IDEA_A]", G[t["A"]]["text"]).replace("[IDEA_B]", G[t["B"]]["text"])
        return sp, up, {"cond_A": G[t["A"]]["condition"], "cond_B": G[t["B"]]["condition"]}

    run(tasks, TESTJ, T_PAIR, lambda r: (r["pair_id"], r["kind"]), build, NS.parse_pair, label)


def shuffled(xs, salt):
    xs = list(xs)
    random.Random(CFG["seed"] + salt).shuffle(xs)
    return xs


# ------------------------------------------------------------------------------ commands
def test_plan(rubric):
    ids = [i for v in SAMPLE["test"].values() for i in v]
    pm = {p["pair_id"]: p for p in SAMPLE["test_pairs"]}
    a1 = [{"gen_id": i, "set": "test", "rubric": r, "pass": 1} for r in (rubric, "old_v1") for i in shuffled(ids, 1)]
    a2 = [{"gen_id": i, "set": "test", "rubric": r, "pass": 2} for r in (rubric, "old_v1") for i in shuffled(ids, 2)]
    p1 = [{**p, "set": "test", "kind": "AB"} for p in shuffled(SAMPLE["test_pairs"], 3)]
    p2 = ([{**p, "A": p["B"], "B": p["A"], "set": "test", "kind": "BA"} for p in shuffled(SAMPLE["test_pairs"], 4)] +
          [{**pm[i], "set": "test", "kind": "AB_repeat"} for i in shuffled(SAMPLE["test_repeat"], 5)])
    return a1, p1, a2, shuffled(p2, 6)


def dev_plan(rubric):
    ids = [i for v in SAMPLE["dev"].values() for i in v]
    cal = [h["gen_id"] for h in human_rows("abs", sets=("calibration",))]
    return ([{"gen_id": i, "set": "dev", "rubric": rubric, "pass": 1} for i in shuffled(ids, 7)] +
            [{"gen_id": i, "set": "human_cal", "rubric": rubric, "pass": 1} for i in cal])


def cmd_estimate():
    tok_abs_in, tok_abs_out = 1350, 200
    tok_old_in, tok_old_out = 1100, 150
    tok_pair_in, tok_pair_out = 700, 120
    d = len(dev_plan("x")) * (1 + CFG["max_dev_revisions"])
    pg = DEVJ["price_usd_per_1m"]
    dev_cost = d * (tok_abs_in * pg["input"] + (tok_abs_out + 1024) * pg["output"]) / 1e6
    a1, p1, a2, p2 = test_plan("x")
    po = TESTJ["price_usd_per_1m"]
    n_new = sum(1 for t in a1 + a2 if t["rubric"] != "old_v1")
    n_old = len(a1) + len(a2) - n_new
    n_pair = len(p1) + len(p2)
    test_cost = (n_new * (tok_abs_in * po["input"] + tok_abs_out * po["output"]) +
                 n_old * (tok_old_in * po["input"] + tok_old_out * po["output"]) +
                 n_pair * (tok_pair_in * po["input"] + tok_pair_out * po["output"])) / 1e6
    print(json.dumps({"gemini_dev_calls_max": d, "gemini_dev_cost_usd_max": round(dev_cost, 2),
                      "openai_test_calls": n_new + n_old + n_pair, "openai_abs_new": n_new, "openai_abs_old": n_old,
                      "openai_pairs": n_pair, "openai_test_cost_usd": round(test_cost, 2),
                      "budget_usd": CFG["budget_usd"], "spent": round(spent(), 3),
                      "assumption": "tokens/call from v2 records; Gemini output includes up to 1024 thinking tokens"}, indent=1))


def cmd_smoke():
    G = gens()
    gid = SAMPLE["dev"][next(iter(SAMPLE["dev"]))][0]
    out = LOGS / "smoke.jsonl"
    for spec in (DEVJ, TESTJ):
        up = fill_abs("novelty_abs_v2b", G[gid]["brand"], G[gid]["text"])
        r = P2.call(spec, P.read_text("judge_system_prompt.txt"), up, validate=NS.parse_abs)
        r["est_cost_usd"] = cost(r, spec)
        P.append_jsonl(out, {"spec": spec["model"], "gen_id": gid, **r})
        print(spec["model"], r.get("ok"), r.get("model_returned"), r.get("parsed", {}).get("novelty"),
              r.get("usage"), round(r["est_cost_usd"], 5), r.get("error"))


def cmd_dev(rubric):
    run_abs(dev_plan(rubric), DEVJ, DEV_ABS, "gemini-dev")
    G = gens()
    recs = {(r["gen_id"], r["rubric"]): r for r in P.load_jsonl(DEV_ABS) if r.get("ok")}
    claude = {r["gen_id"]: r["parsed"] for r in P.load_jsonl(HERE.parent / "novelty_v2/data/abs_judgments.jsonl")
              if r.get("ok") and r["rubric"] == "novelty_abs_v2b" and r["set"] == "dev"}
    ids = [i for v in SAMPLE["dev"].values() for i in v]
    sc = [recs[(i, rubric)]["parsed"]["novelty"] for i in ids if (i, rubric) in recs]
    print("DEV dist", NS.dist(sc)["counts"], "| Claude v2b same ideas", NS.dist([claude[i]["novelty"] for i in ids])["counts"])
    print("recall x score", Counter((recs[(i, rubric)]["parsed"].get("relation_to_closest", recs[(i, rubric)]["parsed"].get("precedent_recall")), recs[(i, rubric)]["parsed"]["novelty"])
                                   for i in ids if (i, rubric) in recs))
    print("Gemini vs Claude (DEV)", NS.agreement([claude[i]["novelty"] for i in ids if (i, rubric) in recs], sc))
    cal = human_rows("abs", sets=("calibration",))
    hv = [h["novelty"] for h in cal]
    gv = [recs[(h["gen_id"], rubric)]["parsed"]["novelty"] for h in cal]
    print("human CALIBRATION (12): human", hv, "gemini", gv, "spearman", round(NS.spearman(hv, gv), 2))


def cmd_freeze(rubric):
    out = LOGS / "freeze.json"
    if out.exists():
        sys.exit("already frozen: " + out.read_text(encoding="utf-8"))
    files = {"rubric": PROMPTS / f"{rubric}.txt", "formats": PROMPTS / "familiar_formats.txt",
             "pair_prompt": PROMPTS / "novelty_pair_v1.txt", "old_judge_prompt": P.PROMPTS / "judge_prompt.txt",
             "judge_system": P.PROMPTS / "judge_system_prompt.txt", "plan": HERE / "ANALYSIS_PLAN_v3.md",
             "config": HERE / "study_config.json", "sample": HERE / CFG["sample_file"],
             "human_abs": HUMAN_DIR / CFG["human_abs_file"], "human_pairs": HUMAN_DIR / CFG["human_pair_file"]}
    rec = {"frozen_at": P.now(), "test_rubric": rubric, "files": {k: str(v) for k, v in files.items()},
           "sha256": {k: sha(v) for k, v in files.items()},
           "note": "OpenAI TEST calls and the human-agreement analysis on human TEST rows were run only after this record."}
    out.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(json.dumps(rec["sha256"], indent=1))


def check_freeze():
    fz = json.loads((LOGS / "freeze.json").read_text(encoding="utf-8"))
    for k, p in fz["files"].items():
        if sha(Path(p)) != fz["sha256"][k]:
            sys.exit(f"{k} changed after freeze; refusing")
    return fz


def cmd_test():
    fz = check_freeze()
    a1, p1, a2, p2 = test_plan(fz["test_rubric"])
    run_abs(a1, TESTJ, T_ABS, "openai-abs-pass1")
    run_pairs(p1, "openai-pairs-AB")
    run_abs(a2, TESTJ, T_ABS, "openai-abs-pass2")
    run_pairs(p2, "openai-pairs-BA+repeat")
    print("study spend", round(spent(), 3))


# ------------------------------------------------------------------------------ analysis
def boot_ci(fn, n_items, n_boot, salt):
    rng = random.Random(CFG["seed"] + salt)
    vals = []
    for _ in range(n_boot):
        idx = [rng.randrange(n_items) for _ in range(n_items)]
        v = fn(idx)
        if v == v:
            vals.append(v)
    vals.sort()
    if not vals:
        return [float("nan"), float("nan")]
    return [vals[int(0.025 * (len(vals) - 1))], vals[int(0.975 * (len(vals) - 1))]]


def verdict_from_points(pa):
    """pa = points of idea A (1 win, .5 similar, 0 loss), possibly averaged over orders."""
    return "A" if pa > 0.5 + 1e-9 else "B" if pa < 0.5 - 1e-9 else "SIMILAR"


def pts_A(rec, a_id):
    """Points for idea a_id from one pair record (handles reversed records)."""
    v = rec["parsed"]["verdict"]
    if v == "SIMILAR":
        return 0.5
    win = rec["A"] if v == "A" else rec["B"]
    return 1.0 if win == a_id else 0.0


def cmd_analyze():
    fz = check_freeze()
    rub = fz["test_rubric"]
    G = gens()
    test_ids = [i for v in SAMPLE["test"].values() for i in v]
    v1 = NS.v1_scores(1)
    c2 = {(r["gen_id"], r["rubric"], r["pass"]): r["parsed"] for r in P.load_jsonl(HERE.parent / "novelty_v2/data/abs_judgments.jsonl") if r.get("ok")}
    c2p = {(r["pair_id"], r["kind"]): r for r in P.load_jsonl(HERE.parent / "novelty_v2/data/pair_judgments.jsonl") if r.get("ok")}
    oa = {(r["gen_id"], r["rubric"], r["pass"]): r["parsed"] for r in P.load_jsonl(T_ABS) if r.get("ok")}
    op = {(r["pair_id"], r["kind"]): r for r in P.load_jsonl(T_PAIR) if r.get("ok")}
    res = {"generated": P.now(), "freeze": fz, "dev_judge": DEVJ["model"], "test_judge": TESTJ["model"]}
    # ---- cost / completeness
    allrec = {"gemini_dev": P.load_jsonl(DEV_ABS), "openai_abs": P.load_jsonl(T_ABS), "openai_pairs": P.load_jsonl(T_PAIR)}
    res["calls"] = {k: {"records": len(v), "ok": sum(1 for r in v if r.get("ok")),
                        "retried": sum(1 for r in v if r.get("n_attempts", 1) > 1),
                        "est_cost_usd": sum(r.get("est_cost_usd") or 0 for r in v),
                        "models_returned": dict(Counter(r.get("model_returned") for r in v))} for k, v in allrec.items()}
    res["calls"]["total_est_cost_usd"] = spent()
    # ---- idea-level scores
    S = {}
    S["claude_old_v1"] = {i: v1[i]["novelty"] for i in test_ids}
    S["claude_old_rerun"] = {i: c2[(i, "old_v1", 3)]["novelty"] for i in test_ids}
    S["claude_v2b_p1"] = {i: c2[(i, "novelty_abs_v2b", 1)]["novelty"] for i in test_ids}
    S["claude_v2b_mean"] = {i: (c2[(i, "novelty_abs_v2b", 1)]["novelty"] + c2[(i, "novelty_abs_v2b", 2)]["novelty"]) / 2 for i in test_ids}
    S["openai_old_p1"] = {i: oa[(i, "old_v1", 1)]["novelty"] for i in test_ids if (i, "old_v1", 1) in oa}
    S["openai_old_mean"] = {i: (oa[(i, "old_v1", 1)]["novelty"] + oa[(i, "old_v1", 2)]["novelty"]) / 2
                            for i in test_ids if (i, "old_v1", 1) in oa and (i, "old_v1", 2) in oa}
    S["openai_new_p1"] = {i: oa[(i, rub, 1)]["novelty"] for i in test_ids if (i, rub, 1) in oa}
    S["openai_new_mean"] = {i: (oa[(i, rub, 1)]["novelty"] + oa[(i, rub, 2)]["novelty"]) / 2
                            for i in test_ids if (i, rub, 1) in oa and (i, rub, 2) in oa}
    S["claude_pair_winrate"] = NS.pair_winrates([c2p[(p["pair_id"], "main")] for p in SAMPLE["test_pairs"]])
    # OpenAI order-averaged pair points
    pts = defaultdict(list)
    ab_only = defaultdict(list)
    for p in SAMPLE["test_pairs"]:
        ab, ba = op.get((p["pair_id"], "AB")), op.get((p["pair_id"], "BA"))
        if ab and ba:
            pa = (pts_A(ab, p["A"]) + pts_A(ba, p["A"])) / 2
            pts[p["A"]].append(pa)
            pts[p["B"]].append(1 - pa)
        if ab:
            ab_only[p["A"]].append(pts_A(ab, p["A"]))
            ab_only[p["B"]].append(1 - pts_A(ab, p["A"]))
    S["openai_pair_winrate_bothorders"] = {k: NS.mean(v) for k, v in pts.items()}
    S["openai_pair_winrate_ABonly"] = {k: NS.mean(v) for k, v in ab_only.items()}
    use_v1 = {i: v1[i]["usefulness"] for i in test_ids}
    # ---- LLM-internal metrics (OpenAI)
    L = res["openai_internal"] = {}
    L["dist"] = {k: NS.dist([oa[(i, r, p)]["novelty"] for i in test_ids if (i, r, p) in oa])
                 for k, (r, p) in {"old_p1": ("old_v1", 1), "old_p2": ("old_v1", 2), "new_p1": (rub, 1), "new_p2": (rub, 2)}.items()}
    L["retest"] = {}
    for name, r in (("old", "old_v1"), ("new", rub)):
        ii = [i for i in test_ids if (i, r, 1) in oa and (i, r, 2) in oa]
        L["retest"][name] = NS.agreement([oa[(i, r, 1)]["novelty"] for i in ii], [oa[(i, r, 2)]["novelty"] for i in ii])
    ii = [i for i in test_ids if (i, "old_v1", 1) in oa and (i, "old_v1", 2) in oa]
    L["retest"]["old_usefulness"] = NS.agreement([oa[(i, "old_v1", 1)]["usefulness"] for i in ii], [oa[(i, "old_v1", 2)]["usefulness"] for i in ii])
    # pairs: position bias & consistency
    abr = [op[(p["pair_id"], "AB")] for p in SAMPLE["test_pairs"] if (p["pair_id"], "AB") in op]
    bar = [op[(p["pair_id"], "BA")] for p in SAMPLE["test_pairs"] if (p["pair_id"], "BA") in op]
    dec = [r for r in abr + bar if r["parsed"]["verdict"] != "SIMILAR"]
    L["pairs"] = {"n_AB": len(abr), "n_BA": len(bar), "verdicts_AB": dict(Counter(r["parsed"]["verdict"] for r in abr)),
                  "verdicts_BA": dict(Counter(r["parsed"]["verdict"] for r in bar)),
                  "share_first_shown_among_decisive": sum(r["parsed"]["verdict"] == "A" for r in dec) / len(dec) if dec else None,
                  "n_decisive": len(dec)}

    def consist(kind2):
        same = opp = n = 0
        for p in SAMPLE["test_pairs"]:
            a, b = op.get((p["pair_id"], "AB")), op.get((p["pair_id"], kind2))
            if not a or not b:
                continue
            n += 1
            wa, wb = NS.winner(a, None), NS.winner(b, None)
            same += wa == wb
            opp += {wa, wb} == {p["A"], p["B"]}
        return {"n": n, "same_outcome": same / n if n else None, "opposite_winner": opp / n if n else None}
    L["pairs"]["reversed_consistency"] = consist("BA")
    L["pairs"]["repeat_consistency"] = consist("AB_repeat")
    L["condition_signal"] = {k: NS.condition_signal(S[k], G, SAMPLE["test"]) for k in
                             ("openai_old_mean", "openai_new_mean", "openai_pair_winrate_bothorders") if len(S[k]) == len(test_ids)}
    L["cross"] = {"spearman_openai_new_vs_claude_v2b": NS.spearman([S["openai_new_mean"][i] for i in test_ids], [S["claude_v2b_mean"][i] for i in test_ids]),
                  "spearman_openai_new_vs_usefulness_v1": NS.spearman([S["openai_new_mean"][i] for i in test_ids], [use_v1[i] for i in test_ids]),
                  "spearman_openai_pair_vs_claude_pair": NS.spearman([S["openai_pair_winrate_bothorders"][i] for i in test_ids], [S["claude_pair_winrate"][i] for i in test_ids])}
    txt = [r["text"] for r in P.load_jsonl(T_ABS) + P.load_jsonl(T_PAIR) if r.get("ok")]
    pat = re.compile(r"never (been )?(done|seen)|no (known )?precedent|unprecedented|first[- ]ever|no one has|nobody has", re.I)
    L["precedent_claims"] = {"n": len(txt), "claims": sum(bool(pat.search(t)) for t in txt),
                             "uncertain_marks": sum("(uncertain)" in t for t in txt)}
    L["precedent_recall_new_p1"] = dict(Counter(oa[(i, rub, 1)].get("relation_to_closest", oa[(i, rub, 1)].get("precedent_recall")) for i in test_ids if (i, rub, 1) in oa))
    # ---- human agreement (TEST rows only; calibration reported separately)
    H = res["human"] = {}
    for sets, tag in ((("test",), "test"), (("calibration",), "calibration")):
        ha = human_rows("abs", sets)
        hp = human_rows("pair", sets)
        blk = H[tag] = {"n_abs": len(ha), "n_pairs": len(hp),
                        "human_novelty_dist": NS.dist([h["novelty"] for h in ha]),
                        "human_pair_verdicts": dict(Counter(h["verdict"] for h in hp))}
        hv = [h["novelty"] for h in ha]
        blk["abs_spearman"] = {}
        for k, sc in S.items():
            if not all(h["gen_id"] in sc for h in ha):
                continue
            xs = [sc[h["gen_id"]] for h in ha]
            rho = NS.spearman(hv, xs)
            ci = boot_ci(lambda idx: NS.spearman([hv[j] for j in idx], [xs[j] for j in idx]), len(ha), CFG["n_boot"], 11) if tag == "test" else None
            e = {"rho": rho, "ci95": ci}
            if k in ("claude_old_v1", "claude_old_rerun", "claude_v2b_p1", "openai_old_p1", "openai_new_p1"):
                e.update(exact=NS.mean(a == b for a, b in zip(hv, xs)), qwk=NS.qwk(hv, [int(x) for x in xs]),
                         mean_llm_minus_human=NS.mean(b - a for a, b in zip(hv, xs)))
            blk["abs_spearman"][k] = e
        # paired bootstrap: each method minus openai_new_mean (the simplest frozen absolute method)
        if tag == "test" and all(h["gen_id"] in S["openai_new_mean"] for h in ha):
            ref = [S["openai_new_mean"][h["gen_id"]] for h in ha]
            blk["abs_diff_vs_openai_new_mean"] = {}
            for k, sc in S.items():
                if k == "openai_new_mean" or not all(h["gen_id"] in sc for h in ha):
                    continue
                xs = [sc[h["gen_id"]] for h in ha]
                blk["abs_diff_vs_openai_new_mean"][k] = {
                    "diff": NS.spearman(hv, xs) - NS.spearman(hv, ref),
                    "ci95": boot_ci(lambda idx: NS.spearman([hv[j] for j in idx], [xs[j] for j in idx]) -
                                    NS.spearman([hv[j] for j in idx], [ref[j] for j in idx]), len(ha), CFG["n_boot"], 12)}
        # pair agreement
        preds = {}
        for h in hp:
            pid = h["pair_id"]
            pr = {}
            if (pid, "main") in c2p:
                pr["claude_pair_AB"] = c2p[(pid, "main")]["parsed"]["verdict"]
            if (pid, "AB") in op:
                pr["openai_pair_AB"] = op[(pid, "AB")]["parsed"]["verdict"]
            if (pid, "AB") in op and (pid, "BA") in op:
                pr["openai_pair_bothorders"] = verdict_from_points((pts_A(op[(pid, "AB")], h["A"]) + pts_A(op[(pid, "BA")], h["A"])) / 2)
            for k in ("claude_old_v1", "claude_old_rerun", "claude_v2b_mean", "openai_old_mean", "openai_new_mean"):
                if h["A"] in S[k] and h["B"] in S[k]:
                    d = S[k][h["A"]] - S[k][h["B"]]
                    pr["abs_" + k] = "A" if d > 1e-9 else "B" if d < -1e-9 else "SIMILAR"
            preds[h["item"]] = pr
        hab = {h["gen_id"]: h["novelty"] for h in human_rows("abs", ("test", "calibration"))}
        blk["pair_agreement"] = {}
        methods = sorted({k for v in preds.values() for k in v}) + ["human_own_absolute"]
        for m in methods:
            rows = []
            for h in hp:
                if m == "human_own_absolute":
                    if h["A"] in hab and h["B"] in hab:
                        d = hab[h["A"]] - hab[h["B"]]
                        rows.append((h["verdict"], "A" if d > 0 else "B" if d < 0 else "SIMILAR"))
                elif m in preds[h["item"]]:
                    rows.append((h["verdict"], preds[h["item"]][m]))
            if not rows:
                continue
            ex = [a == b for a, b in rows]
            dd = [(a == b) for a, b in rows if a != "SIMILAR" and b != "SIMILAR"]
            e = {"n": len(rows), "exact_3way": NS.mean(ex), "n_both_decisive": len(dd),
                 "direction_agree": NS.mean(dd) if dd else None}
            if tag == "test":
                e["exact_ci95"] = boot_ci(lambda idx: NS.mean(ex[j] for j in idx), len(ex), CFG["n_boot"], 13)
            blk["pair_agreement"][m] = e
        # usefulness (bonus: researcher added a usefulness column)
        hu = [(h["usefulness"], h["gen_id"]) for h in ha if h["usefulness"] is not None]
        if hu:
            hv_u = [u for u, _ in hu]
            blk["usefulness"] = {"n": len(hu), "human_dist": NS.dist(hv_u)}
            cu = [v1[g]["usefulness"] for _, g in hu]
            blk["usefulness"]["claude_v1"] = {"rho": NS.spearman(hv_u, cu), "exact": NS.mean(a == b for a, b in zip(hv_u, cu)),
                                              "qwk": NS.qwk(hv_u, cu), "mean_llm_minus_human": NS.mean(b - a for a, b in zip(hv_u, cu))}
            if all((g, "old_v1", 1) in oa for _, g in hu):
                ou = [oa[(g, "old_v1", 1)]["usefulness"] for _, g in hu]
                blk["usefulness"]["openai_old_p1"] = {"rho": NS.spearman(hv_u, ou), "exact": NS.mean(a == b for a, b in zip(hv_u, ou)),
                                                      "qwk": NS.qwk(hv_u, ou), "mean_llm_minus_human": NS.mean(b - a for a, b in zip(hv_u, ou))}
            blk["usefulness"]["human_novelty_vs_human_usefulness_rho"] = NS.spearman([h["novelty"] for h in ha if h["usefulness"] is not None], hv_u)
            if tag == "test":
                blk["usefulness"]["claude_v1"]["ci95"] = boot_ci(lambda idx: NS.spearman([hv_u[j] for j in idx], [cu[j] for j in idx]), len(hu), CFG["n_boot"], 14)
    (RESULTS / "v3_summary.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    write_idea_csv(test_ids, G, S, oa, rub, v1)
    write_report(res)
    figure(res)


def write_idea_csv(test_ids, G, S, oa, rub, v1):
    cols = list(S)
    with open(RESULTS / "v3_test_idea_scores.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["gen_id", "brand", "condition"] + cols + ["openai_old_usefulness_p1", "claude_usefulness_v1", "composite_v1_preserved"])
        for i in sorted(test_ids):
            n, u = v1[i]["novelty"], v1[i]["usefulness"]
            w.writerow([i, G[i]["brand"], G[i]["condition"]] + [repr(S[c][i]) if i in S[c] else "" for c in cols] +
                       [oa.get((i, "old_v1", 1), {}).get("usefulness", ""), u, repr(P.comp_mean(n, u))])


LABEL = {"claude_old_v1": "Claude · old rubric (v1 scores)", "claude_old_rerun": "Claude · old rubric (re-run)",
         "claude_v2b_p1": "Claude · revised v2b (pass 1)", "claude_v2b_mean": "Claude · revised v2b (mean of 2)",
         "openai_old_p1": "GPT-4.1 · old rubric (pass 1)", "openai_old_mean": "GPT-4.1 · old rubric (mean of 2)",
         "openai_new_p1": "GPT-4.1 · revised (pass 1)", "openai_new_mean": "GPT-4.1 · revised (mean of 2)",
         "claude_pair_winrate": "Claude · pairwise win rate (one order)",
         "openai_pair_winrate_bothorders": "GPT-4.1 · pairwise win rate (both orders)",
         "openai_pair_winrate_ABonly": "GPT-4.1 · pairwise win rate (one order)"}


def ff(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def write_report(res):
    fz = res["freeze"]
    L, H = res["openai_internal"], res["human"]
    o = []
    a = o.append
    a("# Novelty measurement v3 — results (auto-generated by novelty_v3.py analyze)\n")
    a(f"- Rubric revision (DEV) judge: `{res['dev_judge']}`; TEST judge: `{res['test_judge']}`; TEST rubric `{fz['test_rubric']}` frozen at {fz['frozen_at']}.")
    c = res["calls"]
    a(f"- Calls: Gemini DEV {c['gemini_dev']['ok']} ok, OpenAI absolute {c['openai_abs']['ok']} ok, OpenAI pairs {c['openai_pairs']['ok']} ok; "
      f"estimated API cost ${c['total_est_cost_usd']:.2f} (list prices × recorded tokens; the provider invoice is authoritative).")
    a("- Human ratings: one rater (the researcher), blind to condition and LLM scores. **Agreement is reported on human TEST rows only**; calibration rows are listed separately. With n = 43 ideas / 24 pairs the intervals are wide.\n")
    t = H["test"]
    a(f"## 1. Agreement with the human absolute novelty rating (TEST rows, n = {t['n_abs']})\n")
    hd = t["human_novelty_dist"]
    a(f"Human distribution 1–5: {hd['counts']} (mean {hd['mean']:.2f}, share 4–5 {hd['share_4_5']*100:.0f}%).\n")
    a("| Method | Spearman ρ | 95% CI | exact | weighted κ | mean (LLM − human) |")
    a("|---|---|---|---|---|---|")
    for k, e in sorted(t["abs_spearman"].items(), key=lambda kv: -(kv[1]["rho"] if kv[1]["rho"] == kv[1]["rho"] else -9)):
        a(f"| {LABEL.get(k, k)} | {ff(e['rho'])} | [{ff(e['ci95'][0])}, {ff(e['ci95'][1])}] | "
          f"{ff(e.get('exact', None) and e['exact']*100, 0) + '%' if 'exact' in e else '—'} | {ff(e.get('qwk'))} | {ff(e.get('mean_llm_minus_human'))} |")
    if "abs_diff_vs_openai_new_mean" in t:
        a("\nDifference in ρ versus *GPT-4.1 · revised (mean of 2)* (paired bootstrap):\n")
        a("| Method | Δρ | 95% CI |")
        a("|---|---|---|")
        for k, e in t["abs_diff_vs_openai_new_mean"].items():
            a(f"| {LABEL.get(k, k)} | {e['diff']:+.2f} | [{e['ci95'][0]:+.2f}, {e['ci95'][1]:+.2f}] |")
    a(f"\n## 2. Agreement with the human pairwise judgement (TEST rows, n = {t['n_pairs']})\n")
    a(f"Human verdicts: {t['human_pair_verdicts']}. Absolute methods predict the pair by the sign of the score difference (equal → SIMILAR).\n")
    a("| Method | exact (A/B/SIMILAR) | 95% CI | direction agree when both decisive |")
    a("|---|---|---|---|")
    for k, e in sorted(t["pair_agreement"].items(), key=lambda kv: -kv[1]["exact_3way"]):
        a(f"| {k} | {e['exact_3way']*100:.0f}% | [{e['exact_ci95'][0]*100:.0f}%, {e['exact_ci95'][1]*100:.0f}%] | "
          f"{ff(e['direction_agree'] and e['direction_agree']*100, 0)}% (n={e['n_both_decisive']}) |")
    if "usefulness" in t:
        u = t["usefulness"]
        a(f"\n## 3. Usefulness (the rater added a usefulness column; n = {u['n']})\n")
        a(f"Human 1–5: {u['human_dist']['counts']}. Claude v1: ρ {ff(u['claude_v1']['rho'])} [{ff(u['claude_v1']['ci95'][0])}, {ff(u['claude_v1']['ci95'][1])}], "
          f"exact {u['claude_v1']['exact']*100:.0f}%, κ {ff(u['claude_v1']['qwk'])}, mean shift {u['claude_v1']['mean_llm_minus_human']:+.2f}."
          + (f" GPT-4.1 (old rubric): ρ {ff(u['openai_old_p1']['rho'])}, exact {u['openai_old_p1']['exact']*100:.0f}%, κ {ff(u['openai_old_p1']['qwk'])}, mean shift {u['openai_old_p1']['mean_llm_minus_human']:+.2f}." if 'openai_old_p1' in u else ""))
        a(f"Human novelty vs human usefulness: ρ {ff(u['human_novelty_vs_human_usefulness_rho'])}.")
    cb = H["calibration"]
    a(f"\n(Calibration rows, not used for agreement claims: n = {cb['n_abs']} ideas, {cb['n_pairs']} pairs; "
      + ", ".join(f"{k} ρ {ff(v['rho'])}" for k, v in cb["abs_spearman"].items() if k in ("claude_old_v1", "openai_new_p1", "claude_v2b_p1")) + ".)")
    a("\n## 4. GPT-4.1 judge on all 110 TEST ideas\n")
    a("| Score set | 1 | 2 | 3 | 4 | 5 | share 4–5 | mean |")
    a("|---|---|---|---|---|---|---|---|")
    for k, d in L["dist"].items():
        a(f"| {k} | " + " | ".join(map(str, d["counts"])) + f" | {d['share_4_5']*100:.0f}% | {d['mean']:.2f} |")
    a("\n| Retest (pass 1 vs 2) | exact | ±1 | weighted κ | Spearman |")
    a("|---|---|---|---|---|")
    for k, g in L["retest"].items():
        a(f"| {k} | {g['exact']*100:.0f}% | {g['within1']*100:.0f}% | {ff(g['qwk'])} | {ff(g['spearman'])} |")
    pp = L["pairs"]
    a(f"\nPairs: first-shown idea chosen in {pp['share_first_shown_among_decisive']*100:.1f}% of {pp['n_decisive']} decisive verdicts (AB and BA runs). "
      f"Same order repeated: same outcome {pp['repeat_consistency']['same_outcome']*100:.0f}% (n={pp['repeat_consistency']['n']}); "
      f"order reversed: same outcome {pp['reversed_consistency']['same_outcome']*100:.0f}%, opposite winner {pp['reversed_consistency']['opposite_winner']*100:.0f}% (n={pp['reversed_consistency']['n']}).")
    a("\n| Condition separation (GPT-4.1) | perm p | signal ratio | cell r |")
    a("|---|---|---|---|")
    for k, cs in L["condition_signal"].items():
        a(f"| {LABEL.get(k, k)} | {cs['perm_p']:.3f} | {cs['signal_ratio']:.2f} | {cs['within_cell_r']:.2f} |")
    cr = L["cross"]
    a(f"\nCross-judge: GPT-4.1 revised vs Claude v2b ρ {ff(cr['spearman_openai_new_vs_claude_v2b'])}; GPT-4.1 vs Claude pairwise win rates ρ {ff(cr['spearman_openai_pair_vs_claude_pair'])}; "
      f"GPT-4.1 revised novelty vs v1 usefulness ρ {ff(cr['spearman_openai_new_vs_usefulness_v1'])}. "
      f"'No precedent' claims: {L['precedent_claims']['claims']}/{L['precedent_claims']['n']}; precedent_recall (revised pass 1): {L['precedent_recall_new_p1']}.")
    (RESULTS / "v3_results.md").write_text("\n".join(o) + "\n", encoding="utf-8")
    print("wrote", RESULTS / "v3_results.md")


def figure(res):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    t = res["human"]["test"]["abs_spearman"]
    keys = sorted(t, key=lambda k: t[k]["rho"])
    ink, muted, grid = "#1f2328", "#59636e", "#d8dee4"
    col = {"claude": "#8c959f", "openai": "#2a78d6"}
    fig, ax = plt.subplots(figsize=(7.6, 0.42 * len(keys) + 1.2), dpi=150)
    for y, k in enumerate(keys):
        e = t[k]
        c = col["openai"] if k.startswith("openai") else col["claude"]
        ax.plot(e["ci95"], [y, y], color=c, lw=2, solid_capstyle="round", zorder=2)
        ax.scatter([e["rho"]], [y], color=c, s=40, zorder=3, edgecolor="white", linewidth=1.2,
                   marker="D" if "pair" in k else "o")
        ax.text(e["ci95"][1] + 0.02, y, f"{e['rho']:.2f}", va="center", fontsize=7, color=muted)
    ax.axvline(0, color=muted, lw=0.8)
    ax.set_yticks(range(len(keys)))
    ax.set_yticklabels([LABEL.get(k, k) for k in keys], fontsize=7.5, color=ink)
    ax.set_xlabel("Spearman ρ with the human novelty rating (95% bootstrap CI)", fontsize=8, color=ink)
    ax.grid(axis="x", color=grid, lw=0.6, zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_title(f"Agreement with one human rater, TEST ideas (n = {res['human']['test']['n_abs']})", fontsize=9, color=ink, loc="left")
    fig.tight_layout()
    (RESULTS / "figures").mkdir(exist_ok=True)
    fig.savefig(RESULTS / "figures" / "v3_human_agreement.png")
    plt.close(fig)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    {"estimate": cmd_estimate, "smoke": cmd_smoke, "dev": lambda: cmd_dev(arg or "novelty_abs_v2b"),
     "freeze": lambda: cmd_freeze(arg or sys.exit("rubric stem required")), "test": cmd_test,
     "analyze": cmd_analyze}.get(cmd, lambda: print(__doc__))()
