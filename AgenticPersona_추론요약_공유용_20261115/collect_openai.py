from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "generations_claude_original.jsonl"
SOURCE_SHA = "c0a196f21abe185bb7dd7f8c7e5eb3b22800486a234114913661db8b62ab1809"
MODEL = "gpt-6.1-terra"
REASONING = {"effort": "high", "summary": "auto"}
MAX_OUTPUT_TOKENS = 8192
RATE_LIMIT_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 180
PRICE_PER_MILLION = {"input": 1.0, "cached_input": 0.05, "output": 5.0}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_source() -> list[dict]:
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise SystemExit("The pinned Claude file failed its SHA-256 check.")
    rows = [json.loads(line) for line in raw.splitlines()]
    grouped = Counter((r["brand"], r["condition"]) for r in rows)
    if len(rows) != 330 or len({r["gen_id"] for r in rows}) != 330 or len(grouped) != 55 or set(grouped.values()) != {6}:
        raise SystemExit("Unexpected original pilot assignment.")
    return rows


def api_key(env_path: Path) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            match = re.fullmatch(r"\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*(.*?)\s*", line)
            if match:
                key = match[1].strip("\"'")
                break
    if not key:
        raise SystemExit("Set OPENAI_API_KEY or provide an .env with --env-file.")
    return key


def build_request(row: dict) -> dict:
    return {
        "model": MODEL,
        "input": [
            {"role": "system", "content": row["system_prompt"]},
            {"role": "user", "content": row["user_prompt"]},
        ],
        "reasoning": REASONING,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "store": False,
    }


def extract(response: dict) -> tuple[str, list[str]]:
    final, summary = [], []
    for item in response.get("output", []):
        if item.get("type") == "reasoning":
            summary.extend(
                block["text"] for block in item.get("summary", [])
                if block.get("type") == "summary_text" and block.get("text", "").strip()
            )
        elif item.get("type") == "message" and item.get("role") == "assistant":
            final.extend(
                block["text"] for block in item.get("content", [])
                if block.get("type") == "output_text" and block.get("text")
            )
    return "".join(final).strip(), summary


def atomic_text(path: Path, text: str) -> None:
    pending = path.with_suffix(path.suffix + ".partial")
    with pending.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def save_record(path: Path, record: dict) -> None:
    atomic_text(path, json.dumps(record, ensure_ascii=False) + "\n")


def error_code(error: HTTPError) -> str | None:
    try:
        code = json.load(error).get("error", {}).get("code")
    except (OSError, ValueError, AttributeError):
        return None
    return code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", code) else None


def attempt(path: Path, record: dict, payload: dict, key: str) -> None:
    for retry in range(RATE_LIMIT_RETRIES + 1):
        client_id = f"agentic-persona-{uuid4().hex}"
        entry = {"client_request_id": client_id, "sent_at": now(), "state": "dispatching"}
        record["attempts"].append(entry)
        record["state"] = "in_flight"
        save_record(path, record)
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Client-Request-Id": client_id,
        }
        for variable, header in (("OPENAI_ORG_ID", "OpenAI-Organization"), ("OPENAI_PROJECT_ID", "OpenAI-Project")):
            if os.environ.get(variable):
                headers[header] = os.environ[variable]
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as result:
                entry["server_request_id"] = result.headers.get("x-request-id")
                answer = json.load(result)
        except HTTPError as error:
            code = error_code(error)
            entry.update(http_status=error.code, error_code=code, server_request_id=error.headers.get("x-request-id"))
            if error.code == 429 and code != "insufficient_quota" and retry < RATE_LIMIT_RETRIES:
                entry["state"] = "rate_limited"
                record["state"] = "rejected"
                save_record(path, record)
                delay = error.headers.get("Retry-After", "")
                time.sleep(min(30, float(delay)) if re.fullmatch(r"\d+(\.\d+)?", delay) else 2 ** retry)
                continue
            entry["state"] = "http_error"
            record["state"] = "rejected" if 400 <= error.code < 500 else "unknown"
            break
        except (URLError, TimeoutError, OSError, ValueError) as error:
            entry.update(state="transport_error", error_type=type(error).__name__)
            record["state"] = "unknown"
            break
        else:
            entry["state"] = "received"
            record["response"] = answer
            final, summary = extract(answer)
            record.update(final_text=final, reasoning_summary=summary)
            record["state"] = "completed" if answer.get("status") == "completed" and final else "incomplete"
            break
    record["finished_at"] = now()
    save_record(path, record)


def collect(row: dict, path: Path, key: str) -> dict:
    payload = build_request(row)
    record = {name: row[name] for name in ("gen_id", "brand", "condition", "rep")}
    record.update(request=payload, claude_final_text=row["text"], attempts=[])
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous["gen_id"] != row["gen_id"] or previous["request"] != payload:
            raise RuntimeError("An existing record has a different task or request configuration.")
        if previous["state"] != "rejected":
            raise RuntimeError("A response or unresolved attempt already exists for this task.")
        record["attempts"] = previous["attempts"]
    attempt(path, record, payload, key)
    return record


def records(path: Path) -> dict[str, dict]:
    result = {}
    for file in sorted(path.glob("*.json")):
        row = json.loads(file.read_text(encoding="utf-8"))
        if row["gen_id"] in result:
            raise SystemExit("Duplicate generation IDs in the checkpoint files.")
        result[row["gen_id"]] = row
    return result


