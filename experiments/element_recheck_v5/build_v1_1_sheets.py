"""Build v1.1 coding workbooks (calibration for B: 9 items; main: 24 items for A and B).

Read-only on all inputs. No model calls. Writes only to human_coding_v1_1/ and the analyst-only folder.
xlsx is written by hand (zip + XML) with list validation, locked cells, and fixed zip timestamps
so that the file hash is reproducible.
"""
import csv
import hashlib
import json
import os
import random
import re
import sys
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "human_coding_v1_1")
ANALYST = os.path.join(HERE, "_analyst_only_DO_NOT_SHOW_CODERS")
SEED = 20261126
sys.path.insert(0, os.path.join(ROOT, "experiments", "remaining_work_v5"))
sys.path.insert(0, os.path.join(ROOT, "experiments", "selection_focus_v5"))
import xlsx_read  # noqa: E402

CODES = {
    "Dior": [f"Dior-{c}" for c in "ABCDEFGH"] + ["Dior-Z"],
    "Canva": [f"Canva-{c}" for c in ["A", "B", "C", "D", "E", "F", "F2", "G", "H", "I", "J", "K", "Z"]],
    "Mastercard": [f"MC-{c}" for c in ["A1", "A2", "A3", "B", "C", "D", "E", "F", "G", "H", "Z"]],
}
Q6COLS = [("MARK", "Dior"), ("MARK_ACT", "Dior"), ("MARK_ACT_수선한 사람", "Dior"),
          ("EMPLOYER_KIT", "Canva"), ("KEEPSAKE", "Canva"),
          ("MERCHANT_RECOGNITION", "Mastercard"), ("PAID_INVITATION", "Mastercard")]
# Claude translations for the two replacement items (not in the earlier Korean workbook). Marked for review.
CLAUDE_KO = {
    "Canva|BASE|2|LEDGER|r2": (
        "계좌 자동 입금은 첫 급여를 손에 쥐던 것에서 앱에서 흘끗 보는 숫자로 바꿔 놓았다. Canva는 그 순간에 의식을 "
        "되돌려 준다. 대표 '급여 명세 조각(stub)' 템플릿은 첫 급여일을 액자에 넣을 수 있는 기념물로 만든다. 날짜, 직장, "
        "그 주에 한 일, 가장 먼저 알린 사람을 담는다. 금액은 직접 보이기로 하지 않는 한 가려진다. 숫자는 사적이지만 "
        "이정표는 그렇지 않기 때문이다. 몇 번의 클릭으로 인쇄해 액자에 넣을 수 있다. 프리랜서에게는 '처음 받은 대금' "
        "버전이 있고, 첫 직장이 순탄치 않았던 사람을 위한 더 차분한 변형판도 있다. 기념물이 호응을 얻으면, 팀은 첫 "
        "급여일이 어떻게 이루어지는지 간단히 설명하는 안내와 함께 팀이 서명한 버전을 신입에게 보낼 수 있다. 그러면 "
        "사무적인 이메일이 환영 인사가 된다."),
    "Mastercard|BASE|3|NEUTRAL|r2": (
        "친구가 커피값이나 저녁값을 내주면, 우리는 보통 '다음에 갚을게'라고 말한다. 하나 빚졌어(Owe Me One)는 그 말을 "
        "실제 선택지로 바꾼다. 개인 간 결제에서 평소의 송금 옆에 '직접 만나서 갚기'가 나온다. 돈을 보내는 대신 친구와 "
        "날짜를 정하고, 빚은 함께 보내는 시간으로 갚는다. 결제 브랜드가 결제를 완료하지 않기로 한다는 점이 도발이다. "
        "Mastercard는 돈을 움직이므로, 돈이 무엇을 위한 것인지 말할 수 있다. 사람들을 서로에게 데려가는 것이다. 만남이 "
        "이루어지지 않으면 요청은 조용히 일반 결제로 바뀐다. 결제 파트너와 함께 시범 운영이나 시제품으로 시작하고, 이어 "
        "카페와 식당 호스트, 그리고 '누구에게 하나 빚졌나요?'라는 소셜 대화를 더한다. 성공은 실제로 이루어진 만남의 "
        "수로 센다."),
}


