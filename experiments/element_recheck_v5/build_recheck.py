"""Element re-check review (2026-11-26). Read-only on all inputs.

Reads the researcher-A re-check tab exports ("element_confirmation_readable.xlsm - <n> <brand>.csv")
from the project root, compares the base text with the sheet we generated
(experiments/remaining_work_v5/element_confirmation_sheet_A.csv), and writes review_6_items.csv.
Claude-proposed quotes are asserted to be exact substrings of the source text.
No model calls.
"""
import csv
import glob
import hashlib
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
SHEET_A = os.path.join(ROOT, "experiments", "remaining_work_v5", "element_confirmation_sheet_A.csv")
PARTIAL = os.path.join(ROOT, "coding_researcher_A_partial.csv")

CASES = [  # sheet order of the 9 calibration items (from coding_researcher_A_partial.csv)
    (1, "K6e0d7b70", "Canva"), (2, "Kde2b84f2", "Mastercard"), (3, "Kd1fa6a9a", "Canva"),
    (4, "Kdc93a943", "Dior"), (5, "K35d9fc1b", "Mastercard"), (6, "K397eccb7", "Dior"),
    (7, "K46cb224f", "Mastercard"), (8, "K0b6dfe7c", "Mastercard"), (9, "K479c22c0", "Canva"),
]
BLOCKS = ["다른 후보 요소 1", "다른 후보 요소 2", "다른 후보 요소 3", "Q6 근거 확인"]
FIELDS = ["요소 이름", "최종안 근거 문장", "출처 후보 번호", "선택 후보에 없었나요?",
          "역할 · main/auxiliary", "기능 · needed/develops/extra/unclear", "메모"]


def parse_tab(path):
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    head = {}
    blocks = {b: {} for b in BLOCKS}
    cur = None
    for r in rows:
        if not r:
            continue
        key = r[0].strip()
        val = r[1] if len(r) > 1 else ""
        if key in BLOCKS:
            cur = key
            continue
        if cur and key in FIELDS:
            blocks[cur][key] = val
            continue
        if key in ("판단 기준", "작성 방법"):
            cur = None
        head[key] = val
    return head, blocks


def load_sheet_a():
    out = {}
    for r in csv.DictReader(open(SHEET_A, encoding="utf-8-sig")):
        out.setdefault(r["item"], r)
    return out


def must_in(quote, text, label):
    assert quote in text, f"quote not found in {label}: {quote[:40]}"
    return quote


