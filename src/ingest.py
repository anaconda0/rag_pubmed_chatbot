"""Inspect and ingest the PubMed CSV dataset into MongoDB.

Run from the project root:

    python src/ingest.py --inspect-only
    python src/ingest.py --limit 100
    python src/ingest.py
"""

from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm

try:
    from src.chunking import clean_text, split_text_into_chunks
    from src.config import (
        CSV_FILE_NAME,
        DATA_DIR,
        MONGO_WRITE_BATCH_SIZE,
    )
    from src.database import (
        chunk_exists,
        ensure_indexes,
        get_chunks_collection,
        get_mongo_client,
        ping_mongodb,
        upsert_chunk_documents,
    )
    from src.embeddings import EmbeddingModel
except ModuleNotFoundError:  # Allows: python src/ingest.py
    from chunking import clean_text, split_text_into_chunks  # type: ignore
    from config import CSV_FILE_NAME, DATA_DIR, MONGO_WRITE_BATCH_SIZE  # type: ignore
    from database import (  # type: ignore
        chunk_exists,
        ensure_indexes,
        get_chunks_collection,
        get_mongo_client,
        ping_mongodb,
        upsert_chunk_documents,
    )
    from embeddings import EmbeddingModel  # type: ignore


TEXT_COLUMN_CANDIDATES = [
    "abstractText",
    "abstract",
    "Abstract",
    "summary",
    "text",
    "Text",
    "content",
    "body",
]

LIST_LABEL_COLUMNS = ["meshMajor", "meshroot", "labels", "Labels", "categories"]
SEARCH_COLUMNS = ["Title", "abstractText", "meshMajor", "meshroot"]


def find_csv_files(data_dir: Path = DATA_DIR) -> list[Path]:
    """Return all CSV files found in data/."""

    if not data_dir.exists():
        raise FileNotFoundError(f"Data folder not found: {data_dir}")

    return sorted(data_dir.glob("*.csv"))


def select_dataset_file(csv_name: str = CSV_FILE_NAME) -> Path:
    """Choose which CSV file to ingest.

    If PUBMED_CSV_FILE is set, that exact file is used. Otherwise:
    1. If only one CSV exists, use it.
    2. Prefer a file with "processed" in the name.
    3. Fall back to the largest CSV file.
    """

    if csv_name:
        csv_path = DATA_DIR / csv_name
        if not csv_path.exists():
            raise FileNotFoundError(f"Configured CSV file not found: {csv_path}")
        return csv_path

    csv_files = find_csv_files(DATA_DIR)
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in: {DATA_DIR}")

    if len(csv_files) == 1:
        return csv_files[0]

    processed_files = [
        path for path in csv_files if "processed" in path.name.lower()
    ]
    if processed_files:
        return max(processed_files, key=lambda path: path.stat().st_size)

    return max(csv_files, key=lambda path: path.stat().st_size)


def read_dataset(csv_path: Path, limit: int | None = None) -> pd.DataFrame:
    """Read the CSV into a pandas DataFrame."""

    return pd.read_csv(csv_path, low_memory=False, nrows=limit)


def filter_dataset_by_search(
    dataframe: pd.DataFrame,
    search_text: str,
) -> pd.DataFrame:
    """Keep rows where the topic appears in title, abstract, or labels."""

    search_text = search_text.strip()
    if not search_text:
        return dataframe

    existing_columns = [
        column for column in SEARCH_COLUMNS if column in dataframe.columns
    ]

    if not existing_columns:
        raise ValueError(
            f"None of the searchable columns were found: {SEARCH_COLUMNS}"
        )

    combined_text = (
        dataframe[existing_columns]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
    )
    mask = combined_text.str.contains(search_text, case=False, na=False)

    return dataframe.loc[mask].copy()


def detect_text_column(dataframe: pd.DataFrame) -> str:
    """Detect the column that most likely contains the main abstract text."""

    for column in TEXT_COLUMN_CANDIDATES:
        if column in dataframe.columns and dataframe[column].notna().any():
            return column

    best_column = None
    best_score = -1.0

    for column in dataframe.columns:
        series = dataframe[column].dropna().astype(str).head(100)
        if series.empty:
            continue

        average_length = series.str.len().mean()
        column_name = column.lower()

        score = float(average_length)
        if "abstract" in column_name or "text" in column_name:
            score += 500
        if column_name in {"title", "pmid", "meshmajor", "meshid", "meshroot"}:
            score -= 300

        if score > best_score:
            best_score = score
            best_column = column

    if best_column is None:
        raise ValueError("Could not detect a usable text column in the CSV.")

    return best_column


