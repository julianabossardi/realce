"""
Deteccao de conteudo padronizado (formularios, anexos e declaracoes que se
repetem identicamente entre documentos) - adendo tecnico pos-deploy, item
4. Roda em DUAS fases porque a decisao "esse chunk se repete em muitos
documentos DISTINTOS" so pode ser tomada depois que TODOS os chunks do
acervo ja existem em memoria - ao contrario das demais etapas do
pipeline, nao da para decidir isso documento a documento.

Marca, nao exclui: chunks padronizados continuam na tabela `chunks`,
acessiveis via `/documentos/{id}/completo` e na exploracao livre do
acervo - so saem do ranking da busca priorizada por padrao (ver
`app/search.py`, `db/migrations/0007_normalizacao_enriquecimento.sql`).
"""
from __future__ import annotations

import hashlib
import re

from ingestion.normalize import MARCADOR_CAMPO_PREENCHIMENTO

_PLACEHOLDER_RE = re.compile(r"\[[A-Z]+_[A-Z]+\]")
_ESPACOS_RE = re.compile(r"\s+")

LIMIAR_DOCUMENTOS_DISTINTOS = 5  # chunk aparece (mesmo hash) em >= N documentos -> padronizado
LIMIAR_OCORRENCIAS_CAMPO = 4  # >= N marcadores de campo de preenchimento no chunk...
LIMIAR_DENSIDADE_CAMPO = 0.15  # ...e essa densidade (marcadores / palavras uteis) -> padronizado


def hash_normalizado(texto_chunk: str) -> str:
    """Hash usado para AGRUPAR chunks estruturalmente identicos entre
    documentos - generaliza pseudonimos de anonimizacao (`[PESSOA_A]` vs
    `[PESSOA_B]` no mesmo campo de um formulario, em documentos
    diferentes, nao podem impedir o agrupamento) e colapsa espacos antes
    de calcular o sha256."""
    generico = _PLACEHOLDER_RE.sub("[X]", texto_chunk)
    generico = _ESPACOS_RE.sub(" ", generico).strip().lower()
    return hashlib.sha256(generico.encode("utf-8")).hexdigest()


def parece_formulario(texto_chunk: str) -> bool:
    """Heuristica de densidade: chunk dominado por campos de preenchimento
    vazios (marcador `[CAMPO]` de `ingestion/normalize.py`) em vez de
    texto util - tipico de anexo/declaracao padrao mesmo quando ainda nao
    se repetiu o bastante entre documentos para o hash pegar (ex: primeiro
    documento do municipio a usar aquele formulario)."""
    ocorrencias = texto_chunk.count(MARCADOR_CAMPO_PREENCHIMENTO)
    if ocorrencias < LIMIAR_OCORRENCIAS_CAMPO:
        return False
    texto_sem_campo = texto_chunk.replace(MARCADOR_CAMPO_PREENCHIMENTO, "")
    palavras_uteis = texto_sem_campo.split()
    densidade = ocorrencias / max(len(palavras_uteis), 1)
    return densidade > LIMIAR_DENSIDADE_CAMPO


def marcar_padronizados(chunks_por_documento: dict[str, list[dict]]) -> int:
    """Recebe {documento_id: [chunk, ...]} com todos os chunks do acervo
    (cada chunk precisa ter `id` e `texto`; `hash_normalizado` e calculado
    aqui se ainda nao estiver presente) e marca `eh_padronizado=True`
    IN-PLACE nos dicts que atingem o limiar de recorrencia entre
    documentos ou a heuristica de densidade de campo. Devolve o total de
    chunks marcados - quem chama e responsavel por persistir (UPDATE em
    lote) no Postgres."""
    for chunks in chunks_por_documento.values():
        for c in chunks:
            c.setdefault("hash_normalizado", hash_normalizado(c["texto"]))
            c.setdefault("eh_padronizado", False)

    contagem_docs_por_hash: dict[str, set[str]] = {}
    for doc_id, chunks in chunks_por_documento.items():
        for c in chunks:
            contagem_docs_por_hash.setdefault(c["hash_normalizado"], set()).add(doc_id)

    hashes_repetidos = {h for h, docs in contagem_docs_por_hash.items() if len(docs) >= LIMIAR_DOCUMENTOS_DISTINTOS}

    total_marcados = 0
    for chunks in chunks_por_documento.values():
        for c in chunks:
            if c["hash_normalizado"] in hashes_repetidos or parece_formulario(c["texto"]):
                c["eh_padronizado"] = True
                total_marcados += 1
    return total_marcados
