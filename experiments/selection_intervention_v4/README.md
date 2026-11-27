# 선택 후 요소 검토 개입 연구 (v4, 탐색적)

선행 작업: Dior 단계별 수렴 분석 ([../pilot_v3_structured/results/dior_convergence_analysis.md](../pilot_v3_structured/results/dior_convergence_analysis.md)).
이 폴더는 그 관찰을 출발점으로 (1) 같은 절차를 세 브랜드에 적용한 기존 자료 분석과 (2) 관찰된 지점(선택 후 수정)에 개입을 넣은 파일럿을 담는다.

| 파일 | 내용 |
|---|---|
| [results/existing_analysis.md](results/existing_analysis.md) | 기존 v3 기록 분석 (Dior·Canva·Mastercard, 같은 코딩 기준, 선택 비교 기준, 요소 유입 단계) |
| [DESIGN.md](DESIGN.md) | 파일럿 설계와 분석 계획 (호출 전 고정, `logs/freeze_hashes.txt`) |
| [results/pilot_report.md](results/pilot_report.md) | 파일럿 결과 |
| `coding_existing.py`, `aux_manual.py` | 분석자 1인 코딩 (코드북, 재배정, 요소 유입 판정) |
| `analyze_existing.py` | 기존 자료 분석 → `results/existing_*` |
| `pilot4.py`, `analyze_pilot.py`, `prompts/`, `config.json` | 파일럿 실행·분석 |
| `data/` | `select.jsonl`(공통 선택 24), `revise.jsonl`(두 조건 48), `codes.jsonl`(블라인드 코딩 72), `judgments.jsonl`(B/F/L) |
| `../../human_rating_blind_v4_selection/` | 조건을 가린 사람 평가 시트 (미평가) |

## 재현 (Git Bash, 이 폴더에서)

```bash
python analyze_existing.py          # 기존 자료, 호출 없음
python pilot4.py setup              # 세트·순서 선택, 해시 (이미 실행됨: 다시 돌리면 plan.json이 같은 시드로 다시 쓰인다)
python pilot4.py select && python pilot4.py revise   # Claude CLI (claude-sonnet-5-5)
python pilot4.py code && python pilot4.py judge      # gpt-6-astra
python pilot4.py human
python pilot4.py analyze
```

키는 프로젝트 루트 `.env`에서 pilot3를 통해 읽고 출력하지 않는다. 기록된 jsonl은 이어서 실행할 때 완료된 항목을 건너뛴다.
