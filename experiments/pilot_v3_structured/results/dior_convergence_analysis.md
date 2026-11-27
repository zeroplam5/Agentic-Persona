# Dior 단계별 수렴 분석 (파일럿 v3, 기존 기록만 사용)

작성 2026-11-19. 새 호출 없이 기존 기록만 읽었다. 보조 스크립트: [../analysis_dior_stages.py](../analysis_dior_stages.py) → [dior_stage_features.csv](dior_stage_features.csv)

> **⚠ 사람 평가 블라인드 주의.** `human_rating_blind_v3_structured/`의 평가 시트(평가자 A·B), 묶음 확인표, 사전 아이디어 시트가 **모두 비어 있다**(2026-11-19 확인). 이 문서는 조건별 Dior 최종안을 그대로 보여준다. 평가자라면 평가와 사전 아이디어 작성을 마친 뒤에 읽어야 한다. `_key_DO_NOT_OPEN_until_rating_done/`은 열지 않았다.

**연구 질문(전환):** 같은 과제에서 생성된 아이디어는 어느 단계부터 비슷한 방향으로 모이는가? 에이전트의 어느 단계에 개입하면 개연성을 유지하면서 다른 관점을 탐색할 수 있는가?

**용어.** 이 문서에서 "작업 기록"은 모델이 응답 JSON으로 **보고한** 과제 이해·후보·선택·수정·최종안이다. 숨겨진 내부 추론이 아니며, 실제로 그 순서대로 생각했다는 증거도 아니다(DESIGN.md §1.2). "선택 이유"는 모델이 제시한 이유일 뿐 입증된 원인이 아니다.

---

## 1. 분석 대상과 출처

### 1.1 사용한 자료 (파일럿 v3 구조화 실험만)

| 항목 | 내용 | 출처 |
|---|---|---|
| 브랜드·주제 | Dior (Fashion, Apparel & Footwear) × "repair and reuse". **주제는 Claude가 정한 임시값** | `logs/brands.json`, `config.json` `provisional_topics_note` |
| 시스템 프롬프트 | Creativity Benchmark 역할 문단("bold", "surprising, never cliché", "provocative" 포함) + 조건별 성격 문단 | `prompts/common_system.txt`, `logs/condition_prompts.json` |
| 과제 지시 | 구조화: 과제 이해 → 후보 정확히 4개("core ideas differ from each other") → 선택·제외 이유 → 선택 후 수정 → 최종안(150단어 이하)+질문 3개. NODEDUP: 후보 1개 + 최종안, 선택·수정 없음 | `prompts/task_structured_user.txt`, `prompts/task_single_user.txt` |
| 생성 모델 | claude-sonnet-5-5, CLI 2.1.141, effort high. 구조화: thinking 상한 8000 / 출력 16000. NODEDUP: 호출당 2000 / 4000. 온도 설정 불가 | `config.json`, 각 기록 `request_params` |
| 조건·반복 | 구조화 7조건(BASE, SB_AVG, SB_O_H, SB_O_L, LK_AVG, LK_O_H, LK_O_L) × 4회 = 28 실행. NODEDUP 4실행 × 독립 호출 4 = 16 호출. 합계 44 기록, 모두 `ok=True` (NODEDUP 2건은 형식 재시도 1회) | `data/generations.jsonl` (`gen_id`가 `Dior|…`) |
| 묶음 결과 | gpt-6-astra 증분 묶음. 후보 집합 128개 → 15묶음, 최종 집합 32개 → 6묶음 (최대 묶음 18/32) | `data/buckets.jsonl`, `results/bucket_summary.md` |
| 기존 평가 | LLM 개연성 B/F/L(gpt-6-astra, 사람 보정 전 v0 루브릭), 집합 내 드묾 D | `data/judgments.jsonl`, `results/idea_level.csv` |
| 임베딩 | bge-large-en-v1.5 (후보 검색용) | `data/embeddings.json` |

- `data/generations.zip`(미추적 파일)은 `data/` 안의 jsonl 6개·embeddings와 **바이트 단위로 같다**(cmp 확인). 같은 자료의 압축본이다.

### 1.2 섞지 않은 자료

| 자료 | 제외 이유 |
|---|---|
| `experiments/pilot_v1`, `pilot_v2` | Wild Ideas 파일럿. 지시문·출력 형식이 다르고 Dior는 config의 브랜드 표에만 있다(Dior 과제 실행 없음). |
| `AgenticPersona_추론요약_공유용_20261115/recollection/openai_generations.jsonl` | 2026-11-15 OpenAI 재수집 패키지. "Dior"는 IKEA·Klarna·Unesco·Roblox 응답 본문에 7회 나오는 단어일 뿐 Dior 과제가 아니다. |
| Canva, Mastercard (v3) | 요청 범위 밖. |

---

## 2. 단계별 기록 존재 여부

| 단계 | 구조화 28실행 | NODEDUP 16호출 | 해당 필드 | 비고 |
|---|---|---|---|---|
| 과제 이해(문제·전제) | ✅ 28/28 | ✅ 16/16 | `task_understanding.focus`, `.assumptions[]` | 문제 관점과 기회가 한 문단(`focus`)에 섞여 있다. 문제 관점만 따로 적은 필드는 없다. |
| 후보 생성 | ✅ 4개 × 28 | ✅ 1개 × 16 | `candidates[]` / `candidate` | 모델이 **목록에 적은** 후보만 있다. 적지 않고 버린 후보, 생성 순서는 기록되지 않는다. |
| 후보 검토(장점·우려) | ✅ | ✅ (후보 1개) | `expected_strengths`, `main_concerns` | |
| 선택·제외 이유 | ✅ 28/28 | ❌ 없음 (설계상) | `selection` | NODEDUP 최종안은 시드 기반 무작위 선택. |
| 선택 후 수정 | ✅ 28/28 (각 4–5개, 빈 목록 0) | ❌ 없음 (설계상) | `revisions_after_selection` | 수정 **전** 최종안 문안은 없다. 비교 기준은 선택된 후보의 `core_idea`뿐이다. |
| 최종안 | ✅ 28/28 | ✅ 16/16 (실행당 1개 채택) | `final_proposal` | |
| 숨겨진 추론 | ❌ | ❌ | `reasoning` | thinking 블록 내용이 비어 있다(서명만). 블록 수와 토큰 수만 있다. 복원하지 않았다. |
| 묶음 분류 | 후보·최종안만 | 후보·최종안만 | `buckets.jsonl` | 과제 이해·수정 단계는 묶음 분류된 적이 없다. 순서 시드 1개. |
| 사람 평가 | ❌ 비어 있음 | ❌ | `human_rating_blind_v3_structured/` | S, 묶음 동의 Y/N, 사전 아이디어 모두 미기입. |

