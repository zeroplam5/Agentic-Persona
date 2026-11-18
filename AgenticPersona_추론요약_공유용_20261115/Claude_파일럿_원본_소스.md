# Claude 파일럿 원본 소스

저장소 `zeroplam5/Agentic-Persona`의 커밋 `13396b8f4d3bc6bcffb69e3f6bfa1d02e822a35c`가 기준이다. 아래 링크는 이 커밋을 가리킨다.

- [Claude 수집·평가 코드 pilot.py](https://github.com/zeroplam5/Agentic-Persona/blob/13396b8f4d3bc6bcffb69e3f6bfa1d02e822a35c/experiments/pilot_v1/pilot.py)
- [파일럿 설정 config.json](https://github.com/zeroplam5/Agentic-Persona/blob/13396b8f4d3bc6bcffb69e3f6bfa1d02e822a35c/experiments/pilot_v1/config.json)
- [고정 프롬프트 폴더](https://github.com/zeroplam5/Agentic-Persona/tree/13396b8f4d3bc6bcffb69e3f6bfa1d02e822a35c/experiments/pilot_v1/prompts)
- [파일럿 사전 명세](https://github.com/zeroplam5/Agentic-Persona/blob/13396b8f4d3bc6bcffb69e3f6bfa1d02e822a35c/experiments/pilot_v1/PREREGISTRATION.md)

전체 Claude 코드를 내려받을 때는 아래처럼 고정 커밋을 사용한다. 함께 제공된 [OpenAI 수집 코드](collect_openai.py)는 패키지의 고정 JSONL을 읽는다.

```powershell
git clone https://github.com/zeroplam5/Agentic-Persona.git Claude_원본
git -C Claude_원본 checkout --detach 13396b8f4d3bc6bcffb69e3f6bfa1d02e822a35c
```
