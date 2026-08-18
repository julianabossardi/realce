"""
Indexacao (Secao 4.5 do brief, revisao 2) - substitui o antigo
`embed_and_load.py`.

Le `ingestion/data/extracted_manifest.json` (gerado por `extract.py`) e
`ingestion/data/quarentena.json`. Para cada documento com extracao ok:

    1. calcula o hash SHA-256 do PDF original (linhagem - Secao 4.8)
    2. anonimiza o texto INTEIRO do documento, usando as categorias de
       sigilo ATIVAS lidas de `categoria_sigilo` (Secao 4.3) - pseudonimos
       consistentes por entidade, gravados em `entidades_mascaradas`
    3. classifica o nivel de restricao do documento (regra simples para a
       PoC - ver `_classificar_nivel_restricao`)
    4. extrai metadados leves (`ingestion/metadata.py`) - pre-filtro de busca
    5. faz chunking do texto anonimizado, com offset de caracteres e
       metadados de linhagem por chunk (metodo de extracao + versao,
       modelo de embeddings)
    6. gera embeddings locais (BAAI/bge-m3) por chunk
    7. insere `documentos` e `chunks` no Postgres local

Documentos em quarentena (extract.py) sao gravados na tabela `quarentena`,
nao em `documentos`/`chunks`.

Uso:
    python index.py
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pdfplumber  # noqa: E402

from app.anonymize import Categoria, anonimizar_documento  # noqa: E402
from app.db import get_connection  # noqa: E402
from app.embeddings import MODEL_NAME as EMBEDDING_MODEL_NAME  # noqa: E402
from app.embeddings import embed_textos  # noqa: E402
from ingestion.metadata import extrair_metadados  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
EXTRACTED_MANIFEST_PATH = os.path.join(DATA_DIR, "extracted_manifest.json")
QUARENTENA_PATH = os.path.join(DATA_DIR, "quarentena.json")

CHUNK_SIZE_CHARS = 2000  # aprox. 500 tokens em portugues
CHUNK_OVERLAP_CHARS = 300
EMBED_BATCH_SIZE = 16

_PAGE_MARKER_RE = re.compile(r"<<PAGINA:(\d+)>>")

_VERSAO_METODO = {
    "pdfplumber": f"pdfplumber-{pdfplumber.__version__}",
    "ocr": f"pytesseract-{importlib.metadata.version('pytesseract')}",
    "ocr_baixa_confianca": f"pytesseract-{importlib.metadata.version('pytesseract')}",
}


def _hash_sha256(caminho_arquivo: str) -> str:
    h = hashlib.sha256()
    with open(caminho_arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(8192), b""):
            h.update(bloco)
    return h.hexdigest()


def _carregar_categorias_ativas(conn) -> list[Categoria]:
    with conn.cursor() as cur:
        cur.execute(
            "select id, nome, tipo_deteccao, padrao, nivel_restricao "
            "from categoria_sigilo where ativo = true"
        )
        return [Categoria(**row) for row in cur.fetchall()]


def _classificar_nivel_restricao(entidades) -> str:
    """Regra simples para a PoC (Secao 4.3): documentos sem nenhuma
    entidade sensivel sao publicos; com nomes de pessoa sao restritos; com
    CPF/RG (dado mais sensivel) sao sigilosos. Em producao essa marcacao
    viria de regra de negocio validada com o MPRJ, nao de heuristica."""
    categorias_presentes = {e.categoria_nome for e in entidades}
    if categorias_presentes & {"CPF", "RG"}:
        return "sigiloso"
    if "PESSOA" in categorias_presentes:
        return "restrito"
    return "publico"


def montar_texto_com_marcadores(paginas: list[dict]) -> str:
    partes = []
    for p in paginas:
        partes.append(f"<<PAGINA:{p['pagina']}>>{p['texto']}")
    return "\n\n".join(partes)


def chunkar_texto_anonimizado(texto_com_marcadores: str, metodo_por_pagina: dict[int, str]) -> list[dict]:
    """Divide o texto anonimizado em chunks de ~CHUNK_SIZE_CHARS caracteres
    com sobreposicao, preservando pagina de origem e offset de caracteres
    (linhagem - Secao 4.8) de cada chunk."""
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
        bruto = texto_limpo[start:end]
        trecho = bruto.strip()
        if trecho:
            offset_inicio = start + (len(bruto) - len(bruto.lstrip()))
            pagina = pagina_no_offset(offset_inicio)
            metodo = metodo_por_pagina.get(pagina, "pdfplumber")
            chunks.append(
                {
                    "texto": trecho,
                    "pagina": pagina,
                    "metodo_extracao": metodo,
                    "metodo_extracao_versao": _VERSAO_METODO.get(metodo, metodo),
                    "offset_inicio": offset_inicio,
                    "offset_fim": offset_inicio + len(trecho),
                }
            )
        if end == len(texto_limpo):
            break
        start = end - CHUNK_OVERLAP_CHARS

    return chunks


def carregar_quarentena(conn) -> None:
    if not os.path.exists(QUARENTENA_PATH):
        return
    with open(QUARENTENA_PATH, encoding="utf-8") as f:
        quarentena = json.load(f)
    if not quarentena:
        return

    with conn.cursor() as cur:
        for q in quarentena:
            cur.execute(
                "select id from quarentena where arquivo_local = %s", (q["arquivo_local"],)
            )
            if cur.fetchone():
                continue
            cur.execute(
                """
                insert into quarentena
                    (arquivo_local, municipio, territory_id, tipo_erro, mensagem_erro, metodo_que_falhou)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    q["arquivo_local"],
                    q.get("municipio"),
                    q.get("territory_id"),
                    q["tipo_erro"],
                    q.get("mensagem_erro"),
                    q.get("metodo_que_falhou"),
                ),
            )
    print(f"Quarentena: {len(quarentena)} documento(s) registrado(s).")


