"""Novelty-measurement study on the existing pilot v1 ideas (no regeneration).

Compares three ways of scoring novelty on the same ideas:
  1. old 1-5 absolute rubric (pilot v1 judge prompt; v1 scores + one fresh re-run)
  2. revised 1-5 absolute rubric (prompts/novelty_abs_v2*.txt; novelty only)
  3. same-brand pairwise comparison (prompts/novelty_pair_v1.txt; A / B / SIMILAR)

Data are split into DEV (prompt checking, may be looked at while adjusting prompts) and
TEST (final check; run only after `freeze`). The judge never sees condition labels or
earlier scores. Pilot v1 files are only read, never written.

Commands (run from this folder):
  python novelty_study.py sample        # split DEV/TEST, build pair design (seeded)
  python novelty_study.py dev [rubric]  # DEV: absolute (rubric file stem, default novelty_abs_v2) + DEV pairs
  python novelty_study.py freeze <rubric>   # hash the prompts/spec used for TEST
  python novelty_study.py test          # TEST: new abs x2, old rubric re-run, pairs (+reversed, repeat)
  python novelty_study.py analyze       # results/*  (run with uv + numpy + matplotlib for figures)
  python novelty_study.py human         # ../../../human_rating_blind_novelty/ (+ key kept here)
  python novelty_study.py estimate      # planned calls and cost estimate only
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pilot as P  # noqa: E402  (pilot v1 module: CLI call, retry, pool, IO helpers)

PROMPTS = HERE / "prompts"
DATA = HERE / "data"
LOGS = HERE / "logs"
RESULTS = HERE / "results"
CFG = json.loads((HERE / "study_config.json").read_text(encoding="utf-8"))
SEED = CFG["seed"]
JUDGE = CFG["judge_model"]
ABS = DATA / "abs_judgments.jsonl"
PAIR = DATA / "pair_judgments.jsonl"
CONDS = P.CONDITIONS
HUMAN_DIR = HERE.parents[2] / "human_rating_blind_novelty"
HUMAN_KEY = HERE / "human_key_DO_NOT_OPEN_until_rating_done"


# --------------------------------------------------------------------------------- io
def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gens() -> dict[str, dict]:
    return {g["gen_id"]: g for g in P.load_jsonl(P.DATA / "generations.jsonl") if g.get("ok")}


def v1_scores(pass_no=1) -> dict[str, dict]:
    return {j["gen_id"]: j["parsed"] for j in P.load_jsonl(P.DATA / "judgments.jsonl")
            if j.get("ok") and j["pass"] == pass_no}


def spent() -> float:
    tot = 0.0
    for f in (ABS, PAIR):
        for r in P.load_jsonl(f):
            tot += float(r.get("attempts_cost_usd") or 0)
    return tot


def sample() -> dict:
    return json.loads((LOGS / "sample.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------- parsing
def parse_abs(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
        n = int(j["novelty"])
    except Exception:
        return None
    if not 1 <= n <= 5:
        return None
    j["novelty"] = n
    return j


def parse_pair(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
        v = str(j["verdict"]).strip().upper()
    except Exception:
        return None
    if v not in ("A", "B", "SIMILAR"):
        return None
    j["verdict"] = v
    return j


# -------------------------------------------------------------------------- sample
def cmd_sample() -> None:
    out = LOGS / "sample.json"
    if out.exists():
        print("sample.json exists; not overwritten")
        return
    G = gens()
    rng = random.Random(SEED)
    brands = sorted({g["brand"] for g in G.values()})
    cell = defaultdict(list)
    for gid, g in sorted(G.items()):
        cell[(g["brand"], g["condition"])].append(gid)
    dev, test = {}, {}
    for b in brands:
        for c in CONDS:
            ids = sorted(cell[(b, c)])
            rng.shuffle(ids)
            dev[f"{b}|{c}"] = ids[:CFG["dev_per_cell"]]
            test[f"{b}|{c}"] = ids[CFG["dev_per_cell"]:CFG["dev_per_cell"] + CFG["test_per_cell"]]

    def round_robin(perm):
        """Regular tournament on 11 conditions: each is shown first (A) in 5 and second in 5."""
        m = []
        k = len(perm)
        for i in range(k):
            for j in range(i + 1, k):
                d = j - i
                m.append((perm[i], perm[j]) if d <= (k - 1) // 2 else (perm[j], perm[i]))
        return m

    test_pairs, dev_pairs = [], []
    for b in brands:
        perm = CONDS[:]
        rng.shuffle(perm)
        matches = round_robin(perm)
        # which of the 2 TEST ideas of a condition plays each match: 5 matches per idea,
        # A/B positions split 3/2 or 2/3 per idea
        side_idea = {}
        for c in CONDS:
            a_m = [i for i, (x, _) in enumerate(matches) if x == c]
            b_m = [i for i, (_, y) in enumerate(matches) if y == c]
            k = rng.choice([2, 3])
            a0 = set(rng.sample(a_m, k))
            b0 = set(rng.sample(b_m, 5 - k))
            for i in a_m:
                side_idea[(i, "A")] = 0 if i in a0 else 1
            for i in b_m:
                side_idea[(i, "B")] = 0 if i in b0 else 1
        for i, (ca, cb) in enumerate(matches):
            ga = test[f"{b}|{ca}"][side_idea[(i, "A")]]
            gb = test[f"{b}|{cb}"][side_idea[(i, "B")]]
            test_pairs.append({"pair_id": f"T{b[:3]}{i:02d}", "brand": b, "A": ga, "B": gb})
        # DEV: one idea per condition; random subset of the round robin
        perm2 = CONDS[:]
        rng.shuffle(perm2)
        sub = rng.sample(round_robin(perm2), CFG["dev_pairs_per_brand"])
        for i, (ca, cb) in enumerate(sub):
            dev_pairs.append({"pair_id": f"D{b[:3]}{i:02d}", "brand": b,
                              "A": dev[f"{b}|{ca}"][0], "B": dev[f"{b}|{cb}"][0]})
    reversed_ids, repeat_ids, dev_rev = [], [], []
    for b in brands:
        ids = [p["pair_id"] for p in test_pairs if p["brand"] == b]
        pick = rng.sample(ids, CFG["reversed_per_brand"] + CFG["repeat_per_brand"])
        reversed_ids += pick[:CFG["reversed_per_brand"]]
        repeat_ids += pick[CFG["reversed_per_brand"]:]
        dids = [p["pair_id"] for p in dev_pairs if p["brand"] == b]
        dev_rev += rng.sample(dids, CFG["dev_reversed_per_brand"])
    rec = {"created": P.now(), "seed": SEED, "method": (
        "Per brand x condition cell (6 ideas), shuffle with random.Random(seed): first "
        f"{CFG['dev_per_cell']} -> DEV, next {CFG['test_per_cell']} -> TEST, rest unused. "
        "TEST pairs: per brand, conditions randomly ordered, then all 55 condition pairs once "
        "(regular tournament: each condition is A in 5 and B in 5); each TEST idea plays 5 matches "
        "with A/B split 3/2 or 2/3. Reversed (B,A) and same-order repeat subsets sampled per brand. "
        "DEV pairs: random subset of a separately ordered round robin, one DEV idea per condition."),
        "dev": dev, "test": test, "test_pairs": test_pairs, "dev_pairs": dev_pairs,
        "test_reversed": reversed_ids, "test_repeat": repeat_ids, "dev_reversed": dev_rev}
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    # balance report
    cnt = Counter()
    pos = Counter()
    for p in test_pairs:
        for side in ("A", "B"):
            c = G[p[side]]["condition"]
            cnt[(p["brand"], c)] += 1
            pos[(c, side)] += 1
    print("TEST pairs", len(test_pairs), "per brand-cond appearances",
          sorted(set(cnt.values())), "A/B per condition", sorted({(pos[(c,'A')], pos[(c,'B')]) for c in CONDS}))
    print("DEV ideas", sum(len(v) for v in dev.values()), "TEST ideas", sum(len(v) for v in test.values()),
          "DEV pairs", len(dev_pairs))


# ------------------------------------------------------------------------- calling
def fill_abs(tpl: str, g: dict) -> str:
    return (tpl.replace("[FORMATS]", (PROMPTS / "familiar_formats.txt").read_text(encoding="utf-8").strip())
            .replace("[BRAND]", g["brand"]).replace("[IDEA]", g["text"]))


def run_abs(tasks: list[dict], label: str) -> None:
    """tasks: {gen_id, set, rubric, pass}. rubric 'old_v1' uses the pilot v1 judge prompt."""
    G = gens()
    done = {(r["gen_id"], r["rubric"], r["pass"]) for r in P.load_jsonl(ABS) if r.get("ok")}
    tasks = [t for t in tasks if (t["gen_id"], t["rubric"], t["pass"]) not in done]
    sp = P.read_text("judge_system_prompt.txt")

    def work(t):
        if spent() > CFG["study_budget_usd"]:
            return
        g = G[t["gen_id"]]
        if t["rubric"] == "old_v1":
            up = P.read_text("judge_prompt.txt").replace("[BRAND]", g["brand"]).replace("[IDEA]", g["text"])
            val = P.parse_judge
        else:
            up = fill_abs((PROMPTS / f"{t['rubric']}.txt").read_text(encoding="utf-8"), g)
            val = parse_abs
        r = P.call_with_retry(sp, up, JUDGE, validate=val)
        P.append_jsonl(ABS, {**t, "phase": "novelty_abs", "model_requested": JUDGE, "brand": g["brand"],
                             "condition": g["condition"], "idea": g["text"],
                             "system_prompt": sp, "user_prompt": up, **r})

    P.run_pool(tasks, work, label)


def run_pairs(tasks: list[dict], label: str) -> None:
    """tasks: {pair_id, set, kind, brand, A, B, prompt}."""
    G = gens()
    done = {(r["pair_id"], r["kind"]) for r in P.load_jsonl(PAIR) if r.get("ok")}
    tasks = [t for t in tasks if (t["pair_id"], t["kind"]) not in done]
    sp = P.read_text("judge_system_prompt.txt")

    def work(t):
        if spent() > CFG["study_budget_usd"]:
            return
        tpl = (PROMPTS / f"{t['prompt']}.txt").read_text(encoding="utf-8")
        up = (tpl.replace("[BRAND]", t["brand"]).replace("[IDEA_A]", G[t["A"]]["text"])
              .replace("[IDEA_B]", G[t["B"]]["text"]))
        r = P.call_with_retry(sp, up, JUDGE, validate=parse_pair)
        # conditions stored for analysis only; never shown to the judge
        P.append_jsonl(PAIR, {**t, "phase": "novelty_pair", "model_requested": JUDGE,
                              "cond_A": G[t["A"]]["condition"], "cond_B": G[t["B"]]["condition"],
                              "system_prompt": sp, "user_prompt": up, **r})

    P.run_pool(tasks, work, label)


def shuffled(xs, salt):
    xs = list(xs)
    random.Random(SEED + salt).shuffle(xs)
    return xs


def dev_tasks(rubric):
    S = sample()
    ids = [i for v in S["dev"].values() for i in v]
    abs_t = [{"gen_id": i, "set": "dev", "rubric": rubric, "pass": 1} for i in shuffled(ids, 11)]
    pm = {p["pair_id"]: p for p in S["dev_pairs"]}
    pr = [{**p, "set": "dev", "kind": "main", "prompt": CFG["pair_prompt"]} for p in shuffled(S["dev_pairs"], 12)]
    pr += [{**pm[i], "A": pm[i]["B"], "B": pm[i]["A"], "set": "dev", "kind": "reversed",
            "prompt": CFG["pair_prompt"]} for i in shuffled(S["dev_reversed"], 13)]
    return abs_t, pr


def test_tasks(rubric):
    S = sample()
    ids = [i for v in S["test"].values() for i in v]
    pm = {p["pair_id"]: p for p in S["test_pairs"]}
    wave1_abs = ([{"gen_id": i, "set": "test", "rubric": rubric, "pass": 1} for i in shuffled(ids, 21)] +
                 [{"gen_id": i, "set": "test", "rubric": "old_v1", "pass": 3} for i in shuffled(ids, 22)])
    wave1_pair = [{**p, "set": "test", "kind": "main", "prompt": CFG["pair_prompt"]}
                  for p in shuffled(S["test_pairs"], 23)]
    wave2_abs = [{"gen_id": i, "set": "test", "rubric": rubric, "pass": 2} for i in shuffled(ids, 24)]
    wave2_pair = ([{**pm[i], "A": pm[i]["B"], "B": pm[i]["A"], "set": "test", "kind": "reversed",
                    "prompt": CFG["pair_prompt"]} for i in S["test_reversed"]] +
                  [{**pm[i], "set": "test", "kind": "repeat", "prompt": CFG["pair_prompt"]}
                   for i in S["test_repeat"]])
    return wave1_abs, wave1_pair, wave2_abs, shuffled(wave2_pair, 25)


def cmd_estimate() -> None:
    S = sample()
    a, p = dev_tasks("x")
    w1a, w1p, w2a, w2p = test_tasks("x")
    n_abs, n_pair = len(a) * (1 + CFG["max_dev_revisions"]) + len(w1a) + len(w2a), len(p) + len(w1p) + len(w2p)
    c = CFG["est_cost_per_call_usd"]
    print(json.dumps({"dev_abs_per_rubric": len(a), "dev_pairs": len(p), "test_abs": len(w1a) + len(w2a),
                      "test_pairs": len(w1p) + len(w2p), "max_calls": n_abs + n_pair,
                      "est_cost_per_call_usd": c, "max_est_cost_usd": round((n_abs + n_pair) * c, 2),
                      "study_budget_usd": CFG["study_budget_usd"], "spent_so_far": round(spent(), 3)}, indent=1))


def cmd_dev(rubric: str) -> None:
    a, p = dev_tasks(rubric)
    run_abs(a, f"dev-abs-{rubric}")
    if not any(r.get("set") == "dev" for r in P.load_jsonl(PAIR) if r.get("ok")) or "--pairs" in sys.argv:
        run_pairs(p, "dev-pairs")
    print("spent (study total)", round(spent(), 3))


def cmd_freeze(rubric: str) -> None:
    out = LOGS / "freeze.json"
    if out.exists():
        print("already frozen:", out.read_text(encoding="utf-8"))
        return
    files = [PROMPTS / f"{rubric}.txt", PROMPTS / "familiar_formats.txt", PROMPTS / f"{CFG['pair_prompt']}.txt",
             P.PROMPTS / "judge_prompt.txt", P.PROMPTS / "judge_system_prompt.txt", HERE / "ANALYSIS_PLAN.md",
             HERE / "study_config.json", LOGS / "sample.json"]
    rec = {"frozen_at": P.now(), "test_rubric": rubric, "sha256": {f.name: sha(f) for f in files},
           "note": "TEST judgments were requested only after this record was written."}
    out.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(json.dumps(rec, indent=1))


def cmd_test() -> None:
    fz = json.loads((LOGS / "freeze.json").read_text(encoding="utf-8"))
    for name, h in fz["sha256"].items():
        f = next(p for p in [PROMPTS / name, P.PROMPTS / name, HERE / name, LOGS / name] if p.exists())
        if sha(f) != h:
            sys.exit(f"{name} changed after freeze; refusing to run TEST")
    w1a, w1p, w2a, w2p = test_tasks(fz["test_rubric"])
    run_abs(w1a, "test-abs-wave1")
    run_pairs(w1p, "test-pairs-main")
    run_abs(w2a, "test-abs-retest")
    run_pairs(w2p, "test-pairs-reversed-repeat")
    print("spent (study total)", round(spent(), 3))


# ------------------------------------------------------------------------ statistics
def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def spearman(a, b):
    return P.pearson(P.rank(a), P.rank(b))


def qwk(a, b, k=5):
    n = len(a)
    O = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        O[x - 1][y - 1] += 1
    ha = [sum(O[i]) for i in range(k)]
    hb = [sum(O[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = (i - j) ** 2 / (k - 1) ** 2
            num += w * O[i][j]
            den += w * ha[i] * hb[j] / n
    return 1 - num / den if den else float("nan")


def agreement(a, b):
    return {"n": len(a), "exact": mean(x == y for x, y in zip(a, b)),
            "within1": mean(abs(x - y) <= 1 for x, y in zip(a, b)),
            "qwk": qwk(a, b), "spearman": spearman(a, b), "mean_diff_2_minus_1": mean(y - x for x, y in zip(a, b))}


def dist(xs):
    c = Counter(xs)
    n = len(xs)
    p = [c.get(k, 0) / n for k in range(1, 6)]
    ent = -sum(q * math.log2(q) for q in p if q > 0)
    m = mean(xs)
    return {"n": n, "counts": [c.get(k, 0) for k in range(1, 6)], "share_4_5": p[3] + p[4],
            "mean": m, "sd": math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)), "entropy_bits": ent}


def condition_signal(idea_score: dict[str, float], G, test: dict, n_perm=5000, salt=31):
    """idea_score: gen_id -> score (TEST ideas). Condition scores are brand-equal means.
    Returns spread of condition means, permutation p (labels shuffled within brand), and the
    within-cell consistency r (idea #1 vs idea #2 of each brand x condition cell, brand-centred)."""
    brands = sorted({k.split("|")[0] for k in test})

    def cond_means(lab):
        out = {}
        for c in CONDS:
            out[c] = mean(mean(idea_score[i] for i in lab[(b, c)]) for b in brands)
        return out

    lab = {(b, c): test[f"{b}|{c}"] for b in brands for c in CONDS}
    cm = cond_means(lab)
    gm = mean(cm.values())
    stat = mean((v - gm) ** 2 for v in cm.values())
    rng = random.Random(SEED + salt)
    ge = 0
    null = []
    for _ in range(n_perm):
        plab = {}
        for b in brands:
            ids = [i for c in CONDS for i in lab[(b, c)]]
            rng.shuffle(ids)
            for k, c in enumerate(CONDS):
                plab[(b, c)] = ids[2 * k:2 * k + 2]
        pm = cond_means(plab)
        g2 = mean(pm.values())
        s = mean((v - g2) ** 2 for v in pm.values())
        null.append(s)
        ge += s >= stat - 1e-12
    bm = {b: mean(idea_score[i] for c in CONDS for i in lab[(b, c)]) for b in brands}
    x = [idea_score[lab[(b, c)][0]] - bm[b] for b in brands for c in CONDS]
    y = [idea_score[lab[(b, c)][1]] - bm[b] for b in brands for c in CONDS]
    total_var = mean((idea_score[i] - bm[b]) ** 2 for b in brands for c in CONDS for i in lab[(b, c)])
    return {"condition_means": cm, "var_condition_means": stat, "null_mean_var": mean(null),
            "signal_ratio": stat / mean(null) if mean(null) else float("nan"),
            "perm_p": (ge + 1) / (n_perm + 1), "within_cell_r": P.pearson(x, y),
            "idea_var_within_brand": total_var}


# -------------------------------------------------------------------------- analyze
def latest(recs, key):
    out = {}
    for r in recs:
        if r.get("ok"):
            out[key(r)] = r
    return out


def cmd_analyze() -> None:
    G = gens()
    S = sample()
    fz = json.loads((LOGS / "freeze.json").read_text(encoding="utf-8")) if (LOGS / "freeze.json").exists() else None
    A = P.load_jsonl(ABS)
    PR = P.load_jsonl(PAIR)
    v1 = v1_scores(1)
    v1b = v1_scores(2)
    absr = latest(A, lambda r: (r["gen_id"], r["rubric"], r["pass"]))
    pr = latest(PR, lambda r: (r["pair_id"], r["kind"]))
    res = {"generated": P.now(), "freeze": fz, "judge": JUDGE, "cost": {}, "dev": {}, "test": {}}
    # ----- cost & failures
    for name, recs in (("abs", A), ("pair", PR)):
        res["cost"][name] = {"records": len(recs), "ok": sum(1 for r in recs if r.get("ok")),
                             "usd_nominal": sum(float(r.get("attempts_cost_usd") or 0) for r in recs),
                             "retried": sum(1 for r in recs if r.get("n_attempts", 1) > 1)}
    res["cost"]["total_usd_nominal"] = res["cost"]["abs"]["usd_nominal"] + res["cost"]["pair"]["usd_nominal"]
    # ----- DEV
    dev_ids = [i for v in S["dev"].values() for i in v]
    for rub in sorted({r["rubric"] for r in A if r.get("set") == "dev"}):
        sc = [absr[(i, rub, 1)]["parsed"]["novelty"] for i in dev_ids if (i, rub, 1) in absr]
        res["dev"][rub] = {"dist": dist(sc), "old_v1_same_ideas": dist([v1[i]["novelty"] for i in dev_ids])}
    dpairs = {p["pair_id"]: p for p in S["dev_pairs"]}
    dm = [pr[(i, "main")] for i in dpairs if (i, "main") in pr]
    res["dev"]["pairs"] = pair_stats(dm, [pr[(i, "reversed")] for i in S["dev_reversed"] if (i, "reversed") in pr],
                                     pr, "main", "reversed")
    # ----- TEST
    test_ids = [i for v in S["test"].values() for i in v]
    rub = fz["test_rubric"] if fz else None
    have_test = rub and all((i, rub, 1) in absr for i in test_ids)
    if have_test:
        T = res["test"]
        new1 = {i: absr[(i, rub, 1)]["parsed"]["novelty"] for i in test_ids}
        new2 = {i: absr[(i, rub, 2)]["parsed"]["novelty"] for i in test_ids if (i, rub, 2) in absr}
        old1 = {i: v1[i]["novelty"] for i in test_ids}
        old3 = {i: absr[(i, "old_v1", 3)]["parsed"]["novelty"] for i in test_ids if (i, "old_v1", 3) in absr}
        use1 = {i: v1[i]["usefulness"] for i in test_ids}
        T["dist"] = {"old_v1_pass1": dist(list(old1.values())), "old_rerun": dist(list(old3.values())),
                     "new_pass1": dist(list(new1.values())), "new_pass2": dist(list(new2.values())),
                     "old_v1_all330_context": dist([s["novelty"] for s in v1.values()])}
        ids3 = [i for i in test_ids if i in old3]
        ids2 = [i for i in test_ids if i in new2]
        T["retest"] = {"old_v1_pass1_vs_old_rerun": agreement([old1[i] for i in ids3], [old3[i] for i in ids3]),
                       "new_pass1_vs_new_pass2": agreement([new1[i] for i in ids2], [new2[i] for i in ids2]),
                       "old_v1_original_retest_66_context": agreement(
                           [v1[i]["novelty"] for i in v1b], [v1b[i]["novelty"] for i in v1b])}
        T["cross_method"] = {"spearman_new1_old1": spearman([new1[i] for i in test_ids], [old1[i] for i in test_ids]),
                             "spearman_new1_usefulness_v1": spearman([new1[i] for i in test_ids],
                                                                     [use1[i] for i in test_ids]),
                             "spearman_old1_usefulness_v1": spearman([old1[i] for i in test_ids],
                                                                     [use1[i] for i in test_ids])}
        newm = {i: mean([new1[i]] + ([new2[i]] if i in new2 else [])) for i in test_ids}
        tp = {p["pair_id"]: p for p in S["test_pairs"]}
        mains = [pr[(i, "main")] for i in tp if (i, "main") in pr]
        win = pair_winrates(mains)
        T["pairs"] = pair_stats(mains, [pr[(i, "reversed")] for i in S["test_reversed"] if (i, "reversed") in pr],
                                pr, "main", "reversed",
                                repeats=[pr[(i, "repeat")] for i in S["test_repeat"] if (i, "repeat") in pr])
        T["condition_signal"] = {
            "old_v1_pass1": condition_signal(old1, G, S["test"]),
            "new_pass1": condition_signal(new1, G, S["test"]),
            "new_mean_pass1_2": condition_signal(newm, G, S["test"]),
            "pair_winrate": condition_signal(win, G, S["test"]) if len(win) == len(test_ids) else None}
        if old3 and len(old3) == len(test_ids):
            T["condition_signal"]["old_rerun"] = condition_signal(old3, G, S["test"])
        # concordance of absolute scores with pairwise verdicts (main pairs)
        conc = {}
        for name, sc in (("old_v1_pass1", old1), ("old_rerun", old3), ("new_pass1", new1), ("new_mean", newm)):
            dec = agr = tie_eq = ties = n_absdiff = 0
            for r in mains:
                v = r["parsed"]["verdict"]
                if r["A"] not in sc or r["B"] not in sc:
                    continue
                d = sc[r["A"]] - sc[r["B"]]
                if v == "SIMILAR":
                    ties += 1
                    tie_eq += abs(d) < 1e-9
                    continue
                if abs(d) < 1e-9:
                    continue
                n_absdiff += 1
                agr += (d > 0) == (v == "A")
            dec = sum(1 for r in mains if r["parsed"]["verdict"] != "SIMILAR")
            conc[name] = {"pair_decisive": dec, "decisive_and_abs_differs": n_absdiff,
                          "agree_rate": agr / n_absdiff if n_absdiff else float("nan"),
                          "abs_equal_when_pair_similar": tie_eq / ties if ties else float("nan")}
        T["concordance_with_pairwise"] = conc
        # rationale audit
        txt = [absr[(i, rub, p)]["text"] for i in test_ids for p in (1, 2) if (i, rub, p) in absr]
        old_txt = [absr[(i, "old_v1", 3)]["text"] for i in ids3]
        pat = re.compile(r"never (been )?(done|seen)|no (known )?precedent|unprecedented|first[- ]ever|"
                         r"no one has|nobody has", re.I)
        T["rationale_audit"] = {"new_abs_n": len(txt), "new_abs_precedent_claims": sum(bool(pat.search(t)) for t in txt),
                                "new_abs_uncertain_marks": sum("(uncertain)" in t for t in txt),
                                "old_rerun_n": len(old_txt),
                                "old_rerun_precedent_claims": sum(bool(pat.search(t)) for t in old_txt),
                                "pair_n": len(mains),
                                "pair_precedent_claims": sum(bool(pat.search(r["text"])) for r in mains),
                                "regex": pat.pattern}
        recall = Counter(absr[(i, rub, 1)]["parsed"].get("precedent_recall") for i in test_ids)
        T["precedent_recall_new_pass1"] = dict(recall)
        by_recall = defaultdict(list)
        for i in test_ids:
            by_recall[absr[(i, rub, 1)]["parsed"].get("precedent_recall")].append(new1[i])
        T["novelty_by_recall"] = {k: dist(v) for k, v in by_recall.items() if len(v) > 1}
        write_idea_table(test_ids, G, old1, old3, new1, new2, win)
    (RESULTS / "novelty_study_summary.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str),
                                                       encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("cost", "dev")}, indent=1, default=str)[:6000])
    if have_test:
        figures(res)
        write_report(res)