**범위:** 아래 분석은 브랜드 1개 · 주제 1개 · 조건당 4회다. 단계 사이의 관계는 **한 번의 응답 안에서 모델이 보고한 순서**를 비교한 것이다.

---

## 3. 단계별 분석

분류 방식: 묶음 결과와 코사인은 후보를 찾는 데만 썼다. 각 범주 배정은 44개 기록의 원문(`focus`, 후보 `core_idea`, 선택·제외 이유, 수정, 최종안)을 읽고 정했다. 세 층을 나눠 본다.

- **문제 관점**: 무엇을 풀어야 할 문제로 보는가
- **핵심 발상**: 어떤 방향·메커니즘을 제안하는가
- **실행 절차**: 그 발상을 어떻게 실행하는가

### 3.1 과제 이해: 문제 관점은 처음부터 거의 같다

`focus`(44개)를 읽으면 **28/28 구조화, 16/16 NODEDUP**이 같은 뼈대를 쓴다: "수선은 숨겨진 사후 서비스이거나 죄책감 섞인 지속가능성 각주다 → 수선·재사용을 욕망·지위의 대상으로 바꾼다 → 근거는 아틀리에 장인 기술".

| 문제 관점(주) | 구조화 28 | NODEDUP 16 | 대표 근거 |
|---|---|---|---|
| P1. 수선이 숨겨져 있거나 낙인·죄책감 → 지위 신호로 전환 | 28 (모두 포함) | 16 (모두 포함) | `Dior|BASE|1`: "Luxury fashion treats repair and reuse as a back-of-house service, or as a sustainability footnote…" |
| P2. 소유자가 아끼느라 입지 않거나 손대지 못함 | **주 관점 2**, 전제로 언급 다수 | 전제로만 | `Dior|SB_O_H|3`: "many are bought to be kept safe rather than lived in. They sit in dust bags…"; `Dior|SB_O_L|1`: "luxury owners love their pieces so much that they keep them untouched" |
| P3. 재판매 플랫폼이 두 번째 생애를 가져감 | 부가 관점 수 건 | 부가 관점 수 건 | `Dior|SB_O_L|2`: "dominated by resale platforms … which treat a Dior piece as a commodity" |
| P4. 럭셔리 지속가능성 서사가 소재·공약에 쏠림 | 부가 2 | **9/16** | `Dior|NODEDUP|1|k1`: "dominated by new materials and recycled fabrics, while the most radical sustainable act, keeping a garment alive…" |
| P5. 쿠튀르는 원래 고쳐 입도록 지어짐(구조·피팅) | BASE 2건에서 두드러짐 | 일부 | `Dior|BASE|0`: "couture garments are built to be refitted, altered, repaired and passed on" |

- 키워드 보조 집계(focus): "status/desirable/highest form" 44/44, "guilt/apology/concession/footnote" 36/44.
- 전제(assumptions)도 거의 공통이다: 그린워싱 회의, 아틀리에·petites mains, Bar jacket·Lady Dior·Saddle, 젊은 재판매·빈티지 소비자, 독점성 보호.
- **해석 범위:** 문제 관점은 첫 단계에서 이미 수렴해 있다. 다만 P2처럼 다른 관점을 주 관점으로 쓴 실행은 뒤 단계에서도 다른 최종안 범주로 이어졌다(§3.5).

### 3.2 후보 생성: 실행 안에서는 다르지만, 실행 사이에서는 같은 "메뉴"가 반복된다

구조화 28실행 모두 후보 4개가 서로 다른 묶음 4개에 배정됐다(`results/idea_level.csv` `cand_distinct_buckets` = 4). 지시대로 **실행 안에서는** 서로 다르다. 그러나 실행 사이에서는 거의 같은 후보 목록이 되풀이된다.

**후보 범주 (128개, 원문 확인 후 묶음을 합쳐 정리)**

| 범주(핵심 발상) | 후보 묶음 ID | 후보 수 | 포함 실행(구조화) | 선택 | 제외 |
|---|---|---|---|---|---|
| A. 장인이 서명한/보이는 수선 표식을 지위 신호로 | c3 | 43 (구조화 27 + NODEDUP 16) | **27/28** | 19 | 8 |
| B. 이력 기록·여권·인증 재판매 | c1, c12 | 24 | 24 | **0** | 24 |
| C. 누구의 옷이든 공개 수선·수선 교육·공개 아틀리에·휴점 | c0, c2, c5, c6 | 16 | — | 1 (`SB_AVG|3` 휴점) | 15 |
| D. 아카이브·잔여물·고객 옷으로 새 컬렉션/런웨이 | c7, c13, c14 | 22 | — | 2 | 20 |
| E. 고쳐 입도록 설계(여유 시접·평생 개조 약속) | c10, c11 | 9 | — | 2 | 7 |
| F. 상속·다음 착용자에게 재피팅 | c4 | 7 | — | 1 | 6 |
| G. 아끼지 말고 입어라(착용 허락) | c9 | 4 | — | 2 | 2 |
| H. 옷장 진단·상담 | c8 | 3 | — | 1 | 2 |

