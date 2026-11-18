"""Analysis for pilot v3 (run via `python pilot3.py analyze`). Follows ANALYSIS_PLAN.md. Stdlib only.

Writes results/idea_level.csv, results/run_process.csv, results/condition_table.csv, results/contrasts.csv,
results/manip_table.csv, results/bucket_summary.md, results/report.md, results/summary.json.
Human columns are used only if both rating sheets have numbers filled in and the key exists.
"""
from __future__ import annotations

import csv
import json
import math
import random
import statistics as st
from collections import Counter, defaultdict

import pilot3 as P

R = P.RESULTS
B_BOOT = 2000


def norm5(x):
    return None if x is None else (x - 1) / 4


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def boot_ci(rows, f, key="brand", n=B_BOOT, seed=1):
    """Resample rows within each brand (stratified bootstrap); f(rows) -> value."""
    by = defaultdict(list)
    for r in rows:
        by[r[key]].append(r)
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        s = []
        for g in by.values():
            s += [rng.choice(g) for _ in g]
        v = f(s)
        if v is not None:
            vals.append(v)
    if not vals:
        return None, None
    vals.sort()
    return vals[int(.025 * len(vals))], vals[int(.975 * len(vals)) - 1]


def fmt(x, d=2):
    return "–" if x is None else f"{x:.{d}f}"