def pair_winrates(mains) -> dict[str, float]:
    pts = defaultdict(list)
    for r in mains:
        v = r["parsed"]["verdict"]
        pts[r["A"]].append(1.0 if v == "A" else 0.5 if v == "SIMILAR" else 0.0)
        pts[r["B"]].append(1.0 if v == "B" else 0.5 if v == "SIMILAR" else 0.0)
    return {k: mean(v) for k, v in pts.items()}


def winner(r, a_id):
    """Map a verdict to the winning gen_id (or 'SIMILAR')."""
    v = r["parsed"]["verdict"]
    return "SIMILAR" if v == "SIMILAR" else (r["A"] if v == "A" else r["B"])


def pair_stats(mains, revs, pr, main_kind, rev_kind, repeats=None):
    vs = Counter(r["parsed"]["verdict"] for r in mains)
    dec = vs["A"] + vs["B"]
    out = {"n": len(mains), "verdicts": dict(vs), "similar_rate": vs["SIMILAR"] / len(mains) if mains else None,
           "share_A_among_decisive": vs["A"] / dec if dec else None,
           "binom_sd_under_no_bias": 0.5 / math.sqrt(dec) if dec else None}

    def consist(others):
        same = 0
        flips = 0
        n = 0
        for r in others:
            m = pr.get((r["pair_id"], main_kind))
            if not m:
                continue
            n += 1
            same += winner(m, None) == winner(r, None)
            flips += {winner(m, None), winner(r, None)} == {r["A"], r["B"]}
        return {"n": n, "same_outcome": same / n if n else None, "opposite_winner": flips / n if n else None}

    out["reversed_order_consistency"] = consist(revs)
    if repeats is not None:
        out["same_order_repeat_consistency"] = consist(repeats)
    # position effect in the reversal subset: winner = first-shown in both runs?
    first = 0
    nn = 0
    for r in revs:
        m = pr.get((r["pair_id"], main_kind))
        if m and m["parsed"]["verdict"] != "SIMILAR" and r["parsed"]["verdict"] != "SIMILAR":
            nn += 1
            first += m["parsed"]["verdict"] == "A" and r["parsed"]["verdict"] == "A"
            first -= 0
    out["reversal_both_pick_first_shown"] = {"n_both_decisive": nn, "both_A": first}
    return out