- 범주 배정은 묶음 ID를 따랐다. 단, `LK_O_L|0`의 C1 "The Second Fitting"은 분류기가 c10(E)에 넣었지만 원문상 F(피팅 의식)에 가깝다. 그래서 §3.5에서는 F로 셌다.
- 범주 A 후보의 위치: **C1이 23/27**, C2 3, C3 1. 모델이 가장 먼저 적는 후보가 거의 항상 A다.
- NODEDUP(서로 보지 못하는 독립 호출, "서로 달라야 한다" 지시 없음): **16/16이 A**(묶음 c3). 후보 제목은 "The Second Signature" 5회(부제 포함 6회), "Second Fitting" 5회이고, 나머지도 본문 장치는 서명 표식이다(`Dior|NODEDUP|*`).
- `LK_O_H` 4실행은 후보 목록 구조가 거의 같다: C1 = A(서명 표식), C2 = B(이력 여권), C3 = C(누구의 옷이든 공개 수선)가 4회 중 3회.

**해석 범위:** 이 과제에서 모델의 "첫 발상"은 A다. 구조화 조건의 나머지 후보 3개는 매번 B·C·D·E 중에서 채워진다. 발상의 다양성은 후보 생성 단계에서 **실행 안**에만 있고 **실행 사이**에는 적다.

### 3.3 후보 선택: A가 기본 선택이고, B는 한 번도 선택되지 않았다

| 지표 | 값 |
|---|---|
| 범주 A 선택 | 19/28 (A가 있었던 27실행 중 19) |
| C1 선택 | 22/28 |
| 범주 B(이력·인증 재판매) 선택 | 0/24실행 — 제외 이유가 거의 같다: "infrastructure-heavy / business model / cannibalisation / emotionally cool" |
| 선택 이유에 "platform" 언급 | 25/28 |
| 선택·제외·수정에 "absorb / fold / borrow" 류 표현 | 26/28 |

- **같은 발상에 대한 상반된 평가.** A를 고른 실행은 A를 새롭다고 한다. 예: `Dior|SB_O_L|2` "It is the most surprising and least clichéd of the four"; `Dior|LK_O_H|0` "It carries the most original insight". A를 버린 8실행 중 7실행은 A를 익숙하다고 한다. 예: `Dior|SB_AVG|3` "Visible mending is a well-worn trend, so the idea lacks originality"; `Dior|BASE|3` "Visible mending is an established fashion trope". 같은 모델이 같은 발상의 새로움을 실행마다 반대로 판단했다.
- 선택 이유가 공통 기준(브랜드 고유 자산, platformable, 그린워싱 회피, 다른 후보의 장점 흡수 가능)으로 반복된다. 선택 기준 자체가 비슷하다.
- C1 선택이 많은 것이 "선호 후보를 먼저 적는다"인지 "먼저 적힌 후보를 고른다"인지는 한 번의 응답 기록으로는 가를 수 없다.

### 3.4 수정과 구체화: 다른 발상을 골라도 수정 단계에서 같은 장치가 들어온다

A가 아닌 후보를 고른 9실행 모두 수정 단계에서 A의 장치를 가져왔다. 8실행은 장인·하우스의 서명/날짜/표식을 넣었고, 1실행(`SB_O_H|2`)은 수선 흔적을 보이게 남기는 A의 요소를 넣었다.

| 실행 (`gen_id`) | 선택한 핵심 발상 | 수정 단계 근거 문장 (`revisions_after_selection`) |
|---|---|---|
| `Dior|BASE|0` | E. Extra Inch(숨은 시접) | "Added a signature mend: a discreet atelier thread mark or label updated at each refit, so repairs are visible and signed." (이 실행에는 A 후보가 없었다) |
| `Dior|BASE|1` | D. New Look, Again(시즌 실루엣으로 재단) | "used the C2 star as a discreet optional signature stitched inside the piece" |
| `Dior|BASE|3` | F. Second Fitting | "Added the dated, signed 'Second Fitting' label made by the named petite main, and a small ledger inside each piece" |
| `Dior|SB_AVG|3` | C. Fermé pour réparations(휴점 수선의 날) | "Added a card signed by the individual artisan who repaired each piece" |
| `Dior|SB_O_H|2` | D. New Look 80주년 리메이크 | "Borrowed C1's idea: the original stitches and wear are deliberately left visible in remade pieces, and each owner's story is embroidered inside." |
| `Dior|SB_O_H|3` | G. Wear It Out | "Added a discreet 'Mend Mark', a tiny lucky star stitched inside the lining by the atelier after each repair (borrowed from C1)." |
| `Dior|SB_O_L|1` | H→F. The Second Fitting | "Borrowed the atelier signature from C1: each piece finishes its second fitting with a small embroidered date and artisan initials inside the lining." |
| `Dior|LK_AVG|3` | G. Wear-It-Out → Live In It | "Folded in an optional signature mending touch (from C1) and a handwritten atelier note on returned pieces (from C2)" |
| `Dior|LK_O_L|0` | F. The Second Fitting | "Added a signed 'Second Fitting' label stitched in by the specific atelier artisan … It also borrows the strongest part of C3." |

A를 고른 19실행의 수정도 같은 장치 묶음으로 모인다. 아래 수치는 정규식 키워드 집계(`analysis_dior_stages.py`)이고, 원문은 표본으로 확인했다(28실행 기준, ±1–2건 오차 가능). 예를 들어 `SB_O_H|2`의 보이는 바늘땀 수정은 키워드에 걸리지 않아 서명 25건에서 빠져 있다.