def inspect_dataset(dataframe: pd.DataFrame, csv_path: Path, text_column: str) -> None:
    """Print the dataset information requested by the user."""

    print("\nDataset inspection")
    print("------------------")
    print(f"File name: {csv_path.name}")
    print(f"Columns: {list(dataframe.columns)}")
    print("\nFirst 3 rows:")

    with pd.option_context("display.max_columns", None, "display.max_colwidth", 120):
        print(dataframe.head(3).to_string(index=False))

    print(f"\nDetected main text/abstract column: {text_column}")


def is_binary_label_column(dataframe: pd.DataFrame, column: str) -> bool:
    """Detect one-letter 0/1 label columns such as A, B, C, D."""

    if not (len(column) == 1 and column.isalpha() and column.isupper()):
        return False

    values = dataframe[column].dropna().unique()
    allowed_values = {0, 1, "0", "1"}
    return len(values) > 0 and set(values).issubset(allowed_values)


def detect_binary_label_columns(dataframe: pd.DataFrame) -> list[str]:
    """Return all detected single-letter multilabel columns."""

    return [
        column
        for column in dataframe.columns
        if is_binary_label_column(dataframe, column)
    ]


def parse_list_like_value(value: Any) -> list[Any]:
    """Parse values that look like Python lists inside the CSV."""

    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, float) and pd.isna(value):
        return []

    if not isinstance(value, str):
        return [value]

    value = value.strip()
    if not value:
        return []

    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return [value]

    if isinstance(parsed, list):
        return parsed

    return [parsed]


def to_python_value(value: Any) -> Any:
    """Convert pandas/numpy scalar values to plain Python values."""

    if value is None:
        return None

    if isinstance(value, float) and pd.isna(value):
        return None

    if hasattr(value, "item"):
        return value.item()

    return value


def extract_labels(
    row: pd.Series,
    binary_label_columns: list[str],
) -> dict[str, Any]:
    """Collect labels from the dataset row when label columns are available."""

    active_label_codes = []
    for column in binary_label_columns:
        if int(row.get(column, 0)) == 1:
            active_label_codes.append(column)

    labels: dict[str, Any] = {
        "active_label_codes": active_label_codes,
    }

    if "meshMajor" in row:
        labels["mesh_major"] = parse_list_like_value(row["meshMajor"])

    if "meshroot" in row:
        labels["mesh_root"] = parse_list_like_value(row["meshroot"])

    for column in LIST_LABEL_COLUMNS:
        if column in row and column not in {"meshMajor", "meshroot"}:
            labels[column] = parse_list_like_value(row[column])

    return labels


