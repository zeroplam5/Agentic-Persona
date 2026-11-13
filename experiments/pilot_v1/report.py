"""Report v1.1: recompute everything from the stored raw records (no new model calls),
verify against the earlier outputs, and write an improved report + figures.

Run (v1):  uv run --no-project --python 3.12 --with numpy --with matplotlib python report.py
Run (v2):  set PILOT_MODULE=pilot2 and PILOT_DIR=../pilot_v2, then the same command (writes into pilot_v2/results).
The composite definition, display rounding and tie rules below are shared by every experiment version.
Inputs (read-only): data/generations.jsonl, data/judgments.jsonl, data/manipulation_check.jsonl,
                    results/diversity_cells.json, results/summary.json, results/idea_level_scores.csv
Outputs: results/report_v1.1.md, results/condition_table.csv, results/high_low_table.csv,
         results/verification_v1.1.json, results/figures/*.png
The earlier results/report.md and summary.json are NOT modified.
"""
from __future__ import annotations

import csv
import json
import math
import random
import statistics as st
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import importlib  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

_MOD = os.environ.get("PILOT_MODULE", "pilot")
if os.environ.get("PILOT_DIR"):
    sys.path.insert(0, str(Path(os.environ["PILOT_DIR"]).resolve()))
pilot = importlib.import_module(_MOD)  # experiment module: loaders, bootstrap, manipulation-check scoring
IS_V1 = _MOD == "pilot"
VERSION = "v1.1" if IS_V1 else pilot.CONFIG["experiment"].rsplit("_", 1)[-1]

ROOT = pilot.ROOT
RES = pilot.RESULTS
FIG = RES / "figures"
FIG.mkdir(parents=True, exist_ok=True)
CONDS = pilot.CONDITIONS
TRAITS = pilot.TRAITS
REFS = getattr(pilot, "REFERENCE_CONDITIONS", ["BASE"])          # non-trait conditions
PRIMARY_REF = getattr(pilot, "PRIMARY_REF", "BASE")               # reference for trait effects
EXTRA_CONTRASTS = getattr(pilot, "EXTRA_CONTRASTS", [])           # e.g. CTRL vs BASE
JUDGE_NAME = (pilot.CONFIG.get("judge_model") or pilot.CONFIG.get("judge", {}).get("model"))
GEN_NAME = (pilot.CONFIG.get("generator_model") or pilot.CONFIG.get("generator", {}).get("model"))
TRAIT_KO = {"O": "개방성", "C": "성실성", "E": "외향성", "A": "친화성", "N": "신경성"}

# ---- fixed composite definition (user decision, 2026-11-12) -------------------------
W_N, W_U = 0.5, 0.5


def norm(x: int) -> float:
    return (x - 1) / 4


def composite(n: int, u: int) -> float:
    """Representative score: 100 x (0.5 x norm(novelty) + 0.5 x norm(usefulness))."""
    return 100 * (W_N * norm(n) + W_U * norm(u))


def harmonic(n: int, u: int) -> float:
    """Secondary only. 0 whenever novelty == 1 or usefulness == 1."""
    a, b = norm(n), norm(u)
    return 0.0 if a + b == 0 else 100 * 2 * a * b / (a + b)


# ---- palette (dataviz reference palette, validated 2-slot light) --------------------
C_HIGH, C_LOW = "#2a78d6", "#eb6834"
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({
    "font.family": ["Malgun Gothic", "DejaVu Sans"], "axes.unicode_minus": False,
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
})


def R(x: float, nd: int, sign: str = "") -> str:
    """Display-only rounding: strip float noise (9 dp), then round half-up. Computation never uses this."""
    from decimal import Decimal, ROUND_HALF_UP
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    q = Decimal(repr(round(float(x), 9))).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)
    if q == 0:
        q = abs(q)
    return (f"{q:+}" if sign else f"{q}")


def fmt(x, nd=2, sign=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{R(x, nd, "+")}" if sign else f"{R(x, nd)}"


def boot_mean_over_brands(brand_vals: dict[str, float], n_boot=10000, seed=pilot.SEED):
    rng = random.Random(seed)
    v = [brand_vals[b] for b in sorted(brand_vals)]
    bs = sorted(sum(v[rng.randrange(len(v))] for _ in v) / len(v) for _ in range(n_boot))
    return bs[int(0.025 * n_boot)], bs[int(0.975 * n_boot) - 1]


def out_tokens(g: dict) -> int:
    """Generated tokens incl. any hidden reasoning, across providers (Claude CLI / OpenAI / Gemini)."""
    u = g.get("usage") or {}
    if "output_tokens" in u:
        return u["output_tokens"]
    if "completion_tokens" in u:
        return u["completion_tokens"]
    return (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)


def color_of(c: str) -> str:
    return C_HIGH if c.endswith("_H") else C_LOW if c.endswith("_L") else INK if c == "BASE" else MUTED


def marker_of(c: str) -> str:
    return "D" if c == "BASE" else "^" if c in REFS else "o"


def label_of(c: str) -> str:
    return "BASE (기준)" if c == "BASE" else (c + " (대조)" if c in REFS else c)


def same(a: float, b: float) -> bool:
    """Equality on raw values up to float summation-order noise (means of integer scores)."""
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)


def competition_rank(values: list[float]) -> list[int]:
    """1 = highest; exact ties on raw values share a rank (1,2,2,4)."""
    order = sorted(range(len(values)), key=lambda i: -values[i])
    ranks = [0] * len(values)
    for pos, i in enumerate(order):
        if pos > 0 and same(values[i], values[order[pos - 1]]):
            ranks[i] = ranks[order[pos - 1]]
        else:
            ranks[i] = pos + 1
    return ranks


