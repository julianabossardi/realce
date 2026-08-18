"""
Embeddings locais (Secao 4.2/5 do brief) via sentence-transformers.

Modelo: BAAI/bge-m3 - multilingue, bom desempenho em portugues, roda em CPU
(sem GPU dedicada necessaria para o volume desta PoC), baixado uma unica vez
na primeira execucao e cacheado localmente pelo huggingface_hub. Nenhuma
chamada de rede acontece depois disso.

Dimensao do vetor: 1024 (ver db/migrations - coluna `embedding vector(1024)`).
"""
from __future__ import annotations

from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-m3"

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_textos(textos: list[str]) -> list[list[float]]:
    """Embeddings para documentos/chunks (indexacao)."""
    model = _get_model()
    vetores = model.encode(textos, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vetores]


def embed_consulta(consulta: str) -> list[float]:
    """Embedding para a consulta do usuario (busca)."""
    model = _get_model()
    vetor = model.encode([consulta], normalize_embeddings=True, show_progress_bar=False)[0]
    return vetor.tolist()
