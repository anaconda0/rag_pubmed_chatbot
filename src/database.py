"""MongoDB helper functions for storing embedded chunks."""

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, MongoClient, UpdateOne
from pymongo.collection import Collection
from pymongo.errors import ServerSelectionTimeoutError

try:
    from src.config import (
        MONGO_COLLECTION_NAME,
        MONGO_DATABASE_NAME,
        MONGO_SERVER_SELECTION_TIMEOUT_MS,
        MONGO_URI,
    )
except ModuleNotFoundError:  # Allows: python src/ingest.py
    from config import (  # type: ignore
        MONGO_COLLECTION_NAME,
        MONGO_DATABASE_NAME,
        MONGO_SERVER_SELECTION_TIMEOUT_MS,
        MONGO_URI,
    )


def get_mongo_client() -> MongoClient:
    """Create a MongoDB client.

    The client connects lazily, so we call ping_mongodb() before ingestion to
    make sure MongoDB is actually reachable.
    """

    return MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS,
    )


def ping_mongodb(client: MongoClient) -> None:
    """Raise a clear error if MongoDB is not running or not reachable."""

    try:
        client.admin.command("ping")
    except ServerSelectionTimeoutError as exc:
        raise RuntimeError(
            "Could not connect to MongoDB. Make sure MongoDB is running and "
            f"MONGO_URI is correct. Current MONGO_URI: {MONGO_URI}"
        ) from exc


def get_chunks_collection(client: MongoClient | None = None) -> Collection:
    """Return the MongoDB collection used to store RAG chunks."""

    mongo_client = client or get_mongo_client()
    database = mongo_client[MONGO_DATABASE_NAME]
    return database[MONGO_COLLECTION_NAME]


def ensure_indexes(collection: Collection) -> None:
    """Create indexes used by the ingestion and future retrieval code."""

    # chunk_hash is unique so the same chunk cannot be inserted twice.
    collection.create_index(
        [("chunk_hash", ASCENDING)],
        unique=True,
        name="unique_chunk_hash",
    )

    # These indexes are useful for filtering/debugging stored chunks.
    collection.create_index(
        [("metadata.source_file", ASCENDING)],
        name="source_file_index",
    )
    collection.create_index(
        [("metadata.row_index", ASCENDING)],
        name="row_index_index",
    )


def chunk_exists(collection: Collection, chunk_hash: str) -> bool:
    """Return True when a chunk hash already exists in MongoDB."""

    existing = collection.find_one({"chunk_hash": chunk_hash}, {"_id": 1})
    return existing is not None


def add_timestamps(document: dict[str, Any]) -> dict[str, Any]:
    """Add a created_at timestamp before inserting a document."""

    document["created_at"] = datetime.now(timezone.utc)
    return document


def upsert_chunk_documents(
    collection: Collection,
    documents: list[dict[str, Any]],
) -> int:
    """Insert chunk documents while skipping duplicates.

    Each document is matched by chunk_hash. If the hash already exists, MongoDB
    leaves the existing document unchanged. The return value is the number of
    newly inserted documents.
    """

    if not documents:
        return 0

    operations = []
    for document in documents:
        document = add_timestamps(document)
        operations.append(
            UpdateOne(
                {"chunk_hash": document["chunk_hash"]},
                {"$setOnInsert": document},
                upsert=True,
            )
        )

    result = collection.bulk_write(operations, ordered=False)
    return result.upserted_count
