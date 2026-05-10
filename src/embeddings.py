"""Sentence-transformers embedding helpers."""

from sentence_transformers import SentenceTransformer

try:
    from src.config import (
        EMBEDDING_BATCH_SIZE,
        EMBEDDING_DEVICE,
        EMBEDDING_MODEL_NAME,
    )
except ModuleNotFoundError:  # Allows: python src/ingest.py
    from config import (  # type: ignore
        EMBEDDING_BATCH_SIZE,
        EMBEDDING_DEVICE,
        EMBEDDING_MODEL_NAME,
    )


class EmbeddingModel:
    """Small wrapper around SentenceTransformer.

    Keeping model loading in one class makes the rest of the code easier to
    read and makes it simple to swap the model later.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME) -> None:
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device=EMBEDDING_DEVICE)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Convert a list of text chunks into embedding vectors."""

        if not texts:
            return []

        embeddings = self.model.encode(
            texts,
            batch_size=EMBEDDING_BATCH_SIZE,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        # MongoDB stores plain Python lists cleanly.
        return embeddings.tolist()

    def embed_text(self, text: str) -> list[float]:
        """Embed one text string."""

        return self.embed_texts([text])[0]
