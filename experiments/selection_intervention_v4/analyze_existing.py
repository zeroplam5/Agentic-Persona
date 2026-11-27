"""Exploratory analysis of existing pilot v3 structured records (no new model calls).

  python analyze_existing.py      # -> results/existing_*.csv, results/existing_summary.json

Reads ../pilot_v3_structured/data/{generations,buckets}.jsonl and coding_existing.py.
Model-reported plans / selection reasons / revisions are treated as REPORTED work records, not hidden reasoning.
"""
from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from coding_existing import BUCKET_DEFAULT, FAMILY, FINAL, OVERRIDES

ROOT = Path(__file__).resolve().parent
V3 = ROOT.parent / "pilot_v3_structured" / "data"
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)
BRANDS = ["Dior", "Canva", "Mastercard"]
SEED = 20261123
NSIM = 20000


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


gens = load(V3 / "generations.jsonl")
bucket = {(r["set"], r["item_id"]): r["bucket"] for r in load(V3 / "buckets.jsonl") if r.get("phase") == "assign"}


def cand_code(brand, item_id):
    if item_id in OVERRIDES:
        return OVERRIDES[item_id][0]
    return BUCKET_DEFAULT[brand][bucket[("cand", item_id)]]


def fam(brand, code):
    return FAMILY.get(brand, {}).get(code, code)


# ------------------------------------------------------------------ build run table
runs = []
for g in gens:
    if g["kind"] != "structured":
        continue
    p = g["parsed"]
    cands = [{"id": c["id"], "pos": i + 1, "title": c["title"], "core": c["core_idea"],
              "code": cand_code(g["brand"], f'{g["run_id"]}|{c["id"]}')} for i, c in enumerate(p["candidates"])]
    sel = p["selection"]["selected_id"]
    runs.append({"brand": g["brand"], "run_id": g["run_id"], "cond": g["condition"], "cands": cands, "sel": sel,
                 "sel_pos": [c["id"] for c in cands].index(sel) + 1,
                 "sel_code": next(c["code"] for c in cands if c["id"] == sel),
                 "final_code": FINAL[g["brand"]][g["run_id"]],
                 "rej": {r["id"]: r["reason"] for r in p["selection"]["rejected"]},
                 "rev": [r["change"] + " || " + r.get("reason", "") for r in p["revisions_after_selection"]],
                 "final_text": p["final_proposal"]["title"] + ": " + p["final_proposal"]["idea"],
                 "out_tokens": g["usage"].get("output_tokens")})
nodedup = defaultdict(list)
for g in gens:
    if g["kind"] == "single":
        nodedup[g["brand"]].append(cand_code(g["brand"], f'{g["run_id"]}|C{g["k"] + 1}'))

# position weights pooled over all 84 structured runs (selection frequency by position)
pos_counts = Counter(r["sel_pos"] for r in runs)
POSW = [pos_counts[i] / len(runs) for i in range(1, 5)]


def hhi(counter):
    n = sum(counter.values())
    return sum((v / n) ** 2 for v in counter.values())


def simulate(brand_runs, weights, level):
    rng = random.Random(SEED)
    obs = Counter(level(r["sel_code"]) for r in brand_runs)
    top_code, top_obs = obs.most_common(1)[0]
    obs_hhi = hhi(obs)
    ge_top = ge_hhi = 0
    top_sims = []
    for _ in range(NSIM):
        c = Counter()
        for r in brand_runs:
            pick = rng.choices(r["cands"], weights=weights)[0]
            c[level(pick["code"])] += 1
        top_sims.append(c[top_code])
        ge_top += c[top_code] >= top_obs
        ge_hhi += hhi(c) >= obs_hhi - 1e-12
    return {"top_code": top_code, "top_observed": top_obs, "top_expected": round(sum(top_sims) / NSIM, 2),
            "p_top_ge_obs": round(ge_top / NSIM, 4), "hhi_observed": round(obs_hhi, 3),
            "p_hhi_ge_obs": round(ge_hhi / NSIM, 4)}


summary = {"position_selection_counts_pooled": dict(sorted(pos_counts.items())), "position_weights": POSW,
           "nsim": NSIM, "seed": SEED, "brands": {}}
