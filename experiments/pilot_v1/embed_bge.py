"""Embed successful generations with BAAI/bge-large-en-v1.5 (same encoder as the Creativity Benchmark paper).

Run with an isolated env, e.g.:
  uv run --python 3.12 --with sentence-transformers==3.4.1 --with numpy python embed_bge.py [EXPERIMENT_DIR] [--warmup]
Writes data/embeddings_bge_large_en_v1.5.npz (ids, vectors, model info).
"""
import json
import sys
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL = "BAAI/bge-large-en-v1.5"
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
ROOT = Path(_args[0]).resolve() if _args else Path(__file__).resolve().parent  # experiment folder (default: pilot_v1)

m = SentenceTransformer(MODEL, device="cpu")
if "--warmup" in sys.argv:
    print("warmup ok", m.get_sentence_embedding_dimension())
    sys.exit(0)

gens = {}
for line in (ROOT / "data" / "generations.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        r = json.loads(line)
        if r.get("ok"):
            gens[r["gen_id"]] = r["text"]
ids = sorted(gens)
V = m.encode([gens[i] for i in ids], normalize_embeddings=True, batch_size=16, show_progress_bar=False)
np.savez(ROOT / "data" / "embeddings_bge_large_en_v1.5.npz", ids=np.array(ids, dtype=object), vectors=V,
         model=MODEL, note="no query instruction prefix; normalize_embeddings=True")
print("embedded", len(ids), V.shape)