def write_idea_table(test_ids, G, old1, old3, new1, new2, win):
    with open(RESULTS / "novelty_test_idea_scores.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["gen_id", "brand", "condition", "old_v1_pass1", "old_rerun", "new_pass1", "new_pass2",
                    "pair_winrate_5matches", "usefulness_v1", "composite_v1_preserved"])
        v1 = v1_scores(1)
        for i in sorted(test_ids):
            g = G[i]
            n, u = v1[i]["novelty"], v1[i]["usefulness"]
            w.writerow([i, g["brand"], g["condition"], old1[i], old3.get(i, ""), new1[i], new2.get(i, ""),
                        f"{win[i]:.4f}" if i in win else "", u, f"{P.comp_mean(n, u):.4f}"])


# --------------------------------------------------------------------------- figures
def figures(res) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available; figures skipped")
        return
    figdir = RESULTS / "figures"
    figdir.mkdir(exist_ok=True)
    T = res["test"]
    ink, muted, grid = "#1f2328", "#59636e", "#d8dee4"
    colors = {"old_v1_pass1": "#8c959f", "new_pass1": "#2a78d6"}
    labels = {"old_v1_pass1": "Old rubric (v1)", "new_pass1": "Revised rubric (pass 1)"}
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=150)
    w = 0.38
    for k, (name, off) in enumerate((("old_v1_pass1", -w / 2), ("new_pass1", w / 2))):
        cnt = T["dist"][name]["counts"]
        n = sum(cnt)
        xs = [s + off for s in range(1, 6)]
        ys = [c / n * 100 for c in cnt]
        ax.bar(xs, ys, width=w - 0.04, color=colors[name], label=labels[name], zorder=2)
        for x, y, c in zip(xs, ys, cnt):
            if c:
                ax.text(x, y + 1, str(c), ha="center", va="bottom", fontsize=7, color=muted)
    ax.set_xticks(range(1, 6))
    ax.set_xlabel("Novelty score", color=ink)
    ax.set_ylabel("% of TEST ideas (n=110)", color=ink)
    ax.grid(axis="y", color=grid, lw=0.6, zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("Novelty score distribution on the same 110 TEST ideas", fontsize=10, color=ink, loc="left")
    fig.tight_layout()
    fig.savefig(figdir / "n1_novelty_distribution.png")
    plt.close(fig)

    # condition means for each method, z-scored across conditions for shape comparison
    cs = T["condition_signal"]
    methods = [("old_v1_pass1", "Old rubric (v1)", "#8c959f", "o"), ("new_mean_pass1_2", "Revised rubric (mean of 2 passes)", "#2a78d6", "s"),
               ("pair_winrate", "Pairwise win rate", "#eb6834", "D")]
    order = sorted(CONDS, key=lambda c: -cs["new_mean_pass1_2"]["condition_means"][c])
    fig, axs = plt.subplots(1, 3, figsize=(10, 3.8), dpi=150, sharey=True)
    for ax, (key, lab, col, mk) in zip(axs, methods):
        if not cs.get(key):
            continue
        cm = cs[key]["condition_means"]
        ys = list(range(len(order)))
        xs = [cm[c] for c in order]
        ax.hlines(ys, min(xs), xs, color=grid, lw=1, zorder=1)
        ax.scatter(xs, ys, color=col, marker=mk, s=36, zorder=3, edgecolor="white", linewidth=1)
        ax.set_yticks(ys)
        ax.set_yticklabels(order, fontsize=8)
        ax.invert_yaxis()
        ax.set_title(f"{lab}\nperm p={cs[key]['perm_p']:.3f}, cell r={cs[key]['within_cell_r']:.2f}",
                     fontsize=8, color=ink, loc="left")
        ax.grid(axis="x", color=grid, lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(labelsize=7)
    fig.suptitle("Condition means on TEST ideas (brand-equal); each panel has its own scale",
                 fontsize=9, color=ink, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(figdir / "n2_condition_means_by_method.png")
    plt.close(fig)


# ---------------------------------------------------------------------------- report
def f(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else P.f2(x, nd) if hasattr(P, "f2") else f"{x:.{nd}f}"


def write_report(res) -> None:
    T = res["test"]
    D = T["dist"]
    L = []
    a = L.append
    a("# Novelty measurement study v2 — results (auto-generated by novelty_study.py analyze)\n")
    a(f"- Generated: {res['generated']}; judge: `{res['judge']}` (same as pilot v1); TEST rubric: `{res['freeze']['test_rubric']}`; frozen at {res['freeze']['frozen_at']}.")
    a(f"- Nominal cost of this study (CLI-reported, subscription): ${res['cost']['total_usd_nominal']:.2f} "
      f"(absolute {res['cost']['abs']['ok']} ok records, pairwise {res['cost']['pair']['ok']} ok records).")
    a("- Pairwise results are **relative novelty among the ideas compared here**, not market-level novelty. No method here is validated against human ratings.\n")
    a("## 1. Distribution (TEST, same 110 ideas)\n")
    a("| Method | n | 1 | 2 | 3 | 4 | 5 | share 4–5 | mean | SD |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    for k, lab in (("old_v1_pass1", "Old rubric, v1 scores"), ("old_rerun", "Old rubric, re-run now"),
                   ("new_pass1", "Revised rubric, pass 1"), ("new_pass2", "Revised rubric, pass 2"),
                   ("old_v1_all330_context", "(context) old rubric, all 330")):
        d = D[k]
        a(f"| {lab} | {d['n']} | " + " | ".join(str(c) for c in d["counts"]) +
          f" | {d['share_4_5']*100:.1f}% | {d['mean']:.2f} | {d['sd']:.2f} |")
    a("\n## 2. Re-rating agreement\n")
    a("| Comparison | n | exact | ±1 | weighted κ (quadratic) | Spearman | mean shift |")
    a("|---|---|---|---|---|---|---|")
    for k, lab in (("old_v1_pass1_vs_old_rerun", "Old rubric: v1 vs re-run"),
                   ("new_pass1_vs_new_pass2", "Revised rubric: pass 1 vs 2"),
                   ("old_v1_original_retest_66_context", "(context) old rubric, v1 retest 66")):
        g = T["retest"][k]
        a(f"| {lab} | {g['n']} | {g['exact']*100:.0f}% | {g['within1']*100:.0f}% | {g['qwk']:.2f} | {g['spearman']:.2f} | {g['mean_diff_2_minus_1']:+.2f} |")
    p = T["pairs"]
    a(f"\nPairwise (main {p['n']} pairs): verdicts {p['verdicts']}; SIMILAR {p['similar_rate']*100:.0f}%; "
      f"share of decisive verdicts choosing A (first shown) {p['share_A_among_decisive']*100:.1f}% "
      f"(±{p['binom_sd_under_no_bias']*100:.1f} pp is 1 SD if no bias).")
    r, s = p["reversed_order_consistency"], p["same_order_repeat_consistency"]
    a(f"- Same order repeated (n={s['n']}): same outcome {s['same_outcome']*100:.0f}%, opposite winner {s['opposite_winner']*100:.0f}%.")
    a(f"- Order reversed (n={r['n']}): same outcome {r['same_outcome']*100:.0f}%, opposite winner {r['opposite_winner']*100:.0f}%; "
      f"both runs picked the first-shown idea in {p['reversal_both_pick_first_shown']['both_A']} of {p['reversal_both_pick_first_shown']['n_both_decisive']} pairs decisive in both runs.")
    a("\n## 3. Separation between conditions (TEST)\n")
    a("Condition means are brand-equal. `signal ratio` = variance of the 11 condition means ÷ its average under random relabelling of conditions within brand (≈1 means no more spread than chance). `cell r` = correlation between the two TEST ideas of the same brand × condition cell after removing brand means.\n")
    a("| Method | perm p | signal ratio | cell r | highest | lowest |")
    a("|---|---|---|---|---|---|")
    for k, lab in (("old_v1_pass1", "Old rubric, v1 scores"), ("old_rerun", "Old rubric, re-run"),
                   ("new_pass1", "Revised, pass 1"), ("new_mean_pass1_2", "Revised, mean of 2 passes"),
                   ("pair_winrate", "Pairwise win rate")):
        c = T["condition_signal"].get(k)
        if not c:
            continue
        cm = c["condition_means"]
        hi = max(cm, key=cm.get)
        lo = min(cm, key=cm.get)
        a(f"| {lab} | {c['perm_p']:.3f} | {c['signal_ratio']:.2f} | {c['within_cell_r']:.2f} | {hi} {cm[hi]:.2f} | {lo} {cm[lo]:.2f} |")
    a("\n## 4. Agreement between methods\n")
    cm_ = T["cross_method"]
    a(f"- Spearman, revised pass 1 vs old v1 novelty: {cm_['spearman_new1_old1']:.2f}. With v1 usefulness: revised {cm_['spearman_new1_usefulness_v1']:.2f}, old {cm_['spearman_old1_usefulness_v1']:.2f}.")
    a("\n| Absolute scores vs pairwise verdict | pairs decisive and scores differ | agree with pairwise winner | scores equal when pair = SIMILAR |")
    a("|---|---|---|---|")
    for k, c in T["concordance_with_pairwise"].items():
        a(f"| {k} | {c['decisive_and_abs_differs']} | {c['agree_rate']*100:.0f}% | {c['abs_equal_when_pair_similar']*100:.0f}% |")
    ra = T["rationale_audit"]
    a(f"\n## 5. Rationale audit\n\n- Claims of 'never done / no precedent' (regex): revised {ra['new_abs_precedent_claims']}/{ra['new_abs_n']}, "
      f"old re-run {ra['old_rerun_precedent_claims']}/{ra['old_rerun_n']}, pairwise {ra['pair_precedent_claims']}/{ra['pair_n']}. '(uncertain)' marks: {ra['new_abs_uncertain_marks']}.")
    a(f"- Revised rubric `precedent_recall` (pass 1): {T['precedent_recall_new_pass1']}.")
    (RESULTS / "novelty_study_results.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", RESULTS / "novelty_study_results.md")


# ----------------------------------------------------------------------------- human
def cmd_human() -> None:
    S = sample()
    G = gens()
    rng = random.Random(SEED + 41)
    tp = S["test_pairs"]
    # Seeded random search (2,000 draws): per brand `human_pairs_per_brand` pairs, each condition
    # at most twice per brand; keep the draw whose overall condition counts are most even
    # (smallest max-min, then smallest variance). Ties -> first draw found.
    brands = sorted({p["brand"] for p in tp})
    best, best_key = None, None
    for _ in range(2000):
        chosen = []
        for b in brands:
            bp = [p for p in tp if p["brand"] == b]
            rng.shuffle(bp)
            used = Counter()
            k = 0
            for p in bp:
                ca, cb = G[p["A"]]["condition"], G[p["B"]]["condition"]
                if used[ca] < 2 and used[cb] < 2:
                    chosen.append(p)
                    used[ca] += 1
                    used[cb] += 1
                    k += 1
                if k == CFG["human_pairs_per_brand"]:
                    break
        cnt = Counter(G[p[s]]["condition"] for p in chosen for s in ("A", "B"))
        vals = [cnt.get(c, 0) for c in CONDS]
        key = (max(vals) - min(vals), sum((v - mean(vals)) ** 2 for v in vals))
        if best_key is None or key < best_key:
            best, best_key = chosen, key
    chosen = best
    rng.shuffle(chosen)
    ideas = sorted({i for p in chosen for side in ("A", "B") for i in [p[side]]})
    rng.shuffle(ideas)
    HUMAN_DIR.mkdir(exist_ok=True)
    HUMAN_KEY.mkdir(exist_ok=True)
    n_cal = CFG["human_calibration_pairs"]
    with open(HUMAN_DIR / "novelty_pairs_sheet.csv", "w", newline="", encoding="utf-8-sig") as f1, \
         open(HUMAN_KEY / "pairs_key.csv", "w", newline="", encoding="utf-8-sig") as k1:
        w, k = csv.writer(f1), csv.writer(k1)
        w.writerow(["pair_item", "set", "brand", "idea_A", "idea_B", "more_novel_A_B_SIMILAR", "comment"])
        k.writerow(["pair_item", "pair_id", "gen_A", "cond_A", "gen_B", "cond_B"])
        for n, p in enumerate(chosen, 1):
            item = f"P{n:03d}"
            w.writerow([item, "calibration" if n <= n_cal else "test", p["brand"], G[p["A"]]["text"], G[p["B"]]["text"], "", ""])
            k.writerow([item, p["pair_id"], p["A"], G[p["A"]]["condition"], p["B"], G[p["B"]]["condition"]])
    with open(HUMAN_DIR / "novelty_absolute_sheet.csv", "w", newline="", encoding="utf-8-sig") as f2, \
         open(HUMAN_KEY / "absolute_key.csv", "w", newline="", encoding="utf-8-sig") as k2:
        w, k = csv.writer(f2), csv.writer(k2)
        cal_ideas = {p[s] for p in chosen[:n_cal] for s in ("A", "B")}
        w.writerow(["item_id", "set", "brand", "idea", "closest_familiar_format", "novelty_1to5", "comment"])
        k.writerow(["item_id", "gen_id", "condition"])
        for n, i in enumerate(ideas, 1):
            w.writerow([f"N{n:03d}", "calibration" if i in cal_ideas else "test", G[i]["brand"], G[i]["text"], "", "", ""])
            k.writerow([f"N{n:03d}", i, G[i]["condition"]])
    # leak check
    bad = [c for c in CONDS if c != "BASE"]
    for fn in ("novelty_pairs_sheet.csv", "novelty_absolute_sheet.csv"):
        t = (HUMAN_DIR / fn).read_text(encoding="utf-8-sig")
        hdr = t.splitlines()[0].lower()
        assert "condition" not in hdr and "score" not in hdr.replace("novelty_1to5", ""), fn
        assert not any(re.search(rf"\b{c}\b", t) for c in bad), fn
    print(f"human: {len(chosen)} pairs ({n_cal} calibration), {len(ideas)} ideas -> {HUMAN_DIR}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
    {"sample": cmd_sample, "estimate": cmd_estimate, "dev": lambda: cmd_dev(arg or "novelty_abs_v2"),
     "freeze": lambda: cmd_freeze(arg or sys.exit("rubric name required")), "test": cmd_test,
     "analyze": cmd_analyze, "human": cmd_human}.get(cmd, lambda: print(__doc__))()
