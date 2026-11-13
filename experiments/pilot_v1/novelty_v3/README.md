# 새로움 측정 v3 (루브릭 수정 = Gemini, TEST = OpenAI, 사람 평가와 비교)

v2와 아이디어·DEV/TEST 분할·쌍 설계가 같다. v1과 v2의 파일은 읽기만 하고 수정하지 않는다.

| 파일 | 내용 |
|---|---|
| [ANALYSIS_PLAN_v3.md](ANALYSIS_PLAN_v3.md) | TEST 전에 고정한 계획, 결정 규칙, Gemini DEV 기록 |
| [results/해석_v3.md](results/해석_v3.md) | 해석 요약 |
| `results/v3_results.md`, `results/v3_summary.json` | 표, 원 정밀도 값 |
| `results/v3_test_idea_scores.csv` | TEST 아이디어별 점수 (Claude/GPT-4.1, 기존/개선, 쌍대 승률, 유용성, v1 종합점수 보존) |
| `results/figures/v3_human_agreement.png` | 사람 평가와의 일치 |
| `prompts/novelty_abs_v2c.txt` | TEST에 쓴 개선 루브릭. v2b와 다른 곳은 범주 정의 한 곳 |
| `data/gemini_dev_abs.jsonl`, `data/openai_test_abs.jsonl`, `data/openai_test_pairs.jsonl` | 프롬프트 전문, 원시 응답, 요청 파라미터, 반환 모델, 토큰, 추정 비용 |
| `logs/freeze.json` | 동결 해시. 프롬프트, 계획, 설정, 표본, 사람 평가 파일 포함 |

## 재실행

```bash
python novelty_v3.py estimate
python novelty_v3.py smoke
python novelty_v3.py dev novelty_abs_v2b
python novelty_v3.py dev novelty_abs_v2c
python novelty_v3.py freeze novelty_abs_v2c
python novelty_v3.py test
uv run --no-project --python 3.12 --with numpy --with matplotlib python novelty_v3.py analyze
```

API 키는 프로젝트 루트 `.env`에서 읽는다(`../../pilot_v2/pilot2.py`의 `load_env`). 키는 로그나 데이터 파일에 기록하지 않는다. 사람 평가 파일은 `../../../human_rating_blind_novelty/*_rated.csv`이고, 키는 `../novelty_v2/human_key_DO_NOT_OPEN_until_rating_done/`에 있다.

참고: Gemini DEV 실행 중 속도 제한(429) 때문에 `workers`를 6에서 3으로 줄였다가, 동결 직전에 6으로 되돌렸다. 해시에는 되돌린 값이 들어 있다. 동결 뒤에 바꾼 파일은 없다.
