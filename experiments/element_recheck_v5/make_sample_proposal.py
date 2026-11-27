"""Analyst-only: propose the ~24-item main human-coding sample. Read-only; no model calls."""
import csv, hashlib, json, os, collections
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_analyst_only_DO_NOT_SHOW_CODERS")
SEED = 20261124
ARMS = ["BASELINE", "LEDGER", "FOCUS", "NEUTRAL"]
# 2 sets per brand: prefer sets with no calibration item; one absorb-plan set for Dior and Canva.
CHOSEN = ["Dior|BASE|0", "Dior|SB_O_H|2", "Canva|BASE|3", "Canva|BASE|2", "Mastercard|SB_O_H|0", "Mastercard|BASE|3"]
ABSORB = {"Dior|SB_O_H|2", "Dior|SB_O_L|0", "Dior|SB_AVG|3", "Canva|BASE|2", "Canva|SB_O_L|3"}
kid = lambda iid: "K" + hashlib.sha256(f"{SEED}|{iid}".encode()).hexdigest()[:8]
cal = {r["item"] for r in csv.DictReader(open(os.path.join(ROOT, "coding_researcher_A_partial.csv"), encoding="utf-8-sig"))}
sheet = {r["item"] for r in csv.DictReader(open(os.path.join(ROOT, "human_coding_blind_v5_focus", "coding_sheet_researcherA.csv"), encoding="utf-8-sig"))}
rev = {json.loads(l)["item_id"] for l in open(os.path.join(ROOT, "experiments", "selection_focus_v5", "data", "revise.jsonl"), encoding="utf-8") if '"ok": true' in l or True}
rows = []
for s in CHOSEN:
    for a in ARMS:
        r1 = f"{s}|{a}|r1"
        use, note = r1, "r1 (기존 48건 시트에 있음)"
        if kid(r1) in cal:
            use, note = f"{s}|{a}|r2", f"r1={kid(r1)}이 보정 9건이라 r2로 교체 (새 시트 행 필요)"
        assert use in rev, use
        rows.append(dict(item=kid(use), item_id=use, set=s, brand=s.split("|")[0], arm=a,
                         absorb_plan_set="yes" if s in ABSORB else "no",
                         in_existing_48_sheet="yes" if kid(use) in sheet else "no",
                         overlaps_calibration_9="yes" if kid(use) in cal else "no", note=note))
with open(os.path.join(OUT, "main_sample_proposal.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(len(rows), collections.Counter((r["brand"], r["arm"]) for r in rows).most_common(3))
print("overlap", sum(r["overlaps_calibration_9"] == "yes" for r in rows), "replaced", sum("교체" in r["note"] for r in rows))
for r in rows:
    if "교체" in r["note"]: print(r["item"], r["item_id"], r["note"])
