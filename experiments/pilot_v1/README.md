# Big Five × Wild Ideas 파일럿 v1

- 설계: [PREREGISTRATION.md](PREREGISTRATION.md) (결과 확인 전 작성, 해시는 `logs/prereg_hash.txt`)
- 자료 검증: [SOURCE_VERIFICATION.md](SOURCE_VERIFICATION.md)
- 결과(최신): `results/report_v1.1.md`(대표 종합점수 기준 표·그림 개선판), `results/condition_table.csv`, `results/high_low_table.csv`, `results/figures/`, `results/verification_v1.1.json`. 사람 평가를 마치기 전에는 열지 않기를 권장한다.
- 결과(최초, 수정하지 않음): `results/report.md`, `results/summary.json`, `results/idea_level_scores.csv`
- 사람 평가: 평가자용 파일만 따로 모은 [../../human_rating_blind_v1/](../../human_rating_blind_v1/)(조건·LLM 점수 없음). 키는 `human_eval/_key_DO_NOT_OPEN_until_rating_done/`에 있다.
- 새로움 측정 개선 연구(기존 아이디어 재평가, 결과는 별도 저장): [novelty_v2/](novelty_v2/), 해석은 `novelty_v2/results/해석_새로움연구.md`
- 새로움 측정 v3(루브릭 수정 Gemini, TEST OpenAI, 사람 평가 일치): [novelty_v3/](novelty_v3/), 해석은 `novelty_v3/results/해석_v3.md`
- 다음 실험: [../pilot_v2/](../pilot_v2/) (Average 명시, 대조 조건, API 경로; 초안)

## 폴더 구조

| 경로 | 내용 |
|---|---|
| `config.json` | 모델, 시드, 표본 크기, 비용 상한, Appendix A.2 브랜드 표 전사본 |
| `prompts/` | 원 시스템·사용자 프롬프트, 평가 채점표, IPIP-50 문항 |
| `logs/brands.json`, `logs/generation_plan.json`, `logs/condition_prompts.json` | 뽑힌 브랜드, 섞인 호출 순서, 조건별 최종 시스템 프롬프트 |
| `data/generations.jsonl` | 생성 원시 기록: 프롬프트 전문, 응답, 사용 모델(`model_usage`), 토큰, 비용, 시각, 오류, 재시도 |
| `data/manipulation_check.jsonl` | IPIP-50 응답 원문과 파싱 결과 |
| `data/judgments.jsonl` | 평가자 프롬프트 전문, 원시 응답, 점수, 근거(1차·재검사) |
| `data/embeddings_bge_large_en_v1.5.npz` | 다양성용 임베딩 |

## 재실행

```bash
python pilot.py setup      # 같은 시드면 같은 브랜드·순서
python pilot.py generate   # 성공한 gen_id는 건너뜀(재개 가능)
python pilot.py manip
python pilot.py judge
uv run --no-project --python 3.12 --with sentence-transformers==3.4.1 --with numpy python embed_bge.py
python pilot.py diversity
python pilot.py analyze
python pilot.py human
uv run --no-project --python 3.12 --with numpy --with matplotlib python report.py   # 보고서 v1.1 + 그림
```

`report.py`가 대표 종합점수 공식, 집계 규칙(브랜드 동일 가중), 동률·반올림 규칙의 기준 구현이다. v2도 같은 파일을 쓴다.

LLM 샘플링은 시드로 고정할 수 없으므로, 재실행하면 다른 문장이 나온다. 정확한 재현은 저장된 원시 응답으로 한다.

## 모델 인증 (비밀키를 채팅이나 파일에 쓰지 말 것)

v1 파이프라인은 Claude Code CLI(`claude -p`)의 로그인 인증(구독)을 그대로 쓴다. 별도 키가 필요 없다. v2는 프로젝트 루트 `.env`의 OpenAI·Gemini 키를 쓴다([../pilot_v2/README.md](../pilot_v2/README.md)).

API 키로 돌리려면(온도 같은 샘플링 파라미터를 직접 지정할 수 있어 재현성이 좋아진다):

1. Anthropic Console에서 키를 발급한다.
2. PowerShell에서 사용자 환경변수로 설정한다: `[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "<키>", "User")`. 그런 다음 새 터미널을 연다. 키는 저장소 파일이나 채팅에 붙여 넣지 않는다.
3. 그 후 SDK 기반 호출 경로(`anthropic` 패키지, `temperature=1.0` 명시)를 추가하면 된다. 이 경로는 아직 구현하지 않았다.