def main() -> None:
    gens = {g["gen_id"]: g for g in pilot.load_jsonl(pilot.DATA / "generations.jsonl") if g.get("ok")}
    judg = [j for j in pilot.load_jsonl(pilot.DATA / "judgments.jsonl") if j.get("ok")]
    p1 = {j["gen_id"]: j["parsed"] for j in judg if j["pass"] == 1}

    ideas = []
    for gid, g in gens.items():
        if gid not in p1:
            continue
        n, u = p1[gid]["novelty"], p1[gid]["usefulness"]
        ideas.append({"gen_id": gid, "brand": g["brand"], "condition": g["condition"], "n": n, "u": u,
                      "comp": composite(n, u), "harm": harmonic(n, u), "floor": n == 1 or u == 1,
                      "tok": out_tokens(g)})
    brands = sorted({i["brand"] for i in ideas})

    cells = defaultdict(list)
    for i in ideas:
        cells[(i["brand"], i["condition"])].append(i)
    cell_sizes = {f"{b}|{c}": len(cells[(b, c)]) for b in brands for c in CONDS}
    balanced = len(set(cell_sizes.values())) == 1

    # ---- aggregation: brand-equal weighting (mean of brand-cell means) is the rule;
    #      idea-pooled mean is computed alongside and must coincide when cells are balanced.
    def cond_stats(c, key):
        bm = {b: st.mean(x[key] for x in cells[(b, c)]) for b in brands if cells[(b, c)]}
        brand_eq = st.mean(bm.values())
        pooled = st.mean(x[key] for b in brands for x in cells[(b, c)])
        return brand_eq, pooled, bm

    tab = {}
    for c in CONDS:
        row = {"condition": c, "n_ideas": sum(len(cells[(b, c)]) for b in brands),
               "n_per_brand": {b: len(cells[(b, c)]) for b in brands}}
        for key in ("n", "u", "comp", "harm", "floor"):
            be, po, bm = cond_stats(c, key)
            row[key] = be
            row[key + "_pooled"] = po
            row[key + "_brand"] = bm
        row["comp_ci"] = boot_mean_over_brands(row["comp_brand"])
        tab[c] = row

    # differences vs BASE: within-brand differences averaged over brands (brand bootstrap CI)
    for c in CONDS:
        r = tab[c]
        for key in ("n", "u", "comp", "harm"):
            if c == "BASE":
                r[key + "_dBASE"] = 0.0
                continue
            pb = {b: (r[key + "_brand"][b], tab["BASE"][key + "_brand"][b]) for b in brands}
            est, lo, hi, npos, nneg = pilot.bootstrap_brand_diff(pb)
            r[key + "_dBASE"], r[key + "_dBASE_ci"], r[key + "_dBASE_dir"] = est, (lo, hi), (npos, nneg)

    # primary reference other than BASE (v2: ALL_AVG) and extra reference contrasts
    if PRIMARY_REF != "BASE":
        for c in CONDS:
            r = tab[c]
            if c == PRIMARY_REF:
                continue
            for key in ("n", "u", "comp"):
                pb = {b: (r[key + "_brand"][b], tab[PRIMARY_REF][key + "_brand"][b]) for b in brands}
                est, lo, hi, npos, nneg = pilot.bootstrap_brand_diff(pb)
                r[key + "_dREF"], r[key + "_dREF_ci"], r[key + "_dREF_dir"] = est, (lo, hi), (npos, nneg)
    extra = {}
    for c1, c2 in EXTRA_CONTRASTS:
        extra[(c1, c2)] = {}
        for key in ("n", "u", "comp"):
            pb = {b: (tab[c1][key + "_brand"][b], tab[c2][key + "_brand"][b]) for b in brands}
            est, lo, hi, npos, nneg = pilot.bootstrap_brand_diff(pb)
            extra[(c1, c2)][key] = {"diff": est, "ci": (lo, hi), "dir": (npos, nneg)}

    ranks = competition_rank([tab[c]["comp"] for c in CONDS])
    for c, rk in zip(CONDS, ranks):
        tab[c]["rank"] = rk
    order = sorted(CONDS, key=lambda c: (-round(tab[c]["comp"], 9), c))

    # High vs Low
    hl = {}
    for t in TRAITS:
        h, l = f"{t}_H", f"{t}_L"
        d = {}
        for key in ("n", "u", "comp"):
            pb = {b: (tab[h][key + "_brand"][b], tab[l][key + "_brand"][b]) for b in brands}
            est, lo, hi, npos, nneg = pilot.bootstrap_brand_diff(pb)
            d[key] = {"H": tab[h][key], "L": tab[l][key], "diff": est, "ci": (lo, hi), "dir": (npos, nneg)}
        hl[t] = d

    # diversity (set level, separate)
    div = json.loads((RES / "diversity_cells.json").read_text(encoding="utf-8"))
    dv = defaultdict(dict)
    for d in div:
        dv[d["condition"]][d["brand"]] = d
    div_tab = {}
    for c in CONDS:
        bge = {b: dv[c][b].get("bge_div", dv[c][b]["tfidf_div"]) for b in brands}
        tf = {b: dv[c][b]["tfidf_div"] for b in brands}
        row = {"bge": st.mean(bge.values()), "tfidf": st.mean(tf.values()), "bge_brand": bge}
        if c != "BASE":
            est, lo, hi, npos, nneg = pilot.bootstrap_brand_diff({b: (bge[b], dv["BASE"][b].get("bge_div", dv["BASE"][b]["tfidf_div"])) for b in brands})
            row.update(d=est, ci=(lo, hi), dir=(npos, nneg))
        div_tab[c] = row

    # distributions
    dist = {k: {s: sum(1 for i in ideas if i[k] == s) for s in range(1, 6)} for k in ("n", "u")}
    dist_c = {c: {k: {s: sum(1 for i in ideas if i["condition"] == c and i[k] == s) for s in range(1, 6)}
                  for k in ("n", "u")} for c in CONDS}
    N = len(ideas)
    conc ={k: max((((a, a + 1), (dist[k][a] + dist[k][a + 1]) / N) for a in range(1, 5)), key=lambda z: z[1]) for k in ("n", "u")}
    n_unique_comp = sorted({round(i["comp"], 6) for i in ideas})

    # tokens
    tok = {c: {"median": st.median(i["tok"] for i in ideas if i["condition"] == c),
               "long_share": st.mean(1.0 if i["tok"] > 250 else 0.0 for i in ideas if i["condition"] == c)} for c in CONDS}

    manip = pilot.manip_summary()

    # ---- verification against earlier outputs ---------------------------------------
    ver = {"composite_formula": "100*(0.5*(N-1)/4 + 0.5*(U-1)/4)",
           "n_ideas": N, "cells_balanced": balanced, "cell_size_set": sorted(set(cell_sizes.values()))}
    ver["brand_equal_vs_pooled_max_abs_diff"] = {
        k: max(abs(tab[c][k] - tab[c][k + "_pooled"]) for c in CONDS) for k in ("n", "u", "comp", "harm")}
    if IS_V1:
        verify_against_v1_outputs(ver, ideas, tab, div_tab)
    # display-rounding check: does rounding to 1 decimal ever make the displayed order disagree with the raw order?
    disp = [(R(tab[c]["comp"], 1), c) for c in order]
    ver["display_ties_after_rounding_1dp"] = [
        [a[1], b[1]] for a, b in zip(disp, disp[1:]) if a[0] == b[0] and not same(tab[a[1]]["comp"], tab[b[1]]["comp"])]
    ver["exact_raw_ties"] = [[a, b] for a, b in zip(order, order[1:]) if same(tab[a]["comp"], tab[b]["comp"])]
    ver["dBASE_shown_vs_difference_of_shown_means_mismatch"] = [
        c for c in CONDS if c != "BASE" and R(tab[c]["comp_dBASE"], 1, "+") != R(float(R(tab[c]["comp"], 1)) - float(R(tab["BASE"]["comp"], 1)), 1, "+")]
    (RES / f"verification_{VERSION}.json").write_text(json.dumps(ver, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---- CSV exports (raw precision) ---------------------------------------------------
    with open(RES / "condition_table.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["rank", "condition", "is_base", "n_ideas", "novelty_mean", "usefulness_mean", "composite_mean",
                    "composite_ci95_lo", "composite_ci95_hi", "composite_minus_BASE", "dBASE_ci95_lo", "dBASE_ci95_hi",
                    "brands_up", "brands_down", "harmonic_mean_secondary", "floor_share", "bge_diversity_setlevel",
                    "median_output_tokens", "long_output_share"])
        for c in order:
            r = tab[c]
            ci = r.get("comp_dBASE_ci", (0.0, 0.0))
            dr = r.get("comp_dBASE_dir", (0, 0))
            w.writerow([r["rank"], c, c == "BASE", r["n_ideas"], r["n"], r["u"], r["comp"], *r["comp_ci"], r["comp_dBASE"],
                        *ci, *dr, r["harm"], r["floor"], div_tab[c]["bge"], tok[c]["median"], tok[c]["long_share"]])
    with open(RES / "high_low_table.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["trait", "metric", "high", "low", "high_minus_low", "ci95_lo", "ci95_hi", "brands_high_gt_low", "brands_low_gt_high"])
        for t, d in hl.items():
            for key, lab in (("n", "novelty"), ("u", "usefulness"), ("comp", "composite")):
                x = d[key]
                w.writerow([t, lab, x["H"], x["L"], x["diff"], *x["ci"], *x["dir"]])

    figs = make_figures(tab, order, hl, div_tab, dist, tok, brands)
    write_report(tab, order, hl, div_tab, dist, dist_c, conc, tok, manip, ver, brands, figs, N, n_unique_comp, extra)
    print(json.dumps(ver, indent=1, ensure_ascii=False))


def verify_against_v1_outputs(ver, ideas, tab, div_tab):
    """v1 only: compare the recomputation with the earlier summary.json / idea_level_scores.csv."""
    old = json.loads((RES / "summary.json").read_text(encoding="utf-8"))
    old_ideas = {r["gen_id"]: r for r in csv.DictReader(open(RES / "idea_level_scores.csv", encoding="utf-8-sig"))}
    ver["idea_level_max_abs_diff_comp_vs_old_csv"] = max(abs(i["comp"] - float(old_ideas[i["gen_id"]]["comp_mean"])) for i in ideas)
    ver["idea_level_max_abs_diff_harm_vs_old_csv"] = max(abs(i["harm"] - float(old_ideas[i["gen_id"]]["comp_harm"])) for i in ideas)
    ver["idea_level_novelty_usefulness_mismatch"] = sum(
        int(old_ideas[i["gen_id"]]["novelty"]) != i["n"] or int(old_ideas[i["gen_id"]]["usefulness"]) != i["u"] for i in ideas)
    mk = {"n": "novelty", "u": "usefulness", "comp": "comp_mean", "harm": "comp_harm", "floor": "floor"}
    ver["condition_mean_max_abs_diff_vs_old_summary"] = {
        k: max(abs(tab[c][k] - old["by_condition"][c][v]) for c in CONDS) for k, v in mk.items()}
    ver["dBASE_max_abs_diff_vs_old_summary"] = {
        k: max(abs(tab[c][k + "_dBASE"] - old["vs_base"][c][v]["diff"]) for c in CONDS[1:]) for k, v in mk.items() if k != "floor"}
    ver["dBASE_ci_max_abs_diff_vs_old_summary"] = {
        k: max(max(abs(a - b) for a, b in zip(tab[c][k + "_dBASE_ci"], old["vs_base"][c][v]["ci95"])) for c in CONDS[1:])
        for k, v in mk.items() if k != "floor"}
    ver["diversity_max_abs_diff_vs_old_summary"] = max(abs(div_tab[c]["bge"] - old["by_condition"][c]["diversity"]) for c in CONDS)
    ver["display_changed_vs_old_report_1dp"] = [
        f"{c} {lab}: 이전 {old_v:.1f} → 현재 {R(new_v, 1)} (원값 {new_v:.4f})"
        for c in CONDS for lab, new_v, old_v in (("종합", tab[c]["comp"], old["by_condition"][c]["comp_mean"]),
                                                  ("조화", tab[c]["harm"], old["by_condition"][c]["comp_harm"]))
        if f"{old_v:.1f}" != R(new_v, 1)]


# ------------------------------------------------------------------------------------------
def make_figures(tab, order, hl, div_tab, dist, tok, brands):
    out = {}
    base = tab["BASE"]["comp"]

    # F1: composite by condition (sorted), brand-bootstrap CI, BASE highlighted
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ys = list(range(len(order)))[::-1]
    for y, c in zip(ys, order):
        r = tab[c]
        is_base = c == "BASE"
        col = color_of(c)
        ax.plot(r["comp_ci"], [y, y], color=col, lw=2, solid_capstyle="round", alpha=0.55)
        ax.plot(r["comp"], y, ls="", ms=9 if is_base else 8, color=col, mec=SURF, mew=2,
                marker=marker_of(c), zorder=3)
        ax.text(r["comp_ci"][1] + 0.6, y, f"{R(r['comp'], 1)}", va="center", fontsize=9, color=INK2)
    ax.axvline(base, color=MUTED, lw=1, ls=(0, (4, 3)), zorder=1)
    ax.set_yticks(ys, [label_of(c) for c in order])
    for lab in ax.get_yticklabels():
        if "BASE" in lab.get_text():
            lab.set_fontweight("bold")
            lab.set_color(INK)
    ax.set_xlabel("대표 종합점수 (0–100, 산술평균)  ·  막대 = 브랜드 부트스트랩 95% 구간")
    ax.set_title(f"조건별 대표 종합점수 (탐색적 파일럿, 조건당 {tab['BASE']['n_ideas']}개, LLM 평가자 1개)", loc="left", fontsize=11, color=INK)
    ax.grid(axis="y", visible=False)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker="o", ls="", color=C_HIGH, label="High 조건"),
                       Line2D([], [], marker="o", ls="", color=C_LOW, label="Low 조건"),
                       Line2D([], [], marker="D", ls="", color=INK, label="BASE (점선 = BASE 값)")]
              + ([Line2D([], [], marker="^", ls="", color=MUTED, label="대조 조건")] if len(REFS) > 1 else []),
              loc="lower right", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "f1_composite_by_condition.png", dpi=160)
    plt.close(fig)
    out["f1"] = "figures/f1_composite_by_condition.png"

    # F2: High vs Low dumbbells, three panels
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6), sharey=True)
    traits = list(TRAITS)
    def lims(key, pad, step):
        vals = [hl[t][key][k] for t in traits for k in ("H", "L")] + [tab["BASE"][key]]
        return (math.floor((min(vals) - pad) / step) * step, math.ceil((max(vals) + pad) / step) * step)
    for ax, (key, title, xl) in zip(axes, (("n", "새로움 (1–5)", lims("n", 0.1, 0.1)), ("u", "유용성 (1–5)", lims("u", 0.1, 0.1)),
                                             ("comp", "대표 종합점수 (0–100)", lims("comp", 2, 5)))):
        bval = tab["BASE"][key]
        ax.axvline(bval, color=MUTED, lw=1, ls=(0, (4, 3)))
        for y, t in enumerate(traits[::-1]):
            d = hl[t][key]
            ax.plot([d["L"], d["H"]], [y, y], color=GRID, lw=3, solid_capstyle="round", zorder=1)
            ax.plot(d["H"], y, "o", ms=8, color=C_HIGH, mec=SURF, mew=2, zorder=3)
            ax.plot(d["L"], y, "s", ms=7.5, color=C_LOW, mec=SURF, mew=2, zorder=3)
            nd = 1 if key == "comp" else 2
            ax.text(xl[1] + (xl[1] - xl[0]) * 0.04, y, R(d['diff'], nd, "+"), va="center", ha="left", fontsize=9, color=INK2)
        ax.text(xl[1] + (xl[1] - xl[0]) * 0.04, len(traits) - 0.45, "H−L", va="center", ha="left", fontsize=8.5, color=MUTED)
        ax.set_xlim(xl[0], xl[1] + (xl[1] - xl[0]) * 0.22)
        ax.set_ylim(-0.6, len(traits) - 0.2)
        ax.set_title(title, loc="left", fontsize=10, color=INK)
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(range(len(traits)), [f"{TRAIT_KO[t]} ({t})" for t in traits[::-1]])
    from matplotlib.lines import Line2D
    fig.legend(handles=[Line2D([], [], marker="o", ls="", color=C_HIGH, label="High"),
                        Line2D([], [], marker="s", ls="", color=C_LOW, label="Low"),
                        Line2D([], [], ls=(0, (4, 3)), color=MUTED, label="BASE")],
               loc="upper right", ncol=3, frameon=False, fontsize=9)
    fig.suptitle(f"특성별 High vs Low (조건당 {tab['BASE']['n_ideas']}개 평균, 탐색적)", x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(FIG / "f2_high_vs_low.png", dpi=160)
    plt.close(fig)
    out["f2"] = "figures/f2_high_vs_low.png"

    # F3: score distributions (single series per panel)
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.2), sharey=True)
    tot = sum(dist["n"].values())
    for ax, (k, title) in zip(axes, (("n", "새로움 점수 분포"), ("u", "유용성 점수 분포"))):
        xs = [1, 2, 3, 4, 5]
        vs = [dist[k][s] for s in xs]
        ax.bar(xs, vs, width=0.72, color=C_HIGH, edgecolor=SURF, linewidth=2)
        for x, v in zip(xs, vs):
            ax.text(x, v + tot * 0.01, f"{v}\n({v / tot:.0%})", ha="center", va="bottom", fontsize=8.5, color=INK2)
        ax.set_xticks(xs)
        ax.set_title(title + f" (n={tot})", loc="left", fontsize=10, color=INK)
        ax.set_ylim(0, max(max(dist['n'].values()), max(dist['u'].values())) * 1.25)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("아이디어 수")
    fig.tight_layout()
    fig.savefig(FIG / "f3_score_distributions.png", dpi=160)
    plt.close(fig)
    out["f3"] = "figures/f3_score_distributions.png"

    # F4: set-level diversity (separate from composite), brand points + condition mean
    dorder = sorted(CONDS, key=lambda c: (-div_tab[c]["bge"], c))
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ys = list(range(len(dorder)))[::-1]
    for y, c in zip(ys, dorder):
        col = color_of(c)
        bv = list(div_tab[c]["bge_brand"].values())
        ax.plot(bv, [y] * len(bv), "o", ms=4, color=MUTED, alpha=0.7, zorder=2)
        ax.plot(div_tab[c]["bge"], y, marker_of(c), ms=8.5, color=col, mec=SURF, mew=2, zorder=3)
    ax.axvline(div_tab["BASE"]["bge"], color=MUTED, lw=1, ls=(0, (4, 3)))
    ax.set_yticks(ys, [label_of(c) for c in dorder])
    ax.set_xlabel("평균 쌍별 코사인 거리 (bge-large-en-v1.5, 브랜드×조건 6개 집합)  ·  회색 점 = 브랜드별")
    ax.set_title("집합 수준 다양성 (종합점수와 별도 지표)", loc="left", fontsize=11, color=INK)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(FIG / "f4_diversity.png", dpi=160)
    plt.close(fig)
    out["f4"] = "figures/f4_diversity.png"

    # F5: long-output share vs composite and vs diversity (two panels, no dual axis)
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
    for ax, (ykey, ylab) in zip(axes, (("comp", "대표 종합점수"), ("div", "다양성 (bge)"))):
        for c in CONDS:
            x = tok[c]["long_share"]
            y = tab[c]["comp"] if ykey == "comp" else div_tab[c]["bge"]
            col = color_of(c)
            ax.plot(x, y, marker_of(c), ms=8, color=col, mec=SURF, mew=2)
            off = {("comp", "O_L"): (6, -12), ("div", "O_H"): (6, 5), ("div", "O_L"): (6, -12),
                   ("div", "N_L"): (-6, 6)}.get((ykey, c), (5, 3))
            ax.annotate(c, (x, y), xytext=off, textcoords="offset points", fontsize=8, color=INK2,
                        ha="right" if off[0] < 0 else "left")
        ax.set_xlabel("긴 출력(>250 토큰) 비율 — 내부 사고 사용 추정")
        ax.set_ylabel(ylab)
        ax.set_xlim(-0.08, 1.15)
    fig.suptitle("교란 점검: 조건별 생성 토큰 길이와 결과 (탐색적, 사전등록 아님)", x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(FIG / "f5_token_confound.png", dpi=160)
    plt.close(fig)
    out["f5"] = "figures/f5_token_confound.png"
    return out


# ------------------------------------------------------------------------------------------
def write_report(tab, order, hl, div_tab, dist, dist_c, conc, tok, manip, ver, brands, figs, N, n_unique_comp, extra):
    L = []
    a = L.append
    nb, nper = len(brands), tab["BASE"]["n_ideas"]
    reps = max(ver["cell_size_set"])
    a("# 파일럿 v1 결과 보고서 (v1.1, 표시·집계 개선판)\n" if IS_V1 else f"# 파일럿 {VERSION} 결과 보고서\n")
    a(f"> **탐색적 파일럿 결과다. 확인된 성격별 성능 순위가 아니다.** 브랜드 {nb}개(" + ", ".join(brands) +
      f"), 조건별 아이디어 {nper}개(브랜드당 {reps}개), 생성 모델 {GEN_NAME}, 평가자는 LLM 1개({JUDGE_NAME})다. 사람 평가와의 일치 여부는 아직 검증되지 않았다.\n")
    if IS_V1:
        a("> 이 보고서는 저장된 생성·평가·조작 확인 기록에서 다시 계산했다. 새로 생성하거나 평가하지 않았다. 이전 보고서 `report.md`와 `summary.json`은 수정하지 않았다.\n")

    a("## 1. 대표 종합점수의 정의와 집계\n")
    a("- 아이디어별로 `종합 = 100 × (0.5 × (새로움−1)/4 + 0.5 × (유용성−1)/4)`를 구한다. 새로움과 유용성은 각각 1–5점이고, 두 축의 비중은 같다.")
    a(f"- 점수가 정수라 종합점수가 가질 수 있는 값은 {len(n_unique_comp)}가지뿐이다(12.5점 간격; 관찰된 값: {', '.join(f'{v:g}' for v in n_unique_comp)}).")
    a("- **집계 규칙:** 조건 점수는 브랜드별 평균을 먼저 구한 뒤, 그 브랜드 평균들을 같은 비중으로 평균한다. 브랜드마다 사례 수가 달라도 특정 브랜드의 비중이 커지지 않게 하기 위해서다. 이번 자료는 모든 브랜드×조건 셀이 "
      f"{ver['cell_size_set']}개로 같아서, 아이디어 전체를 그냥 평균한 값과 정확히 일치한다(최대 차이 {max(ver['brand_equal_vs_pooled_max_abs_diff'].values()):.1e}).")
    a(f"- **BASE 대비 차이:** 각 브랜드 안에서 (조건 평균 − BASE 평균)을 구하고 브랜드에 걸쳐 평균한다. 95% 구간은 브랜드 단위 부트스트랩(10,000회, 시드 고정)이다. 괄호 (↑/↓)는 BASE보다 높았던/낮았던 브랜드 수다({nb}개 중; 나머지는 동률)." + (f" 성격 조건의 1차 비교 기준은 {PRIMARY_REF}이며(나머지 특성이 모두 Average로 같고 표적 특성만 다름), BASE 대비 차이는 함께 보고한다." if PRIMARY_REF != "BASE" else ""))
    a("- 순위와 차이는 원자료로 계산하고, 표에 보일 때만 반올림한다. 원자료 값이 정확히 같으면 같은 순위를 준다.\n")

    a("## 2. 조건 비교표 (대표 종합점수 순)\n")
    has_ref = PRIMARY_REF != "BASE"
    a("| 순위 | 조건 | 새로움 평균 | 유용성 평균 | **대표 종합점수** [95% 구간] | BASE 대비 차이 [95% 구간] (↑/↓) |"
      + (f" {PRIMARY_REF} 대비 차이 [95% 구간] (↑/↓) |" if has_ref else "") + " n |")
    a("|---|---|---|---|---|---|" + ("---|" if has_ref else "") + "---|")
    for c in order:
        r = tab[c]
        name = "**▶ BASE (성격 미지정)**" if c == "BASE" else (f"*{c} (대조)*" if c in REFS else c)
        dd = "기준" if c == "BASE" else f"{R(r['comp_dBASE'], 1, "+")} [{R(r['comp_dBASE_ci'][0], 1, "+")}, {R(r['comp_dBASE_ci'][1], 1, "+")}] ({r['comp_dBASE_dir'][0]}/{r['comp_dBASE_dir'][1]})"
        rd = ""
        if has_ref:
            rd = " 기준 |" if c == PRIMARY_REF else f" {R(r['comp_dREF'], 1, '+')} [{R(r['comp_dREF_ci'][0], 1, '+')}, {R(r['comp_dREF_ci'][1], 1, '+')}] ({r['comp_dREF_dir'][0]}/{r['comp_dREF_dir'][1]}) |"
        a(f"| {r['rank']} | {name} | {R(r['n'], 2)} | {R(r['u'], 2)} | **{R(r['comp'], 1)}** [{R(r['comp_ci'][0], 1)}, {R(r['comp_ci'][1], 1)}] | {dd} |{rd} {r['n_ideas']} |")
    if ver["exact_raw_ties"]:
        a("\n동률(원자료 기준 같은 값, 부동소수점 오차 1e-9 이내): " + "; ".join(" = ".join(p) for p in ver["exact_raw_ties"]) + ". 공동 순위를 주었고, 표의 위아래 순서는 조건 이름순이다.")
    a(f"\n![조건별 대표 종합점수]({figs['f1']})\n")
    a(f"- 브랜드 {nb}개로 만든 부트스트랩 구간이라 거칠다. 같은 자료에서 여러 대비를 동시에 봤으므로 일부 구간이 0을 벗어나는 것은 우연으로도 기대된다.\n")
    if extra:
        a("### 대조 조건끼리의 비교\n")
        a("| 대비 | 새로움 | 유용성 | 대표 종합점수 | 해석 목적 |")
        a("|---|---|---|---|---|")
        purpose = {("ALL_AVG", "BASE"): "모든 특성 Average 명시 vs 성격 미지정",
                   ("CTRL", "BASE"): "성격과 무관한 프로필 문장 추가의 효과",
                   ("ALL_AVG", "CTRL"): "성격 내용 자체의 효과(같은 형식)"}
        for (c1, c2), d in extra.items():
            cells = []
            for key, nd in (("n", 2), ("u", 2), ("comp", 1)):
                x = d[key]
                cells.append(f"{R(x['diff'], nd, '+')} [{R(x['ci'][0], nd, '+')}, {R(x['ci'][1], nd, '+')}] ({x['dir'][0]}/{x['dir'][1]})")
            a(f"| {c1} − {c2} | " + " | ".join(cells) + f" | {purpose.get((c1, c2), '')} |")
        a("")

    a("## 3. 특성별 High vs Low\n")
    a("| 특성 | 지표 | High | Low | High − Low [95% 구간] (H>L / L>H 브랜드 수) |")
    a("|---|---|---|---|---|")
    for t, d in hl.items():
        for key, lab, nd in (("n", "새로움", 2), ("u", "유용성", 2), ("comp", "종합", 1)):
            x = d[key]
            a(f"| {TRAIT_KO[t]} ({t}) | {lab} | {R(x['H'], nd)} | {R(x['L'], nd)} | {R(x['diff'], nd, "+")} [{R(x['ci'][0], nd, "+")}, {R(x['ci'][1], nd, "+")}] ({x['dir'][0]}/{x['dir'][1]}) |")
    a(f"\n![High vs Low]({figs['f2']})\n")
    if IS_V1:
        a("- 개방성에서는 High가 새로움에서 앞서고 Low가 유용성에서 앞서서, 종합점수 차이는 거의 0이다. 종합점수만 보면 이런 맞교환이 가려지므로 두 축을 함께 봐야 한다.\n")
    else:
        a("- 종합점수 차이가 작아도 새로움과 유용성이 반대 방향으로 움직였을 수 있으므로 세 행을 함께 본다.\n")

    a("## 4. 다양성 (집합 수준, 종합점수와 별도)\n")
    a(f"다양성은 아이디어 하나가 아니라 같은 브랜드×조건의 아이디어 {reps}개 집합에 대한 값이다. 따라서 종합점수에 합치지 않는다. 지표는 원 논문과 같은 BAAI/bge-large-en-v1.5 임베딩의 평균 쌍별 코사인 거리이고, TF-IDF 거리는 어휘 수준 보조 지표다.\n")
    a("| 조건 | 다양성 (bge) | BASE 대비 [95% 구간] (↑/↓) | TF-IDF 다양성 |")
    a("|---|---|---|---|")
    for c in sorted(CONDS, key=lambda c: (-div_tab[c]["bge"], c)):
        r = div_tab[c]
        dd = "기준" if c == "BASE" else f"{R(r['d'], 3, "+")} [{R(r['ci'][0], 3, "+")}, {R(r['ci'][1], 3, "+")}] ({r['dir'][0]}/{r['dir'][1]})"
        a(f"| {'**▶ BASE**' if c == 'BASE' else c} | {R(r['bge'], 3)} | {dd} | {R(r['tfidf'], 3)} |")
    a(f"\n![다양성]({figs['f4']})\n")
    if IS_V1:
        a("- BASE는 같은 아이디어를 반복하는 경향이 있었다(예: IKEA 6개 모두 이별 쇼룸 계열). 서로 반대 방향인 O_H와 O_L이 비슷하게 높아서, 다양성 상승은 특정 특성 방향보다는 '성격 문장 추가' 또는 추론 길이 차이(7절)와 더 잘 맞는다.\n")

    a("## 5. 보조 지표: 조화평균 종합점수와 바닥 비율\n")
    a("- 조화평균 = `100 × 2NU/(N+U)`(N, U는 0–1 정규화 점수, N+U=0이면 0). **새로움이나 유용성 중 하나라도 1점이면 정규화 값이 0이 되어, 다른 항목이 5점이어도 조화평균은 0점이다.** 두 항목이 모두 좋아야 높게 나오는 엄격한 지표라 보조로만 쓴다.")
    n1, u1 = dist["n"][1], dist["u"][1]
    a(f"- 이번 자료에서 1점은 새로움 {n1}건, 유용성 {u1}건이다(어느 축이든 1점인 아이디어는 전체의 {R(100 * sum(r['floor'] * r['n_ideas'] for r in tab.values()) / N, 1)}%). "
      "바닥 비율이 낮으면 '0점 처리'가 조건 비교를 크게 바꾸지 않는다. 다만 조화평균은 두 축 중 낮은 쪽의 차이를 더 크게 반영한다.\n")
    a("| 조건 | 대표 종합(산술) | 조화평균(보조) | BASE 대비(조화) | 바닥 비율 (어느 축이든 1점) |")
    a("|---|---|---|---|---|")
    for c in order:
        r = tab[c]
        hd = "기준" if c == "BASE" else f"{R(r['harm_dBASE'], 1, "+")}"
        a(f"| {'**▶ BASE**' if c == 'BASE' else c} | {R(r['comp'], 1)} | {R(r['harm'], 1)} | {hd} | {R(r['floor'], 3)} |")

    a("\n## 6. 새로움·유용성 점수 분포\n")
    a(f"![점수 분포]({figs['f3']})\n")
    a("| 점수 | 1 | 2 | 3 | 4 | 5 |")
    a("|---|---|---|---|---|---|")
    for k, lab in (("n", "새로움"), ("u", "유용성")):
        a(f"| {lab} | " + " | ".join(f"{dist[k][s]} ({dist[k][s] / N:.1%})" for s in range(1, 6)) + " |")
    (na, nb), ns = conc["n"]
    (ua, ub), us = conc["u"]
    a(f"\n- **쏠림 확인:** 새로움은 {na}–{nb}점에 {ns:.1%}, 유용성은 {ua}–{ub}점에 {us:.1%}가 몰려 있다. " + ("특히 새로움은 천장(4–5점)에 몰려 조건 간 구분력이 낮다. Wild Ideas 과제가 원래 '기이한 아이디어'를 요구하므로, 현재 채점표로는 모든 응답이 '새롭다'로 판정되기 쉽다." if IS_V1 else "한쪽 끝 두 단계에 80% 이상이 몰리면 그 축의 조건 간 구분력이 낮다고 본다."))
    a("- 조건별 분포(새로움 1–5 / 유용성 1–5 건수):\n")
    a("| 조건 | 새로움 1/2/3/4/5 | 유용성 1/2/3/4/5 |")
    a("|---|---|---|")
    for c in CONDS:
        a(f"| {c} | {'/'.join(str(dist_c[c]['n'][s]) for s in range(1, 6))} | {'/'.join(str(dist_c[c]['u'][s]) for s in range(1, 6))} |")

    a("\n## 7. 교란 점검: 조건별 생성 토큰\n")
    a("| 조건 | 출력 토큰 중앙값 | 긴 출력(>250 토큰) 비율 |")
    a("|---|---|---|")
    for c in CONDS:
        a(f"| {c} | {R(tok[c]['median'], 0)} | {R(tok[c]['long_share'], 2)} |")
    a(f"\n![토큰 교란]({figs['f5']})\n")
    if IS_V1:
        a("- 이 분석은 사전등록하지 않은 탐색 분석이다. 출력 토큰은 약 100개와 400–1,100개 두 무리로 나뉜다(내부 사고 사용 여부로 추정). 그 비율이 성격 문장에 따라 0%에서 100%까지 달라졌고, 긴 출력 비율이 높은 조건이 다양성과 유용성도 높은 경향이 있다.\n")
    else:
        a(f"- 생성 설정: {json.dumps({k: v for k, v in pilot.CONFIG['generator'].items() if not k.startswith('_')}, ensure_ascii=False)}. 추론(사고) 사용은 API 설정으로 고정했다. 그래도 조건마다 출력 길이가 다르면 위 표에 드러난다.\n")

    if manip:
        a(f"## 8. 성격 조작 확인 (IPIP-50 자기보고, 조건당 {pilot.CONFIG['manip_reps']}회)\n")
        mref = manip.get("_reference", "BASE")
        a(f"| 조건 | O | C | E | A | N | 표적 변화 vs {mref} | 표적 외 평균 절대 변화 |")
        a("|---|---|---|---|---|---|---|---|")
        for c in CONDS:
            if c in manip:
                d = manip[c]
                a(f"| {c} | " + " | ".join(f"{R(d[t], 2)}" for t in "OCEAN") +
                  f" | {fmt(d.get('target_change_vs_base'), 2, True)} | {fmt(d.get('mean_abs_offtarget_change_vs_base'))} |")
        if IS_V1:
            a("\n- Low 지시와 N_H는 표적 특성을 크게 움직였다. High 지시(O, C, A)와 N_L은 BASE가 이미 천장이나 바닥 근처라 변화가 작았다.\n")
        else:
            a("")

    a("## 9. 해석과 한계\n")
    a(f"1. **탐색적 파일럿이다.** 브랜드 {nb}개, 조건별 {nper}개 아이디어(브랜드당 {reps}개), 평가자는 LLM 1개다. 순위는 이 모델·프롬프트·평가자에서 관찰된 값일 뿐, 확인된 성격별 성능 순위가 아니다. 10개 성격 조건 × 여러 지표를 비교했으므로 p값을 보고하지 않는다.")
    a("2. **사람 평가와의 일치가 검증되지 않았다.** 원 논문은 LLM 평가자와 인간 순위의 일치가 약하다고 보고했다. 원 논문의 인간 쌍대 선호 레이블은 공개되지 않아 쓰지 못했다(써도 새 결과물의 정답 점수가 되지 않는다). 조건을 가린 사람 평가 자료가 `human_eval/`에 있다.")
    if IS_V1:
        a("3. **생성 토큰 차이 때문에 성격 지시의 효과와 추론 과정의 효과를 구분하기 어렵다.** 7절 참조. 이번 CLI 환경에서는 사고 사용과 온도를 통제할 수 없었다.")
    else:
        a("3. **추론 예산은 API 설정으로 고정했다.** 그래도 출력 길이 차이는 남을 수 있으니 7절을 확인한다. 생성 모델이 v1과 다르므로 v1과 v2 결과를 직접 비교하지 않는다.")
    a("4. **성격 조작 확인은 자기보고 설문이다.** 아이디어 문장 자체에 성격이 드러났는지는 따로 측정하지 않았다.")
    a("5. 새로움 점수가 천장에 몰려 있어(6절) 조건 간 새로움 차이는 과소 추정되었을 수 있다.")
    if IS_V1:
        a("6. 대표 종합점수 공식(산술 50:50)은 사전등록에서 '파일럿의 주 종합점수'로 정했던 것과 같다. 본 실험의 최종 공식으로는 사용자가 파일럿 결과를 본 뒤 2026-11-12에 확정했다. 따라서 이번 파일럿에 대해서는 사후 선택이 아니며, 본 실험(v2)에는 사전 확정 공식으로 적용된다.\n")
    else:
        a("6. 대표 종합점수 공식(산술 50:50)과 집계 규칙은 실행 전에 확정했다(2026-11-12).\n")
    if not IS_V1:
        (RES / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        return

    a("## 10. 계산 검증 (이전 결과와 대조)\n")
    a("`verification_v1.1.json` 요약:\n")
    a(f"- 아이디어별 종합점수: 이전 `idea_level_scores.csv`의 comp_mean과 최대 차이 {ver['idea_level_max_abs_diff_comp_vs_old_csv']:.1e}. 원점수 불일치 {ver['idea_level_novelty_usefulness_mismatch']}건.")
    a(f"- 조건 평균: 이전 summary.json과 최대 차이 {json.dumps({k: float(f'{v:.1e}') for k, v in ver['condition_mean_max_abs_diff_vs_old_summary'].items()})}.")
    a(f"- BASE 대비 차이: 최대 차이 {json.dumps({k: float(f'{v:.1e}') for k, v in ver['dBASE_max_abs_diff_vs_old_summary'].items()})}. 95% 구간 끝점 최대 차이 {json.dumps({k: float(f'{v:.1e}') for k, v in ver['dBASE_ci_max_abs_diff_vs_old_summary'].items()})}.")
    a(f"- 다양성(bge) 조건 평균: 최대 차이 {ver['diversity_max_abs_diff_vs_old_summary']:.1e}.")
    a(f"- 반올림 때문에 같아 보이지만 원자료로는 다른 순위: {ver['display_ties_after_rounding_1dp'] or '없음'}. 원자료 완전 동률: {ver['exact_raw_ties'] or '없음'}.")
    a(f"- 표의 'BASE 대비 차이'(원자료 차이를 반올림)와 '반올림된 평균끼리의 차이'가 다르게 보이는 조건: {ver['dBASE_shown_vs_difference_of_shown_means_mismatch'] or '없음'}. "
      "계산 오류가 아니라 표시 방식 때문이다. 예를 들어 E_H는 표에 63.3, BASE는 61.7로 보여 둘을 빼면 +1.6이지만, 원자료 차이는 63.333 − 61.667 = +1.667이라서 +1.7로 표시된다. 차이와 순위는 항상 원자료로 계산한다.")
    a("- 표시 반올림: 부동소수점 오차를 없애려고 소수 9자리에서 정리한 뒤 사사오입한다. 이전 보고서(`report.md`)는 파이썬 기본 반올림을 써서, 정확히 +1.25인 차이가 조건에 따라 +1.3(A_L)과 +1.2(E_L, N_L)로 다르게 표시됐다. 원자료 값은 셋 다 +1.25로 같다.")
    a("- 위 규칙 때문에 이전 보고서와 표시값이 0.1 달라진 항목(값 자체는 동일): " + ("; ".join(ver["display_changed_vs_old_report_1dp"]) or "없음") + ".")
    (RES / "report_v1.1.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