def kid(iid):
    return "K" + hashlib.sha256(f"20261124|{iid}".encode()).hexdigest()[:8]


# ------------------------------------------------------------------ data
def load_ko():
    wb = xlsx_read.read(os.path.join(ROOT, "coding_researcher_A_ko.xlsx"))["코딩"]
    recs, cur = {}, None
    for r in wb:
        if not r or not r[0]:
            continue
        k, v = r[0], (r[1] if len(r) > 1 else None)
        if k == "ID · 브랜드 · 주제":
            parts = [p.strip() for p in v.split("|")]
            cur = {"item": parts[0], "topic_ko": parts[2]}
            recs[parts[0]] = cur
        elif cur is not None and k in ("후보 C1", "후보 C2", "후보 C3", "후보 C4", "최종 제목", "최종 아이디어", "선택된 후보"):
            cur[k] = v or ""
    return recs


def load_items():
    import pilot5  # read-only use of the item loader
    return {it["item_id"]: it for it in pilot5.items(include_v3=False)}


def build_records(item_ids, items, ko):
    recs = []
    for iid in item_ids:
        it = items[iid]
        k = kid(iid)
        src = ko.get(k)
        r1 = ko.get(kid(iid.rsplit("|", 1)[0] + "|r1"))
        if src is None:  # replacement item: candidates from the r1 row of the same set/arm (identical candidates)
            r1_it = items[iid.rsplit("|", 1)[0] + "|r1"]
            assert r1_it["cands"] == it["cands"] and r1_it["selected"] == it["selected"]
            assert r1_it["final"]["title"] == it["final"]["title"]
            src = dict(r1)
            src["최종 아이디어"] = CLAUDE_KO[iid]
            tr = "Claude 번역(검토 필요)"
        else:
            tr = "기존 번역"
        assert src["선택된 후보"] == it["selected"], iid
        recs.append(dict(
            item=k, brand=it["brand"], topic=src["topic_ko"], selected=it["selected"],
            cands_ko=[src[f"후보 C{i}"] for i in range(1, 5)],
            title_ko=src["최종 제목"], final_ko=src["최종 아이디어"], translation=tr,
            final_en=f'{it["final"]["title"]}: {it["final"]["idea"]}',
            cands_en="\n\n".join(f'{c["id"]}. {c["title"]}: {c["core_idea"]}' for c in it["cands"]),
            nonselected=[c["id"] for c in it["cands"] if c["id"] != it["selected"]],
        ))
    return recs


def order_no_adjacent_set(item_ids, seed):
    rng = random.Random(seed)
    for _ in range(10000):
        ids = item_ids[:]
        rng.shuffle(ids)
        sets = [i.rsplit("|", 2)[0] for i in ids]
        if all(a != b for a, b in zip(sets, sets[1:])):
            return ids
    raise RuntimeError("no order")


