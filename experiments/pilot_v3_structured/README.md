# 파일럿 v3: Big Five 페르소나 × 구조화 아이디어 작업

- 설계: [DESIGN.md](DESIGN.md) · 분석 계획(수집 전 고정): [ANALYSIS_PLAN.md](ANALYSIS_PLAN.md) · 고정 해시: `logs/freeze_hashes.txt`
- 코드: [pilot3.py](pilot3.py) (호출·묶음·평가·사람 시트), [embed3.py](embed3.py) (검색용 임베딩), [analyze3.py](analyze3.py) (표·보고서)
- Wild Ideas 파일럿(`../pilot_v1`, `../pilot_v2`)과 별도 실험이다.

## 실행 순서 (Git Bash, 이 폴더에서)

```bash
python pilot3.py setup      # 브랜드·주제, 실행 계획, 조건별 프롬프트, 해시
python pilot3.py smoke      # logs/smoke.jsonl 에만 기록
python pilot3.py generate   # Claude CLI. 중단돼도 재실행하면 이어서 진행
python pilot3.py manip      # Mini-Markers 자기 보고
python pilot3.py observe    # Gemini 관찰자 평정
uv run --no-project --python 3.12 --with sentence-transformers==3.4.1 --with numpy python embed3.py
python pilot3.py bucket     # GPT-6-astra 증분 묶음 분류
python pilot3.py judge      # B/F/L, 차원별 1호출
python pilot3.py human      # ../../human_rating_blind_v3_structured/ 에 시트 생성
python pilot3.py analyze    # results/
```

키는 프로젝트 루트 `.env`(`OPENAI_API_KEY`, `GEMINI_API_KEY`)에서 읽고 출력·기록하지 않는다. Claude는 CLI 구독 인증을 쓴다.

## 사람 평가 (연구자 2명)

1. 평가 시트를 열기 **전에** `prior_ideas_BEFORE_viewing.csv`에 브랜드·주제별 자기 아이디어를 적는다(선택. 적어야 "원래 생각하지 못한 발상" 비교가 가능).
2. `rating_sheet_raterA.csv`(연구자 1), `rating_sheet_raterB.csv`(연구자 2)를 서로 상의하지 않고 채운다. 1–5 정수.
3. `bucket_review.csv`에서 LLM 묶음 판단에 동의하는지 Y/N.
4. 끝난 뒤 `python pilot3.py analyze`를 다시 실행하면 S와 종합점수가 채워진다. 키 폴더는 평가가 끝난 뒤에만 연다.
