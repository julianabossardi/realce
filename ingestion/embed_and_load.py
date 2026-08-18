"""
Chunking + anonimizacao + embeddings locais + carga no Postgres local
(Secoes 4.1.1 e 4.2 do brief).

Le ingestion/data/extracted_manifest.json (gerado por extract.py). Para cada
documento:
    1. concatena o texto das paginas (com marcador de pagina)
    2. anonimiza o texto INTEIRO do documento (Secao 4.1.1 - acontece na
       ingestao, para todo documento, nao sob demanda)
    3. grava o mapeamento mascarado->original em `entidades_mascaradas`
    4. faz chunking do texto ja anonimizado
    5. gera embeddings locais (BAAI/bge-m3) por chunk
    6. insere `documentos` e `chunks` no Postgres local

Uso:
    python embed_and_load.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.anonymize import anonimizar_documento  # noqa: E402
from app.db import get_connection  # noqa: E402
from app.embeddings import embed_textos  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
EXTRACTED_MANIFEST_PATH = os.path.join(DATA_DIR, "extracted_manifest.json")

CHUNK_SIZE_CHARS = 2000  # aprox. 500 tokens em portugues
CHUNK_OVERLAP_CHARS = 300
EMBED_BATCH_SIZE = 16

_PAGE_MARKER_RE = re.compile(r"<<PAGINA:(\d+)>>")


def montar_texto_com_marcadores(paginas: list[dict]) -> str:
    partes = []
    for p in paginas:
        partes.append(f"<<PAGINA:{p['pagina']}>>{p['texto']}")
    return "\n\n".join(partes)


def chunkar_texto_anonimizado(texto_com_marcadores: str, metodo_por_pagina: dict[int, str]) -> list[dict]:
    """Divide o texto anonimizado (que ainda carrega os marcadores de
    pagina) em chunks de ~CHUNK_SIZE_CHARS caracteres com sobreposicao,
    preservando a pagina de origem de cada chunk para rastreabilidade."""
    # remove marcadores do texto, guardando os offsets de pagina
    limpo = []
    offsets_pagina = []  # (offset_no_texto_limpo, pagina)
    cursor = 0
    pagina_atual = None
    for match in _PAGE_MARKER_RE.finditer(texto_com_marcadores):
        pagina_atual = int(match.group(1))
        trecho_antes = texto_com_marcadores[cursor:match.start()]
        limpo.append(trecho_antes)
        offsets_pagina.append((sum(len(s) for s in limpo), pagina_atual))
        cursor = match.end()
    limpo.append(texto_com_marcadores[cursor:])
    texto_limpo = "".join(limpo)

    def pagina_no_offset(offset: int) -> int:
        pagina = offsets_pagina[0][1] if offsets_pagina else 1
        for off, pag in offsets_pagina:
            if off <= offset:
                pagina = pag
            else:
                break
        return pagina

    chunks = []
    start = 0
    while start < len(texto_limpo):
        end = min(start + CHUNK_SIZE_CHARS, len(texto_limpo))
        trecho = texto_limpo[start:end].strip()
        if trecho:
            pagina = pagina_no_offset(start)
            chunks.append(
                {
                    "texto": trecho,
                    "pagina": pagina,
                    "metodo_extracao": metodo_por_pagina.get(pagina, "pdfplumber"),
                }
            )
        if end == len(texto_limpo):
            break
        start = end - CHUNK_OVERLAP_CHARS

    return chunks


def carregar_documento(conn, doc: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "select id from documentos where arquivo_local = %s", (doc["arquivo_local"],)
        )
        if cur.fetchone():
            print(f"  [ja carregado] {doc['arquivo_local']}")
            return

    metodo_por_pagina = {p["pagina"]: p["metodo"] for p in doc["paginas"]}

    texto_bruto = montar_texto_com_marcadores(doc["paginas"])
    texto_anonimizado, entidades = anonimizar_documento(texto_bruto)

    qualidade_extracao = {
        "paginas": [
            {"pagina": p["pagina"], "metodo": p["metodo"], "tem_tabela": p["tem_tabela"]}
            for p in doc["paginas"]
        ]
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            insert into documentos
                (municipio, territory_id, data_publicacao, edicao, url_origem,
                 arquivo_local, num_paginas, metodo_extracao_predominante, qualidade_extracao)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                doc["municipio"],
                doc["territory_id"],
                doc["data"],
                doc.get("edicao") or None,
                doc["url_origem"],
                doc["arquivo_local"],
                doc["num_paginas"],
                doc["metodo_extracao_predominante"],
                json.dumps(qualidade_extracao, ensure_ascii=False),
            ),
        )
        documento_id = cur.fetchone()["id"]

        if entidades:
            cur.executemany(
                """
                insert into entidades_mascaradas (documento_id, tipo_entidade, placeholder, valor_original)
                values (%s, %s, %s, %s)
                """,
                [(documento_id, e.tipo_entidade, e.placeholder, e.valor_original) for e in entidades],
            )

    chunks = chunkar_texto_anonimizado(texto_anonimizado, metodo_por_pagina)
    if not chunks:
        print(f"  [sem conteudo apos chunking] {doc['arquivo_local']}")
        return

    embeddings = []
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = [c["texto"] for c in chunks[i:i + EMBED_BATCH_SIZE]]
        embeddings.extend(embed_textos(batch))

    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into chunks (documento_id, indice, pagina, texto, metodo_extracao, embedding)
            values (%s, %s, %s, %s, %s, %s)
            """,
            [
                (documento_id, i, c["pagina"], c["texto"], c["metodo_extracao"], embeddings[i])
                for i, c in enumerate(chunks)
            ],
        )

    print(f"  [ok] {doc['arquivo_local']} -> {len(chunks)} chunks, {len(entidades)} entidades mascaradas")


def main():
    with open(EXTRACTED_MANIFEST_PATH, encoding="utf-8") as f:
        documentos = json.load(f)

    print(f"Carregando {len(documentos)} documentos no Postgres local...")
    conn = get_connection()
    try:
        for doc in documentos:
            try:
                carregar_documento(conn, doc)
            except Exception as exc:  # noqa: BLE001
                print(f"  [erro] {doc['arquivo_local']}: {exc}")
    finally:
        conn.close()

    print("Concluido.")


if __name__ == "__main__":
    main()
