"""Retrieve the most relevant PubMed chunks from MongoDB.

This file does not use an LLM. It only:
1. Embeds the user's question.
2. Compares that embedding with stored chunk embeddings.
3. Returns the top matching chunks.

Run a quick test from the project root:

    python src/retriever.py "What is vitamin D deficiency in pregnancy?"
"""

from __future__ import annotations

import argparse
import heapq
import math
from typing import Any

from tqdm import tqdm

try:
    from src.database import get_chunks_collection, get_mongo_client, ping_mongodb
    from src.embeddings import EmbeddingModel
except ModuleNotFoundError:  # Allows: python src/retriever.py
    from database import get_chunks_collection, get_mongo_client, ping_mongodb  # type: ignore
    from embeddings import EmbeddingModel  # type: ignore


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """Calculate cosine similarity between two vectors.

    Cosine similarity is high when two vectors point in the same direction.
    For semantic search, a higher score usually means the text is more relevant
    to the question.
    """

    if not vector_a or not vector_b:
        return 0.0

    dot_product = 0.0
    norm_a = 0.0
    norm_b = 0.0

    for value_a, value_b in zip(vector_a, vector_b):
        dot_product += value_a * value_b
        norm_a += value_a * value_a
        norm_b += value_b * value_b

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot_product / (math.sqrt(norm_a) * math.sqrt(norm_b))


def format_result(document: dict[str, Any], score: float) -> dict[str, Any]:
    """Keep only the fields the RAG chain needs."""

    return {
        "text": document.get("text", ""),
        "score": float(score),
        "metadata": document.get("metadata", {}),
        "chunk_hash": document.get("chunk_hash"),
    }


def retrieve_similar_chunks(question: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Return the top_k MongoDB chunks most similar to the user question."""

    question = question.strip()
    if not question:
        raise ValueError("Question cannot be empty.")

    print("Embedding user question...")
    embedding_model = EmbeddingModel()
    question_embedding = embedding_model.embed_text(question)

    client = get_mongo_client()
    ping_mongodb(client)
    collection = get_chunks_collection(client)

    query_filter = {"embedding": {"$exists": True}}
    projection = {
        "text": 1,
        "embedding": 1,
        "metadata": 1,
        "chunk_hash": 1,
    }

    total_chunks = collection.count_documents(query_filter)
    if total_chunks == 0:
        client.close()
        return []

    # A small heap lets us keep only the best top_k chunks instead of sorting
    # every document after the scan.
    best_matches: list[tuple[float, int, dict[str, Any]]] = []
    counter = 0

    cursor = collection.find(query_filter, projection)
    try:
        for document in tqdm(
            cursor,
            total=total_chunks,
            desc="Searching chunks",
            unit="chunk",
        ):
            chunk_embedding = document.get("embedding")
            if not chunk_embedding:
                continue

            score = cosine_similarity(question_embedding, chunk_embedding)
            result = format_result(document, score)

            heap_item = (score, counter, result)
            counter += 1

            if len(best_matches) < top_k:
                heapq.heappush(best_matches, heap_item)
            elif score > best_matches[0][0]:
                heapq.heapreplace(best_matches, heap_item)
    finally:
        cursor.close()
        client.close()

    best_matches.sort(key=lambda item: item[0], reverse=True)
    return [item[2] for item in best_matches]


def print_retrieved_chunks(chunks: list[dict[str, Any]]) -> None:
    """Print retrieved chunks in a readable format for debugging."""

    if not chunks:
        print("No chunks found.")
        return

    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.get("metadata", {})
        print(f"\nChunk {index}")
        print(f"Score: {chunk['score']:.4f}")
        print(f"PMID: {metadata.get('pmid')}")
        print(f"Title: {metadata.get('title')}")
        print(f"Text: {chunk.get('text', '')}")


def parse_args() -> argparse.Namespace:
    """Read the question from the command line."""

    parser = argparse.ArgumentParser(description="Retrieve PubMed chunks.")
    parser.add_argument("question", help="Question to search for.")
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of chunks to retrieve.",
    )
    return parser.parse_args()


def main() -> None:
    """Command line entry point for testing retrieval."""

    args = parse_args()
    chunks = retrieve_similar_chunks(args.question, top_k=args.top_k)
    print_retrieved_chunks(chunks)


if __name__ == "__main__":
    main()