def export(rows: list[dict], out: Path, checkpoint: Path) -> None:
    saved = records(checkpoint)
    ordered = [saved[row["gen_id"]] for row in rows if row["gen_id"] in saved]
    complete = [r for r in ordered if r["state"] == "completed"]
    summaries = [r for r in complete if r["reasoning_summary"]]
    sizes = [len(" ".join(r["reasoning_summary"]).split()) for r in summaries]
    states = Counter(r["state"] for r in ordered)
    usage = [r["response"].get("usage") or {} for r in ordered if "response" in r]
    inputs = sum(u.get("input_tokens") or 0 for u in usage)
    cached = sum((u.get("input_tokens_details") or {}).get("cached_tokens") or 0 for u in usage)
    outputs = sum(u.get("output_tokens") or 0 for u in usage)
    reasoning = sum((u.get("output_tokens_details") or {}).get("reasoning_tokens") or 0 for u in usage)
    cost = ((inputs - cached) * PRICE_PER_MILLION["input"] + cached * PRICE_PER_MILLION["cached_input"] + outputs * PRICE_PER_MILLION["output"]) / 1_000_000
    atomic_text(out / "openai_generations.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered))
    lines = [
        "# OpenAI Wild Ideas 재수집",
        "",
        f"- 모델 요청 {MODEL}, reasoning effort {REASONING['effort']}, summary {REASONING['summary']}",
        f"- 최종안 회수 {len(complete)}/{len(rows)}건, 추론 요약 포함 {len(summaries)}/{len(complete)}건",
        f"- 저장 상태 {dict(states)}, 미시도 {len(rows) - len(ordered)}건",
        f"- 입력 {inputs:,}토큰, 출력 {outputs:,}토큰, 그중 추론 {reasoning:,}토큰",
        f"- 반환된 사용량의 기본 요금 환산 약 US${cost:.4f}. 사용량이 없는 요청은 환산에서 빠진다.",
        "",
        "OpenAI가 반환한 공개 추론 요약을 원문 그대로 표시한다. 모델을 변경한 새 실험이다.",
        "",
    ]
    if sizes:
        lines.extend([f"요약의 공백 기준 중앙값 {statistics.median(sizes):g}단어, 범위 {min(sizes)}~{max(sizes)}단어.", ""])
    lines.extend([
        "## 전체 집계",
        "",
        "| 성향 | 예정 | 최종안 | 요약 반환 | 요약 반환 비율 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for condition in sorted({r["condition"] for r in rows}):
        intended = sum(r["condition"] == condition for r in rows)
        valid = sum(r["condition"] == condition for r in complete)
        exposed = sum(r["condition"] == condition for r in summaries)
        rate = f"{exposed/valid:.1%}" if valid else "—"
        lines.append(f"| {condition} | {intended} | {valid} | {exposed} | {rate} |")
    lines.extend(["", "## 개별 응답", ""])
    groups = sorted({(r["brand"], r["condition"]) for r in rows})
    for brand, condition in groups:
        group = [r for r in complete if (r["brand"], r["condition"]) == (brand, condition)]
        if not group:
            continue
        lines.extend([f"## {brand} · {condition}", ""])
        for row in group:
            final = row["final_text"]
            lines.extend([
                f"### {row['gen_id']}",
                "",
                f"**OpenAI 최종안** ({len(final.split())}단어)",
                "",
                final,
                "",
                "**OpenAI 추론 요약**",
                "",
                "\n\n".join(row["reasoning_summary"]) or "이 응답에는 공개 요약이 반환되지 않았다.",
                "",
                "**기존 Claude 최종안**",
                "",
                row["claude_final_text"],
                "",
            ])
    atomic_text(out / "reasoning_report.md", "\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-run the pinned Wild Ideas pilot with OpenAI reasoning summaries.")
    parser.add_argument("--out", type=Path, default=ROOT / "recollection")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--gen-id", action="append")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    rows = read_source()
    if args.gen_id and not set(args.gen_id).issubset({r["gen_id"] for r in rows}):
        parser.error("Unknown --gen-id")
    assignments = [(index, row) for index, row in enumerate(rows, 1)
                   if not args.gen_id or row["gen_id"] in args.gen_id]
    if args.dry_run:
        print(f"Validated source: 330 unique generations, 55 cells, 6 repeats per cell. Selected {len(assignments)}.")
        return
    args.out.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out / "records"
    checkpoint.mkdir(exist_ok=True)
    if args.report_only:
        export(rows, args.out, checkpoint)
        return
    key = api_key(args.env_file)
    lock = args.out / ".running"
    try:
        lock.mkdir()
    except FileExistsError:
        raise SystemExit(f"Another collector has locked {args.out}. Confirm it stopped before removing {lock.name}.")
    try:
        saved = records(checkpoint)
        assignments = [(i, r) for i, r in assignments if r["gen_id"] not in saved or saved[r["gen_id"]]["state"] == "rejected"]
        random.Random(20261115).shuffle(assignments)
        print(f"Dispatching {len(assignments)} generations with up to {args.workers} workers.", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for offset in range(0, len(assignments), args.workers):
                batch = assignments[offset:offset + args.workers]
                futures = {pool.submit(collect, r, checkpoint / f"{i:03}.json", key): r for (i, r) in batch}
                attempts = []
                for future in as_completed(futures):
                    record = future.result()
                    attempts.append(record)
                    print(f"{record['gen_id']} {record['state']} summary_blocks={len(record.get('reasoning_summary', []))}", flush=True)
                if any(r["state"] in {"rejected", "unknown"} for r in attempts):
                    for r in attempts:
                        last = r["attempts"][-1]
                        if r["state"] in {"rejected", "unknown"}:
                            print(f"Stopped dispatch after {r['gen_id']}: HTTP {last.get('http_status')}, {last.get('error_code') or last.get('error_type')}", flush=True)
                    break
    finally:
        try:
            export(rows, args.out, checkpoint)
        finally:
            lock.rmdir()


if __name__ == "__main__":
    main()

