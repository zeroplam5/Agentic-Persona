# 자료 검증: 프로젝트 가정과 실제 자료 비교 (2026-11-12)

상태 표기: **확인**(원문에서 직접 확인) / **불일치·보완**(가정과 다르거나 추가 정보) / **미확인**(접근하지 못함)

## 1. Creativity Benchmark (Bhat, Browne, Bingemann; arXiv:2509.09702v2, 2025-10-19) — 첨부 PDF

| 항목 | 프로젝트 문서의 가정 | 실제 자료 | 상태 |
|---|---|---|---|
| 과제 문구 | 낯설고 화제성 있으면서 브랜드에 맞는 아이디어, 50단어 미만 한 문장 | A.1.2 WILD IDEAS: "What is your wildest unconventional campaign idea for [BRAND], something no traditional agency would dare present, but that could hijack culture, spark headlines, and get people talking. Keep it under 50 words. Make it strange, fresh, or provocative but still creatively smart and on-brand. Avoid generic stunts or randomness. Surprise me in a good way." "한 문장"은 사용자 프롬프트가 아니라 **시스템 프롬프트**의 규칙("Respond in a single, concise sentence")이다. | 확인 |
| 시스템 프롬프트 | 대담함·창의성 지시가 들어 있음 | A.1.1 하나를 Insights·Ideas·Wild Ideas **세 과제 모두**에 쓴다. "world-class brand strategist", "surprising, and never cliché", "wild ideas are provocative but strategically grounded" 등과 서식 규칙 5개가 들어 있다. | 확인 |
| 브랜드 | Appendix A.2 확인 필요 | 12개 범주, 브랜드 100개(Table A1 51개, A2 49개). `config.json`에 전사했다. | 확인 |
| 생성 설정 | (언급 없음) | T = 1.0, 나머지는 공급자 기본값(§4.1). 다양성 분석은 프롬프트당 10회 생성(§6.2.1). | 보완 |
| 다양성 측정 | 집합 수준 측정 | BAAI/bge-large-en-v1.5 임베딩의 평균 쌍별 코사인 거리(§6.2.2–6.2.3). 모델 간 거리와 Ideas↔Wild Ideas 프롬프트 재구성 거리도 있다. | 보완 |
| 인간 평가 | 기존 응답 쌍에 대한 선호 | 실무자 678명, 익명 쌍 비교 11,012건. 선택지는 X / Y / 너무 비슷함(무승부) / 모르겠음(건너뛰기). Bradley-Terry로 분석했다. 개별 아이디어의 새로움·유용성 점수는 **없다**. | 확인 |
| 인간 레이블 공개 | 접근 여부 검증 필요 | 논문 본문에 데이터·코드 공개 문구가 없다. arXiv의 "Code, Data and Media" 항목이 비어 있고, creativitybenchmark.ai와 Springboards 보도자료에도 다운로드 링크나 요청 절차가 없다(2026-11-12 확인). 사이트 FAQ 답변 본문은 렌더링되지 않아 읽지 못했다. | **공개되지 않음(현재 확인 범위)** |
| LLM 평가자 | (언급 없음) | Part C: 세 가지 LLM-as-judge 설정과 인간 순위의 상관이 약하고 일관되지 않으며, 평가자별 편향이 있다고 보고했다. → 이번 파일럿의 LLM 점수는 사람 평가를 대신하지 못한다. | 보완 |
| 범위 | 최종 산출물 평가 | 모델 산출물에 대한 선호 평가이며, 에이전트 과정은 평가하지 않는다. | 확인 |

참고: 인터페이스 설명(§5.2.2)은 "Platform Idea"라고 쓰지만 프롬프트 표기는 "IDEAS"이다(같은 과제로 보인다).

## 2. 성격 프롬프트 선행연구

### 2.1 Kao & Volkova, *Evaluating LLM Alignment under Big Five Personality Prompting* (CEUR-WS Vol-4178 paper6, CC BY 4.0) — 첨부 PDF

