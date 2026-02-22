from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import logging

from app.rag.retrieve import rewrite_query, retrieve_debug

logging.basicConfig(level=logging.INFO)

TEST_QUERIES = [
    "Combien coûte un communiqué ?",
    "Prix communiqué",
    "Communiqué 600",
]
EXPECTED_TOKENS = ("communiqué", "communique", "600", "prix", "tarif")


if __name__ == "__main__":
    for query in TEST_QUERIES:
        print("=" * 80)
        rewritten = rewrite_query(query)
        print(f"Query: {query}")
        print(f"Rewritten: {rewritten}")
        results = retrieve_debug(query, k=10)
        correct_in_top10 = False
        for idx, chunk in enumerate(results, start=1):
            content = chunk.content.replace("\n", " ")
            metadata = {k: v for k, v in chunk.payload.items() if k != "content"}
            print(f"[{idx}] score={chunk.score:.4f} id={chunk.point_id}")
            print(f"metadata={metadata}")
            print(f"chunk={content[:320]}")
            if any(token in content.lower() for token in EXPECTED_TOKENS):
                correct_in_top10 = True
        print(f"correct_chunk_in_top10={correct_in_top10}")
