"""Analysis of pilot v4 (python pilot4.py analyze). Writes results/pilot_items.csv, results/pilot_summary.json."""
from __future__ import annotations

import csv
import json
import math
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

from coding_existing import BUCKET_DEFAULT, FAMILY, FINAL as FINAL_V3, OVERRIDES

ROOT = Path(__file__).resolve().parent
DATA, RES = ROOT / "data", ROOT / "results"
V3 = ROOT.parent / "pilot_v3_structured" / "data"
ARMS = ["BASELINE", "REVIEW", "V3_ORIGINAL"]


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")] if p.exists() else []


def fam(brand, c):
    return FAMILY.get(brand, {}).get(c, c)


def hhi(c):
    n = sum(c.values())
    return round(sum((v / n) ** 2 for v in c.values()), 3) if n else None


def sign_test(pos, neg):
    n = pos + neg
    if n == 0:
        return None
    k = min(pos, neg)
    return round(min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n), 4)


def main():
    plan = {s["set_id"]: s for s in json.loads((ROOT / "logs" / "plan.json").read_text(encoding="utf-8"))}
    bucket = {r["item_id"]: r["bucket"] for r in load(V3 / "buckets.jsonl")
              if r.get("phase") == "assign" and r["set"] == "cand"}

    def cand_code(brand, iid):
        return OVERRIDES[iid][0] if iid in OVERRIDES else BUCKET_DEFAULT[brand][bucket[iid]]

    sel = {r["set_id"]: r for r in load(DATA / "select.jsonl") if r.get("ok")}
    rev = {r["item_id"]: r for r in load(DATA / "revise.jsonl") if r.get("ok")}
    codes = {r["item_id"]: r for r in load(DATA / "codes.jsonl") if r.get("ok")}
    judg = defaultdict(dict)
    for r in load(DATA / "judgments.jsonl"):
        if r.get("ok"):
            judg[r["item_id"]][r["dim"]] = r["parsed"]["score"]

    rows = []
    for sid, s in plan.items():
        b = s["brand"]
        if sid not in sel:
            continue
        srec = sel[sid]
        sel_orig = srec["idmap"][srec["parsed"]["selection"]["selected_id"]]
        sel_code = cand_code(b, f"{sid}|{sel_orig}")
        v3_sel_code = cand_code(b, f'{sid}|{s["v3_selected_original_id"]}')
        for arm in ARMS:
            iid = f"{sid}|{arm}"
            c = codes.get(iid)
            if c is None:
                continue
            p = c["parsed"]
            r = rev.get(iid)
            row = {"item_id": iid, "set_id": sid, "brand": b, "arm": arm,
                   "selected_code": v3_sel_code if arm == "V3_ORIGINAL" else sel_code,
                   "coder_main": p["final_main_code"], "coder_retained": p["selected_core_retained"],
                   "n_added": len(p["added_elements"]),
                   "n_added_from_other_cand": sum(1 for e in p["added_elements"] if str(e.get("similar_in", "none")).lower() != "none"),
                   "n_added_main_role": sum(1 for e in p["added_elements"] if e.get("role") == "main"),
                   "safeguards_added": int(p.get("safeguards_added", 0)),
                   "B": judg[iid].get("B"), "F": judg[iid].get("F"), "L": judg[iid].get("L")}
            if arm == "V3_ORIGINAL":
                row["manual_main"] = FINAL_V3[b][sid]
            for k, v in p["recurring"].items():
                row[f"{k}_in_selected"] = int(v["in_selected"])
                row[f"{k}_in_final"] = int(v["in_final"])
                row[f"{k}_imported"] = int(v["in_final"] and not v["in_selected"])
            if r:
                row.update(output_tokens=(r.get("usage") or {}).get("output_tokens"), cost_usd=r.get("total_cost_usd"),
                           elapsed_s=r.get("elapsed_s"), thinking_blocks=r["reasoning"]["thinking_blocks"],
                           n_revisions=len(r["parsed"]["revisions_after_selection"]),
                           final_words=len(r["parsed"]["final_proposal"]["idea"].split()))
                if arm == "REVIEW":
                    ce = r["parsed"]["element_review"]["candidate_elements"]
                    row.update(ledger_n=len(ce), ledger_included=sum(bool(e.get("include")) for e in ce),
                               ledger_from_other_cand=sum(str(e.get("source", "")).upper().startswith("C") for e in ce),
                               ledger_from_other_cand_included=sum(str(e.get("source", "")).upper().startswith("C") and bool(e.get("include")) for e in ce))
            rows.append(row)

    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(RES / "pilot_items.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    S = {"n_sets": len(sel), "n_items": len(rows)}
    # ---- coder validation on original v3 finals
    v3r = [r for r in rows if r["arm"] == "V3_ORIGINAL"]
    S["coder_vs_manual_main_exact"] = f'{sum(r["coder_main"] == r["manual_main"] for r in v3r)}/{len(v3r)}'
    S["coder_vs_manual_main_family"] = f'{sum(fam(r["brand"], r["coder_main"]) == fam(r["brand"], r["manual_main"]) for r in v3r)}/{len(v3r)}'
    S["coder_vs_manual_disagreements"] = [(r["set_id"], r["manual_main"], r["coder_main"]) for r in v3r if r["coder_main"] != r["manual_main"]]
    # ---- selection (shared)
    S["selection_same_original_candidate_as_v3"] = sum(
        sel[s]["idmap"][sel[s]["parsed"]["selection"]["selected_id"]] == plan[s]["v3_selected_original_id"] for s in sel)
    S["selection_presented_position"] = dict(sorted(Counter(sel[s]["parsed"]["selection"]["selected_id"] for s in sel).items()))
    S["selection_original_position"] = dict(sorted(Counter(sel[s]["idmap"][sel[s]["parsed"]["selection"]["selected_id"]] for s in sel).items()))
    # ---- per arm
    per = {}
    for arm in ARMS:
        ar = [r for r in rows if r["arm"] == arm]
        d = {"n": len(ar),
             "retained": dict(Counter(r["coder_retained"] for r in ar)),
             "main_eq_selected_code": sum(r["coder_main"] == r["selected_code"] for r in ar),
             "main_eq_selected_family": sum(fam(r["brand"], r["coder_main"]) == fam(r["brand"], r["selected_code"]) for r in ar),
             "added_mean": round(st.mean(r["n_added"] for r in ar), 2),
             "added_from_other_cand_mean": round(st.mean(r["n_added_from_other_cand"] for r in ar), 2),
             "added_from_other_cand_total": sum(r["n_added_from_other_cand"] for r in ar),
             "added_main_role_total": sum(r["n_added_main_role"] for r in ar),
             "safeguards_mean": round(st.mean(r["safeguards_added"] for r in ar), 2)}
        for dim in "BFL":
            v = [r[dim] for r in ar if r[dim] is not None]
            d[f"{dim}_mean"] = round(st.mean(v), 2) if v else None
        el = defaultdict(lambda: Counter())
        for r in ar:
            for k in r:
                if k.endswith("_imported"):
                    e = k[:-9]
                    el[e]["imported"] += r[k]
                    el[e]["in_final"] += r[f"{e}_in_final"]
                    el[e]["in_selected"] += r[f"{e}_in_selected"]
                    el[e]["n"] += 1
        d["recurring"] = {k: dict(v) for k, v in el.items()}
        bymain = {}
        for b in ("Dior", "Canva", "Mastercard"):
            c = Counter(r["coder_main"] for r in ar if r["brand"] == b)
            bymain[b] = {"dist": dict(c.most_common()), "hhi": hhi(c)}
        d["final_main_by_brand"] = bymain
        if arm != "V3_ORIGINAL":
            for k in ("output_tokens", "cost_usd", "elapsed_s", "n_revisions", "final_words", "thinking_blocks"):
                v = [r[k] for r in ar if r.get(k) is not None]
                d[f"{k}_mean"] = round(st.mean(v), 4 if k == "cost_usd" else 1)
                d[f"{k}_sum"] = round(sum(v), 4) if k in ("output_tokens", "cost_usd", "elapsed_s") else None
        if arm == "REVIEW":
            for k in ("ledger_n", "ledger_included", "ledger_from_other_cand", "ledger_from_other_cand_included"):
                d[k + "_total"] = sum(r.get(k, 0) for r in ar)
        per[arm] = d
    S["per_arm"] = per
    # ---- paired REVIEW vs BASELINE
    by = {(r["set_id"], r["arm"]): r for r in rows}
    pairs = [(by[(s, "BASELINE")], by[(s, "REVIEW")]) for s in sel if (s, "BASELINE") in by and (s, "REVIEW") in by]
    pd = {}
    for metric in ["n_added", "n_added_from_other_cand", "safeguards_added", "B", "F", "L"]:
        diffs = [rv[metric] - bl[metric] for bl, rv in pairs if bl[metric] is not None and rv[metric] is not None]
        pos, neg = sum(x > 0 for x in diffs), sum(x < 0 for x in diffs)
        pd[metric] = {"mean_diff_review_minus_baseline": round(st.mean(diffs), 3) if diffs else None,
                      "review_higher": pos, "review_lower": neg, "ties": len(diffs) - pos - neg,
                      "sign_test_p": sign_test(pos, neg)}
    imp = {}
    for bl, rv in pairs:
        for k in bl:
            if k.endswith("_imported"):
                e = k[:-9]
                imp.setdefault(e, Counter())
                imp[e][(bl[k], rv[k])] += 1
    pd["recurring_imported_pairs(baseline,review)"] = {e: {f"{a}{b}": n for (a, b), n in c.items()} for e, c in imp.items()}
    S["paired"] = pd
    sel_cost = [sel[s].get("total_cost_usd") or 0 for s in sel]
    sel_tok = [(sel[s].get("usage") or {}).get("output_tokens") or 0 for s in sel]
    S["selection_calls"] = {"n": len(sel), "cost_sum": round(sum(sel_cost), 4), "output_tokens_sum": sum(sel_tok),
                            "elapsed_sum": round(sum(sel[s]["elapsed_s"] for s in sel), 1)}
    (RES / "pilot_summary.json").write_text(json.dumps(S, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(S, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