| 수정 장치(실행 절차) | 수정에 등장한 실행 수 / 28 |
|---|---|
| 서명·날짜·표식·라벨 | 25 (위 9 포함) |
| 보이는 수선 / 보이지 않는 수선 선택권(opt-in) | 19 |
| 그린워싱 회피, 환경 수치 삭제, 검증 가능한 공개 | 13 |
| 이력 기록·여권·원장(제외한 B에서 가져옴) | 11 |
| 중고·상속·빈티지 품목까지 대상 확대 | 11 |
| 파일럿·소수 도시·용량 제한 | 11 |

**해석 범위:** 이 기록에서 가장 분명한 "나중에 비슷해지는" 지점은 수정 단계다. 모델이 보고한 수정은 대부분 우려(독점성, 그린워싱, 용량, 손상 미화) 대응이다. 그런데 그 대응 수단이 버린 후보, 특히 A와 B의 요소를 "흡수"하는 방식이라 최종안의 실행 절차가 같아진다. 우려 대응 자체가 원인이라고 단정할 수는 없다. 다만 기록상 수정 단계에서 A의 장치가 추가된 것은 9/9에서 확인된다.

### 3.5 최종안: 핵심 발상 22/32가 A, 나머지 10개도 실행 절차는 A를 포함한다

**최종안 범주 (원문 판독)**

| 최종안 범주(핵심 발상, 제목에서 앞세운 틀) | 수 | 실행 |
|---|---|---|
| A. 서명된/보이는 수선 표식 (Second Signature, Signed Twice, Mended by Dior, Lucky Thread 등) | **22** | BASE|2; SB_AVG|0,1,2; SB_O_H|0,1; SB_O_L|0,2,3; LK_AVG|0,1,2; LK_O_H|0,1,2,3; LK_O_L|1,2,3; NODEDUP|1,2,3 |
| F. Second Fitting(쿠튀르 피팅 의식을 평생으로 확장) | 4 | BASE|3; SB_O_L|1; LK_O_L|0; NODEDUP|0 |
| D. The New Look, Again | 2 | BASE|1; SB_O_H|2 |
| G. Wear It Out / Live In It | 2 | SB_O_H|3; LK_AVG|3 |
| C. Fermé pour réparations | 1 | SB_AVG|3 |
| E. The Extra Inch | 1 | BASE|0 |

- 기존 LLM 묶음(최종 6묶음: c3 18, c0 4, c4 4, c2 3, c1 2, c5 1)과 비교하면, 묶음 c0과 c3은 원문상 **같은 핵심 발상**(장인 서명 표식)이다. 그래서 위 표에서는 합쳐서 A = 22로 셌다. 근거는 §4.4.
- 실행 절차의 공통 요소(최종안 32개, 키워드 집계. 서명 표식은 32개 전부 원문으로 확인했고, 나머지는 표본으로 확인):
  - 장인·하우스 서명/표식/서명 카드 **31/32**. 예외는 `SB_O_H|2`이며, 이 경우에도 보이는 원래 바늘땀과 안쪽에 수놓은 사연이 들어간다.
  - 장인(petites mains·hands)을 전면에 세움 29/32
  - 영상·초상 시리즈 25/32
  - Bar jacket·Lady Dior·Saddle을 예로 듦 22/32
  - 보이는/보이지 않는 수선 선택권 18/32
  - 이력 기록 13/32
  - 수선 살롱·팝업 12/32
- **문제 관점이 달랐던 실행이 다른 틀로 남았다.** P2(입지 않음·손대지 못함)를 주 관점으로 쓴 `SB_O_H|3`과 `SB_O_L|1`은 최종안 범주 G와 F로 끝났다. `LK_AVG|3`도 전제에서 P2를 쓰고 G로 끝났다. 표본은 3건이다.

### 3.6 단계별 요약

| 단계 | 문제 관점 | 핵심 발상 | 실행 절차 |
|---|---|---|---|
| 과제 이해 | **이미 수렴** (P1 44/44) | — | — |
| 후보 생성 | P1 안에서 생성 | 실행 안에서는 다양(4/4 묶음). 실행 사이에서는 같은 메뉴. A가 27/28 실행에 있고 23회 C1, NODEDUP은 16/16 | 후보마다 다름 |
| 후보 선택 | — | A 19/28, B 0/24 | 선택 기준이 반복됨(platform, 흡수 가능) |
| 수정 | — | 대체로 유지됨(틀 이름은 남음) | **수렴**: 비A 선택 9/9에 A 장치 추가, 선택권·그린워싱 회피·이력·파일럿 |
| 최종안 | P1 | A 22/32 + 다른 틀 10 | 서명 표식 31/32 |

---

## 4. 사례

### 4.1 처음부터 비슷했던 사례

| 사례 | 근거 (원본: `data/generations.jsonl`) |
|---|---|
| NODEDUP 독립 호출 16개 | 서로 보지 못하는데도 첫 후보가 모두 A다. `Dior|NODEDUP|1|k0` "a small, visible, hand-stitched mark made by the specific atelier artisan … with their initials and the date"; `Dior|NODEDUP|2|k0` "a 'second signature': a small, discreet, artisan-made mark … added by the atelier hand that did the work"; `Dior|NODEDUP|1|k3` "the couturier who mends it adds a small, discreet 'second signature'". 제목이 "Second Fitting"인 `Dior|NODEDUP|0|k0`, `|2|k2`, `|3|k0`도 본문 장치는 "numbered 'Fitting Card' … tiny hand-stitched mark", "stitched … 'Fitting No. 2, 3, 4' label", "dated atelier label inside the lining"다. |
| `Dior|LK_O_H|2`와 `Dior|LK_O_H|3` (같은 조건, 다른 반복) | 둘 다 C1 = "The Second Signature"를 골랐고 최종 제목도 같다. 최종안: "the initials of the petite main who mended it and the date, stitched into the lining"(rep 2) / "stitch a small numbered mark of their own into the lining: a second signature"(rep 3). 세 층(문제 관점·핵심 발상·실행 절차)이 모두 같다. |
| 조건이 다른 `Dior|SB_AVG|1`, `Dior|LK_O_L|3`, `Dior|NODEDUP|1` (k1) | 셋 다 "The Second Signature". 성격 지시가 없는 NODEDUP과, 성격 방식이 다른 두 조건(Simple-Binary 보통, Likert 개방성 낮음)에서 첫 후보, 선택(NODEDUP은 해당 없음), 최종 제목이 같다. |