- 원문(§3): `"You have [High/Low] [Extraversion/Agreeableness/Conscientiousness/Neuroticism/Openness to Experience]."` — **확인**
- 한 번에 한 특성만 지정하고 나머지는 언급하지 않는다(= 미지정).
- 사용 범위: IPIP 50문항 설문 응답에만 썼고, 창의 과제에는 쓰지 않았다. 따라서 이 문구를 Wild Ideas에 쓰는 것은 우리의 **변형**이다.
- 결과 요약: Low 조건에서 일부 모델(Claude 3 Haiku 포함)은 특정 문항을 의도대로 표현하지 못했다.

### 2.2 Boone et al., *Does Personality Persuade?* (arXiv:2611.06572v1, 2026-11-04) — 첨부 PDF

- 형식: CAT(각 특성 Low/Average/High)와 NUM(20/50/80), 5특성 전체를 지정하는 완전 요인설계(243 프로필). 설문 프롬프트 템플릿은 `Your big 5 personality profile is: {profile}`이고, 사용자 연구용 확장은 `Big five profile: {big_5_profile}`이다. **`{profile}`을 실제로 어떤 문자열로 채웠는지는 본문에 없다** → 원문 문구 **미확인**.
- 우리 설계와 직접 관련된 결과:
  - 특성을 빼면(NUM-None/CAT-None) 프로필 표준편차가 3.8–7.0에서 7.7–13.5로 커졌다. 빠진 특성이 다른 특성과 함께 표류한다. 저자들은 이 형식을 제외했다. → **"나머지 미지정" 선택에 불리한 근거**이다.
  - 성격 미지정(base) 모델도 중립이 아니다(성실성·친화성 높음). "모두 Average" 지시도 친화성·성실성을 50 아래로 내리지 못한다. → 프로젝트 문서의 "보통 지정 ≠ 성격 미지정" 가정과 **일치**한다.
  - 한 특성을 바꾸면 다른 특성도 움직인다(예: 성실성↑ → 신경성↓ 평균 13.2점).
- 모델은 오픈웨이트 모델이고, 결과는 설문 기준이다. 창의 과제가 아니다.

### 2.3 *The Power of Personality* (arXiv:2502.20859) — 첨부되지 않음

- 검색 요약으로만 확인했다: Big Five 특성을 프롬프트로 부여하고 닫힌 과제와 열린(창의) 과제, 다중 에이전트에서 비교했다. v1과 v2의 기술이 다르다. 정확한 프롬프트, 창의성 채점 방식, 효과 크기는 **미확인**이다(본문 미열람).

## 3. 첨부 자료 관련 주의

- `CreativityBench_ ... Affordance-Based Tool Repurposing.pdf`(arXiv:2605.02910)은 이름이 비슷하지만 **다른 벤치마크**(도구 용도 전환 추론)이다. Wild Ideas의 출처가 아니다.
- `designing-ai-agents-with-personalities-a-psychometric-approach.pdf`와 `huang-et-al-2026-...pdf`는 텍스트가 동일한 **중복 파일**이다(Huang et al., *Personality Science* 2026, CC BY-NC). BFI-2 기반 Likert·Expanded 형식 프롬프트는 본 실험의 대안 후보이다.
- CognitionLight 논문은 프로젝트 문서대로 성격 프롬프트의 출처가 아니다. 이번 실험에는 쓰지 않았다.

## 4. 이번 파일럿에서 고정한 것과 미결로 남긴 것

- 고정(사전등록): CEUR 문구 원문, 나머지 특성 미지정, BASE = 원 시스템 프롬프트, 주 종합점수 = 산술평균(조화평균은 보조).
- 미결(사용자 결정 필요): 본 실험에서 나머지 특성을 Average로 명시할지(Boone et al. 근거), 본 실험의 종합 공식, 일반 창의 지시 대조 조건 포함 여부.
