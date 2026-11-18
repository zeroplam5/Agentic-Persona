# Agentic-Persona 후속 실험 공유 자료

## 처음 읽을 자료

1. [최종 연구보고서](최종_연구보고서.md)에서 설계, 수집 결과, 다섯 브랜드의 판단 차이, 사람 평가 범위를 확인한다.
2. [330건 상세 보고서](recollection/reasoning_report.md)에서 OpenAI 최종안·공개 추론 요약·기존 Claude 최종안을 `gen_id`로 대조한다.
3. [Slack 사례](Slack_사용자_선호_분석.md)와 [다른 네 브랜드 검증 메모](4개_브랜드_선호_분기_검증.md)는 원문에 근거한 후속 채택 실험 후보를 설명한다.

## 코드와 자료

| 파일 | 내용 |
| --- | --- |
| [collect_openai.py](collect_openai.py) | 이 실험에 사용한 수집 코드 원본. Python 표준 라이브러리로 동작한다. |
| [generations_claude_original.jsonl](generations_claude_original.jsonl) | 기존 Claude 330건의 고정 스냅샷. 원래 시스템 프롬프트와 사용자 브리프가 들어 있다. |
| [recollection/openai_generations.jsonl](recollection/openai_generations.jsonl) | 새 실행 330건의 요청 본문, 응답 전문, 공개 추론 요약, 최종안, 사용량, 원본 Claude 최종안. |
| [claude_human_ratings.json](claude_human_ratings.json) | 기존 사람 평가 55건 및 30쌍과 Claude 실행 ID의 연결. |
| [Claude 파일럿 원본 소스](Claude_파일럿_원본_소스.md) | 원본 `pilot.py`, 프롬프트, 설정과 고정 커밋. |
| [verify_package.py](verify_package.py) · [SHA256SUMS.txt](SHA256SUMS.txt) | 파일 무결성과 330건 대응을 확인하는 오프라인 검증. |

## 검증과 재실행

압축을 풀고 이 폴더에서 실행한다. 아래 두 확인은 OpenAI 호출 없이 동작한다.

```powershell
python -B verify_package.py
python -B collect_openai.py --dry-run
```

새로 수집할 때는 로컬 환경에 본인의 `OPENAI_API_KEY`를 설정한 후 별도 결과 폴더를 사용한다. Slack 한 건을 먼저 확인할 수 있다. 다음 명령은 유료 OpenAI 요청을 보낸다.

```powershell
python -B collect_openai.py --out fresh_recollection --workers 1 --gen-id 'Slack|BASE|1'
```

전체 330건으로 이어가려면 같은 결과 폴더에서 아래 명령을 실행한다. 시작할 때 이미 회수한 답안은 건너뛴다. 이번 수집에 사용한 API 키는 공유본에 포함되지 않는다.

```powershell
python -B collect_openai.py --out fresh_recollection --workers 18
```
