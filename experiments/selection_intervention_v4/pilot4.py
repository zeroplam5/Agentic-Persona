"""Pilot v4: post-selection element review vs current revision step (exploratory). See DESIGN.md.

Same initial candidates and the same selection are given to both arms; only the post-selection step differs.

  python pilot4.py setup      # choose candidate sets, shuffled orders, freeze hashes -> logs/
  python pilot4.py smoke      # 1 select + 2 revise calls -> logs/smoke.jsonl only
  python pilot4.py select     # shared selection call per set (Claude CLI)
  python pilot4.py revise     # BASELINE and REVIEW arm per set (Claude CLI)
  python pilot4.py code       # blind coding of finals (gpt-6-astra), incl. original v3 finals of the same sets
  python pilot4.py judge      # brand fit / feasibility / logic per final (gpt-6-astra, v3 rubric)
  python pilot4.py human      # blind human sheet -> ../../human_rating_blind_v4_selection/
  python pilot4.py analyze    # results/pilot_report.md, results/pilot_items.csv

Reuses ../pilot_v3_structured/pilot3.py call helpers (same CLI, model, effort, thinking/output caps).
Keys are read from the project .env by pilot3 and never printed or logged.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "pilot_v3_structured"))
import pilot3 as p3  # noqa: E402

from coding_existing import CODEBOOK, FINAL as FINAL_V3  # noqa: E402

PROMPTS = ROOT / "prompts"
DATA = ROOT / "data"
LOGS = ROOT / "logs"
RES = ROOT / "results"
for d in (DATA, LOGS, RES):
    d.mkdir(exist_ok=True)
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SEED = CFG["seed"]
HUMAN = ROOT.parent.parent / "human_rating_blind_v4_selection"

# pilot3 settings overridden for this study (model/effort/caps unchanged)
p3.CONFIG["generator"]["isolated_cwd"] = CFG["isolated_cwd"]
p3.CONFIG["budget_usd"] = CFG["budget_usd"]
p3.CONFIG["workers"] = CFG["workers"]
GEN_ENV = p3.CONFIG["generator"]["cli_env"]  # MAX_THINKING_TOKENS 8000, CLAUDE_CODE_MAX_OUTPUT_TOKENS 16000
SYSTEM = p3.system_prompt("BASE")  # common system prompt, no persona block

ELEMENTS = {
    "Dior": {"MARK": "a mark, signature, initials, date, label, star or signed card added by the artisan or house to a repaired piece"},
    "Canva": {"EMPLOYER_KIT": "a version, kit or channel through which employers, managers, HR or teams send or use the idea for new hires",
              "KEEPSAKE": "a frameable, printable or shareable memento or card of the first-paycheck moment"},
    "Mastercard": {"MERCHANT_RECOGNITION": "a merchant-side recognition or unhurried-till layer: a Regulars mark or sticker, staff greeting people by name, a chosen name shown at tap, a slow lane, or a slower or warmer payment sound",
                   "PAID_INVITATION": "a pre-paid or covered invitation or treat sent to another person, often unlocking only when both are present"},
}


def rt(name):
    return (PROMPTS / name).read_text(encoding="utf-8")


def v3_runs():
    out = {}
    for g in p3.load_jsonl(p3.DATA / "generations.jsonl"):
        if g["kind"] == "structured" and g.get("ok"):
            out[g["run_id"]] = g
    return out


def render_candidates(cands):
    keep = ("id", "title", "core_idea", "brand_connection", "expected_strengths", "main_concerns")
    return json.dumps([{k: c.get(k) for k in keep} for c in cands], indent=2, ensure_ascii=False)


def fill(tpl, s, **kw):
    t = tpl.replace("[BRAND]", s["brand"]).replace("[CATEGORY]", s["category"]).replace("[TOPIC]", s["topic"])
    for k, v in kw.items():
        t = t.replace(f"[{k}]", v)
    return t


# ------------------------------------------------------------------ parsers
def parse_select(text, ids=("C1", "C2", "C3", "C4")):
    j = p3._json_obj(text)
    try:
        s = j["selection"]
        assert s["selected_id"] in ids and s.get("reasons_for_selection")
        assert {r["id"] for r in s["rejected"]} == set(ids) - {s["selected_id"]}
        return j
    except Exception:
        return None


def parse_revise(text, review=False):
    j = p3._json_obj(text)
    try:
        assert isinstance(j["revisions_after_selection"], list)
        fp = j["final_proposal"]
        assert fp.get("title") and fp.get("idea") and len(fp.get("follow_up_questions", [])) == 3
        if review:
            er = j["element_review"]
            assert er.get("selected_core_idea") and isinstance(er.get("candidate_elements"), list)
        return j
    except Exception:
        return None


def parse_code(text, keys):
    j = p3._json_obj(text)
    try:
        assert j["final_main_code"] and j["selected_core_retained"] in ("yes", "partial", "no")
        assert isinstance(j["added_elements"], list)
        int(j.get("safeguards_added", 0))
        for k in keys:
            assert isinstance(j["recurring"][k]["in_selected"], bool) and isinstance(j["recurring"][k]["in_final"], bool)
        return j
    except Exception:
        return None


# ------------------------------------------------------------------ setup
def cmd_setup():
    runs = v3_runs()
    rng = random.Random(SEED)
    sets = []
    for b in CFG["brands"]:
        base = sorted(r for r in runs if r.startswith(b + "|BASE|"))
        other = sorted(r for r in runs if r.startswith(b + "|") and "|BASE|" not in r)
        chosen = base + rng.sample(other, CFG["sets_per_brand"] - len(base))
        for rid in chosen:
            g = runs[rid]
            order = list(range(4))
            rng.shuffle(order)
            sets.append({"set_id": rid, "brand": g["brand"], "category": g["category"], "topic": g["topic"],
                         "source_condition": g["condition"],
                         "presented_order_original_pos": [i + 1 for i in order],
                         "v3_selected_original_id": g["parsed"]["selection"]["selected_id"]})
    (LOGS / "plan.json").write_text(json.dumps(sets, indent=1, ensure_ascii=False), encoding="utf-8")
    freeze()
    print(f"{len(sets)} sets written to logs/plan.json")


def freeze():
    files = sorted([*PROMPTS.glob("*.txt"), ROOT / "DESIGN.md", ROOT / "config.json", LOGS / "plan.json"])
    lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(ROOT).as_posix()}" for f in files]
    (LOGS / "freeze_hashes.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def plan():
    return json.loads((LOGS / "plan.json").read_text(encoding="utf-8"))


def presented_candidates(s):
    """Candidates in the shuffled order, relabelled C1..C4. Returns (list, map new_id -> original id)."""
    g = v3_runs()[s["set_id"]]
    orig = g["parsed"]["candidates"]
    out, idmap = [], {}
    for new_i, orig_pos in enumerate(s["presented_order_original_pos"]):
        c = dict(orig[orig_pos - 1])
        idmap[f"C{new_i + 1}"] = c["id"]
        c["id"] = f"C{new_i + 1}"
        out.append(c)
    return out, idmap


# ------------------------------------------------------------------ generation
def do_select(s, log=DATA / "select.jsonl"):
    cands, idmap = presented_candidates(s)
    up = fill(rt("select_user.txt"), s, CANDIDATES=render_candidates(cands))
    res = p3.call("claude", GEN_ENV, SYSTEM, up, validate=parse_select)
    p3.append_jsonl(log, {"set_id": s["set_id"], "phase": "select", "idmap": idmap, "user_prompt": up,
                          "system_prompt": SYSTEM, **res})


def selections():
    return {r["set_id"]: r for r in p3.load_jsonl(DATA / "select.jsonl") if r.get("ok")}


def do_revise(s, arm, sel_rec, log=DATA / "revise.jsonl"):
    cands, idmap = presented_candidates(s)
    tpl = rt("revise_intervention_user.txt" if arm == "REVIEW" else "revise_baseline_user.txt")
    up = fill(tpl, s, CANDIDATES=render_candidates(cands),
              SELECTION=json.dumps(sel_rec["parsed"], indent=2, ensure_ascii=False))
    res = p3.call("claude", GEN_ENV, SYSTEM, up, validate=lambda t: parse_revise(t, review=arm == "REVIEW"))
    p3.append_jsonl(log, {"item_id": f'{s["set_id"]}|{arm}', "set_id": s["set_id"], "arm": arm, "phase": "revise",
                          "idmap": idmap, "user_prompt": up, "system_prompt": SYSTEM, **res})


def cmd_smoke():
    s = plan()[0]
    log = LOGS / "smoke.jsonl"
    do_select(s, log)
    rec = [r for r in p3.load_jsonl(log) if r["phase"] == "select"][-1]
    print("select ok:", rec.get("ok"), rec.get("error"), "tokens", (rec.get("usage") or {}).get("output_tokens"),
          "cost", rec.get("total_cost_usd"))
    if rec.get("ok"):
        for arm in CFG["arms"]:
            do_revise(s, arm, rec, log)
        for r in [x for x in p3.load_jsonl(log) if x["phase"] == "revise"][-2:]:
            print(r["arm"], "ok:", r.get("ok"), r.get("error"), "tokens", (r.get("usage") or {}).get("output_tokens"),
                  "cost", r.get("total_cost_usd"))


def cmd_select():
    done = set(selections())
    p3.run_pool([s for s in plan() if s["set_id"] not in done], do_select, "select")


def cmd_revise():
    sels = selections()
    done = {r["item_id"] for r in p3.load_jsonl(DATA / "revise.jsonl") if r.get("ok")}
    tasks = [(s, a) for s in plan() for a in CFG["arms"] if s["set_id"] in sels and f'{s["set_id"]}|{a}' not in done]
    random.Random(SEED + 1).shuffle(tasks)
    p3.run_pool(tasks, lambda t: do_revise(t[0], t[1], sels[t[0]["set_id"]]), "revise")


# ------------------------------------------------------------------ items (finals to code / judge / rate)
def items():
    """Pilot finals for both arms + the original v3 single-call final of the same set (reference)."""
    sels = selections()
    out = []
    v3 = v3_runs()
    for r in p3.load_jsonl(DATA / "revise.jsonl"):
        if not r.get("ok"):
            continue
        s = next(x for x in plan() if x["set_id"] == r["set_id"])
        cands, _ = presented_candidates(s)
        out.append({"item_id": r["item_id"], "set_id": r["set_id"], "arm": r["arm"], "brand": s["brand"],
                    "topic": s["topic"], "cands": cands, "selected": sels[r["set_id"]]["parsed"]["selection"]["selected_id"],
                    "final": r["parsed"]["final_proposal"]})
    for s in plan():
        g = v3[s["set_id"]]
        out.append({"item_id": f'{s["set_id"]}|V3_ORIGINAL', "set_id": s["set_id"], "arm": "V3_ORIGINAL",
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
        p3.append_jsonl(out, {"item_id": it["item_id"], "set_id": it["set_id"], "arm": it["arm"], "brand": it["brand"],
                              "phase": "code", "user_prompt": up, **res})

    p3.run_pool(todo, work, "code")


def cmd_judge():
    out = DATA / "judgments.jsonl"
    done = {r["j_id"] for r in p3.load_jsonl(out) if r.get("ok")}
    tasks = [(it, d) for it in items() for d in p3.DIMS if f'{it["item_id"]}|{d}' not in done]
    random.Random(SEED + 3).shuffle(tasks)

    def work(t):
        it, d = t
        up = (p3.read_text(p3.DIMS[d]).replace("[BRAND]", it["brand"]).replace("[TOPIC]", it["topic"])
              .replace("[TITLE]", it["final"]["title"]).replace("[IDEA]", it["final"]["idea"]))
        res = p3.call("openai", p3.CONFIG["judge"], p3.read_text("judge_system.txt"), up, validate=p3.parse_score)
        p3.append_jsonl(out, {"j_id": f'{it["item_id"]}|{d}', "item_id": it["item_id"], "arm": it["arm"],
                              "brand": it["brand"], "dim": d, "phase": "judge", "user_prompt": up, **res})

    p3.run_pool(tasks, work, "judge")


# ------------------------------------------------------------------ human sheet (blind to arm)
def cmd_human():
    HUMAN.mkdir(exist_ok=True)
    keydir = HUMAN / "_key_DO_NOT_OPEN_until_rating_done"
    keydir.mkdir(exist_ok=True)
    its = [it for it in items() if it["arm"] in CFG["arms"]]
    rng = random.Random(SEED + 4)
    rng.shuffle(its)
    rows, key = [], []
    for it in its:
        hid = "H" + hashlib.sha256(f'{SEED}|{it["item_id"]}'.encode()).hexdigest()[:8]
        rows.append({"item": hid, "brand": it["brand"], "topic": it["topic"], "title": it["final"]["title"],
                     "idea": it["final"]["idea"], "follow_up_questions": " | ".join(it["final"]["follow_up_questions"]),
                     "S1_satisfaction_1to5": "", "S2_new_perspective_1to5": "", "S3_helps_followup_ideas_1to5": "",
                     "B_brand_fit_1to5_optional": "", "F_feasibility_1to5_optional": "", "L_logic_1to5_optional": "",
                     "new_thoughts_optional": ""})
        key.append({"item": hid, "item_id": it["item_id"], "arm": it["arm"]})
    for rater in ("A", "B"):
        with open(HUMAN / f"rating_sheet_rater{rater}.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    with open(keydir / "key.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0]))
        w.writeheader()
        w.writerows(key)
    (HUMAN / "README_평가안내.md").write_text(
        "# 사람 평가 안내 (파일럿 v4)\n\n"
        "- 각 행은 기획안 하나입니다. 어떤 절차로 만들어졌는지는 가려져 있습니다. 성격 조건은 모두 같습니다(지정 없음).\n"
        "- 평가자 A·B는 서로 상의하지 않고 각자 시트를 채웁니다. 1–5 정수.\n"
        "  - S1 만족: 이 기획안을 내 작업에 참고하고 싶은 정도\n"
        "  - S2 새 관점: 내가 떠올리지 못한 관점을 주는 정도\n"
        "  - S3 후속 생각: 이 안을 보고 다른 아이디어가 떠오르는 정도\n"
        "  - B/F/L(선택): 브랜드 적합 / 실행 가능성 / 논리\n"
        "- 같은 브랜드의 비슷한 안이 여러 번 나올 수 있습니다. 순서는 무작위입니다.\n"
        "- `_key_DO_NOT_OPEN_until_rating_done/`은 평가를 마친 뒤에만 엽니다.\n",
        encoding="utf-8")
    print(f"{len(rows)} items -> {HUMAN}")


if __name__ == "__main__":
    cmds = {"setup": cmd_setup, "smoke": cmd_smoke, "select": cmd_select, "revise": cmd_revise, "code": cmd_code,
            "judge": cmd_judge, "human": cmd_human}
    if len(sys.argv) < 2 or (sys.argv[1] not in cmds and sys.argv[1] != "analyze"):
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "analyze":
        import analyze_pilot
        analyze_pilot.main()
    else:
        cmds[sys.argv[1]]()
        print("cost this session:", {k: round(v, 3) for k, v in p3._cost.items()})