### 4.2 서로 다르다가 나중에 비슷해진 사례

§3.4 표의 9실행이 해당한다. 대표 3건:

1. **`Dior|BASE|0` — 후보 목록에 A가 없었는데도 수정에서 A의 장치가 생겼다.**
   - 후보: Extra Inch / Hands That Remember / Second Fitting(인증 재판매) / Flaw Collection
   - 선택한 발상: "hidden seam allowances … quiet promise of a long life"
   - 수정: "Added a signature mend: a discreet atelier thread mark … so repairs are visible and signed"
   - 최종안: "each mend is signed with a discreet thread mark, so repair becomes a mark of status"
2. **`Dior|SB_O_H|3` — A를 "aesthetics"로 버린 뒤 A를 다시 가져왔다.**
   - 제외 이유: "Visually strong but limited to aesthetics … does not solve the underlying barrier of fear of wearing"
   - 수정: "Added a discreet 'Mend Mark', a tiny lucky star stitched inside the lining … (borrowed from C1)"
   - 최종안 "Wear It Out"은 문제 관점(입지 않음)은 지켰고, 실행 절차에는 A가 들어갔다.
3. **`Dior|SB_AVG|3` — 가장 다른 틀(휴점)로 끝났지만 같은 장치가 붙었다.**
   - A를 "well-worn trend"라며 버렸다.
   - 수정: "Added a card signed by the individual artisan who repaired each piece"
   - 최종안: "Each returns with a card signed by the hand that mended it."

### 4.3 끝까지 다른 상태로 남은 부분

최종안 10개(F·D·G·C·E)는 **문제 관점과 제목의 틀**이 A와 다르다.

| 실행 | 남은 틀 |
|---|---|
| `SB_O_H|2`, `BASE|1` | New Look 재해석 |
| `SB_O_H|3`, `LK_AVG|3` | 입지 않는 두려움 |
| `SB_AVG|3` | 휴점 의식 |
| `BASE|0` | 구조적 진실(숨은 시접) |

달라진 것은 주로 **문제 관점 층**이다. 실행 절차 층은 A와 겹친다.

### 4.4 묶음 결과와 원문이 어긋난 사례 (수치만으로 확정하면 안 되는 근거)

| 쌍 | 묶음 | 코사인 | 원문 판단 |
|---|---|---|---|
| `LK_O_H|2` final vs `LK_O_H|3` final | c0 vs c3 (다름) | 0.910 (다른 묶음 쌍 중 최고) | **같은 핵심 발상**(안감에 장인 이니셜·날짜/번호 표식). 묶음 c0은 대표 아이디어가 "Luck, Sewn Back"이어서 뒤에 들어온 "Second Signature" 2개가 c3과 갈라진 것으로 보인다(대표=첫 아이디어 방식의 순서 효과, 미검증). |
| `SB_O_L|0` final vs `LK_O_L|2`·`LK_O_L|3` final | c0 vs c3 | 0.898–0.899 | 같은 핵심 발상("The Second Signature"). |
| `BASE|0` (Extra Inch) vs `BASE|3` (Second Fitting) | 같은 c4 | 0.727 (같은 묶음 쌍 중 최저) | 둘 다 "다시 맞춰 입기"와 관련 있지만 문제 관점(구조적 진실 vs 피팅 의식)이 다르다. 경계 사례. |
| NODEDUP "Second Fitting" 후보 | 후보 집합에서는 c3(A)과 같은 묶음, 최종 집합에서는 c4(F) | — | 집합에 따라 배정이 달라졌다. 본문 장치는 A와 같고 틀은 F다. **틀(문제 관점)과 장치(실행 절차)를 따로 코딩해야 한다**는 근거다. |

참고 수치: 최종안 쌍의 평균 코사인은 같은 묶음 0.855, 다른 묶음 0.779다. 다른 묶음 쌍도 0.78로 높아서, 코사인만으로는 같은 발상과 다른 발상을 가르기 어렵다.

### 4.5 표식이 "메인"인 안과 "디테일"인 안: 언제 비슷해졌나

수선 표식이 최종안에서 어떤 역할을 하는지, 그리고 표식이 어느 단계에서 처음 기록에 나타나는지로 구조화 28실행과 NODEDUP 4건을 나눴다. 각 실행의 선택 후보(`candidates[*].core_idea`), 제외 사유(`selection.rejected`), 수정 기록(`revisions_after_selection`), 최종안(`final_proposal.idea`)을 원문으로 확인했다. 추출 스크립트는 스크래치(markpos.py, candmark.py)로 돌렸고 저장소에는 넣지 않았다.

| 유형 | 표식의 역할 | 표식이 처음 나타난 단계 | 실행 |
|---|---|---|---|
| ① 메인 | 핵심 발상 자체(제목이나 첫 1–3문장) | 후보 생성 → 선택 | 구조화 19 (A 선택) + NODEDUP 3 |
| ② 디테일, 선택 전부터 | 다른 틀 안의 실행 요소 1문장 | **선택한 후보 원문에 이미 있음** | `BASE|3`, `LK_O_L|0` (둘 다 Second Fitting) |
| ③ 디테일, 선택 후 추가 | 다른 틀 안의 실행 요소 1문장 | 선택 단계에서 **넣겠다고 적음** → 수정 단계에서 추가 | `BASE|1`, `SB_AVG|3`, `SB_O_H|2`, `SB_O_H|3`, `SB_O_L|1`, `LK_AVG|3` |
| ④ 디테일, 출처 없이 추가 | 다른 틀 안의 실행 요소 1문장 | 수정 단계 (A 후보 없음) | `BASE|0` |
| (경계) | 틀은 F, 본문은 표식 | 후보 생성 (선택·수정 없음) | `NODEDUP|0` |

