"""OpenAI embedding provider implementation."""

from openai import OpenAI

from .base import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI text-embedding-3-small provider."""

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self._model = "text-embedding-3-small"
        self._dimension = 1536

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for single text."""
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        response = self.client.embeddings.create(
            model=self._model,
            input=text
        )
        return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        # Filter empty texts and track indices
        valid_texts = []
        valid_indices = []
        for i, text in enumerate(texts):
            if text and text.strip():
                valid_texts.append(text)
                valid_indices.append(i)

        if not valid_texts:
            return [[] for _ in texts]

        response = self.client.embeddings.create(
            model=self._model,
            input=valid_texts
        )

        # Map results back to original positions
        results: list[list[float]] = [[] for _ in texts]
        for idx, embedding_data in zip(valid_indices, response.data):
            results[idx] = embedding_data.embedding

        return results

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model