# ---- hand review, case 6 (K397eccb7). Quotes are checked against the sheet text at run time. ----
def review_case6(head, blocks):
    final = head["최종안 · 한국어"]
    sel = head["후보 C2 (선택)"]
    c1, c3, c4 = head["후보 C1"], head["후보 C3"], head["후보 C4"]
    rows = []
    b1, q6 = blocks["다른 후보 요소 1"], blocks["Q6 근거 확인"]
    # block 1
    rows.append(dict(
        block="다른 후보 요소 1", origin="연구자 A 작성",
        check_source_is_nonselected="예 (C3는 선택되지 않은 후보)",
        check_A_text_where="'요소 이름' 칸의 문장은 최종안 문장 그대로다(앞 공백 1칸). 같은 내용이 선택 후보 C2에도 있다. '최종안 근거 문장' 칸에는 연구자의 해석(공개 수선 = 서명 활동)이 들어 있다. 두 칸이 서로 바뀐 형태다",
        check_element_in_source_candidate="연구자가 적은 문장(매장 아틀리에·프티트 맹의 공개 수선)은 C3에 없다. C3는 '수선 자국에 남기는 시그니처 스티치'를 다룬다",
        check_element_in_final="예 (연구자가 적은 문장 그대로)",
        check_in_selected_candidate="예. C2: '" + must_in("매장 바닥과 쇼윈도는 실제로 일하는 아틀리에가 되어, 프티트 맹(petites mains)이 고객의 Dior 옷을 공개적으로 수선한다", sel, "C2") + "'. 최종안에서 새로 붙은 부분은 '중고나 물려받은 옷을 포함한'뿐이다. 연구자도 '선택 후보에 없었나요?'에 FALSE(=선택 후보에 있었음)를 적었다",
        claude_candidate_quote="[Claude 제안] C3: '" + must_in("수선한 Dior 옷은 까나주(cannage) 무늬 짜깁기나 같은 색조의 실처럼 은은한 오트쿠튀르 수준의 시그니처 스티치로 복원되어", c3, "C3") + "'",
        claude_final_quote="[Claude 제안] 최종안: '" + must_in("고객은 보이지 않는 수선 대신 같은 색조의 까나주 짜깁기 같은 은은한 시그니처 수선을 고를 수 있고", final, "final") + "'",
        claude_selected_review="C2에는 시그니처 수선·까나주·표식에 해당하는 문장이 없다. 이 제안 문장이라면 '선택 후보에 없던 C3 요소'에 해당할 수 있다",
        function_same="제안 문장: 기능이 같다(수선 자리에 하우스의 은은한 시그니처를 남김). 최종안에서는 고객이 '고를 수 있는' 선택지로 들어갔다",
        sheet_rule_conflict="출처 C3와 FALSE(선택 후보에 있었음)를 함께 적었다. 시트 규칙('선택 후보에 이미 있으면 새 유입으로 세지 않음')대로라면 연구자가 적은 문장은 유입으로 세지 않는다",
        initial_vs_recheck="최초: Q4 main, Q5 develops / 재확인: auxiliary, develops. 역할 값이 바뀌었다(두 값 모두 보존)",
        needs_confirmation="확인 필요",
        question="Q-6a, Q-6b",
    ))
    # Q6 block
    rows.append(dict(
        block="Q6 근거 확인", origin="연구자 A 작성",
        check_source_is_nonselected="해당 없음 (연구자가 C2 = 선택 후보를 적음)",
        check_A_text_where="근거 문장은 최종안 문장 그대로다(앞 공백 1칸). 블록 1의 '요소 이름'과 같은 문장이다",
        check_element_in_source_candidate="C2에 같은 내용(공개 수선)이 있다",
        check_element_in_final="공개 수선 문장은 최종안에 있다",
        check_in_selected_candidate="공개 수선: 예. 단, 현재 MARK 정의('수선한 옷에 장인이나 하우스가 더하는 표식, 서명, 이니셜, 날짜, 라벨, 별, 서명 카드')에 맞는 문장은 C2에 없다",
        claude_candidate_quote="[Claude 제안] MARK 정의에 맞을 수 있는 후보 문장은 C3에만 있다: '" + must_in("은은한 오트쿠튀르 수준의 시그니처 스티치로 복원되어", c3, "C3") + "'",
        claude_final_quote="[Claude 제안] 최종안: '" + must_in("같은 색조의 까나주 짜깁기 같은 은은한 시그니처 수선을 고를 수 있고", final, "final") + "'",
        claude_selected_review="연구자가 든 문장(공개 수선)은 옷에 더하는 표식이 아니라 수선 활동이다. 기존 정의로는 MARK 근거로 보기 어렵다. 제안 문장으로 보면 MARK=1은 유지될 수 있다. 다만 근거가 '선택 후보에 있던 요소'가 아니라 'C3에서 온 요소'로 바뀐다",
        function_same="정의 적용 문제(유사 표현 문제 아님)",
        sheet_rule_conflict="Q6 블록에도 역할 main·기능 needed가 적혀 있다. Q6은 존재 여부만 보는 문항이라 이 두 값은 분석에 쓰지 않는다(보존만 한다)",
        initial_vs_recheck="최초 Q6 MARK=1, 재확인에서도 MARK 근거를 적음. 0/1 값 자체는 바뀌지 않음",
        needs_confirmation="확인 필요",
        question="Q-6c",
    ))
    # Claude-only observations (not researcher input)
    rows.append(dict(
        block="(연구자 미기재) 참고 1", origin="Claude 관찰 — 연구자 판단 아님",
        check_source_is_nonselected="C4는 선택되지 않은 후보",
        check_A_text_where="연구자는 이 요소를 적지 않았다. 빈칸을 '유입 없음'으로 해석하지 않는다",
        check_element_in_source_candidate="C4: '" + must_in("각 옷의 이야기가 함께 소개된다", c4, "C4") + "'",
        check_element_in_final="최종안: '" + must_in("그들의 이야기는 짧은 인물 소개로 공유된다", final, "final") + "'",
        check_in_selected_candidate="C2에 고객 이야기 공유는 없다",
        claude_candidate_quote="[Claude 제안] 위 C4 문장", claude_final_quote="[Claude 제안] 위 최종안 문장",
        claude_selected_review="선택 후보에 없음",
        function_same="비슷하다(고객 옷의 이야기를 알림). 다만 C4에서는 런웨이 쇼의 일부이고, 최종안에서는 수선 고객 소개다. 기능이 같은지는 판단이 갈릴 수 있다",
        sheet_rule_conflict="", initial_vs_recheck="최초·재확인 모두 기재 없음",
        needs_confirmation="확인 필요", question="Q-6d",
    ))
    rows.append(dict(
        block="(연구자 미기재) 참고 2", origin="Claude 관찰 — 연구자 판단 아님",
        check_source_is_nonselected="C1은 선택되지 않은 후보",
        check_A_text_where="연구자는 이 요소를 적지 않았다",
        check_element_in_source_candidate="C1: '" + must_in("평생 수선 약속", c1, "C1") + "'",
        check_element_in_final="최종안: '" + must_in("이날은 상설 Dior 수선 서비스의 공개적인 얼굴이므로, 돌봄은 1년 내내 이어진다", final, "final") + "'",
        check_in_selected_candidate="C2에 상설 서비스는 없다(1년에 하루 행사)",
        claude_candidate_quote="[Claude 제안] 위 C1 문장", claude_final_quote="[Claude 제안] 위 최종안 문장",
        claude_selected_review="선택 후보에 없음",
        function_same="약하다. C1은 옷 설계에 붙은 개인 약속이고, 최종안은 하루 행사를 상시 서비스로 잇는 장치다. 선택 발상 자체에서 나온 확장일 수 있다",
        sheet_rule_conflict="", initial_vs_recheck="최초·재확인 모두 기재 없음",
        needs_confirmation="질문하지 않음(판단이 바뀔 가능성 낮음). 연구자가 원하면 검토",
        question="",
    ))
    return rows


