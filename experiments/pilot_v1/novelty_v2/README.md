# 새로움 측정 개선 연구 (파일럿 v1 아이디어 재평가)

v1에서 새로움 점수가 몰린 문제를 다룬다. 아이디어는 새로 생성하지 않았다. 기존 330개 중 일부를 다시 평가해 세 가지 측정 방식을 비교했다. v1 결과 파일은 읽기만 하고 수정하지 않았다.

| 파일 | 내용 |
|---|---|
| [ANALYSIS_PLAN.md](ANALYSIS_PLAN.md) | TEST 실행 전에 고정한 표본·지표·판단 규칙과 DEV 기록 |
| [COMPOSITE_OPTIONS.md](COMPOSITE_OPTIONS.md) | 쌍대 비교·새 루브릭을 쓸 때의 종합점수 후보와 검증 계획(미결정) |
| `prompts/novelty_abs_v2b.txt` | 개선 절대평가 루브릭(TEST에 사용). `novelty_abs_v2.txt`는 DEV 1차본 |
| `prompts/novelty_pair_v1.txt` | 쌍대 비교 프롬프트 |
| `prompts/familiar_formats.txt` | 익숙한 캠페인 형식 목록. 연구자가 작성했고, 검증된 선행 사례 자료가 아니다 |
| `study_config.json` | 시드, 표본 크기, 평가자 모델, 비용 상한 |
| `logs/sample.json` | DEV/TEST 분할과 쌍 설계(시드 20261114) |
| `logs/freeze.json` | TEST 직전 프롬프트·계획·표본의 SHA-256 |
| `data/abs_judgments.jsonl`, `data/pair_judgments.jsonl` | 프롬프트 전문, 원시 응답, 파싱 결과, 토큰, 비용, 시각, 재시도 |
| `results/novelty_study_results.md` | 결과 표(자동 생성) |
| `results/novelty_study_summary.json` | 모든 지표의 원 정밀도 값 |
| `results/novelty_test_idea_scores.csv` | TEST 아이디어별 점수: 기존·재실행·개선 1·2차, 쌍대 승률, v1 유용성, **v1 종합점수(보존)** |
| `results/figures/` | 분포 그림과 방법별 조건 평균 그림 |
| `human_key_DO_NOT_OPEN_until_rating_done/` | 사람 평가 시트의 조건 키 |

사람 평가 시트는 프로젝트 루트의 [human_rating_blind_novelty/](../../../human_rating_blind_novelty/)에 있다. 조건과 LLM 점수는 빠져 있다.

## 재실행

```bash
python novelty_study.py sample       # 이미 있으면 덮어쓰지 않음
python novelty_study.py estimate
python novelty_study.py dev novelty_abs_v2
python novelty_study.py dev novelty_abs_v2b
python novelty_study.py freeze novelty_abs_v2b
python novelty_study.py test         # 동결 해시가 다르면 실행 거부. 성공한 호출은 건너뛰고 이어서 진행
uv run --no-project --python 3.12 --with numpy --with matplotlib python novelty_study.py analyze
python novelty_study.py human
```

평가자 호출은 v1과 같은 `pilot.py`의 CLI 경로를 쓴다. 모델은 `claude-opus-4-7`이며 구독 인증을 쓰므로 별도 키가 필요 없다. 온도는 CLI에서 지정할 수 없다. 따라서 같은 프롬프트로 다시 실행해도 점수가 다를 수 있으며, 재평가 일치도가 그 변동을 측정한다.

참고: 사람 평가 표본 추출 코드(`cmd_human`)는 동결 후에 고쳤다. 조건 균형을 맞추는 무작위 탐색과 calibration 열을 추가했다. `cmd_human`은 LLM 평가 호출과 무관하다. 동결 해시는 프롬프트, 계획, 설정, 표본 파일에만 걸려 있다.

## 참조 자료에 대한 확인 결과

검증된 선행 캠페인 자료를 평가자에게 주는 방안을 확인했다. 쓸 수 있는 자료가 없었다.

| 자료 | 확인 결과 |
|---|---|
| 원 논문(Creativity Benchmark) | 비교 응답과 선호 레이블이 공개되지 않음 |
| Cannes Lions *The Work*, WARC, Effie Case Library | 구독 상품. 공개 API나 연구 재사용 조건을 찾지 못함 |
| AdForum | 수상작 아카이브. 공개 API나 연구 재사용 조건을 찾지 못함 |
| Adlogue | "공개 DB"라고 소개하지만 API는 대기자 명단 단계. 라이선스와 출처 신뢰성이 확인되지 않음 |

이 자료들은 브랜드별 기존 캠페인을 빠짐없이 담고 있다고 볼 수도 없다.

그래서 평가자 프롬프트는 다음과 같이 구성했다.

- 기억에 의존한다는 한계를 명시한다.
- "선례 없음"이라는 단정을 금지하고, 불확실한 사례에는 "(uncertain)"을 붙이게 한다.
- 연구자가 작성한 익숙한 형식 목록만 참조로 준다.

따라서 새로움 점수는 평가 모델이 기억하는 범위 안의 판단이다. 실제 시장에 선행 사례가 있는지는 검증하지 않았다.
