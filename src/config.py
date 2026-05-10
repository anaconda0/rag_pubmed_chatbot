"""Project configuration.

Most values can be overridden from a .env file or from environment variables.
This keeps the code easy to run locally while still making it configurable.
"""

from pathlib import Path
import os

from dotenv import load_dotenv


# Load variables from a local .env file if one exists.
load_dotenv()


# Paths ---------------------------------------------------------------------

# src/config.py -> project root is one folder above src/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

# Leave empty to auto-detect a CSV in data/.
# Example .env value:
# PUBMED_CSV_FILE=PubMed Multi Label Text Classification Dataset Processed.csv
CSV_FILE_NAME = os.getenv("PUBMED_CSV_FILE", "").strip()


# MongoDB -------------------------------------------------------------------

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DATABASE_NAME = os.getenv("MONGO_DATABASE_NAME", "rag_pubmed_chatbot")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "pubmed_chunks")

# Keep the timeout short so connection mistakes fail quickly.
MONGO_SERVER_SELECTION_TIMEOUT_MS = int(
    os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000")
)


# Embeddings ----------------------------------------------------------------

# This model is small, fast, and works well for a first RAG pipeline.
# You can replace it with a biomedical sentence-transformers model later.
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/all-MiniLM-L6-v2",
)

# Leave empty for sentence-transformers to choose automatically.
# Example .env value: EMBEDDING_DEVICE=cpu
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "").strip() or None

EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))


# Chunking ------------------------------------------------------------------

# These are word counts, not character counts. Word-based chunking is simple
# and works well enough for this beginner-friendly pipeline.
CHUNK_SIZE_WORDS = int(os.getenv("CHUNK_SIZE_WORDS", "180"))
CHUNK_OVERLAP_WORDS = int(os.getenv("CHUNK_OVERLAP_WORDS", "40"))


# Ingestion -----------------------------------------------------------------

# Number of new chunks to embed and write to MongoDB at one time.
MONGO_WRITE_BATCH_SIZE = int(os.getenv("MONGO_WRITE_BATCH_SIZE", "64"))