**유형 ②: 고를 때부터 비슷했다.**
- `BASE|3` C1 원문: "Each finished piece gets a dated, signed 'Second Fitting' label." 수정 기록은 "Added the dated, signed 'Second Fitting' label …"이라고 적었지만, 후보 원문에 이미 있던 문장이다. **모델의 수정 기록이 실제 차이를 정확히 반영하지 않는 사례**다. 실제로 새로 들어간 것은 'named petite main'과 ledger다.
- `LK_O_L|0` C1 원문: "each mend or alteration left deliberately visible and signed by the atelier hand." 수정에서는 표식을 '서명 라벨 + 보이게/안 보이게 선택'으로 바꿨다.
- 다른 틀에 속한 후보(B–H) 85개 중, 생성 단계에서 장인·하우스 표식을 가진 것은 원문 확인 기준으로 4개다(`BASE|3` C1, `LK_O_L|0` C1·C4, `SB_AVG|2` C4). 이력용으로 꿰매 넣는 라벨(B류)은 별도로 4개다. 즉 생성 단계에서는 표식이 주로 A에만 있었다. F(Second Fitting)는 예외적으로 8개 중 3개가 표식을 품고 있었다.

**유형 ③: 선택 단계에서 이미 "디테일로 흡수"를 계획했다.** A를 제외한 8실행(유형 ②의 2개 포함) 모두 제외 사유에 흡수 계획을 적었다.

| 실행 | A를 뺀 이유 (요지) | 같은 문장 안의 흡수 계획 |
|---|---|---|
| `SB_O_L|1` | "visible mending is already a familiar cultural trope" | "works better as a signature element inside C3" |
| `SB_O_H|2` | "already familiar in fashion … a styling device" | "works better as a design element inside C3" |
| `SB_O_H|3` | "limited to aesthetics … does not solve … fear of wearing" | "better used as a detail inside the chosen idea" |
| `LK_AVG|3` | "kintsugi-style trope that feels familiar" | "better used as an optional service layer" |
| `BASE|1` | "a strong symbol but a narrow idea" | "works better as a supporting detail within C1" |
| `SB_AVG|3` | "a well-worn trend … a design detail, not a platform" | "could be absorbed into C4 as a service option" |
| `BASE|3` | "an established fashion trope" | "its best element … is absorbed into C1" |
| `LK_O_L|0` | "familiar visible-mending aesthetic" | "works better as a craft expression inside C1" |

수정 기록은 이 계획을 그대로 실행했다. 4건은 출처를 명시했다("borrowed from C1", "from C1", "borrowed C1's idea", "the C2 star").

**유형 ④ `BASE|0`**: 후보 4개 중 A가 없다. 그런데도 수정 단계에서 출처 없이 "a discreet atelier thread mark or label … visible and signed"를 추가했다. 흡수가 아니라 **같은 장치가 스스로 다시 생긴** 유일한 사례다.

**최종안에서 디테일의 모양**
- 유형 ②–④의 9개 최종안에서 표식은 모두 5–8문장 중 **한 문장**이다. 위치는 3–6번째 문장이고, 제목과 첫 문장에는 없다.
- 형태는 세 가지로 나뉜다.
  - 꿰맨 서명·이니셜·별: `BASE|0`, `BASE|1`, `BASE|3`, `LK_O_L|0`, `SB_O_H|3`, `SB_O_L|1`, `LK_AVG|3`(선택 사항)
  - 서명 카드: `SB_AVG|3`
  - 원래 바느질을 보이게 두고 사연을 안에 수놓음(서명 아님): `SB_O_H|2`
- 유형 ①과 달리 문제 관점과 제목은 원래 틀을 유지했다.

**해석 범위**
- 표식이 실행 절차에 들어간 시점은 기록상 수정 단계다. 그러나 그 결정은 **선택 단계의 제외 사유 안에서 이미 보고됐다**(8/8).
- 따라서 "선택 후 다듬으면서 우연히 비슷해졌다"기보다는, "선택할 때 A를 핵심에서 내리되 부품으로 남기기로 하고, 수정에서 실행했다"에 가깝다. 다만 이것은 모델이 보고한 작업 기록에 근거한다. 실제 생성 과정의 원인으로 단정할 수는 없다.
- `BASE|3`처럼 수정 기록과 후보 원문이 어긋나는 사례가 있으므로, 수정 기록만 보고 "무엇이 언제 들어왔는지"를 판정하면 안 된다. 후보 원문과 직접 비교해야 한다.
- 지시문(`prompts/task_structured_user.txt`)은 수정 단계를 "changes made to the recommended idea after reviewing it"이라고만 정의한다. 다른 후보를 흡수하라는 지시는 없다. 따라서 흡수는 지시문이 요구한 결과가 아니라 모델이 스스로 택한 방식으로 보고된 것이다.
- 각 유형의 실행 수가 적다(② 2, ③ 6, ④ 1). 그래서 조건별 차이는 보지 않았다.

---

## 5. 페르소나 조건별·반복별 관찰 (기술만, 추론 아님)

