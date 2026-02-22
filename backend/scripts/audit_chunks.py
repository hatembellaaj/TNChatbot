from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import json
import os
import re

import psycopg

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
JSON_ONLY_PATTERN = re.compile(r'^\s*[\[{].*[\]}]\s*$', re.DOTALL)


def main() -> None:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    with psycopg.connect(database_url) as conn:
        rows = conn.execute("SELECT id, content, token_count FROM kb_chunks").fetchall()

    total = len(rows)
    if total == 0:
        print("No chunks found")
        return

    token_sizes = []
    under_150 = []
    under_200 = 0
    json_only = []

    for row in rows:
        chunk_id, content, token_count = row
        tokens = token_count or len((content or "").split())
        token_sizes.append(tokens)
        if tokens < 150:
            under_150.append((str(chunk_id), tokens))
        if tokens < 200:
            under_200 += 1
        text = (content or "").strip()
        if text and JSON_ONLY_PATTERN.match(text):
            try:
                json.loads(text)
                json_only.append(str(chunk_id))
            except json.JSONDecodeError:
                pass

    avg = sum(token_sizes) / total
    under_200_pct = (under_200 / total) * 100

    print(f"total_chunks={total}")
    print(f"average_chunk_token_size={avg:.2f}")
    print(f"chunks_under_150={len(under_150)}")
    print(f"chunks_under_200_pct={under_200_pct:.2f}")
    print(f"json_only_chunks={len(json_only)}")

    if under_150:
        print("-- under_150 sample --")
        for chunk_id, size in under_150[:20]:
            print(f"{chunk_id} tokens={size}")

    if json_only:
        print("-- json_only sample --")
        for chunk_id in json_only[:20]:
            print(chunk_id)

    if under_200_pct > 30:
        print("RECOMMENDATION: rebuild index (more than 30% of chunks under 200 tokens).")
    else:
        print("RECOMMENDATION: rebuild not required based on chunk-size criterion.")


if __name__ == "__main__":
    main()
