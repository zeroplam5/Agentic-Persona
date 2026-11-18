from collections import Counter
import hashlib
import json
from pathlib import Path

import collect_openai as collector

ROOT = Path(__file__).resolve().parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    manifest = (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    for entry in manifest:
        digest, relative = entry.split("  ", 1)
        path = ROOT / relative
        require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"SHA-256 mismatch: {relative}")

    original = {row["gen_id"]: row for row in collector.read_source()}
    data = ROOT / "recollection" / "openai_generations.jsonl"
    rows = [json.loads(line) for line in data.read_text(encoding="utf-8").splitlines()]
    require(len(rows) == 330 and {r["gen_id"] for r in rows} == original.keys(), "Unexpected assignment")
    require(len({r["response"]["id"] for r in rows}) == 330, "Duplicate response ID")
    require(set(Counter((r["brand"], r["condition"]) for r in rows).values()) == {6}, "Unexpected cell size")

    for row in rows:
        key = row["gen_id"]
        expected = original[key]
        require(row["state"] == "completed", f"Incomplete response: {key}")
        require(row["request"] == collector.build_request(expected), f"Request mismatch: {key}")
        require(row["claude_final_text"] == expected["text"], f"Claude text mismatch: {key}")
        require(collector.extract(row["response"]) == (row["final_text"], row["reasoning_summary"]), f"Extraction mismatch: {key}")
        require(0 < len(row["final_text"].split()) < 50, f"Unexpected final length: {key}")
    require(sum(bool(r["reasoning_summary"]) for r in rows) == 273, "Unexpected summary coverage")

    ratings = json.loads((ROOT / "claude_human_ratings.json").read_text(encoding="utf-8"))
    absolute, pairs = ratings["absolute"], ratings["pairs"]
    require(len(absolute) == 55 and len(pairs) == 30, "Unexpected human rating count")
    for row in absolute:
        require(original[row["claude_gen_id"]]["brand"] == row["brand"], f"Rating brand mismatch: {row['item_id']}")
    for row in pairs:
        require(all(original[row[field]]["brand"] == row["brand"] for field in ("claude_gen_id_A", "claude_gen_id_B")), f"Pair brand mismatch: {row['pair_item']}")
    print("Verified package hashes, original prompt parity, 330 responses, 273 summaries, and 55 + 30 Claude ratings.")
    print("No model calls were made.")


if __name__ == "__main__":
    main()

