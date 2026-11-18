"""Embed all bucketing items (finals and candidates) with BAAI/bge-large-en-v1.5 for candidate-bucket RETRIEVAL only.
Cosine similarity never decides bucket membership; the LLM does (MuseScorer design).

  uv run --no-project --python 3.12 --with sentence-transformers==3.4.1 --with numpy python embed3.py
Writes data/embeddings.json {item_id: [normalized vector]}.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import pilot3  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

MODEL = pilot3.CONFIG["embedding"]["model"]
items = {it["item_id"]: it["text"] for v in pilot3.bucket_items().values() for it in v}
ids = sorted(items)
m = SentenceTransformer(MODEL, device="cpu")
V = m.encode([items[i] for i in ids], normalize_embeddings=True, batch_size=16, show_progress_bar=False)
out = {i: [round(float(x), 6) for x in v] for i, v in zip(ids, V)}
(ROOT / "data" / "embeddings.json").write_text(json.dumps({"_model": MODEL, **out}), encoding="utf-8")
print("embedded", len(ids), V.shape)
