"""Analysis of pilot v5 (python pilot5.py analyze). Unit of analysis = candidate set; reps are averaged within set x arm.

Writes results/items.csv, results/set_arm.csv, results/summary.json.
"""
from __future__ import annotations

import csv
import json
import math
import random
import re
import statistics as st
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
V4 = ROOT.parent / "selection_intervention_v4"
V3 = ROOT.parent / "pilot_v3_structured" / "data"
import sys  # noqa: E402

sys.path.insert(0, str(V4))
from coding_existing import BUCKET_DEFAULT, FAMILY, FINAL as FINAL_V3, OVERRIDES  # noqa: E402

DATA, RES = ROOT / "data", ROOT / "results"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
ARMS, SEED = CFG["arms"], CFG["seed"]
BRANDS = ("Dior", "Canva", "Mastercard")
ABSORB_SETS = {"Dior|SB_O_H|2", "Dior|SB_O_L|0", "Dior|SB_AVG|3", "Canva|BASE|2", "Canva|SB_O_L|3"}
PAIRS = [("FOCUS", "LEDGER"), ("FOCUS", "BASELINE"), ("LEDGER", "BASELINE"), ("NEUTRAL", "BASELINE"),
         ("LEDGER", "NEUTRAL"), ("FOCUS", "NEUTRAL")]
FUNCS = ("needed", "develops", "extra", "unclear")


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")] if p.exists() else []


def fam(b, c):
    return FAMILY.get(b, {}).get(c, c)


def hhi(c):
    n = sum(c.values())
    return sum((v / n) ** 2 for v in c.values()) if n else None


def sign_test(pos, neg):
    n = pos + neg
    if n == 0:
        return None
    k = min(pos, neg)
    return round(min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n), 4)


def boot_ci(diffs, n=10000, seed=SEED):
    rng = random.Random(seed)
    m = [st.mean(rng.choices(diffs, k=len(diffs))) for _ in range(n)]
    m.sort()
    return round(m[int(0.025 * n)], 3), round(m[int(0.975 * n) - 1], 3)


# ---------------------------------------------------------------- tf-idf
STOP = set("a an the and or of to in on for with by at from as is are be was were it its this that these those their "
           "they them we our you your who what which when where how not no but so into than then there here each every "
           "can could will would should may might one two own more most also just only about over through after before "
           "up out all any some such very new his her he she i me my us".split())


def toks(t):
    return [w for w in re.findall(r"[a-z][a-z'\-]+", t.lower()) if w not in STOP and len(w) > 2]