def spearman(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 3:
        return None

    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = rank([p[0] for p in pairs]), rank([p[1] for p in pairs])
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return None if den == 0 else num / den


def wkappa(a, b, k=5):
    pairs = [(x, y) for x, y in zip(a, b)]
    n = len(pairs)
    if n == 0:
        return None
    w = lambda i, j: (i - j) ** 2 / (k - 1) ** 2
    obs = sum(w(x, y) for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    exp = sum(ca[i] * cb[j] * w(i, j) for i in range(1, k + 1) for j in range(1, k + 1)) / n ** 2
    return None if exp == 0 else 1 - obs / exp


def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------ human
def load_human():
    key_p = P.HUMAN / "_key_DO_NOT_OPEN_until_rating_done" / "key.csv"
    if not key_p.exists():
        return {}, "no human sheets"
    key = {r["item"]: r["run_id"] for r in csv.DictReader(key_p.open(encoding="utf-8"))}
    out = defaultdict(dict)
    filled = 0
    for rater in ("A", "B"):
        p = P.HUMAN / f"rating_sheet_rater{rater}.csv"
        if not p.exists():
            continue
        for r in csv.DictReader(p.open(encoding="utf-8-sig")):
            def num(c):
                try:
                    v = int(str(r.get(c, "")).strip())
                    return v if 1 <= v <= 5 else None
                except ValueError:
                    return None
            vals = {k: num(c) for k, c in [("S1", "S1_satisfaction_1to5"), ("S2", "S2_new_perspective_1to5"),
                                           ("S3", "S3_helps_followup_ideas_1to5"), ("B", "B_brand_fit_1to5_optional"),
                                           ("F", "F_feasibility_1to5_optional"), ("L", "L_logic_1to5_optional")]}
            if any(v is not None for v in vals.values()):
                filled += 1
            vals["new_thoughts"] = (r.get("new_thoughts_optional") or "").strip()
            out[key[r["item"]]][rater] = vals
    return (out if filled else {}), f"{filled} filled rows"


# ------------------------------------------------------------------ main
def main():
    R.mkdir(exist_ok=True)
    runs = P.runs()
    byrun = {r["run_id"]: r for r in runs}
    ba = P.bucket_assignments()
    orig = {k: P.originality(v) for k, v in ba.items()}

    # judgments (pass 0 = primary, pass 1 = retest)
    J = defaultdict(dict)
    retest = []
    jl = [j for j in P.load_jsonl(P.DATA / "judgments.jsonl") if j.get("ok")]
    latest = {j["j_id"]: j for j in jl}
    for j in latest.values():
        J[(j["run_id"], j["pass"])][j["dim"]] = j["parsed"]["score"]
    for (rid, ps), d in J.items():
        if ps == 1:
            for dim, s in d.items():
                if dim in J.get((rid, 0), {}):
                    retest.append((J[(rid, 0)][dim], s, dim))

    human, human_note = load_human()

    # ---------------- idea level
    ideas = []
    for r in runs:
        fo = orig.get((r["brand"], "final"), {}).get(f"{r['run_id']}|final")
        co = orig.get((r["brand"], "cand"), {})
        cb = [co.get(f"{r['run_id']}|{c['id']}") for c in r["candidates"]]
        sel = co.get(f"{r['run_id']}|{r['selected_id']}")
        js = J.get((r["run_id"], 0), {})
        Bn, Fn, Ln = (norm5(js.get(d)) for d in "BFL")
        Pm = mean([Bn, Fn, Ln]) if None not in (Bn, Fn, Ln) else None
        Pmin = min(Bn, Fn, Ln) if Pm is not None else None
        Pgeo = (Bn * Fn * Ln) ** (1 / 3) if Pm is not None else None
        D = fo["shapley"] if fo else None
        h = human.get(r["run_id"], {})
        S_r = {}
        for rater, v in h.items():
            if None not in (v["S1"], v["S2"], v["S3"]):
                S_r[rater] = norm5((v["S1"] + v["S2"] + v["S3"]) / 3)
        S = mean(list(S_r.values())) if S_r else None
        usage = [u or {} for u in r["usage"]]
        reas = [x or {} for x in r["reasoning"]]
        rec = r["record"]
        row = {
            "run_id": r["run_id"], "brand": r["brand"], "topic": r["topic"], "condition": r["condition"], "rep": r["rep"],
            "final_title": r["final"]["title"],
            "bucket_final": fo["bucket"] if fo else None, "m_final": fo["m"] if fo else None, "N_final": fo["N"] if fo else None,
            "D_shapley": D, "D_rarity": fo["rarity"] if fo else None, "D_unique": fo["unique"] if fo else None,
            "D_threshold": fo["threshold"] if fo else None,
            "B_llm_1to5": js.get("B"), "F_llm_1to5": js.get("F"), "L_llm_1to5": js.get("L"),
            "P_mean": Pm, "P_min": Pmin, "P_geo": Pgeo,
            "Auto_100DP": None if None in (D, Pm) else 100 * D * Pm,
            "S_human": S, "S_raterA": S_r.get("A"), "S_raterB": S_r.get("B"),
            "Composite_100DPS": None if None in (D, Pm, S) else 100 * D * Pm * S,
            "Composite_Pmin": None if None in (D, Pmin, S) else 100 * D * Pmin * S,
            "Composite_x5": (None if None in (D, S) or not js or len(js) < 3 else
                             100 * D * (mean([js[d] / 5 for d in "BFL"])) * (S * 4 + 1) / 5),
            "Composite_additive": None if None in (D, Pm, S) else 100 * (D + Pm + S) / 3,
            "cand_distinct_buckets": len({c["bucket"] for c in cb if c}) if all(cb) else None,
            "selected_cand_shapley": sel["shapley"] if sel else None,
            "selected_position": r["selected_id"],
            "n_revisions": len(rec.get("revisions_after_selection") or []) if r["kind"] == "structured" else None,
            "n_assumptions": (len(rec["task_understanding"].get("assumptions") or []) if r["kind"] == "structured" else
                              mean([len(c["task_understanding"].get("assumptions") or []) for c in rec["independent_calls"]])),
            "n_concerns_mean": mean([len(c.get("main_concerns") or []) for c in r["candidates"]]),
            "output_tokens": sum(u.get("output_tokens") or 0 for u in usage),
            "input_tokens": sum(u.get("input_tokens") or 0 for u in usage),
            "thinking_blocks": sum(x.get("thinking_blocks") or 0 for x in reas),
            "visible_chars": sum(x.get("visible_text_chars") or 0 for x in reas),
            "final_words": len(r["final"]["idea"].split()),
        }
        ideas.append(row)
    write_csv(R / "idea_level.csv", ideas)

    # ---------------- condition table
    metrics = ["D_shapley", "D_rarity", "D_unique", "B_llm_1to5", "F_llm_1to5", "L_llm_1to5", "P_mean", "P_min",
               "Auto_100DP", "S_human", "Composite_100DPS", "cand_distinct_buckets", "selected_cand_shapley",
               "n_revisions", "output_tokens", "thinking_blocks", "visible_chars", "final_words"]
    cond_rows = []
    for c in P.ALL_RUN_CONDITIONS:
        rs = [x for x in ideas if x["condition"] == c]
        row = {"condition": c, "n_runs": len(rs)}
        for m in metrics:
            vals = [x[m] for x in rs if x[m] is not None]
            row[m] = round(st.mean(vals), 3) if vals else None
            row[m + "_n"] = len(vals)
        # distinct final buckets among the condition's 4 runs per brand
        dist = []
        for b in {x["brand"] for x in rs}:
            bs = [x["bucket_final"] for x in rs if x["brand"] == b and x["bucket_final"] is not None]
            if bs:
                dist.append(len(set(bs)) / len(bs))
        row["final_distinct_bucket_ratio"] = round(st.mean(dist), 3) if dist else None
        cond_rows.append(row)
    write_csv(R / "condition_table.csv", cond_rows)

    # ---------------- contrasts with stratified bootstrap
    contrasts = [("SB_O_H", "SB_AVG"), ("SB_O_L", "SB_AVG"), ("LK_O_H", "LK_AVG"), ("LK_O_L", "LK_AVG"),
                 ("SB_AVG", "BASE"), ("LK_AVG", "BASE"), ("BASE", "NODEDUP")]
    con_rows = []
    for a, b in contrasts:
        for m in ["D_shapley", "P_mean", "B_llm_1to5", "F_llm_1to5", "L_llm_1to5", "Auto_100DP", "output_tokens",
                  "Composite_100DPS"]:
            rows = [x for x in ideas if x["condition"] in (a, b) and x[m] is not None]

            def diff(s, m=m):
                xa = [x[m] for x in s if x["condition"] == a]
                xb = [x[m] for x in s if x["condition"] == b]
                return st.mean(xa) - st.mean(xb) if xa and xb else None
            d = diff(rows)
            lo, hi = boot_ci(rows, diff) if d is not None else (None, None)
            con_rows.append({"contrast": f"{a} - {b}", "metric": m, "n_a": sum(x["condition"] == a for x in rows),
                             "n_b": sum(x["condition"] == b for x in rows), "diff": None if d is None else round(d, 3),
                             "ci_lo": None if lo is None else round(lo, 3), "ci_hi": None if hi is None else round(hi, 3)})
    write_csv(R / "contrasts.csv", con_rows)

    # ---------------- manipulation check
    mm_rows = [m for m in P.load_jsonl(P.DATA / "manipulation_check.jsonl") if m.get("ok")]
    mm_latest = {m["mc_id"]: m for m in mm_rows}
    key = P.MM["key"]

    def mm_score(parsed, t):
        vals = [parsed[w] for w in key[t]["+"]] + [10 - parsed[w] for w in key[t]["-"]]
        return st.mean(vals)
    obs = {o["run_id"]: o["parsed"] for o in P.load_jsonl(P.DATA / "observer.jsonl") if o.get("ok")}
    manip = []
    for c in P.STRUCT_CONDITIONS:
        ms = [m["parsed"] for m in mm_latest.values() if m["condition"] == c]
        os_ = [v for rid, v in obs.items() if byrun.get(rid, {}).get("condition") == c]
        row = {"condition": c, "n_selfreport": len(ms), "n_observer": len(os_)}
        for t in "OCEAN":
            row[f"self_{t}"] = round(st.mean(mm_score(p, t) for p in ms), 2) if ms else None
            row[f"self_{t}_sd"] = round(st.stdev(mm_score(p, t) for p in ms), 2) if len(ms) > 1 else None
        for t in "OCEAN":
            row[f"obs_{t}"] = round(st.mean(o[t] for o in os_), 2) if os_ else None
        manip.append(row)
    write_csv(R / "manip_table.csv", manip)

    # ---------------- bucket summary + process
    lines = ["# 묶음 요약 (자동 생성)\n", "같은 묶음 = GPT-6-astra가 '같은 핵심 발상'이라고 판단한 것. 코사인은 후보 검색에만 썼다.\n"]
    bsum = {}
    for (brand, setname), rows in sorted(ba.items()):
        sizes = Counter(r["bucket"] for r in rows.values())
        bsum[f"{brand}|{setname}"] = {"n_items": len(rows), "n_buckets": len(sizes),
                                      "singletons": sum(1 for v in sizes.values() if v == 1),
                                      "largest": sizes.most_common(1)[0][1] if sizes else 0}
        lines.append(f"\n## {brand} / {setname}: 아이디어 {len(rows)}개, 묶음 {len(sizes)}개, 단독 묶음 "
                     f"{bsum[f'{brand}|{setname}']['singletons']}개\n")
        if setname == "final":
            for b, n in sizes.most_common():
                if n < 2:
                    break
                mem = sorted([r for r in rows.values() if r["bucket"] == b], key=lambda x: x["order"])
                lines.append(f"\n**묶음 {b} ({n}개)** — 조건: {', '.join(m['condition'] for m in mem)}\n")
                for m in mem:
                    lines.append(f"- {m['text'][:220]}\n")
    (R / "bucket_summary.md").write_text("".join(lines), encoding="utf-8")

    # retest agreement
    rt = {"n": len(retest)}
    if retest:
        rt["exact"] = round(sum(a == b for a, b, _ in retest) / len(retest), 3)
        rt["within1"] = round(sum(abs(a - b) <= 1 for a, b, _ in retest) / len(retest), 3)
        rt["weighted_kappa"] = round(wkappa([a for a, _, _ in retest], [b for _, b, _ in retest]) or 0, 3)

    # human agreement
    hum = {"status": human_note}
    if human:
        for k in ("S1", "S2", "S3", "B", "F", "L"):
            a = [human[r].get("A", {}).get(k) for r in human]
            b = [human[r].get("B", {}).get(k) for r in human]
            hum[f"spearman_AB_{k}"] = spearman(a, b)
        for k, col in (("B", "B_llm_1to5"), ("F", "F_llm_1to5"), ("L", "L_llm_1to5")):
            hv = [mean([human[x["run_id"]].get(rt_, {}).get(k) for rt_ in ("A", "B")]) if x["run_id"] in human else None
                  for x in ideas]
            hum[f"spearman_human_llm_{k}"] = spearman(hv, [x[col] for x in ideas])

    # costs
    def costsum(path, field="est_cost_usd"):
        rows = P.load_jsonl(path)
        return round(sum(float(r.get(field) or 0) + sum(float(a.get(field) or 0) for a in r.get("failed_attempts") or [])
                         for r in rows), 3), len(rows)
    bucket_rows = [r for r in P.load_jsonl(P.DATA / "buckets.jsonl") if r.get("phase") == "assign"]
    costs = {"claude_generate_nominal": costsum(P.DATA / "generations.jsonl", "total_cost_usd"),
             "claude_manip_nominal": costsum(P.DATA / "manipulation_check.jsonl", "total_cost_usd"),
             "openai_judge": costsum(P.DATA / "judgments.jsonl"),
             "openai_bucket": (round(sum(float((r["llm"] or {}).get("est_cost_usd") or 0) for r in bucket_rows), 3),
                               sum(1 for r in bucket_rows if (r["llm"] or {}).get("text") is not None)),
             "gemini_observer": costsum(P.DATA / "observer.jsonl")}
    gen_all = P.load_jsonl(P.DATA / "generations.jsonl")
    errors = {"generation_records": len(gen_all), "generation_failed_final": sum(1 for g in gen_all if not g.get("ok")),
              "generation_retries": sum(len(g.get("failed_attempts") or []) for g in gen_all),
              "bucket_fallbacks": sum(1 for r in bucket_rows if (r["llm"] or {}).get("fallback"))}
    models = sorted({m for g in gen_all for m in (g.get("model_returned") or [])})
    summary = {"conditions": cond_rows, "contrasts": con_rows, "manip": manip, "buckets": bsum, "judge_retest": rt,
               "human": hum, "costs": costs, "errors": errors, "generator_models_returned": models}
    (R / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    report(summary, ideas)
    print("analysis written to", R)


def report(s, ideas):
    L = []
    w = L.append
    w("# 파일럿 v3 결과 (자동 생성 표, 탐색적)\n\n")
    w("Wild Ideas 파일럿(v1)과 다른 실험이다. 브랜드 3개, 조건당 실행 12개. 구간은 브랜드 안 재표집 부트스트랩 95%.\n\n")
    w("## 조건별 평균\n\n")
    cols = [("D_shapley", "D(1/m)"), ("D_unique", "단독 비율"), ("final_distinct_bucket_ratio", "조건 내 서로 다른 묶음 비율"),
            ("B_llm_1to5", "B"), ("F_llm_1to5", "F"), ("L_llm_1to5", "L"), ("P_mean", "P"), ("Auto_100DP", "Auto"),
            ("cand_distinct_buckets", "실행 내 후보 묶음 수"), ("selected_cand_shapley", "선택 후보 D"),
            ("n_revisions", "수정 수"), ("output_tokens", "출력 토큰"), ("thinking_blocks", "thinking 블록"),
            ("S_human", "S(사람)"), ("Composite_100DPS", "종합")]
    w("| 조건 | n | " + " | ".join(c[1] for c in cols) + " |\n|" + "---|" * (len(cols) + 2) + "\n")
    for r in s["conditions"]:
        w(f"| {r['condition']} | {r['n_runs']} | " + " | ".join(
            fmt(r.get(c), 0 if c == "output_tokens" else 2) for c, _ in cols) + " |\n")
    w("\n## 사전 지정 대비 (차이 [95% 구간])\n\n| 대비 | D | P | B | F | L | Auto | 출력 토큰 |\n|---|---|---|---|---|---|---|---|\n")
    by = defaultdict(dict)
    for c in s["contrasts"]:
        by[c["contrast"]][c["metric"]] = c
    for k, d in by.items():
        cell = lambda m, dd=d: (f"{fmt(dd[m]['diff'], 0 if m == 'output_tokens' else 2)} "
                                f"[{fmt(dd[m]['ci_lo'], 0 if m == 'output_tokens' else 2)}, "
                                f"{fmt(dd[m]['ci_hi'], 0 if m == 'output_tokens' else 2)}]") if d.get(m) else "–"
        w(f"| {k} | " + " | ".join(cell(m) for m in ["D_shapley", "P_mean", "B_llm_1to5", "F_llm_1to5", "L_llm_1to5",
                                                    "Auto_100DP", "output_tokens"]) + " |\n")
    w("\n## 조작 확인 (1–9점; self = Claude Mini-Markers 자기 보고, obs = Gemini 관찰자)\n\n")
    w("| 조건 | n | self O | self C | self E | self A | self N | obs O | obs C | obs E | obs A | obs N |\n|" + "---|" * 12 + "\n")
    for r in s["manip"]:
        w(f"| {r['condition']} | {r['n_selfreport']}/{r['n_observer']} | " +
          " | ".join(fmt(r.get(f"self_{t}")) for t in "OCEAN") + " | " + " | ".join(fmt(r.get(f"obs_{t}")) for t in "OCEAN") + " |\n")
    w("\n## 묶음\n\n| 집합 | 아이디어 | 묶음 | 단독 | 최대 묶음 |\n|---|---|---|---|---|\n")
    for k, v in s["buckets"].items():
        w(f"| {k} | {v['n_items']} | {v['n_buckets']} | {v['singletons']} | {v['largest']} |\n")
    w(f"\n## 평가 재검사\n\n{json.dumps(s['judge_retest'], ensure_ascii=False)}\n\n## 사람 평가\n\n{json.dumps(s['human'], ensure_ascii=False, default=str)}\n")
    w(f"\n## 비용·오류\n\n{json.dumps(s['costs'], ensure_ascii=False)}\n\n{json.dumps(s['errors'], ensure_ascii=False)}\n\n"
      f"생성 모델(반환값): {s['generator_models_returned']}\n")
    (R / "report.md").write_text("".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