# ---- researcher A answers, 2026-11-26 (verbatim) and analysis treatment. Original values are never changed. ----
ANSWER_FALSE_ALL = ("'선택 후보에 없었나요?'에 전부 False라고 답했는데 이건 없지 않았다(있었다)는 의미에서 넣은 거임")
ANSWERS = {
    "Q-6a": ("공개 수선",
             "연구자가 C3 출처로 본 요소는 선택 후보 C2에 있던 공개 수선이다(재해석). 기존 가이드 사례 4"
             "('선택 후보 원문에 이미 있던 요소는 Q3에 넣지 않는다')와 충돌한다. 원래 값 Q3=C3는 보존하고, "
             "분석에는 '정의 결정 대기'로 표시한다. 시그니처 수선 문장은 연구자가 고른 근거가 아니므로 연구자 판단으로 기록하지 않는다"),
    "Q-6b": ("원본 값을 더 중요하게 봐줘",
             "이 요소의 1차 값은 최초 값(main, develops)으로 쓴다. 재확인 값(auxiliary, develops)은 보조 열로 보존한다"),
    "Q-6c": ("디자이너가 공개적으로 수선하는 것이 사실상 제품에 서명이 들어간 것과 같음",
             "MARK=1의 연구자 근거는 정의 확장(공개 수선 행위 = 서명)이다. 0/1 값은 보존한다. 현재 정의로는 최종안의 "
             "시그니처 수선 문장이 MARK에 해당할 수 있어(Claude 제안, 연구자 미확인) 값은 같다. 근거는 다르다. "
             "최종안 원문에서 수선하는 사람은 '프티트 맹'이며 '디자이너'라는 말은 없다"),
    "Q-6d": ("못 본거 같아",
             "연구자 미검토. '유입 없음'으로 기록하지 않는다. 연구자 판단 값은 비워 둔다"),
}