def carregar_documento(conn, doc: dict, categorias: list[Categoria]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "select id from documentos where arquivo_local = %s", (doc["arquivo_local"],)
        )
        if cur.fetchone():
            print(f"  [ja carregado] {doc['arquivo_local']}")
            return

    pdf_path = os.path.join(DATA_DIR, doc["arquivo_local"])
    hash_sha256 = _hash_sha256(pdf_path)

    metodo_por_pagina = {p["pagina"]: p["metodo"] for p in doc["paginas"]}

    texto_bruto = montar_texto_com_marcadores(doc["paginas"])
    texto_anonimizado, entidades = anonimizar_documento(texto_bruto, categorias)

    nivel_restricao = _classificar_nivel_restricao(entidades)
    metadados = extrair_metadados(texto_anonimizado)

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
                 arquivo_local, hash_sha256, num_paginas, tipo_documento,
                 metodo_extracao_predominante, qualidade_extracao, nivel_restricao)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                doc["municipio"],
                doc["territory_id"],
                doc["data"],
                doc.get("edicao") or None,
                doc["url_origem"],
                doc["arquivo_local"],
                hash_sha256,
                doc["num_paginas"],
                metadados["tipo_documento"],
                doc["metodo_extracao_predominante"],
                json.dumps(qualidade_extracao, ensure_ascii=False),
                nivel_restricao,
            ),
        )
        documento_id = cur.fetchone()["id"]

        if entidades:
            categoria_id_por_nome = {c.nome: c.id for c in categorias}
            cur.executemany(
                """
                insert into entidades_mascaradas
                    (documento_id, categoria_id, pseudonimo, valor_original, offset_inicio)
                values (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        documento_id,
                        categoria_id_por_nome[e.categoria_nome],
                        e.pseudonimo,
                        e.valor_original,
                        e.offset_inicio,
                    )
                    for e in entidades
                ],
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
            insert into chunks
                (documento_id, indice, pagina, offset_inicio, offset_fim, texto,
                 metodo_extracao, metodo_extracao_versao, embedding_modelo, embedding)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    documento_id,
                    i,
                    c["pagina"],
                    c["offset_inicio"],
                    c["offset_fim"],
                    c["texto"],
                    c["metodo_extracao"],
                    c["metodo_extracao_versao"],
                    EMBEDDING_MODEL_NAME,
                    embeddings[i],
                )
                for i, c in enumerate(chunks)
            ],
        )

    print(
        f"  [ok] {doc['arquivo_local']} -> {len(chunks)} chunks, {len(entidades)} entidades "
        f"mascaradas, restricao={nivel_restricao}, tipo={metadados['tipo_documento']}"
    )


def main():
    with open(EXTRACTED_MANIFEST_PATH, encoding="utf-8") as f:
        documentos = json.load(f)

    conn = get_connection()
    try:
        carregar_quarentena(conn)

        categorias = _carregar_categorias_ativas(conn)
        if not categorias:
            raise RuntimeError(
                "Nenhuma categoria_sigilo ativa encontrada - rode as migrations "
                "(db/migrations/0002_seed_categorias_sigilo.sql)."
            )

        print(f"Carregando {len(documentos)} documentos no Postgres local...")
        for doc in documentos:
            try:
                carregar_documento(conn, doc, categorias)
            except Exception as exc:  # noqa: BLE001
                print(f"  [erro] {doc['arquivo_local']}: {exc}")
    finally:
        conn.close()

    print("Concluido.")


if __name__ == "__main__":
    main()