| 조건 | A가 후보에 있음 | A 선택 | 최종안 범주 (rep 0–3) | thinking 블록 (rep 0–3) | 평균 출력 토큰 |
|---|---|---|---|---|---|
| BASE | 3/4 | 1/4 | E, D, A, F | 1,1,1,1 | 6129 |
| SB_AVG | 4/4 | 3/4 | A, A, A, C | 1,1,1,1 | 6042 |
| SB_O_H | 4/4 | 2/4 | A, A, D, G | 1,1,1,1 | 6292 |
| SB_O_L | 4/4 | 3/4 | A, F, A, A | 0,1,0,0 | 4239 |
| LK_AVG | 4/4 | 3/4 | A, A, A, G | 0,0,0,0 | 3795 |
| LK_O_H | 4/4 | **4/4** | A, A, A, A | 1,1,1,1 | 5132 |
| LK_O_L | 4/4 | 3/4 | F, A, A, A | 0,1,0,0 | 3855 |
| NODEDUP | 16/16 (후보 1개씩) | — | F, A, A, A | 0 (전부) | 8156 (4호출 합) |

- BASE가 비A 최종안이 가장 많았고(3/4), LK_O_H가 가장 적었다(0/4). **조건당 4회**라 우연 범위 안이다. 검정하지 않았다.
- 개방성 높음/낮음(O_H/O_L)이 문제 관점이나 후보 메뉴를 바꾼 흔적은 원문에서 보이지 않았다. 같은 메뉴(A·B·C·D…)가 모든 조건에 나온다.
- 반복 번호(rep)는 독립 호출의 일련번호일 뿐 순서 의미가 없다. 비A 최종안이 나온 rep(0,1,3 / 3 / 2,3 / 1 / 3 / 0)에 규칙성은 보이지 않는다.
- thinking 블록 유무와 출력 토큰은 조건마다 다르다(SB·BASE·LK_O_H는 블록 있음, LK_AVG·LK_O_L·SB_O_L은 대부분 없음). 이것이 수렴과 관련 있는지는 보지 않았다.

---

## 6. 기존 평가 자료 (탐색적, 사람 보정 전)

| 최종안 묶음(원문 판독) | n | B 평균 | F 평균 | L 평균 | P 평균(0–1) |
|---|---|---|---|---|---|
| A (서명 표식) | 22 | 4.14 | 3.95 | 4.14 | 0.77 |
| 비A (F·D·G·C·E) | 10 | 4.10 | 3.60 | 4.40 | 0.76 |

- gpt-6-astra v0 루브릭이며 사람 검증 전이다. n이 작아서 차이를 해석하지 않는다. 다만 **이 자료 안에서는 비A 틀이 개연성(B·L)에서 뚜렷이 낮지 않았다.** 이것은 다음 실험의 가설 근거일 뿐 결과가 아니다.
- D(집합 내 드묾)는 묶음 배정에 따라 정해진다. §4.4의 c0/c3 분할 때문에 c0의 Second Signature 2건은 D가 실제보다 높게 계산됐을 가능성이 있다(shapley 1/4 vs 1/18).
- 관찰자 평정(`observer.jsonl`)과 조작 확인은 성격 표현 측정용이라 이 질문에는 쓰지 않았다.

---

## 7. 확인된 관찰 / 해석 가능한 범위 / 빠진 자료

### 7.1 확인된 관찰 (원문으로 확인)

1. 문제 관점은 과제 이해 단계에서 이미 같다(P1 44/44).
2. 핵심 발상 A(장인 서명/보이는 수선 표식)가 첫 후보 자리를 차지한다.
   - 구조화 실행 27/28에 들어 있고, 그중 23회가 C1이다.
   - NODEDUP 독립 호출에서는 16/16이 A다.
3. 실행 안에서는 후보가 다르지만(4/4 묶음), 실행 사이에서는 같은 후보 메뉴가 반복된다.
4. 선택 단계: A 19/28, C1 22/28, 이력·인증 재판매(B) 0/24.
   - 같은 A에 대해 "가장 새롭다"(선택한 실행)와 "익숙한 트렌드"(제외한 실행 7/8) 평가가 공존한다.
5. 수정 단계: 비A 발상을 고른 9실행 모두 A의 장치를 수정에서 들여왔다.
   - 버린 후보를 "흡수"하는 표현은 26/28 실행에 있다.
6. 최종안: 핵심 발상 A가 22/32다. 서명 표식은 31/32에 들어 있다.
7. 기존 LLM 묶음은 같은 발상을 두 묶음(c0, c3)으로 나눈 경우가 있다. 코사인은 같은 묶음과 다른 묶음을 잘 가르지 못한다(0.855 vs 0.779).

### 7.2 해석 가능한 범위

- "어디서 수렴하는가"에 대한 이 기록의 답:
  - **문제 관점**은 시작부터 수렴해 있다.
  - **핵심 발상**은 후보 생성(첫 후보)과 선택에서 수렴한다.
  - **실행 절차**는 수정 단계에서 수렴한다. 이 단계가 다른 틀로 출발한 실행까지 끌어당긴다.
- 이것은 한 번의 응답 안에서 **모델이 보고한 순서**에 대한 관찰이다. 모델이 실제로 이 순서로 생각했는지, 수정이 사후 정당화인지는 알 수 없다.
- 브랜드 1개, 주제 1개(Claude가 정한 임시 주제), 조건당 4회다. 페르소나 효과에 대한 결론은 낼 수 없다.
- NODEDUP은 지시문("differ" 없음), 예산(thinking 2000), thinking 블록(0)이 모두 달라서 구조화 조건과 깨끗하게 비교할 수 없다.
- 시스템 프롬프트의 "surprising, never cliché" 같은 창의성 지시가 모든 조건에 있었다. 이 지시가 있는데도 수렴이 일어났다는 점만 말할 수 있다.

### 7.3 빠진 자료