# ---- chat answers for the other 8 cases, 2026-11-26 (verbatim). Original values come from coding_researcher_A_partial.csv. ----
# fields: (case, item, question, answer_verbatim, field, original, recheck_after_question, evidence_source, treatment, guide_issue)
REINTERP = "재해석 연결(선택 후보에 있던 장치를 다른 후보 기능으로 읽음)"
CASE_ANSWERS = [
    (1, "K6e0d7b70", "1-1", "(나)", "Q3 출처", "C3", "C3 (재해석)", "연구자",
     "'팀 서명판'은 선택 후보 C1의 '팀도 보내 줄 수 있다'를 C3 기능으로 읽은 것. 새 유입이 아니라 재해석 연결로 분류", REINTERP),
    (2, "Kde2b84f2", "2-1", "전체적으로 결제 시스템을 이용해 만남을 주선한다는 뉘양스가 있음", "Q3 출처", "C4", "C4 (특정 문장 없음)", "연구자",
     "특정 최종안 문장에 연결되지 않는 전체 뉘앙스 유사. 요소 단위 분석에서는 '요소 미특정'으로 둔다", "요소 미특정(전체·주제 수준 유사)"),
    (3, "Kd1fa6a9a", "3-1", "A", "Q1", "C", "A", "연구자",
     "원래 값 C 보존, 재검토 값 A. 코드 문자와 후보 번호 혼동 가능성을 지지", "코드·후보 번호 혼동"),
    (3, "Kd1fa6a9a", "3-2", "맞음", "Q3 요소", "(요소명 없음, 출처 C1)", "환영 메모와 팀 응원 메시지 = C1", "Claude 제안 → 연구자 확인",
     "요소 특정됨. 선택 후보 C2에 없음", ""),
    (3, "Kd1fa6a9a", "3-3", "축하 메시지 등이 기념용 문장으로 해석됨", "Q6 KEEPSAKE", "1", "1 (근거: 환영 메모·팀 응원 메시지)", "연구자",
     "값 보존. KEEPSAKE 정의('액자·인쇄·공유용 기념물·카드')를 축하 메시지까지 넓혀 읽은 것. 같은 문장은 EMPLOYER_KIT에도 해당", "Q6 정의 경계(KEEPSAKE)"),
    (4, "Kdc93a943", "4-1", "같은 판단", "Q3 출처·Q6 MARK", "C3 / MARK=1", "C3 (재해석) / MARK=1 (공개 수선 = 서명)", "연구자",
     "사례 6과 같은 방식으로 기록. 현재 MARK 정의에 맞는 문장은 이 최종안에 없음", REINTERP + "; Q6 정의 경계(MARK_ACT)"),
    (5, "K35d9fc1b", "5-1", "결제 후 서비스를 이용하는 행위, 사람을 만나는 행위 등은 '자리'를 전제로 함", "Q3 출처", "C2", "C2 (특정 문장 없음)", "연구자",
     "글에 쓰인 요소가 아니라 전제에서 추론한 연결. 가이드 원칙('보이는 글에서만')과 맞지 않을 수 있어 '요소 미특정'으로 둔다", "요소 미특정(글에 없는 전제)"),
    (5, "K35d9fc1b", "5-2", "단순히 C2의 요소 뿐 아니라 C4와 강한 결합을 통해 최종안이 나온 것으로 판단함", "Q2", "partial", "partial", "연구자",
     "값 보존. partial 이유 = 다른 후보 요소와의 결합(5-1의 판단에 의존)", ""),
    (7, "K46cb224f", "7-1", "C 같음", "Q1", "H", "C", "연구자", "원래 값 H 보존, 재검토 값 C", "코드 선택 오류"),
    (7, "K46cb224f", "7-2", "맞음", "Q3 요소", "(요소명 없음, 출처 C1)", "제휴 카페와 식당이 만남을 맡음 = C1", "Claude 제안 → 연구자 확인",
     "요소 특정됨. needed의 이유는 답하지 않았음(추론하지 않음)", ""),
    (7, "K46cb224f", "7-3", "너 말이 맞음", "Q6 PAID_INVITATION", "1", "0 (선불 초대 문장 없음에 동의)", "Claude 지적 → 연구자 동의",
     "원래 값 1 보존. 재검토 값 0은 연구자가 '선불 초대 문장이 없다'에 동의한 데서 나온 것", "Q6 근거 없는 1"),
    (8, "K0b6dfe7c", "8-1,2", "너 말이 맞음 - 한적한 시간대를 찾는 것이 해당 아이디어의 핵심으로 보임", "Q3 요소·Q4·Q5", "C4 / main / needed",
     "한적한 시간대에 열림 = C4 / main / needed", "Claude 제안 → 연구자 확인", "요소 특정됨. main·needed 이유: 이 아이디어의 핵심", ""),
    (9, "K479c22c0", "9-1", "네", "Q1", "C", "A", "연구자 (3-1과 같은 답)", "원래 값 C 보존, 재검토 값 A", "코드·후보 번호 혼동"),
    (9, "K479c22c0", "9-2", "(가)", "Q3 출처", "C1", "C1 (재해석)", "연구자",
     "'고용주·급여 팀이 Canva for Teams 템플릿으로 도입'은 선택 후보 C3에도 있음. 재해석 연결로 분류", REINTERP),
    (9, "K479c22c0", "9-3", "검토 후 제외", "Q3 (도와준 사람에게 보냄)", "(기재 없음)", "검토 후 제외", "연구자", "연구자가 검토하고 제외한 요소로 기록", ""),
]