def tfidf_vectors(texts):
    docs = [Counter(toks(t)) for t in texts]
    df = Counter(w for d in docs for w in d)
    n = len(docs)
    vecs = []
    for d in docs:
        v = {w: c * math.log((1 + n) / (1 + df[w])) + 0.0 for w, c in d.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({w: x / norm for w, x in v.items()})
    return vecs


def cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


# ---------------------------------------------------------------- main
def main():
    plan = {s["set_id"]: s for s in json.loads((V4 / "logs" / "plan.json").read_text(encoding="utf-8"))}
    sel = {r["set_id"]: r for r in load(V4 / "data" / "select.jsonl") if r.get("ok")}
    bucket = {r["item_id"]: r["bucket"] for r in load(V3 / "buckets.jsonl")
              if r.get("phase") == "assign" and r["set"] == "cand"}

    def cand_code(b, iid):
        return OVERRIDES[iid][0] if iid in OVERRIDES else BUCKET_DEFAULT[b][bucket[iid]]

    revs_all = load(DATA / "revise.jsonl")
    rev = {r["item_id"]: r for r in revs_all if r.get("ok")}
    codes = {r["item_id"]: r for r in load(DATA / "codes.jsonl") if r.get("ok")}
    judg = defaultdict(dict)
    for r in load(DATA / "judgments.jsonl"):
        if r.get("ok"):
            judg[r["item_id"]][r["dim"]] = r["parsed"]["score"]

    rows = []
    for iid, c in codes.items():
        b, sid, arm = c["brand"], c["set_id"], c["arm"]
        p = c["parsed"]
        if arm == "V3_ORIGINAL":
            rows.append({"item_id": iid, "set_id": sid, "brand": b, "arm": arm, "rep": 0, "coder_main": p["final_main_code"],
                         "manual_main": FINAL_V3[b][sid]})
            continue
        s = sel[sid]
        sel_code = cand_code(b, f'{sid}|{s["idmap"][s["parsed"]["selection"]["selected_id"]]}')
        ae = p["added_elements"]
        other = [e for e in ae if str(e.get("similar_in", "none")).lower() != "none"]
        row = {"item_id": iid, "set_id": sid, "brand": b, "arm": arm, "rep": c["rep"], "absorb_plan_set": int(sid in ABSORB_SETS),
               "selected_code": sel_code, "coder_main": p["final_main_code"],
               "retained_yes": int(p["selected_core_retained"] == "yes"), "retained": p["selected_core_retained"],
               "main_eq_selected": int(fam(b, p["final_main_code"]) == fam(b, sel_code)),
               "n_added": len(ae), "n_other": len(other),
               "n_other_main_role": sum(e.get("role") == "main" for e in other),
               "n_added_main_role": sum(e.get("role") == "main" for e in ae),
               "safeguards": int(p.get("safeguards_added", 0)),
               "recurring_imported": sum(int(v["in_final"] and not v["in_selected"]) for v in p["recurring"].values()),
               "B": judg[iid].get("B"), "F": judg[iid].get("F"), "L": judg[iid].get("L")}
        for f in FUNCS:
            row[f"other_{f}"] = sum(e.get("function") == f for e in other)
            row[f"added_{f}"] = sum(e.get("function") == f for e in ae)
        for k, v in p["recurring"].items():
            row[f"{k}_imported"] = int(v["in_final"] and not v["in_selected"])
        r = rev[iid]
        u = r.get("usage") or {}
        row.update(output_tokens=u.get("output_tokens"),
                   input_tokens=(u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
                   + (u.get("cache_read_input_tokens") or 0),
                   cost_usd=r.get("total_cost_usd"), elapsed_s=r.get("elapsed_s"), n_attempts=r.get("n_attempts"),
                   thinking_blocks=r["reasoning"]["thinking_blocks"],
                   final_words=len(r["parsed"]["final_proposal"]["idea"].split()),
                   n_revisions=len(r["parsed"]["revisions_after_selection"]), final_text=r["parsed"]["final_proposal"]["idea"],
                   final_title=r["parsed"]["final_proposal"]["title"])
        pr = r["parsed"]
        if arm == "LEDGER":
            ce = pr["element_review"]["candidate_elements"]
            isc = [e for e in ce if str(e.get("source", "")).upper().startswith("C")]
            row.update(sr_listed=len(ce), sr_included=sum(bool(e.get("include")) for e in ce),
                       sr_other_listed=len(isc), sr_other_included=sum(bool(e.get("include")) for e in isc))
        elif arm == "FOCUS":
            fc = pr["focus_check"]
            row.update(sr_required=len(fc["required_elements"]),
                       sr_required_new=sum(not e.get("in_recommended_candidate", True) for e in fc["required_elements"]),
                       sr_other_included=len(fc["borrowed_elements"]))
        rows.append(row)

    v3rows = [r for r in rows if r["arm"] == "V3_ORIGINAL"]
    rows = [r for r in rows if r["arm"] != "V3_ORIGINAL"]
    rows.sort(key=lambda r: (r["set_id"], ARMS.index(r["arm"]), r["rep"]))
    keys = []
    for r in rows:
        for k in r:
            if k not in keys and k != "final_text":
                keys.append(k)
    with open(RES / "items.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    S = {"n_items": len(rows), "items_per_arm": dict(Counter(r["arm"] for r in rows))}
    # ---- run log (incl. failures)
    calls = defaultdict(lambda: Counter())
    for r in revs_all:
        calls[r["arm"]]["records"] += 1
        calls[r["arm"]]["ok"] += int(bool(r.get("ok")))
        calls[r["arm"]]["attempts"] += r.get("n_attempts", 1)
        calls[r["arm"]]["failed_attempt_cost"] += sum(float(a.get("total_cost_usd") or 0) for a in r.get("failed_attempts", []))
    S["calls"] = {a: dict(v) for a, v in calls.items()}
    S["coder_validation_v3"] = {
        "exact": f'{sum(r["coder_main"] == r["manual_main"] for r in v3rows)}/{len(v3rows)}',
        "family": f'{sum(fam(r["brand"], r["coder_main"]) == fam(r["brand"], r["manual_main"]) for r in v3rows)}/{len(v3rows)}',
        "disagreements": [(r["set_id"], r["manual_main"], r["coder_main"]) for r in v3rows if r["coder_main"] != r["manual_main"]]}

    METRICS = ["retained_yes", "main_eq_selected", "n_added", "n_other", "n_other_main_role", "other_needed",
               "other_develops", "other_extra", "other_unclear", "added_extra", "recurring_imported", "safeguards",
               "B", "F", "L", "output_tokens", "input_tokens", "cost_usd", "elapsed_s", "final_words", "n_revisions"]
    # ---- set x arm means
    g = defaultdict(list)
    for r in rows:
        g[(r["set_id"], r["arm"])].append(r)
    sa = {}
    for (sid, arm), rs in g.items():
        d = {"set_id": sid, "arm": arm, "brand": rs[0]["brand"], "n_reps": len(rs), "absorb_plan_set": rs[0]["absorb_plan_set"]}
        for m in METRICS:
            v = [x[m] for x in rs if x.get(m) is not None]
            d[m] = st.mean(v) if v else None
            if m in ("n_other", "n_added", "recurring_imported", "B", "F", "L"):
                d[m + "_sd_within"] = st.pstdev(v) if len(v) > 1 else None
        d["main_codes"] = "/".join(x["coder_main"] for x in sorted(rs, key=lambda x: x["rep"]))
        sa[(sid, arm)] = d
    with open(RES / "set_arm.csv", "w", newline="", encoding="utf-8-sig") as f:
        ks = list(next(iter(sa.values())).keys())
        w = csv.DictWriter(f, fieldnames=ks)
        w.writeheader()
        for k in sorted(sa, key=lambda k: (k[0], ARMS.index(k[1]))):
            w.writerow({kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in sa[k].items()})
    sets = sorted({k[0] for k in sa})

    def arm_summary(subset):
        out = {}
        for arm in ARMS:
            ds = [sa[(s, arm)] for s in subset if (s, arm) in sa]
            if not ds:
                continue
            d = {"n_sets": len(ds), "n_items": sum(x["n_reps"] for x in ds)}
            for m in METRICS:
                v = [x[m] for x in ds if x[m] is not None]
                d[m] = round(st.mean(v), 3) if v else None
            for m in ("n_other", "recurring_imported", "B", "F", "L"):
                v = [x[m + "_sd_within"] for x in ds if x.get(m + "_sd_within") is not None]
                d[m + "_mean_within_set_sd"] = round(st.mean(v), 3) if v else None
            its = [r for r in rows if r["arm"] == arm and r["set_id"] in subset]
            d["items_with_any_other"] = f'{sum(r["n_other"] > 0 for r in its)}/{len(its)}'
            d["n_other_total"] = sum(r["n_other"] for r in its)
            d["other_function_totals"] = {f: sum(r[f"other_{f}"] for r in its) for f in FUNCS}
            d["retained_dist"] = dict(Counter(r["retained"] for r in its))
            el = Counter()
            for r in its:
                for k in r:
                    if k.endswith("_imported") and k != "recurring_imported":
                        el[k[:-9]] += r[k]
            d["recurring_imported_by_element"] = dict(el)
            for k in ("sr_listed", "sr_included", "sr_other_listed", "sr_other_included", "sr_required", "sr_required_new"):
                v = [r[k] for r in its if k in r]
                if v:
                    d[k + "_total"] = sum(v)
            out[arm] = d
        return out

    def paired(subset, metrics=("n_other", "n_added", "other_extra", "other_needed", "other_develops",
                                "recurring_imported", "retained_yes", "B", "F", "L", "output_tokens", "cost_usd")):
        out = {}
        for a, b in PAIRS:
            pd = {}
            for m in metrics:
                diffs = [sa[(s, a)][m] - sa[(s, b)][m] for s in subset
                         if (s, a) in sa and (s, b) in sa and sa[(s, a)][m] is not None and sa[(s, b)][m] is not None]
                if not diffs:
                    continue
                pos, neg = sum(x > 1e-9 for x in diffs), sum(x < -1e-9 for x in diffs)
                pd[m] = {"mean_diff": round(st.mean(diffs), 3), "ci95": boot_ci(diffs) if len(diffs) > 2 else None,
                         "higher": pos, "lower": neg, "ties": len(diffs) - pos - neg, "sign_p": sign_test(pos, neg)}
            out[f"{a}-{b}"] = pd
        return out

    S["overall"] = arm_summary(sets)
    S["paired_overall"] = paired(sets)
    S["by_brand"] = {b: {"arms": arm_summary([s for s in sets if s.startswith(b)]),
                         "paired": paired([s for s in sets if s.startswith(b)], ("n_other", "other_extra", "recurring_imported",
                                                                                  "retained_yes", "B", "F", "L"))}
                     for b in BRANDS}
    S["absorb_plan_subgroup"] = {"absorb_sets": arm_summary(sorted(ABSORB_SETS)),
                                 "other_sets": arm_summary([s for s in sets if s not in ABSORB_SETS])}

    # ---- repetition of finals across sets within brand (per rep, then averaged)
    vec = dict(zip([r["item_id"] for r in rows], tfidf_vectors([r["final_title"] + ". " + r["final_text"] for r in rows])))
    rep_out = {}
    for b in BRANDS:
        rep_out[b] = {}
        for arm in ARMS:
            hh, cs = [], []
            for k in range(1, CFG["reps"] + 1):
                its = [r for r in rows if r["brand"] == b and r["arm"] == arm and r["rep"] == k]
                if len(its) < 2:
                    continue
                hh.append(hhi(Counter(fam(b, r["coder_main"]) for r in its)))
                cs.append(st.mean(cos(vec[x["item_id"]], vec[y["item_id"]]) for x, y in combinations(its, 2)))
            # within-set stability across reps (same input, same arm)
            stab = []
            for s in [s for s in sets if s.startswith(b)]:
                its = [r for r in rows if r["set_id"] == s and r["arm"] == arm]
                if len(its) > 1:
                    stab.append(st.mean(cos(vec[x["item_id"]], vec[y["item_id"]]) for x, y in combinations(its, 2)))
            rep_out[b][arm] = {"hhi_main_family_mean_over_reps": round(st.mean(hh), 3) if hh else None,
                               "tfidf_cos_between_sets_mean": round(st.mean(cs), 3) if cs else None,
                               "tfidf_cos_within_set_across_reps": round(st.mean(stab), 3) if stab else None}
    S["repetition"] = rep_out
    (RES / "summary.json").write_text(json.dumps(S, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: S[k] for k in ("n_items", "items_per_arm", "calls", "coder_validation_v3")}, indent=1))


if __name__ == "__main__":
    main()