# ------------------------------------------------------------------ xlsx writer
CLEAN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
ST_DEFAULT, ST_INPUT, ST_HEAD, ST_TEXT, ST_NA = 0, 1, 2, 3, 4
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Malgun Gothic"/></font><font><b/><sz val="11"/><name val="Malgun Gothic"/></font></fonts>
<fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFD9D9D9"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFEFEFEF"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right><top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1" applyProtection="1"><alignment vertical="top" wrapText="1"/><protection locked="0"/></xf>
<xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def col_letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class Sheet:
    def __init__(self, name, widths):
        self.name, self.widths, self.rows, self.dv = name, widths, [], {}

    def add(self, cells):  # cells: list of (value, style)
        self.rows.append(cells)
        return len(self.rows)  # 1-based row number

    def validate(self, ref, formula):
        self.dv.setdefault(formula, []).append(ref)

    def xml(self):
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
               '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
               '<sheetFormatPr defaultRowHeight="16.5"/><cols>']
        for i, w in enumerate(self.widths):
            out.append(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>')
        out.append("</cols><sheetData>")
        for ri, cells in enumerate(self.rows, 1):
            out.append(f'<row r="{ri}">')
            for ci, (v, st) in enumerate(cells):
                ref = f"{col_letter(ci)}{ri}"
                if v is None or v == "":
                    out.append(f'<c r="{ref}" s="{st}"/>')
                else:
                    t = escape(CLEAN.sub("", str(v)))
                    out.append(f'<c r="{ref}" s="{st}" t="inlineStr"><is><t xml:space="preserve">{t}</t></is></c>')
            out.append("</row>")
        out.append("</sheetData>")
        out.append('<sheetProtection sheet="1" objects="1" scenarios="1" formatColumns="0" formatRows="0" insertRows="0"/>')
        if self.dv:
            out.append(f'<dataValidations count="{len(self.dv)}">')
            for formula, refs in self.dv.items():
                out.append(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" errorTitle="목록에서 고르세요" '
                           f'error="목록에 있는 값만 입력할 수 있습니다." sqref="{" ".join(refs)}"><formula1>{escape(formula)}</formula1></dataValidation>')
            out.append("</dataValidations>")
        out.append("</worksheet>")
        return "".join(out)


def write_xlsx(path, sheets):
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>',
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i, sh in enumerate(sheets, 1):
        ct.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        wb.append(f'<sheet name="{escape(sh.name)}" sheetId="{i}" r:id="rId{i}"/>')
        rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
    n = len(sheets) + 1
    rels.append(f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
    ct.append("</Types>")
    wb.append("</sheets></workbook>")
    rels.append("</Relationships>")
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    parts = [("[Content_Types].xml", "".join(ct)), ("_rels/.rels", root_rels), ("xl/workbook.xml", "".join(wb)),
             ("xl/_rels/workbook.xml.rels", "".join(rels)), ("xl/styles.xml", STYLES)]
    parts += [(f"xl/worksheets/sheet{i}.xml", sh.xml()) for i, sh in enumerate(sheets, 1)]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts:
            zi = zipfile.ZipInfo(name, date_time=(2026, 11, 26, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data.encode("utf-8"))


# ------------------------------------------------------------------ workbook content
GUIDE_LINES = [
    "블라인드 코딩 v1.1 — 자세한 기준은 CODING_GUIDE_v1_1.md를 본다.",
    "서로 상의하지 않고 각자 평가한다. 연노란 칸만 입력할 수 있다. 목록이 있는 칸은 목록에서만 고른다.",
    "기준 판본: 한국어 번역. 영어 원문은 '원문' 탭에 있다. 번역이 의심되면 시트1 '번역 확인'에 표시한다.",
    "판단은 보이는 글에서만 한다. 표현이 아니라 요소가 하는 일을 비교한다. 요소가 더해진 것 자체는 좋거나 나쁜 것이 아니다.",
    "",
    "시트1_최종안 (최종안마다 한 줄)",
    "· Q1: 브랜드 코드(예: Dior-C). 후보 번호(C1–C4)가 아니다.",
    "· Q2: yes / partial / no",
    "· 다른 후보 요소: 있음 / 없음을 꼭 고른다. 있음이면 시트2에 쓴다.",
    "· Q6: 해당 브랜드 칸만 0/1. 정의 문구대로 정한다. 1이면 'Q6 근거 문장'을 꼭 복사한다. 넓은 해석은 메모에 'Q6 넓은 해석:'.",
    "· KEEPSAKE: 액자·인쇄·공유가 글에 쓰여 있을 때만 1. 팀의 축하·응원 메시지만으로는 1이 아니다.",
    "· MARK_ACT(Dior): 옷에 표식 없이 사람이 공개적으로 수선하는 행위가 서명 역할을 한다고 볼 때 1. 1이면 '수선한 사람'을 고른다.",
    "· 메모: 대상 문항을 앞에 쓴다(Q2:, Q4:, 전체 유사:, Q6 넓은 해석:).",
    "",
    "시트2_요소 (다른 후보 요소마다 한 줄, 최종안마다 4줄. 모자라면 맨 아래 예비 줄을 쓴다)",
    "· 요소 이름: 짧은 이름. 최종안 근거 문장: 최종안 문장을 그대로 복사.",
    "· 출처 후보: 그 행의 선택되지 않은 후보 번호만 고를 수 있다.",
    "· 선택 후보에도 있었나요?: 예(재해석 연결) / 아니오(새 유입).",
    "· 특정 문장 없이 전체 느낌이나 글에 없는 전제로만 연결되면 시트2에 쓰지 않고, 시트1 메모에 '전체 유사:'로 쓴다.",
    "· Q4: main(지우면 핵심 기제가 바뀜) / auxiliary. Q2=yes인데 main이면 메모에 'Q4:'로 이유를 쓴다.",
    "· Q5 순서: unclear(글로 판단 불가) → needed(없으면 목적이 분명히 덜 충족) → develops(선택 발상을 돕는 세부) → extra(별도 기능).",
]


def make_workbook(path, recs, title):
    if os.path.exists(path):  # never overwrite a frozen (or possibly in-use) workbook
        print("skip existing", os.path.basename(path))
        return
    guide = Sheet("안내", [130])
    guide.add([(title, ST_HEAD)])
    for line in GUIDE_LINES:
        guide.add([(line, ST_TEXT if line else ST_DEFAULT)])

    src = Sheet("원문", [12, 11, 10, 8, 45, 45, 45, 45, 28, 60, 16, 60, 60])
    src.add([(h, ST_HEAD) for h in ["item", "브랜드", "주제", "선택 후보", "후보 C1", "후보 C2", "후보 C3", "후보 C4",
                                    "최종 제목", "최종안 (한국어, 평가 기준)", "번역", "최종안 (영어 원문)", "후보 (영어 원문)"]])
    for r in recs:
        src.add([(r["item"], ST_TEXT), (r["brand"], ST_TEXT), (r["topic"], ST_TEXT), (r["selected"], ST_TEXT)]
                + [((("[선택] " if f"C{i + 1}" == r["selected"] else "") + c), ST_TEXT) for i, c in enumerate(r["cands_ko"])]
                + [(r["title_ko"], ST_TEXT), (r["final_ko"], ST_TEXT), (r["translation"], ST_TEXT),
                   (r["final_en"], ST_TEXT), (r["cands_en"], ST_TEXT)])

    s1 = Sheet("시트1_최종안", [12, 11, 26, 8, 13, 10, 12] + [11] * 7 + [50, 10, 40])
    head = ["item", "브랜드", "최종 제목", "선택 후보", "Q1 핵심 코드", "Q2 유지", "다른 후보 요소"] + \
           [f"Q6 {c}" for c, _ in Q6COLS] + ["Q6 근거 문장", "번역 확인", "메모"]
    s1.add([(h, ST_HEAD) for h in head])
    for r in recs:
        cells = [(r["item"], ST_TEXT), (r["brand"], ST_TEXT), (r["title_ko"], ST_TEXT), (r["selected"], ST_TEXT),
                 ("", ST_INPUT), ("", ST_INPUT), ("", ST_INPUT)]
        for c, b in Q6COLS:
            cells.append(("", ST_INPUT) if b == r["brand"] else ("N/A", ST_NA))
        cells += [("", ST_INPUT), ("", ST_INPUT), ("", ST_INPUT)]
        rn = s1.add(cells)
        s1.validate(f"E{rn}", '"' + ",".join(CODES[r["brand"]]) + '"')
        s1.validate(f"F{rn}", '"yes,partial,no"')
        s1.validate(f"G{rn}", '"있음,없음"')
        for j, (c, b) in enumerate(Q6COLS):
            if b == r["brand"]:
                letter = col_letter(7 + j)
                s1.validate(f"{letter}{rn}", '"디자이너,장인·아틀리에 직원,기타,글에 없음"' if c == "MARK_ACT_수선한 사람" else '"0,1"')
        s1.validate(f"P{rn}", '"의심"')

    s2 = Sheet("시트2_요소", [12, 11, 8, 7, 22, 50, 10, 14, 40, 12, 12, 35])
    s2.add([(h, ST_HEAD) for h in ["item", "브랜드", "선택 후보", "요소 번호", "요소 이름", "최종안 근거 문장", "출처 후보",
                                   "선택 후보에도 있었나요?", "출처 후보 근거 문장 (선택)", "Q4 역할", "Q5 기능", "메모"]])

    def elem_row(item, brand, sel, n, srcs, item_input=False):
        rn = s2.add([(item, ST_INPUT if item_input else ST_TEXT), (brand, ST_TEXT), (sel, ST_TEXT), (n, ST_TEXT)]
                    + [("", ST_INPUT)] * 8)
        s2.validate(f"G{rn}", '"' + ",".join(srcs) + '"')
        s2.validate(f"H{rn}", '"예,아니오"')
        s2.validate(f"J{rn}", '"main,auxiliary"')
        s2.validate(f"K{rn}", '"needed,develops,extra,unclear"')
        if item_input:
            s2.validate(f"A{rn}", f"'원문'!$A$2:$A${len(recs) + 1}")

    for r in recs:
        for n in range(1, 5):
            elem_row(r["item"], r["brand"], r["selected"], str(n), r["nonselected"])
    for n in range(20):
        elem_row("", "", "", "예비", ["C1", "C2", "C3", "C4"], item_input=True)

    write_xlsx(path, [guide, src, s1, s2])


def main():
    os.makedirs(OUT, exist_ok=True)
    items = load_items()
    ko = load_ko()
    by_kid = {kid(i): i for i in items}
    cal_k = [r["item"] for r in csv.DictReader(open(os.path.join(ROOT, "coding_researcher_A_partial.csv"), encoding="utf-8-sig"))]
    cal_ids = order_no_adjacent_set([by_kid[k] for k in cal_k], SEED + 1)
    main_ids = [r["item_id"] for r in csv.DictReader(open(os.path.join(ANALYST, "main_sample_proposal.csv"), encoding="utf-8-sig"))]
    assert not set(map(kid, main_ids)) & set(cal_k)
    main_ids = order_no_adjacent_set(main_ids, SEED + 2)

    cal = build_records(cal_ids, items, ko)
    mn = build_records(main_ids, items, ko)
    make_workbook(os.path.join(OUT, "calibration_researcherB_9.xlsx"), cal, "보정 코딩 · 연구자 B · 9건 (v1.1)")
    make_workbook(os.path.join(OUT, "main_researcherA_24.xlsx"), mn, "본평가 · 연구자 A · 24건 (v1.1)")
    make_workbook(os.path.join(OUT, "main_researcherB_24.xlsx"), mn, "본평가 · 연구자 B · 24건 (v1.1)")

    # 2026-11-26 sample reduced to 6 (2 per brand); see _analyst_only_DO_NOT_SHOW_CODERS/main_sample_6.csv
    six_ids = [r["item_id"] for r in csv.DictReader(open(os.path.join(ANALYST, "main_sample_6.csv"), encoding="utf-8-sig"))]
    six_ids = order_no_adjacent_set(six_ids, SEED + 3)
    six = build_records(six_ids, items, ko)
    assert all(r["translation"] == "기존 번역" for r in six)
    make_workbook(os.path.join(OUT, "main_researcherA_6.xlsx"), six, "본평가 · 연구자 A · 6건 (v1.1)")
    make_workbook(os.path.join(OUT, "main_researcherB_6.xlsx"), six, "본평가 · 연구자 B · 6건 (v1.1, 선택)")

    with open(os.path.join(ANALYST, "v1_1_sheet_order_key.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["workbook", "position", "item", "item_id", "translation"])
        for name, ids, recs in (("calibration_researcherB_9", cal_ids, cal), ("main_24", main_ids, mn), ("main_6", six_ids, six)):
            for p, (iid, r) in enumerate(zip(ids, recs), 1):
                w.writerow([name, p, r["item"], iid, r["translation"]])
    print("calibration", [r["item"] for r in cal])
    print("main", [r["item"] for r in mn], "claude-translated", [r["item"] for r in mn if r["translation"] != "기존 번역"])


if __name__ == "__main__":
    main()
