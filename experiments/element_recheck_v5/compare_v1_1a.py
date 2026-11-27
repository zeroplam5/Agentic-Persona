"""v1.1a: per-item comparison of researcher A (and optional B) with the LLM coder, 6 items.

Reads the preserved filled copies in human_coding_v1_1/filled_2026-11-27/ (read-only).
No inference: a blank stays blank; "있음" with no element rows is reported as 미기재.
Outputs (no condition names) go to results_v1_1a/.
"""
import csv, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
FILLED = os.path.join(ROOT, "human_coding_v1_1", "filled_2026-11-27")
OUT = os.path.join(HERE, "results_v1_1a")
SAMPLE = os.path.join(HERE, "_analyst_only_DO_NOT_SHOW_CODERS", "main_sample_6.csv")
CODES = os.path.join(ROOT, "experiments", "selection_focus_v5", "data", "codes.jsonl")
sys.path.insert(0, HERE)
import importlib.util
spec = importlib.util.spec_from_file_location("dumpmod", os.path.join(HERE, "dump_filled_v1_1a.py"))
dumpmod = importlib.util.module_from_spec(spec); spec.loader.exec_module(dumpmod)

import zipfile, xml.etree.ElementTree as ET, re
NS = dumpmod.NS


def read_sheets(path):
    """{sheet_name: {row: {col: value}}} using the same reader as dump_filled_v1_1a.py."""
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = [dumpmod.text_of(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rmap = {r.get("Id"): r.get("Target") for r in rels.iter(dumpmod.RELNS + "Relationship")}
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
        tgt = rmap[sh.get("{%s}id" % NS["r"])].lstrip("/")
        tgt = tgt if tgt.startswith("xl/") else "xl/" + tgt
        grid = {}
        for c in ET.fromstring(z.read(tgt)).iter("{%s}c" % NS["m"]):
            t = c.get("t"); v = c.find("m:v", NS)
            if t == "s" and v is not None: val = ss[int(v.text)]
            elif t == "inlineStr": val = dumpmod.text_of(c)
            elif v is not None: val = v.text
            else: continue
            m = re.match(r"([A-Z]+)(\d+)", c.get("r"))
            grid.setdefault(int(m.group(2)), {})[dumpmod.col2n(m.group(1))] = val
        out[sh.get("name")] = grid
    return out


def table(grid):
    head = grid[1]
    rows = []
    for r in sorted(k for k in grid if k > 1):
        rows.append({head[c]: grid[r].get(c, "") for c in head})
    return rows


def coder(path):
    sh = read_sheets(path)
    s1 = next(g for n, g in sh.items() if 1 in g and "Q1 핵심 코드" in g[1].values())
    s2 = next((g for n, g in sh.items() if 1 in g and "출처 후보" in g[1].values()), None)
    final = {r["item"]: r for r in table(s1) if r.get("item")}
    elems = []
    if s2 is not None:
        for r in table(s2):
            if r.get("item") and (r.get("요소 이름") or r.get("출처 후보") or r.get("최종안 근거 문장")):
                elems.append(r)
    return final, elems, s2 is not None


def strip(code):
    return code.split("-", 1)[1] if code and "-" in code else code


def main():
    os.makedirs(OUT, exist_ok=True)
    sample = list(csv.DictReader(open(SAMPLE, encoding="utf-8-sig")))
    iid = {r["item"]: r["item_id"] for r in sample}
    llm = {}
    for line in open(CODES, encoding="utf-8"):
        r = json.loads(line)
        if r["item_id"] in iid.values():
            llm[r["item_id"]] = r["parsed"]
    A, A_el, A_has2 = coder(os.path.join(FILLED, "main_researcherA_6_filled.xlsx"))
    B, B_el, B_has2 = coder(os.path.join(FILLED, "main_researcherB_6_filled.xlsx"))
    order = list(A.keys())

    # ---- items: Q1, Q2, other-candidate yes/no
    with open(os.path.join(OUT, "items_Q1_Q2.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "브랜드", "선택 후보", "LLM Q1", "A Q1", "B Q1", "LLM Q2", "A Q2", "B Q2",
                    "LLM 다른 후보 요소(개수)", "A 다른 후보 요소", "B 다른 후보 요소"])
        for k in order:
            p = llm[iid[k]]; a = A[k]; b = B.get(k, {})
            n = sum(1 for e in p["added_elements"] if e["similar_in"] != "none")
            w.writerow([k, a["브랜드"], a["선택 후보"], p["final_main_code"], strip(a["Q1 핵심 코드"]), strip(b.get("Q1 핵심 코드", "")),
                        p["selected_core_retained"], a["Q2 유지"], b.get("Q2 유지", ""),
                        f"{'있음' if n else '없음'}({n})", a["다른 후보 요소"], b.get("다른 후보 요소", "")])

    # ---- 18 pairs: final x non-selected candidate
    def human_pair(final, elems, k, cand):
        flag = final.get(k, {}).get("다른 후보 요소", "")
        rows = [e for e in elems if e["item"] == k and e.get("출처 후보") == cand]
        if flag == "없음":
            return "0", "시트1 없음"
        if flag == "있음":
            if not [e for e in elems if e["item"] == k]:
                return "미기재", "시트1 있음, 시트2 비어 있음"
            new = [e for e in rows if e.get("선택 후보에도 있었나요?") == "아니오"]
            reint = [e for e in rows if e.get("선택 후보에도 있었나요?") == "예"]
            return ("1" if new else "0"), f"새 유입 {len(new)}, 재해석 {len(reint)}"
        return "미기재", "시트1 빈칸"

    pairs = []
    for k in order:
        p = llm[iid[k]]; sel = A[k]["선택 후보"]
        for cand in [c for c in ("C1", "C2", "C3", "C4") if c != sel]:
            le = [e["element"] for e in p["added_elements"] if e["similar_in"] == cand]
            av, an = human_pair(A, A_el, k, cand)
            bv, bn = human_pair(B, B_el, k, cand)
            st = "판정 불가" if av == "미기재" else ("일치" if av == ("1" if le else "0") else
                                                ("LLM만 유입" if le else "A만 유입"))
            pairs.append([k, A[k]["브랜드"], sel, cand, "1" if le else "0", " / ".join(le), av, an, bv, bn, st])
    with open(os.path.join(OUT, "inflow_pairs_18.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "브랜드", "선택 후보", "다른 후보", "LLM 유입", "LLM 요소", "A 새 유입", "A 근거",
                    "B 새 유입", "B 근거", "A–LLM"])
        w.writerows(pairs)

    # ---- Q6 cells (MARK_ACT has no LLM counterpart; listed separately)
    q6 = {"Dior": ["MARK"], "Canva": ["EMPLOYER_KIT", "KEEPSAKE"], "Mastercard": ["MERCHANT_RECOGNITION", "PAID_INVITATION"]}
    cells = []
    for k in order:
        br = A[k]["브랜드"]; p = llm[iid[k]]
        for c in q6[br]:
            lv = "1" if p["recurring"][c]["in_final"] else "0"
            cells.append([k, br, c, lv, A[k].get(f"Q6 {c}", ""), B.get(k, {}).get(f"Q6 {c}", "")])
        if br == "Dior":
            cells.append([k, br, "MARK_ACT (LLM 없음)", "", A[k].get("Q6 MARK_ACT", "") + " / " + A[k].get("Q6 MARK_ACT_수선한 사람", ""),
                          B.get(k, {}).get("Q6 MARK_ACT", "") + " / " + B.get(k, {}).get("Q6 MARK_ACT_수선한 사람", "")])
    with open(os.path.join(OUT, "q6_cells.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "브랜드", "칸", "LLM", "A", "B"])
        w.writerows(cells)

    # ---- summary
    det = [p for p in pairs if p[10] != "판정 불가"]
    dis = [p for p in det if p[10] != "일치"]
    q6c = [c for c in cells if not c[2].startswith("MARK_ACT")]
    print("A sheet2 present:", A_has2, "rows:", len(A_el), "| B sheet2 present:", B_has2, "rows:", len(B_el))
    print(f"pairs determinable {len(det)}/18, disagreements {len(dis)}:",
          {s: sum(1 for p in dis if p[10] == s) for s in ("LLM만 유입", "A만 유입")})
    print("Q1 A=LLM", sum(strip(A[k]["Q1 핵심 코드"]) == llm[iid[k]]["final_main_code"] for k in order),
          "B=LLM", sum(strip(B[k]["Q1 핵심 코드"]) == llm[iid[k]]["final_main_code"] for k in order if k in B))
    print("Q6 A=LLM", sum(c[3] == c[4] for c in q6c), "/", len(q6c), "B=LLM", sum(c[3] == c[5] for c in q6c))


if __name__ == "__main__":
    main()
