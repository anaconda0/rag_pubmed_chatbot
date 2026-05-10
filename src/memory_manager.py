"""Chatbot memory management.

This module has two kinds of memory:

1. Short-term memory
   - Stored only in Python while the app is running.
   - Keeps the last 20 messages in the current session.
   - Each message is a simple role/content pair.

2. Long-term memory
   - Stored in MongoDB.
   - Each message gets an embedding so old messages can be searched by meaning.
   - Retrieval uses cosine similarity, just like the dataset retriever.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import heapq
import math
import os
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from tqdm import tqdm

try:
    from src.config import MONGO_DATABASE_NAME
    from src.database import get_mongo_client, ping_mongodb
    from src.embeddings import EmbeddingModel
except ModuleNotFoundError:  # Allows: python src/memory_manager.py
    from config import MONGO_DATABASE_NAME  # type: ignore
    from database import get_mongo_client, ping_mongodb  # type: ignore
    from embeddings import EmbeddingModel  # type: ignore


SHORT_TERM_MEMORY_LIMIT = 20
LONG_TERM_MEMORY_TOP_K = 5
MEMORY_COLLECTION_NAME = os.getenv("MONGO_MEMORY_COLLECTION_NAME", "chat_memory")
VALID_ROLES = {"user", "assistant"}


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """Calculate cosine similarity between two embedding vectors."""

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


class ChatMemoryManager:
    """Manage short-term and long-term chatbot memory."""

    def __init__(
        self,
        session_id: str = "default",
        short_term_limit: int = SHORT_TERM_MEMORY_LIMIT,
    ) -> None:
        self.session_id = session_id
        self.short_term_messages: deque[dict[str, str]] = deque(
            maxlen=short_term_limit
        )
        self.embedding_model: EmbeddingModel | None = None

    def get_embedding_model(self) -> EmbeddingModel:
        """Load the embedding model once and reuse it."""

        if self.embedding_model is None:
            self.embedding_model = EmbeddingModel()

        return self.embedding_model

    def get_memory_collection(self) -> Collection:
        """Return the MongoDB collection used for long-term chat memory."""

        client = get_mongo_client()
        ping_mongodb(client)
        database = client[MONGO_DATABASE_NAME]
        collection = database[MEMORY_COLLECTION_NAME]
        ensure_memory_indexes(collection)
        return collection

    def add_message(
        self,
        role: str,
        content: str,
        save_to_long_term: bool = True,
    ) -> str | None:
        """Add one message to short-term memory and optionally MongoDB."""

        role = role.strip().lower()
        content = content.strip()

        if role not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {sorted(VALID_ROLES)}")

        if not content:
            return None

        # Short-term memory intentionally stays simple: role/content pairs.
        self.short_term_messages.append(
            {
                "role": role,
                "content": content,
            }
        )

        if save_to_long_term:
            return self.save_message_to_mongodb(role, content)

        return None

    def add_user_message(self, content: str) -> str | None:
        """Convenience helper for storing a user message."""

        return self.add_message("user", content)

    def add_assistant_message(self, content: str) -> str | None:
        """Convenience helper for storing an assistant message."""

        return self.add_message("assistant", content)

    def get_short_term_messages(self) -> list[dict[str, str]]:
        """Return the last 20 messages in the current Python session."""

        return list(self.short_term_messages)

    def clear_short_term_memory(self) -> None:
        """Clear only the current session's short-term memory."""

        self.short_term_messages.clear()

    def save_message_to_mongodb(self, role: str, content: str) -> str:
        """Embed and store a chat message in MongoDB."""

        embedding_model = self.get_embedding_model()
        embedding = embedding_model.embed_text(content)

        collection = self.get_memory_collection()
        document = {
            "session_id": self.session_id,
            "role": role,
            "content": content,
            "embedding": embedding,
            "created_at": datetime.now(timezone.utc),
        }

        result = collection.insert_one(document)

        # Close the MongoDB client created by get_memory_collection().
        collection.database.client.close()

        return str(result.inserted_id)

    def retrieve_relevant_memories(
        self,
        query: str,
        top_k: int = LONG_TERM_MEMORY_TOP_K,
    ) -> list[dict[str, Any]]:
        """Find older chat messages that are semantically related to a query."""

        query = query.strip()
        if not query:
            return []

        collection = self.get_memory_collection()
        query_filter = {
            "session_id": self.session_id,
            "embedding": {"$exists": True},
        }

        total_messages = collection.count_documents(query_filter)
        if total_messages == 0:
            collection.database.client.close()
            return []

        embedding_model = self.get_embedding_model()
        query_embedding = embedding_model.embed_text(query)

        projection = {
            "session_id": 1,
            "role": 1,
            "content": 1,
            "embedding": 1,
            "created_at": 1,
        }

        best_matches: list[tuple[float, int, dict[str, Any]]] = []
        counter = 0
        cursor = collection.find(query_filter, projection)

        try:
            for document in tqdm(
                cursor,
                total=total_messages,
                desc="Searching memory",
                unit="message",
            ):
                message_embedding = document.get("embedding")
                if not message_embedding:
                    continue

                score = cosine_similarity(query_embedding, message_embedding)
                result = format_memory_result(document, score)
                heap_item = (score, counter, result)
                counter += 1

                if len(best_matches) < top_k:
                    heapq.heappush(best_matches, heap_item)
                elif score > best_matches[0][0]:
                    heapq.heapreplace(best_matches, heap_item)
        finally:
            cursor.close()
            collection.database.client.close()

        best_matches.sort(key=lambda item: item[0], reverse=True)
        return [item[2] for item in best_matches]


def ensure_memory_indexes(collection: Collection) -> None:
    """Create helpful indexes for long-term memory."""

    collection.create_index(
        [("session_id", ASCENDING), ("created_at", DESCENDING)],
        name="memory_session_created_at_index",
    )
    collection.create_index(
        [("role", ASCENDING)],
        name="memory_role_index",
    )


def format_memory_result(
    document: dict[str, Any],
    score: float,
) -> dict[str, Any]:
    """Convert a MongoDB memory document into a simple result dictionary."""

    created_at = document.get("created_at")
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()

    return {
        "memory_id": str(document.get("_id")),
        "session_id": document.get("session_id"),
        "role": document.get("role"),
        "content": document.get("content", ""),
        "score": float(score),
        "created_at": created_at,
    }


# This default manager is useful for simple scripts and the future UI.
# In Gradio, keeping this object alive will preserve short-term memory while
# the app process is running.
default_memory_manager = ChatMemoryManager()