def make_chunk_hash(text: str) -> str:
    """Create a stable hash used to avoid duplicate chunks."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_chunk_document(
    chunk_text: str,
    embedding: list[float],
    chunk_hash: str,
    source_file: str,
    row_index: int,
    chunk_index: int,
    text_column: str,
    row: pd.Series,
    labels: dict[str, Any],
) -> dict[str, Any]:
    """Build the MongoDB document for one embedded chunk."""

    return {
        "text": chunk_text,
        "embedding": embedding,
        "chunk_hash": chunk_hash,
        "metadata": {
            "source_file": source_file,
            "row_index": row_index,
            "chunk_index": chunk_index,
            "text_column": text_column,
            "pmid": to_python_value(row.get("pmid")),
            "title": to_python_value(row.get("Title")),
            "labels": labels,
        },
    }


def flush_pending_chunks(
    pending_chunks: list[dict[str, Any]],
    embedding_model: EmbeddingModel,
    collection,
) -> int:
    """Embed pending chunks and write them to MongoDB."""

    if not pending_chunks:
        return 0

    texts = [item["text"] for item in pending_chunks]
    embeddings = embedding_model.embed_texts(texts)

    documents = []
    for item, embedding in zip(pending_chunks, embeddings):
        documents.append(
            build_chunk_document(
                chunk_text=item["text"],
                embedding=embedding,
                chunk_hash=item["chunk_hash"],
                source_file=item["source_file"],
                row_index=item["row_index"],
                chunk_index=item["chunk_index"],
                text_column=item["text_column"],
                row=item["row"],
                labels=item["labels"],
            )
        )

    return upsert_chunk_documents(collection, documents)


def ingest_dataset(
    limit: int | None = None,
    inspect_only: bool = False,
    csv_name: str = CSV_FILE_NAME,
    search_text: str = "",
) -> None:
    """Inspect the CSV and optionally ingest it into MongoDB."""

    csv_path = select_dataset_file(csv_name)

    # If searching by topic, read the full CSV first, filter matching rows,
    # then apply --limit to the matched rows.
    read_limit = None if search_text else limit
    dataframe = read_dataset(csv_path, limit=read_limit)

    if search_text:
        dataframe = filter_dataset_by_search(dataframe, search_text)
        print(f"\nRows matching '{search_text}': {len(dataframe)}")

        if limit is not None:
            dataframe = dataframe.head(limit)
            print(f"Using first {len(dataframe)} matched rows because --limit was set.")

        if dataframe.empty:
            print("No matching rows found. Nothing to ingest.")
            return

    text_column = detect_text_column(dataframe)
    inspect_dataset(dataframe, csv_path, text_column)

    if inspect_only:
        print("\nInspect-only mode enabled. No chunks were written to MongoDB.")
        return

    binary_label_columns = detect_binary_label_columns(dataframe)
    print(f"\nDetected binary label columns: {binary_label_columns}")

    client = get_mongo_client()
    ping_mongodb(client)
    collection = get_chunks_collection(client)
    ensure_indexes(collection)

    print("\nLoading sentence-transformers model...")
    embedding_model = EmbeddingModel()

    pending_chunks: list[dict[str, Any]] = []
    pending_hashes: set[str] = set()
    inserted_count = 0
    duplicate_count = 0
    empty_row_count = 0
    total_chunk_count = 0

    progress = tqdm(
        dataframe.iterrows(),
        total=len(dataframe),
        desc="Ingesting rows",
        unit="row",
    )

    for _, (original_index, row) in enumerate(progress):
        try:
            row_index = int(original_index)
        except (TypeError, ValueError):
            row_index = int(_)

        raw_text = row.get(text_column)
        cleaned_text = clean_text(raw_text)

        if not cleaned_text:
            empty_row_count += 1
            continue

        chunks = split_text_into_chunks(cleaned_text)
        labels = extract_labels(row, binary_label_columns)

        for chunk_index, chunk_text in enumerate(chunks):
            chunk_hash = make_chunk_hash(chunk_text)
            total_chunk_count += 1

            # Skip duplicates already seen in this run or already in MongoDB.
            if chunk_hash in pending_hashes or chunk_exists(collection, chunk_hash):
                duplicate_count += 1
                continue

            pending_hashes.add(chunk_hash)
            pending_chunks.append(
                {
                    "text": chunk_text,
                    "chunk_hash": chunk_hash,
                    "source_file": csv_path.name,
                    "row_index": row_index,
                    "chunk_index": chunk_index,
                    "text_column": text_column,
                    "row": row,
                    "labels": labels,
                }
            )

            if len(pending_chunks) >= MONGO_WRITE_BATCH_SIZE:
                inserted_count += flush_pending_chunks(
                    pending_chunks,
                    embedding_model,
                    collection,
                )
                pending_chunks.clear()
                pending_hashes.clear()

        progress.set_postfix(
            inserted=inserted_count,
            duplicates=duplicate_count,
            pending=len(pending_chunks),
        )

    inserted_count += flush_pending_chunks(
        pending_chunks,
        embedding_model,
        collection,
    )

    print("\nIngestion complete")
    print("------------------")
    print(f"Rows read: {len(dataframe)}")
    print(f"Empty text rows skipped: {empty_row_count}")
    print(f"Chunks created before duplicate checks: {total_chunk_count}")
    print(f"Duplicate chunks skipped: {duplicate_count}")
    print(f"New chunks inserted into MongoDB: {inserted_count}")

    client.close()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""

    parser = argparse.ArgumentParser(
        description="Inspect and ingest the PubMed multilabel CSV dataset."
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="Print dataset information without writing to MongoDB.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only ingest the first N rows. Useful for testing.",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=CSV_FILE_NAME,
        help="CSV file name inside data/. If omitted, the script auto-detects one.",
    )
    parser.add_argument(
        "--search",
        type=str,
        default="",
        help="Only ingest rows containing this text in title, abstract, or labels.",
    )
    return parser.parse_args()


def main() -> None:
    """Command line entry point."""

    args = parse_args()
    ingest_dataset(
        limit=args.limit,
        inspect_only=args.inspect_only,
        csv_name=args.csv,
        search_text=args.search,
    )


if __name__ == "__main__":
    main()
