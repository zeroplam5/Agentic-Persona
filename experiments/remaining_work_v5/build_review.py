"""Build the row-level review of researcher A's 9 partial codings (no model calls, inputs are read only).

  python build_review.py

Inputs (read only):
  ../../coding_researcher_A_partial.csv            researcher A partial extract (9 rows), copy in input_preserved/
  ../../human_coding_blind_v5_focus/coding_sheet_researcherA.csv   original blank sheet (48 rows)
  ../../coding_researcher_A_ko.xlsx                Korean workbook (final texts as researcher A read them)
  ../selection_focus_v5/data/revise.jsonl, codes.jsonl              v5 finals and LLM coder output
Outputs:
  human_coding_review.csv                           coder-facing review (no condition labels, no LLM codes)
  element_confirmation_sheet_A.csv                  fill-in sheet for researcher A (one row per element slot)
  researcher_A_common_answers.csv                   common answers, verbatim (2026-11-25)
  _analyst_only_DO_NOT_SHOW_CODERS/link_llm_comparison.csv          condition + LLM comparison (unblinds)
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from xlsx_read import read as read_xlsx

ROOT = Path(__file__).resolve().parent
PROJ = ROOT.parent.parent
PARTIAL = PROJ / "coding_researcher_A_partial.csv"
ORIG = PROJ / "human_coding_blind_v5_focus" / "coding_sheet_researcherA.csv"
KO_XLSX = PROJ / "coding_researcher_A_ko.xlsx"
WORKFILE_NAME = "coding_researcher_A_ko.xlsx - 코딩.csv"  # named by researcher A as the working file
V5 = ROOT.parent / "selection_focus_v5" / "data"
SEED = 20261124  # v5 config seed used for blinded item ids

BRAND_Q6 = {"Dior": ["MARK"], "Canva": ["EMPLOYER_KIT", "KEEPSAKE"],
            "Mastercard": ["MERCHANT_RECOGNITION", "PAID_INVITATION"]}
ALL_Q6 = ["MARK", "EMPLOYER_KIT", "KEEPSAKE", "MERCHANT_RECOGNITION", "PAID_INVITATION"]
CODES = {"Dior": set("ABCDEFGH"), "Canva": set("ABCDEFGHIJK") | {"F2", "Z"},
         "Mastercard": {"A1", "A2", "A3", "B", "C", "D", "E", "F", "G", "H", "Z"}}
Q3 = "Q3_added_elements_from_other_candidates(element=Cx; ...)"
Q4 = "Q4_role_main_or_auxiliary_per_element"
Q5 = "Q5_function_needed_develops_extra_unclear_per_element"

# Researcher A's answers to the common questions, recorded verbatim as relayed on 2026-11-25.
COMMON_ANSWERS = [
    ("1", "Q3에 후보 원문을 통째로 붙인 의미",
     "Q3은 후보 선택 시 자동 완성 때문에 후보 문장 전체가 함께 들어갔다. 연구자가 선택하려던 값은 문장 앞의 후보 번호 Cx였다. "
     "따라서 후보 전체의 유입을 의미한다고 해석하지 않는다.",
     "반영: Q3 값은 '후보 번호 Cx'로 읽는다. 후보 전체 유입으로 해석하지 않는다."),
    ("2", "한 후보에서 여러 요소가 들어왔다고 본 경우",
     "Q3에 문장 전체가 들어간 이유는 모든 행에서 같다. 한 후보에서 여러 요소가 유입되었다고 판단했는지는 이 답변만으로 확정하지 않는다. "
     "구체적인 요소는 행별로 확인한다.",
     "미확정: 행별 확인(element_confirmation_sheet_A.csv)."),
    ("3", "(분석자 질문 3은 Q4 main의 의미였다. 답변은 MARK 판단에 관한 것이다)",
     "한 사례에서 연구자는 여러 유명 디자이너가 직접 수선하며 쇼를 하는 것이 일종의 서명 역할을 한다고 생각했다. "
     "어느 ID에 대한 판단인지는 확인이 필요하다. 구체적인 표식 없이 디자이너의 참여를 MARK로 볼 수 있는지는 "
     "현재 정의와 대조하여 별도 논의 대상으로 남긴다.",
     "미확정: 해당 ID 확인 필요. MARK 정의 범위는 별도 논의. Q4 main의 의미는 아직 답변되지 않음."),
    ("4", "Q6 비해당 브랜드 열의 값",
     "Q6에서 비해당 브랜드 열에도 값을 입력한 이유는 다른 브랜드의 요소가 해당 브랜드에 영향을 준다고 판단했기 때문이다. "
     "기존 값은 보존한다. 현재 Q6 분석에는 해당 브랜드 열만 사용한다. 이 응답만으로 브랜드 간 영향이 입증되었다고 해석하지 않는다.",
     "반영: 원래 값 보존, 분석은 해당 브랜드 열만. 브랜드 간 영향은 입증된 것으로 보지 않음."),
    ("5", "기준 언어", "연구자는 한국어 번역을 보고 평가했다.",
     "반영: 근거 문장은 한국어 번역 최종안에서 인용하도록 확인 시트를 구성. 영어 원문은 대조용으로 함께 둠."),
    ("6", "작업 파일",
     "평가 작업 파일은 대화에 업로드한 `coding_researcher_A_ko.xlsx - 코딩.csv`이다. 이 파일과 부분 추출 CSV의 Q1~Q6·메모를 "
     "행별 대조해 값이 손실 없이 옮겨졌는지 확인한다.",
     "보류: 이 이름의 파일이 프로젝트 폴더와 대화 첨부 어디에도 없어 대조하지 못함. 파일을 프로젝트에 두면 대조한다."),
]

# Row-level: analyst observation (unchanged facts) and questions focused on the actual element and its evidence sentence.
# Evidence sentences are asked open-ended; the analyst does not propose which sentence is the evidence.
COMMON_ROW_Q = ("[공통] (a) Q3의 후보 {c}에서 최종안에 들어왔다고 본 구체적 요소는 무엇인가? "
                "(b) 그 근거가 되는 최종안(한국어 번역) 문장을 그대로 인용해 달라. "
                "(c) 그 요소가 선택 후보 {s} 원문에는 없다고 보았는가? "
                "(d) 요소가 둘 이상이면 각각 적고, Q4·Q5 값이 어느 요소에 대한 것인지 표시해 달라.")
REVIEW = {
    "K6e0d7b70": dict(
        observation=("선택 후보 C1 원문에 '고용주와 팀도 신입에게 보낼 수 있다'는 문장이 이미 있다(가이드 사례 4와 관련). "
                     "Q4=main, Q2=yes."),
        row_q="[행별] 최종안의 '팀 서명판' 문장을 C3 유입으로 보았는지, 선택 후보 C1에 이미 있던 것으로 보았는지?"),
    "Kde2b84f2": dict(
        observation=("분석자는 최종안에서 C4(집계 결제 데이터로 시간·장소를 찾음)에 대응하는 문장을 찾지 못했다. "
                     "Q4=main, Q2=yes, Q5=unclear. 메모 'This is not for invitation'의 대상 문항이 표시되지 않았다."),
        row_q="[행별] Q5 unclear의 이유는? 메모는 어느 문항(Q3·Q5·Q6 PAID_INVITATION 등)에 대한 것인가?"),
    "Kd1fa6a9a": dict(
        observation=("Q1=C(Canva 코드북 C는 '첫 급여가 무엇이 되었는가 이야기', A는 '급여명세 해설'). Q6 KEEPSAKE=1인데 "
                     "분석자는 최종안에서 액자·공유용 기념물 문장을 찾지 못했다."),
        row_q="[행별] Q1 C는 Canva 코드북의 C(이야기)를 뜻하는가? Q6 KEEPSAKE=1의 근거 문장은?"),
    "Kdc93a943": dict(
        observation=("분석자는 이 최종안의 영어 원문과 한국어 번역 모두에서 서명 수선·표식 문장을 찾지 못했다. 같은 후보 묶음의 "
                     "K397eccb7과 Q3–Q5 입력이 같다. 최종안에는 '프티트 맹(하우스의 숙련 재봉사와 장인)이 공개적으로 수선'하는 "
                     "내용이 있으며, '유명 디자이너'라는 표현은 없다."),
        row_q=("[행별] 공통 답변 3의 '디자이너가 직접 수선하며 쇼를 하는 것이 서명 역할' 사례가 이 행인가? 이 행이라면 Q3 C3와 "
               "Q6 MARK=1은 그 판단에 따른 것인가? K397eccb7과 입력이 섞였을 가능성은?")),
    "K35d9fc1b": dict(
        observation=("분석자는 최종안에서 C2(공유 테이블의 빈자리 예약)에 대응하는 문장을 찾지 못했다. Q2=partial."),
        row_q="[행별] 최종안의 결제음 문장을 Q3 요소로 보았는가? 보았다면 출처 후보는? Q2 partial의 이유는?"),
    "K397eccb7": dict(
        observation=("최종안에 C3와 관련될 수 있는 선택형 서명 수선 문장이 있다. 평가자가 요소명을 적지 않아 기록하지 않았다. "
                     "Q4=main, Q2=yes."),
        row_q=("[행별] 공통 답변 3의 사례가 이 행인가? 최종안의 '이야기를 짧은 인물 소개로 공유' 문장은 검토 후 제외했는가, "
               "입력하지 않은 것인가?")),
    "K46cb224f": dict(
        observation=("Q1=H(약속 돈). Mastercard 코드북 C는 '직접 만나 갚기'. Q5=needed. Q6 PAID_INVITATION=1인데 분석자는 "
                     "최종안에서 선불 초대 문장을 찾지 못했다."),
        row_q="[행별] Q1 H의 근거는? needed로 본 이유는? Q6 PAID_INVITATION=1의 근거 문장은?"),
    "K0b6dfe7c": dict(
        observation=("C4의 핵심인 집계 결제 데이터는 최종안에 없다. 시간대·장소 관련 문장은 있다. Q4=main, Q5=needed, "
                     "Q2=partial, Q1=A3."),
        row_q="[행별] Q4 main과 Q1 A3을 함께 입력한 의미는? needed로 본 이유는?"),
    "K479c22c0": dict(
        observation=("Q1=C(Canva 코드북 A는 '급여명세 해설'). 선택 후보 C3 원문에 '고용주와 급여 제공자가 Canva for Teams 템플릿으로 "
                     "도입'이 이미 있다(가이드 사례 4와 관련). Q4=main, Q2=yes."),
        row_q="[행별] Q1 C의 의미는? '도와준 사람에게 보낸다' 문장은 검토 후 제외했는가, 입력하지 않은 것인가?"),
}
OPEN_COMMON = "[미답변 공통 질문] Q4 main은 '그 요소가 최종안 전체를 이끈다'는 뜻으로 입력했는가?"


def ko_blocks():
    rows = read_xlsx(KO_XLSX)["코딩"]
    out, cur = {}, None
    for r in rows:
        if r and r[0] == "ID · 브랜드 · 주제":
            cur = r[1].split("|")[0].strip()
            out[cur] = {}
        elif cur and r and r[0]:
            out[cur][r[0]] = r[1] if len(r) > 1 else None
    return out


def main():
    part = list(csv.DictReader(open(PARTIAL, encoding="utf-8-sig")))
    orig = {r["item"]: r for r in csv.DictReader(open(ORIG, encoding="utf-8-sig"))}
    ko = ko_blocks()
    base = ["brand", "topic", "candidates", "selected_candidate", "final_title", "final_idea"]
    order = list(orig)
    rev = [json.loads(l) for l in open(V5 / "revise.jsonl", encoding="utf-8")]
    hmap = {"K" + hashlib.sha256(f'{SEED}|{r["item_id"]}'.encode()).hexdigest()[:8]: r["item_id"] for r in rev}
    codes = {json.loads(l)["item_id"]: json.loads(l) for l in open(V5 / "codes.jsonl", encoding="utf-8")}
    workfile = [p for p in PROJ.rglob("*") if p.name == WORKFILE_NAME]
    transfer = ("대조 완료" if workfile else
                f"보류: 연구자 A가 지정한 작업 파일 '{WORKFILE_NAME}'이 프로젝트에 없음(2026-11-25 확인)")

    rows, analyst, sheet = [], [], []
    for r in part:
        iid = r["item"]
        o = orig.get(iid)
        b = r["brand"]
        q3 = r[Q3]
        m = re.match(r"\s*C(\d)\.", q3)
        q3_cand = f"C{m.group(1)}" if m and len(re.findall(r"(?:^|\n)\s*C\d\.", q3)) == 1 else ""
        out_brand_q6 = {k: r[f"Q6_{k}_in_final_0_1"] for k in ALL_Q6 if k not in BRAND_Q6[b]}
        fmt = []
        if r["Q1_main_code"] not in CODES[b]:
            fmt.append("Q1 값이 코드북에 없음")
        if r["Q2_selected_core_retained_yes_partial_no"] not in ("yes", "partial", "no"):
            fmt.append("Q2 허용값 아님")
        if q3 and "=" not in q3.split("\n")[0][:80]:
            fmt.append("Q3에 후보 문장 전체가 들어감(자동 완성, 공통 답변 1). 의도한 값은 후보 번호")
        if r[Q4] in ("main", "auxiliary"):
            fmt.append("Q4에 요소명 없음(값 1개)")
        if r[Q5] in ("needed", "develops", "extra", "unclear"):
            fmt.append("Q5에 요소명 없음(값 1개)")
        filled_out = [k for k, v in out_brand_q6.items() if v.strip() != ""]
        if filled_out:
            fmt.append("Q6 비해당 브랜드 열에 값 입력(공통 답변 4: 브랜드 간 영향 판단): "
                       + ",".join(f"{k}={out_brand_q6[k]}" for k in filled_out))
        rv = REVIEW[iid]
        sel = r["selected_candidate"]
        questions = " ".join([COMMON_ROW_Q.format(c=q3_cand or "?", s=sel), rv["row_q"], OPEN_COMMON])
        row = {
            "item": iid,
            "sheet_position": order.index(iid) + 1 if o else "",
            "found_in_original_sheet": "yes" if o else "no",
            "base_columns_identical_to_original": "yes" if o and all(r[k] == o[k] for k in base) else "no",
            "linked_to_v5_output_and_llm_code": "yes" if hmap.get(iid) in codes else "no",
            "Q1_Q6_notes_transfer_check": transfer,
            "brand": b, "selected_candidate": sel, "final_title": r["final_title"],
            # entered values, verbatim (never edited)
            "A_Q1_main_code": r["Q1_main_code"],
            "A_Q2_retained": r["Q2_selected_core_retained_yes_partial_no"],
            "A_Q3_raw": q3,
            "A_Q4_raw": r[Q4], "A_Q5_raw": r[Q5],
            **{f"A_Q6_{k}": r[f"Q6_{k}_in_final_0_1"] for k in ALL_Q6},
            "A_notes": r["notes"],
            # derived (only when certain)
            "derived_Q3_candidate_id": q3_cand,
            "derived_Q3_reading": "후보 번호 Cx를 선택한 값(공통 답변 1). 후보 전체 유입 아님",
            "derived_Q3_element": "확인 필요",
            "derived_Q4_Q5_link": ("후보 단위로만 연결 가능(Q3 항목 1개, Q4·Q5 값 1개). 요소 단위 연결은 행별 확인 필요"
                                   if q3_cand and r[Q4] and r[Q5] else "연결 불가"),
            "Q6_used_in_analysis": ";".join(f"{k}={r[f'Q6_{k}_in_final_0_1']}" for k in BRAND_Q6[b]),
            "Q6_excluded_out_of_brand(original kept)": ";".join(f"{k}={v}" for k, v in out_brand_q6.items()),
            "format_issues": " | ".join(fmt),
            "rating_language": "한국어 번역(공통 답변 5)",
            "analyst_observation": rv["observation"],
            "questions_for_researcher_A": questions,
            "translation_check": "Q3 후보 번역과 최종안 번역을 영어 원문과 대조함. 판단에 영향을 줄 의미 차이는 찾지 못함",
        }
        rows.append(row)
        # fill-in sheet: 3 element slots per item + one row for Q6 evidence
        k = ko[iid]
        common = {"item": iid, "brand": b, "selected_candidate": sel,
                  "selected_candidate_ko": k.get(f"후보 {sel}", ""),
                  "final_ko(평가 기준)": k.get("최종 아이디어", ""), "final_en(대조용)": r["final_idea"],
                  "A_original_Q3_candidate": q3_cand, "A_original_Q4": r[Q4], "A_original_Q5": r[Q5],
                  "A_original_Q6_brand": row["Q6_used_in_analysis"]}
        for n in (1, 2, 3):
            sheet.append({**common, "slot": f"element_{n}",
                          "element(요소 이름)": "", "evidence_quote_ko(최종안 문장 그대로)": "", "source_candidate(Cx)": "",
                          "absent_from_selected_candidate(예/아니오)": "", "Q4_for_this_element(main/auxiliary)": "",
                          "Q5_for_this_element(needed/develops/extra/unclear)": "", "comment": ""})
        sheet.append({**common, "slot": "Q6_evidence",
                      "element(요소 이름)": "(Q6 해당 브랜드 열에 1을 준 항목)", "evidence_quote_ko(최종안 문장 그대로)": "",
                      "source_candidate(Cx)": "", "absent_from_selected_candidate(예/아니오)": "",
                      "Q4_for_this_element(main/auxiliary)": "", "Q5_for_this_element(needed/develops/extra/unclear)": "",
                      "comment": ""})
        c = codes[hmap[iid]]["parsed"]
        analyst.append({"item": iid, "item_id": hmap[iid], "condition": hmap[iid].split("|")[3],
                        "A_Q1": r["Q1_main_code"], "LLM_Q1": c["final_main_code"],
                        "A_Q2": row["A_Q2_retained"], "LLM_Q2": c["selected_core_retained"],
                        "A_Q3_candidate": q3_cand,
                        "LLM_other_candidate_elements": " | ".join(f'{e["element"]} [{e["similar_in"]}, {e["role"]}, {e["function"]}]'
                                                                   for e in c["added_elements"] if e["similar_in"].lower() != "none"),
                        "A_Q4": r[Q4], "A_Q5": r[Q5],
                        "A_Q6_brand": row["Q6_used_in_analysis"],
                        "LLM_Q6_brand": ";".join(f'{k}={int(v["in_final"])}' for k, v in c["recurring"].items())})

    def write(path, data):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)

    write(ROOT / "human_coding_review.csv", rows)
    write(ROOT / "element_confirmation_sheet_A.csv", sheet)
    write(ROOT / "researcher_A_common_answers.csv",
          [{"no": a, "analyst_question": q, "answer_verbatim": t, "how_recorded": h, "recorded_on": "2026-11-25"}
           for a, q, t, h in COMMON_ANSWERS])
    write(ROOT / "_analyst_only_DO_NOT_SHOW_CODERS" / "link_llm_comparison.csv", analyst)
    print(len(rows), "review rows;", len(sheet), "sheet rows; transfer:", transfer)


if __name__ == "__main__":
    main()
