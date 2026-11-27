# 선택안 중심 점검 연구 (v5, 탐색적)

선행 작업:
- Dior 단계별 분석: [../pilot_v3_structured/results/dior_convergence_analysis.md](../pilot_v3_structured/results/dior_convergence_analysis.md)
- 1차 후속: [../selection_intervention_v4/](../selection_intervention_v4/)

| 파일 | 내용 |
|---|---|
| [DESIGN.md](DESIGN.md) | 사전 고정 설계 (`logs/freeze_hashes.txt`) |
| [results/pilot5_report.md](results/pilot5_report.md) | 결과 보고서 |
| `pilot5.py`, `analyze5.py`, `prompts/`, `config.json` | 실행과 분석. v4의 `pilot4.py`, v3의 `pilot3.py` 호출 함수를 재사용 |
| `data/revise.jsonl` | 288개: 24세트 × 4조건 × 3반복 |
| `data/codes.jsonl` | 312개: 블라인드 코딩, v3 검증 24 포함 |
| `data/judgments.jsonl` | 864개: B/F/L 판정 |
| `logs/smoke.jsonl` | 고정 전 형식 확인 4회. 분석에 쓰지 않음 |
| `../../human_coding_blind_v5_focus/` | 연구자 2인 블라인드 코딩 시트 48건과 `CODING_GUIDE.md` (미평가) |

## 재현 (Git Bash, 이 폴더에서)

```bash
python pilot5.py revise && python pilot5.py code && python pilot5.py judge   # 완료된 항목은 건너뜀
python pilot5.py human
python pilot5.py analyze
```