def apply_answers(row):
    qs = [q.strip() for q in row.get("question", "").split(",") if q.strip()]
    if qs:
        row["A_answer_2026_11_26"] = " / ".join(f"{q}: {ANSWERS[q][0]}" for q in qs if q in ANSWERS)
        row["treatment_after_answer"] = " / ".join(ANSWERS[q][1] for q in qs if q in ANSWERS)
        row["needs_confirmation"] = "답변 받음 — 정의 결정은 두 연구자" if any(q in ("Q-6a", "Q-6c") for q in qs) else "답변 받음"
    if row.get("A_선택 후보에 없었나요?", "").strip().upper() == "FALSE":
        row["A_absent_reading"] = "FALSE = 선택 후보에 있었음 (연구자 답변, 2026-11-26)"
    return row


def main():
    sheet_a = load_sheet_a()
    partial = {r["item"]: r for r in csv.DictReader(open(PARTIAL, encoding="utf-8-sig"))}
    tabs = sorted(glob.glob(os.path.join(ROOT, "element_confirmation_readable.xlsm - *.csv")))
    by_pos = {}
    for t in tabs:
        pos = int(os.path.basename(t).split(" - ")[1].split()[0])
        by_pos[pos] = t
    out = []
    status_lines = []
    for pos, item, brand in CASES:
        base = dict(case=pos, item=item, brand=brand)
        if pos not in by_pos:
            base.update(sheet_status="입력 파일 없음 — 작성 여부 확인 불가 (해당 탭이 프로젝트에 없음)")
            out.append(base)
            status_lines.append(f"{pos} {item}: no tab file")
            continue
        path = by_pos[pos]
        head, blocks = parse_tab(path)
        title = head.get("사례 %d / 9" % pos, "")
        assert item in title, (item, title)
        ref = sheet_a[item]
        base_ok = (head["최종안 · 한국어"] == ref["final_ko(평가 기준)"]
                   and head["선택한 후보"] == ref["selected_candidate_ko"]
                   and head["영어 원문 대조"] == ref["final_en(대조용)"])
        p = partial[item]
        written = any(v.strip() for b in blocks.values() for v in b.values())
        base.update(
            sheet_status="작성함" if written else "미작성",
            base_text_identical_to_generated_sheet="예" if base_ok else "아니오 — 확인 필요",
            sha256_tab=hashlib.sha256(open(path, "rb").read()).hexdigest()[:12],
            initial_ref_shown_in_sheet=head.get("기존 판단 (참고)", ""),
            initial_Q3_candidate="C3" if p["Q3_added_elements_from_other_candidates(element=Cx; ...)"].startswith("C3.") else "확인 필요",
            initial_Q4=p["Q4_role_main_or_auxiliary_per_element"], initial_Q5=p["Q5_function_needed_develops_extra_unclear_per_element"],
            initial_Q6_MARK=p["Q6_MARK_in_final_0_1"],
        )
        status_lines.append(f"{pos} {item}: {'written' if written else 'blank'}; base identical={base_ok}")
        reviews = review_case6(head, blocks) if item == "K397eccb7" else []
        for b in BLOCKS:
            vals = blocks[b]
            rv = next((r for r in reviews if r["block"] == b), None)
            if not any(v.strip() for v in vals.values()) and rv is None:
                row = dict(base, block=b, origin="빈칸", needs_confirmation="빈칸(값 없음으로 해석하지 않음)")
                out.append(row)
                continue
            row = dict(base)
            row.update({"A_" + k: v for k, v in vals.items()})
            row.update(rv or {"block": b})
            out.append(row)
        for r in reviews:
            if r["block"].startswith("(연구자 미기재)"):
                out.append(dict(base, **r))
    cols = ["case", "item", "brand", "sheet_status", "base_text_identical_to_generated_sheet", "sha256_tab",
            "initial_ref_shown_in_sheet", "initial_Q3_candidate", "initial_Q4", "initial_Q5", "initial_Q6_MARK",
            "block", "origin"] + ["A_" + f for f in FIELDS] + [
            "check_source_is_nonselected", "check_A_text_where", "check_element_in_source_candidate",
            "check_element_in_final", "check_in_selected_candidate", "claude_candidate_quote", "claude_final_quote",
            "claude_selected_review", "function_same", "sheet_rule_conflict", "initial_vs_recheck",
            "needs_confirmation", "question", "A_absent_reading", "A_answer_2026_11_26", "treatment_after_answer"]
    out = [apply_answers(r) for r in out]
    with open(os.path.join(HERE, "review_6_items.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="raise")
        w.writeheader()
        for r in out:
            w.writerow(r)
    with open(os.path.join(HERE, "researcher_A_answers_2026-11-26.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question", "item", "answer_verbatim", "treatment"])
        for q, (a, t) in ANSWERS.items():
            w.writerow([q, "K397eccb7", a, t])
        w.writerow(["공통 7", "재확인 시트 전체", ANSWER_FALSE_ALL,
                    "모든 재확인 탭의 FALSE를 '선택 후보에 있었음'으로 읽는다. v1.1에서 질문을 긍정형('선택 후보에도 있었나요?')으로 바꾼다"])
    with open(os.path.join(HERE, "researcher_A_answers_by_case.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "item", "question", "answer_verbatim", "field", "original_value(보존)",
                    "recheck_value_after_question(질문 후 재검토 값)", "evidence_source", "treatment", "guide_issue"])
        w.writerows(CASE_ANSWERS)
    print("\n".join(status_lines))
    print("rows", len(out))


if __name__ == "__main__":
    main()
