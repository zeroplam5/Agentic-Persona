"""Pilot v5: selection-focused check vs baseline vs v4 ledger vs neutral work record (exploratory). See DESIGN.md.

All arms get the same 24 candidate sets (same shuffled order) and the same shared selection record from pilot v4.
Only the post-selection step differs. Each (set, arm) is run `reps` times.

  python pilot5.py setup      # freeze hashes, write logs/plan_v5.json
  python pilot5.py smoke      # 1 call per arm on one set -> logs/smoke.jsonl only (not analysed)
  python pilot5.py revise     # 24 sets x 4 arms x reps (Claude CLI)
  python pilot5.py code       # blind coding (gpt-6-astra), incl. v3 original finals for coder validation
  python pilot5.py judge      # brand fit / feasibility / logic (gpt-6-astra, v3 rubric)
  python pilot5.py human      # blind two-researcher coding sheet -> ../../human_coding_blind_v5_focus/
  python pilot5.py analyze    # results/

Keys are read from the project .env by pilot3 and never printed or logged.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
V4 = ROOT.parent / "selection_intervention_v4"
sys.path.insert(0, str(V4))
import pilot4 as p4  # noqa: E402  (imports pilot3, sets model/caps)

p3 = p4.p3
from coding_existing import CODEBOOK  # noqa: E402

PROMPTS, DATA, LOGS, RES = ROOT / "prompts", ROOT / "data", ROOT / "logs", ROOT / "results"
for d in (DATA, LOGS, RES):
    d.mkdir(exist_ok=True)
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SEED, ARMS, REPS = CFG["seed"], CFG["arms"], CFG["reps"]
HUMAN = ROOT.parent.parent / "human_coding_blind_v5_focus"

p3.CONFIG["generator"]["isolated_cwd"] = CFG["isolated_cwd"]
p3.CONFIG["budget_usd"] = CFG["budget_usd"]
p3.CONFIG["workers"] = CFG["workers"]
GEN_ENV, SYSTEM, ELEMENTS = p4.GEN_ENV, p4.SYSTEM, p4.ELEMENTS
SECTION = {"BASELINE": None, "LEDGER": "element_review", "FOCUS": "focus_check", "NEUTRAL": "writing_notes"}


def rt(name):
    return (PROMPTS / name).read_text(encoding="utf-8")


def plan():
    return p4.plan()  # v4 logs/plan.json (24 sets, shuffled orders)


def selections():
    return p4.selections()  # v4 data/select.jsonl, shared by every arm


def parse_revise(text, arm):
    j = p3._json_obj(text)
    try:
        assert isinstance(j["revisions_after_selection"], list)
        fp = j["final_proposal"]
        assert fp.get("title") and fp.get("idea") and len(fp.get("follow_up_questions", [])) == 3
        if arm == "LEDGER":
            er = j["element_review"]
            assert er.get("selected_core_idea") and isinstance(er.get("candidate_elements"), list)
        elif arm == "FOCUS":
            fc = j["focus_check"]
            assert fc.get("core_purpose") and fc.get("core_direction")
            assert isinstance(fc.get("required_elements"), list) and isinstance(fc.get("borrowed_elements"), list)
        elif arm == "NEUTRAL":
            wn = j["writing_notes"]
            assert wn.get("intended_reader") and isinstance(wn.get("outline"), list)
        return j
    except Exception:
        return None


FUNCS = ("needed", "develops", "extra", "unclear")


def parse_code(text, keys):
    j = p4.parse_code(text, keys)
    try:
        for e in j["added_elements"]:
            assert e.get("function") in FUNCS
        return j
    except Exception:
        return None


# ------------------------------------------------------------------ setup / freeze
def freeze():
    files = sorted([*PROMPTS.glob("*.txt"), ROOT / "DESIGN.md", ROOT / "config.json", V4 / "logs" / "plan.json",
                    V4 / "data" / "select.jsonl"])
    lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(ROOT.parent).as_posix()}" for f in files]
    (LOGS / "freeze_hashes.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def cmd_setup():
    sels = selections()
    assert len(sels) == 24, len(sels)
    rng = random.Random(SEED)
    human_sets = []
    for b in ("Dior", "Canva", "Mastercard"):
        ids = sorted(s["set_id"] for s in plan() if s["brand"] == b)
        human_sets += sorted(rng.sample(ids, CFG["human_coding_sets_per_brand"]))
    out = {"sets": [s["set_id"] for s in plan()], "arms": ARMS, "reps": REPS, "human_coding_sets": human_sets}
    (LOGS / "plan_v5.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    freeze()


# ------------------------------------------------------------------ generation
def do_revise(s, arm, rep, sel_rec, log=DATA / "revise.jsonl"):
    cands, idmap = p4.presented_candidates(s)
    up = p4.fill(rt(f"revise_{arm}_user.txt"), s, CANDIDATES=p4.render_candidates(cands),
                 SELECTION=json.dumps(sel_rec["parsed"], indent=2, ensure_ascii=False))
    res = p3.call("claude", GEN_ENV, SYSTEM, up, validate=lambda t: parse_revise(t, arm))
    p3.append_jsonl(log, {"item_id": f'{s["set_id"]}|{arm}|r{rep}', "set_id": s["set_id"], "arm": arm, "rep": rep,
                          "phase": "revise", "idmap": idmap, "user_prompt": up, "system_prompt": SYSTEM, **res})


def cmd_smoke():
    s = plan()[0]
    sel = selections()[s["set_id"]]
    log = LOGS / "smoke.jsonl"
    for arm in ARMS:
        do_revise(s, arm, 0, sel, log)
    for r in p3.load_jsonl(log)[-len(ARMS):]:
        print(r["arm"], "ok:", r.get("ok"), r.get("error"), "out_tok", (r.get("usage") or {}).get("output_tokens"),
              "cost", r.get("total_cost_usd"), "s", r.get("elapsed_s"))


def cmd_revise():
    sels = selections()
    done = {r["item_id"] for r in p3.load_jsonl(DATA / "revise.jsonl") if r.get("ok")}
    tasks = [(s, a, k) for s in plan() for a in ARMS for k in range(1, REPS + 1)
             if f'{s["set_id"]}|{a}|r{k}' not in done]
    random.Random(SEED + 1).shuffle(tasks)
    p3.run_pool(tasks, lambda t: do_revise(t[0], t[1], t[2], sels[t[0]["set_id"]]), "revise")


# ------------------------------------------------------------------ items
def items(include_v3=True):
    sels = selections()
    pl = {s["set_id"]: s for s in plan()}
    out = []
    for r in p3.load_jsonl(DATA / "revise.jsonl"):
        if not r.get("ok"):
            continue
        s = pl[r["set_id"]]
        cands, _ = p4.presented_candidates(s)
        out.append({"item_id": r["item_id"], "set_id": r["set_id"], "arm": r["arm"], "rep": r["rep"], "brand": s["brand"],
                    "topic": s["topic"], "cands": cands, "selected": sels[r["set_id"]]["parsed"]["selection"]["selected_id"],
                    "final": r["parsed"]["final_proposal"]})
    if include_v3:  # coder validation only (manual main codes exist for these)
        v3 = p4.v3_runs()
        for s in plan():
            g = v3[s["set_id"]]
            out.append({"item_id": f'{s["set_id"]}|V3_ORIGINAL|r0', "set_id": s["set_id"], "arm": "V3_ORIGINAL", "rep": 0,
                        "brand": s["brand"], "topic": s["topic"], "cands": g["parsed"]["candidates"],
                        "selected": g["parsed"]["selection"]["selected_id"], "final": g["parsed"]["final_proposal"]})
    return out


def cmd_code():
    out = DATA / "codes.jsonl"
    done = {r["item_id"] for r in p3.load_jsonl(out) if r.get("ok")}
    todo = [it for it in items() if it["item_id"] not in done]
    random.Random(SEED + 2).shuffle(todo)
    spec = CFG["coder"]

    def work(it):
        keys = list(ELEMENTS[it["brand"]])
        cb = "\n".join(f"{k}: {v}" for k, v in CODEBOOK[it["brand"]].items())
        el = "\n".join(f"{k}: {v}" for k, v in ELEMENTS[it["brand"]].items())
        rk = ", ".join(f'"{k}": {{"in_selected": true, "in_final": true}}' for k in keys)
        cand = "\n\n".join(f'{c["id"]}. {c["title"]}: {c["core_idea"]}' for c in it["cands"])
        up = (rt("code_user.txt").replace("[BRAND]", it["brand"]).replace("[TOPIC]", it["topic"])
              .replace("[SELECTED]", it["selected"]).replace("[CANDIDATES]", cand)
              .replace("[TITLE]", it["final"]["title"]).replace("[IDEA]", it["final"]["idea"])
              .replace("[CODEBOOK]", cb).replace("[ELEMENTS]", el).replace("[RECURRING_KEYS]", rk))
        res = p3.call("openai", spec, rt("code_system.txt"), up, validate=lambda t: parse_code(t, keys))
        p3.append_jsonl(out, {"item_id": it["item_id"], "set_id": it["set_id"], "arm": it["arm"], "rep": it["rep"],
                              "brand": it["brand"], "phase": "code", "user_prompt": up, **res})

    p3.run_pool(todo, work, "code")


def cmd_judge():
    out = DATA / "judgments.jsonl"
    done = {r["j_id"] for r in p3.load_jsonl(out) if r.get("ok")}
    tasks = [(it, d) for it in items(include_v3=False) for d in p3.DIMS if f'{it["item_id"]}|{d}' not in done]
    random.Random(SEED + 3).shuffle(tasks)

    def work(t):
        it, d = t
        up = (p3.read_text(p3.DIMS[d]).replace("[BRAND]", it["brand"]).replace("[TOPIC]", it["topic"])
              .replace("[TITLE]", it["final"]["title"]).replace("[IDEA]", it["final"]["idea"]))
        res = p3.call("openai", p3.CONFIG["judge"], p3.read_text("judge_system.txt"), up, validate=p3.parse_score)
        p3.append_jsonl(out, {"j_id": f'{it["item_id"]}|{d}', "item_id": it["item_id"], "arm": it["arm"],
                              "rep": it["rep"], "brand": it["brand"], "dim": d, "phase": "judge", "user_prompt": up, **res})

    p3.run_pool(tasks, work, "judge")


# ------------------------------------------------------------------ human coding sheet (blind to arm)
def cmd_human():
    pv5 = json.loads((LOGS / "plan_v5.json").read_text(encoding="utf-8"))
    HUMAN.mkdir(exist_ok=True)
    keydir = HUMAN / "_key_DO_NOT_OPEN_until_coding_done"
    keydir.mkdir(exist_ok=True)
    its = [it for it in items(include_v3=False) if it["set_id"] in pv5["human_coding_sets"] and it["rep"] == 1]
    rng = random.Random(SEED + 4)
    rng.shuffle(its)
    rows, key = [], []
    for it in its:
        hid = "K" + hashlib.sha256(f'{SEED}|{it["item_id"]}'.encode()).hexdigest()[:8]
        cand = "\n\n".join(f'{c["id"]}. {c["title"]}: {c["core_idea"]}' for c in it["cands"])
        rows.append({"item": hid, "brand": it["brand"], "topic": it["topic"], "candidates": cand,
                     "selected_candidate": it["selected"], "final_title": it["final"]["title"],
                     "final_idea": it["final"]["idea"],
                     "Q1_main_code": "", "Q2_selected_core_retained_yes_partial_no": "",
                     "Q3_added_elements_from_other_candidates(element=Cx; ...)": "",
                     "Q4_role_main_or_auxiliary_per_element": "",
                     "Q5_function_needed_develops_extra_unclear_per_element": "",
                     **{f"Q6_{k}_in_final_0_1": "" for k in ("MARK", "EMPLOYER_KIT", "KEEPSAKE",
                                                               "MERCHANT_RECOGNITION", "PAID_INVITATION")},
                     "notes": ""})
        key.append({"item": hid, "item_id": it["item_id"], "arm": it["arm"], "rep": it["rep"]})
    for rater in ("A", "B"):
        with open(HUMAN / f"coding_sheet_researcher{rater}.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    with open(keydir / "key.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0]))
        w.writeheader()
        w.writerows(key)
    print(f"{len(rows)} items -> {HUMAN}")


if __name__ == "__main__":
    cmds = {"setup": cmd_setup, "smoke": cmd_smoke, "revise": cmd_revise, "code": cmd_code, "judge": cmd_judge,
            "human": cmd_human}
    if len(sys.argv) < 2 or (sys.argv[1] not in cmds and sys.argv[1] != "analyze"):
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "analyze":
        import analyze5
        analyze5.main()
    else:
        cmds[sys.argv[1]]()
        print("cost this session:", {k: round(v, 3) for k, v in p3._cost.items()})
