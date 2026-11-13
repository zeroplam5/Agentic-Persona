# Big Five × Wild Ideas 파일럿 v2 (초안 — 아직 실행하지 않음)

- 설계: [PREREGISTRATION_v2_DRAFT.md](PREREGISTRATION_v2_DRAFT.md) ("확인 필요" 항목을 먼저 정해야 함)
- 설정: [config.json](config.json)
- 코드: [pilot2.py](pilot2.py) (생성·조작 확인·평가·다양성·사람 평가 표본), 분석과 보고서는 v1과 같은 [../pilot_v1/report.py](../pilot_v1/report.py)를 쓴다

## 실행 순서 (Git Bash 기준, `experiments/pilot_v2`에서)

```bash
python pilot2.py smoke        # 생성·평가 호출 경로 점검(logs/smoke_test.jsonl에만 기록)
python pilot2.py setup        # 브랜드 추첨, 호출 순서 결정, 사전 명세 해시 기록
python pilot2.py generate     # 780회 (중단돼도 재실행하면 이어서 진행)
python pilot2.py manip        # 39회
python pilot2.py judge        # 780 + 156회
uv run --no-project --python 3.12 --with sentence-transformers==3.4.1 --with numpy python ../pilot_v1/embed_bge.py .
python pilot2.py diversity
python pilot2.py human        # ../../human_rating_blind_v2/ 에 블라인드 시트 생성
cd ../pilot_v1 && PILOT_MODULE=pilot2 PILOT_DIR=../pilot_v2 uv run --no-project --python 3.12 --with numpy --with matplotlib python report.py
```

결과는 `results/report.md`, `results/condition_table.csv`, `results/high_low_table.csv`, `results/figures/`에 생긴다.

## API 키

- `pilot2.py`는 프로젝트 루트 `.env`에서 `OPENAI_API_KEY`와 `GEMINI_API_KEY`를 읽는다(`KEY = value`처럼 `=` 주변에 공백이 있어도 된다). 같은 이름의 환경변수가 있으면 그쪽이 우선한다.
- 키는 로그·데이터 파일·화면에 출력하지 않는다. 요청 헤더에만 쓴다.
- `.env`는 버전 관리에 올리지 않는다. 나중에 git을 쓰면 `.gitignore`에 `.env`를 추가해야 한다.

## 기록되는 것

호출마다 다음을 저장한다: 프롬프트 전문, 응답, 요청 파라미터(temperature, 토큰 상한, thinking budget), 실제 서빙된 모델 버전(`model_returned`), 토큰 사용량(OpenAI는 `reasoning_tokens`, Gemini는 `thoughtsTokenCount` 포함), 시각, 오류, 재시도.