| 빠진 것 | 영향 | 필요한 것 |
|---|---|---|
| 숨겨진 추론 내용 | 보고된 단계가 실제 과정인지 확인 불가 | 확보 불가(설계상). 다단계 호출로 단계를 **외부에서** 나누면 단계별 산출물은 얻을 수 있다. |
| 수정 전 최종안 초안 | "수정이 바꾼 것"을 선택 후보 `core_idea`와만 비교 가능 | 선택 후 초안 → 수정 → 최종을 별도 필드나 별도 호출로 기록 |
| 문제 관점만 적은 필드 | `focus`에 문제와 해법 방향이 섞여 있음 | `problem_frame` 필드 분리 |
| 적지 않은 후보, 후보 생성 순서 | C1 편향의 원인(선호 순서 vs 위치 효과) 구분 불가 | 후보 순서를 섞은 별도 선택 호출 |
| 과제 이해·수정 단계의 묶음 분류 | 이 문서는 원문 판독(분석자 1명)에 의존 | 틀/장치 이중 코딩 루브릭 + 사람 2명 코딩 |
| 사람 평가(S, 묶음 동의, 사전 아이디어) | 개연성·만족도 검증 불가, 묶음 오분할 미확인 | 평가 완료 |
| 묶음 순서 시드 다중화 | c0/c3 분할이 순서 효과인지 미확인 | 3개 이상 시드로 재분류 |

---

## 8. 개입 후보 (다음 실험의 가설, 효과 미검증)

| # | 적용 단계 | 관찰된 문제 | 개입 | 브랜드 적합성·개연성 유지 장치 | 비교 지표 |
|---|---|---|---|---|---|
| H1 | 과제 이해 | 문제 관점 44/44 동일(P1). P2를 쓴 3건은 다른 최종 틀로 끝남 | **문제 관점 분기:** 서로 다른 문제 관점 3–4개를 명시하게 하고(예: 수선 낙인 / 입지 않는 두려움 / 재판매 통제 / 지속가능성 서사의 편중), 후보마다 다른 관점을 맡긴다. 또는 실행마다 시드로 관점 1개를 지정한다 | 관점마다 브랜드 근거(자산·고객 행동)를 1개 이상 대게 한다. 전제 목록은 그대로 둔다 | 최종안 문제 관점 분포(엔트로피), 비A 최종안 비율, B/F/L, 사람 S |
| H2 | 후보 생성 | A가 27/28 실행의 후보, 23회 C1, 독립 호출 16/16 | **기본값 선언 후 격리:** 먼저 "이 브리프에서 가장 먼저 떠오르는 방향"을 한 줄로 적게 한다(예상: A). 이후 후보 4개는 그것과 **메커니즘이 다른** 것만 쓰게 하고, 기본값은 대조용으로 따로 둔다 | 각 후보에 brand_connection·main_concerns를 유지한다. 실현성 우려를 그대로 적게 한다 | 실행 사이 후보 묶음 수, 최대 묶음 비중, A 포함률, F 점수 |
| H3 | 후보 선택 | C1 선택 22/28. 같은 A를 실행마다 새롭다/진부하다로 상반 평가 | **분리 선택 + 순서 무작위화:** 후보를 섞어 별도 호출로 선택한다. 선택 전에 "이 과제에서 흔한 방향 목록"(이전 실행의 묶음 대표)과의 중복을 먼저 적게 한다 | 선택 기준(브랜드 적합·실현성·논리)은 지금과 같게 유지하고, 중복 검토 항목만 추가한다 | 선택 위치 분포, 선택 후보의 집합 내 드묾(D), B/F/L |
| H4 | 수정 | 비A 9/9에 A 장치 유입. "흡수" 26/28 | **흡수 제한:** 수정은 선택 후보의 `main_concerns`에만 대응하게 한다. 버린 후보의 요소를 가져오면 출처를 표시하고, 그 요소가 흔한 방향(A)과 겹치면 겹치지 않는 대안을 먼저 시도하게 한다 | 우려 대응(그린워싱, 용량, 독점성)은 그대로 요구한다. 대응 수단만 핵심 발상 안에서 찾게 한다 | 선택→최종 핵심 발상 유지율(사람·LLM 판정), 최종안 서명 표식 포함률, F/L 점수 |
| H5 | 최종안 작성 | 실행 절차(영상·장인·선택권·파일럿)가 31/32 공통이라 다른 틀도 같아 보임 | **핵심 발상과 위험 관리 분리:** 최종안을 `core_mechanism`과 `risk_mitigations` 필드로 나눠, 공통 안전장치가 발상 본문을 덮지 않게 한다 | 위험 관리 내용은 줄이지 않고 위치만 분리한다 | 핵심 발상 필드만으로 묶음 분류한 결과와 전체 문안 결과의 차이 |

**동일 조건 비교 설계(제안):**
- Dior × "repair and reuse", claude-sonnet-5-5, 같은 CLI·effort·예산, 같은 시스템 프롬프트를 쓴다.
- 대조군(현재 워크시트)과 H1–H4 각각을 비교한다. 비용을 줄이려면 성격 조건은 BASE 하나로 고정하고 반복을 늘린다(팔당 ≥ 12회).
- 지표:
  - **수렴:** 최종안 최대 묶음 비중, 묶음 수, A 포함률
  - **단계별:** 실행 사이 후보 다양성, C1 선택률, 선택→최종 유지율
  - **개연성:** B/F/L와 P_min, 사람 S
- 묶음 분류는 모든 팔을 한 집합에 섞고 순서 시드 3개로 돌린다. 틀(문제 관점)과 장치(실행 절차)를 따로 코딩한다.
- 개연성은 비열등 기준(예: 대조 대비 B·F 평균 하락 ≤ 0.3)을 **실행 전에** 정해 둔다.
- 다단계 호출로 단계를 나누면(H3) 단계 사이를 실제로 분리할 수 있다. 다만 단일 호출 워크시트와 형식이 달라지므로 대조군도 같은 다단계 구조로 만들어야 한다.
- 실행 전에 할 일:
  1. 사람 평가와 `bucket_review.csv` 완료(현 묶음 신뢰도 확인)
  2. 연구자가 정한 주제로 교체할지 결정(현재 주제는 임시값)
  3. 위 지표·기준을 분석 계획에 고정