stage_rows = []
for b in BRANDS:
    br = [r for r in runs if r["brand"] == b]
    level = (lambda c, b=b: fam(b, c))
    S = {"n_runs": len(br)}
    # --- candidate stage
    runs_with = Counter()
    for r in br:
        for code in {c["code"] for c in r["cands"]}:
            runs_with[code] += 1
    S["cand_codes_all"] = dict(Counter(c["code"] for r in br for c in r["cands"]).most_common())
    S["cand_runs_containing"] = dict(runs_with.most_common())
    S["cand_within_run_distinct_mean"] = round(sum(len({c["code"] for c in r["cands"]}) for r in br) / len(br), 2)
    S["cand_within_run_distinct_family_mean"] = round(
        sum(len({level(c["code"]) for c in r["cands"]}) for r in br) / len(br), 2)
    S["cand_distinct_codes_total"] = len(runs_with)
    top = runs_with.most_common(1)[0][0]
    S["cand_top_code"] = top
    S["cand_top_code_positions"] = dict(sorted(Counter(c["pos"] for r in br for c in r["cands"] if c["code"] == top).items()))
    S["nodedup_codes"] = dict(Counter(nodedup[b]).most_common())
    # --- selection stage
    S["selected_codes"] = dict(Counter(r["sel_code"] for r in br).most_common())
    S["selected_positions"] = dict(sorted(Counter(r["sel_pos"] for r in br).items()))
    exp_uni, exp_pos = Counter(), Counter()
    for r in br:
        for c, w in zip(r["cands"], POSW):
            exp_uni[c["code"]] += 0.25
            exp_pos[c["code"]] += w
    S["selected_expected_uniform"] = {k: round(v, 2) for k, v in exp_uni.most_common()}
    S["selected_expected_position_weighted"] = {k: round(v, 2) for k, v in exp_pos.most_common()}
    S["sim_uniform"] = simulate(br, [1, 1, 1, 1], level)
    S["sim_position_weighted"] = simulate(br, POSW, level)
    # commonness: selected candidate's run-frequency vs mean of its run's 4 candidates (as in deck slide 21)
    common = sum(runs_with[r["sel_code"]] > sum(runs_with[c["code"]] for c in r["cands"]) / 4 for r in br)
    S["selected_more_common_than_run_mean"] = common
    # --- revision / final
    S["final_codes_structured"] = dict(Counter(r["final_code"] for r in br).most_common())
    S["final_codes_with_nodedup"] = dict(Counter(FINAL[b][k] for k in FINAL[b]).most_common())
    S["retention_selected_eq_final"] = sum(r["sel_code"] == r["final_code"] for r in br)
    S["retention_family"] = sum(level(r["sel_code"]) == level(r["final_code"]) for r in br)
    S["changed_main"] = [(r["run_id"], r["sel_code"], r["final_code"]) for r in br if r["sel_code"] != r["final_code"]]
    S["hhi_selected"] = round(hhi(Counter(r["sel_code"] for r in br)), 3)
    S["hhi_final"] = round(hhi(Counter(r["final_code"] for r in br)), 3)
    if b in FAMILY:
        S["selected_family"] = dict(Counter(level(r["sel_code"]) for r in br).most_common())
        S["final_family"] = dict(Counter(level(r["final_code"]) for r in br).most_common())
    summary["brands"][b] = S
    for r in br:
        stage_rows.append({"run_id": r["run_id"], "brand": b, "condition": r["cond"],
                           "cand_codes_by_pos": " ".join(c["code"] for c in r["cands"]),
                           "selected_id": r["sel"], "selected_pos": r["sel_pos"], "selected_code": r["sel_code"],
                           "final_code": r["final_code"], "main_retained": int(r["sel_code"] == r["final_code"]),
                           "output_tokens": r["out_tokens"]})

with open(OUT / "existing_stage_codes.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(stage_rows[0]))
    w.writeheader()
    w.writerows(stage_rows)

# ------------------------------------------------------------------ recurring auxiliary elements
# Each element has a HOME mechanism code. It is AUXILIARY in a final whose main code is not home.
ELEMENTS = {
    "Dior": {"MARK": (("A",), r"\bsign(?:ed|ature|s)?\b|initials|\bmark\b|label|lucky star|stitched (?:the )?date")},
    "Canva": {"EMPLOYER_KIT": (("F", "F2"), r"employer|\bHR\b|manager|Canva for Teams|\bTeams\b|onboarding|People teams"),
              "KEEPSAKE": (("B",), r"keepsake|frame|framing|memento|share the win|shareable .{0,20}card|celebratory card")},
    "Mastercard": {"MERCHANT_RECOGNITION": (("A1", "A2", "A3"),
                                            r"Regulars?\b|sticker|window|sonic|sound|Take Your Time|slow|greet"),
                   "PAID_INVITATION": (("B",), r"invit|On Me|\btreat\b|on us|covered|pre-?paid")},
}
ABSORB = r"absorb|fold|borrow|reus|inside|within|layer|supporting|secondary|as an? (?:optional|small)|into (?:C\d|the (?:chosen|selected|recommended))|for C\d|of C\d"
DEFER = r"later extension|later phase|later chapter|future|separate initiative|possible extension"

aux_rows = []
for r in runs:
    for el, (home, rx) in ELEMENTS[r["brand"]].items():
        has = lambda t: bool(re.search(rx, t, re.I))
        main_is_home = r["final_code"] in home
        selc = next(c for c in r["cands"] if c["id"] == r["sel"])
        home_rej = [c["id"] for c in r["cands"] if c["code"] in home and c["id"] != r["sel"]]
        rej_plan = [cid for cid in home_rej if re.search(ABSORB, r["rej"].get(cid, ""), re.I)]
        rej_defer = [cid for cid in home_rej if re.search(DEFER, r["rej"].get(cid, ""), re.I)]
        rev_hits = [x for x in r["rev"] if has(x)]
        rev_src = [x for x in rev_hits if any(cid in x for cid in home_rej)]
        in_final = has(r["final_text"])
        if main_is_home:
            stage = "MAIN"
        elif not in_final:
            stage = "absent"
        elif has(selc["core"]):
            stage = "S1_in_selected_candidate"
        elif rej_plan and rev_hits:
            stage = "S2_planned_at_selection_added_in_revision"
        elif rev_hits and home_rej:
            stage = "S3_added_in_revision_home_candidate_present"
        elif rev_hits:
            stage = "S4_added_in_revision_no_home_candidate"
        else:
            stage = "S5_only_in_final_text"
        aux_rows.append({"run_id": r["run_id"], "brand": r["brand"], "element": el, "final_main": r["final_code"],
                         "selected_code": r["sel_code"], "stage_auto": stage,
                         "home_candidates_rejected": " ".join(home_rej), "rej_absorb_plan": " ".join(rej_plan),
                         "rej_deferred": " ".join(rej_defer),
                         "rev_mentions_source": int(bool(rev_src)),
                         "rej_text": " | ".join(f"{cid}: {r['rej'].get(cid, '')}" for cid in home_rej),
                         "rev_hits": " | ".join(rev_hits),
                         "final_hit": (lambda m: r["final_text"][max(0, m.start() - 90): m.end() + 90] if m else "")(
                             re.search(rx, r["final_text"], re.I))})

with open(OUT / "existing_aux_elements_auto.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(aux_rows[0]))
    w.writeheader()
    w.writerows(aux_rows)

aux_sum = defaultdict(Counter)
for a in aux_rows:
    aux_sum[f'{a["brand"]}:{a["element"]}'][a["stage_auto"]] += 1
summary["aux_elements_auto"] = {k: dict(v) for k, v in aux_sum.items()}
(OUT / "existing_summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, indent=1, ensure_ascii=False))

# ------------------------------------------------------------------ content vs position: selection of dominant codes by position
from aux_manual import MANUAL  # noqa: E402

posrows = {}
for b, codes in {"Dior": ["A"], "Canva": ["A", "B"], "Mastercard": ["B"]}.items():
    for code in codes:
        t = {}
        for p in range(1, 5):
            present = [r for r in runs if r["brand"] == b and r["cands"][p - 1]["code"] == code]
            t[p] = {"runs_with_code_at_pos": len(present),
                    "selected_that": sum(r["sel_code"] == code and r["sel_pos"] == p for r in present)}
        posrows[f"{b}:{code}"] = t
# selection rate by position for codes OTHER than the brand's dominant one (baseline for position effect)
other = {}
dom = {"Dior": {"A"}, "Canva": {"A", "B"}, "Mastercard": {"B"}}
for p in range(1, 5):
    pres = [(r, r["cands"][p - 1]) for r in runs if r["cands"][p - 1]["code"] not in dom[r["brand"]]]
    other[p] = {"n": len(pres), "selected": sum(r["sel_pos"] == p for r, c in pres)}
summary["dominant_code_selection_by_position"] = posrows
summary["non_dominant_selection_by_position"] = other
summary["aux_elements_manual"] = {k: {s: (len(v) if isinstance(v, list) else v) for s, v in d.items()}
                                  for k, d in MANUAL.items()}
(OUT / "existing_summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps({"dominant_by_pos": posrows, "non_dominant_by_pos": other,
                  "aux_manual": summary["aux_elements_manual"]}, indent=1))
