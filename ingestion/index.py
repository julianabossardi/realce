"""
Indexacao (Secao 4.5 do brief; camada de normalizacao/enriquecimento
adicionada no adendo tecnico pos-deploy) - substitui o antigo
`embed_and_load.py`.

Le `ingestion/data/extracted_manifest.json` (gerado por `extract.py`) e
`ingestion/data/quarentena.json`. Para cada documento com extracao ok:

    1. NORMALIZA o texto extraido por pagina (`ingestion/normalize.py`) -
       junta hifenizacao quebrada, colapsa quebras de linha/espacos,
       marca campos de preenchimento, remove cabecalho/rodape repetido
    2. calcula o hash SHA-256 do PDF original (linhagem - Secao 4.8)
    3. anonimiza o texto INTEIRO do documento (ja normalizado), usando as
       categorias de sigilo ATIVAS lidas de `categoria_sigilo` (Secao
       4.3) - pseudonimos consistentes por entidade, gravados em
       `entidades_mascaradas`
    4. classifica o nivel de restricao do documento (regra simples para a
       PoC - ver `_classificar_nivel_restricao`)
    5. extrai metadados leves (`ingestion/metadata.py`) - pre-filtro de busca
    6. faz chunking POR FRONTEIRA SEMANTICA (`ingestion/chunk.py`, nao
       mais por contagem bruta de caracteres), com offset de caracteres e
       metadados de linhagem por chunk (metodo de extracao + versao,
       modelo de embeddings)
    7. gera embeddings locais (BAAI/bge-m3) por chunk
    8. gera TITULO e SINTESE do documento (uma chamada ao LLM local POR
       DOCUMENTO, nao por chunk - `app/llm.py`); em caso de falha, recai
       sobre um nome legivel composto a partir de metadado
    9. insere `documentos` e `chunks` no Postgres local

Depois de processar TODOS os documentos, uma segunda fase
(`ingestion/dedupe.py`) marca como `eh_padronizado` os chunks que se
repetem (mesma estrutura, pseudonimos generalizados) em muitos documentos
distintos - formularios e anexos padrao, que saem do ranking de busca por
padrao mas continuam acessiveis (Secao 4.4).

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
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pdfplumber  # noqa: E402

from app.anonymize import Categoria, anonimizar_documento  # noqa: E402
from app.db import get_connection  # noqa: E402
from app.embeddings import MODEL_NAME as EMBEDDING_MODEL_NAME  # noqa: E402
from app.embeddings import embed_textos  # noqa: E402
from app.llm import gerar_titulo_e_sintese  # noqa: E402
from ingestion.chunk import chunkar_texto  # noqa: E402
from ingestion.dedupe import hash_normalizado, marcar_padronizados  # noqa: E402
from ingestion.metadata import extrair_metadados  # noqa: E402
from ingestion.normalize import normalizar_paginas  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
EXTRACTED_MANIFEST_PATH = os.path.join(DATA_DIR, "extracted_manifest.json")
QUARENTENA_PATH = os.path.join(DATA_DIR, "quarentena.json")

EMBED_BATCH_SIZE = 16

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


def _nome_legivel(municipio: str, tipo_documento: str | None, data_publicacao: str | None) -> str:
    """Fallback de titulo quando a geracao por LLM falha (timeout, Ollama
    fora do ar, resposta invalida) - nome legivel composto a partir de
    metadado que ja existe (municipio, tipo, data), no lugar do nome de
    arquivo com hash. Formato: "Niteroi · Portaria · 18/07/2026"."""
    partes = [municipio, tipo_documento or "Diário Oficial"]
    if data_publicacao:
        ano, mes, dia = str(data_publicacao)[:10].split("-")
        partes.append(f"{dia}/{mes}/{ano}")
    return " · ".join(partes)


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


def carregar_documento(conn, doc: dict, categorias: list[Categoria]) -> tuple[str, list[dict]] | None:
    """Insere documento + entidades + chunks. Devolve (documento_id,
    chunks_inseridos) para a fase 2 (deteccao de conteudo padronizado, que
    precisa ver os chunks de TODOS os documentos antes de decidir) - ou
    None se o documento ja estava carregado ou nao sobrou conteudo."""
    with conn.cursor() as cur:
        cur.execute(
            "select id from documentos where arquivo_local = %s", (doc["arquivo_local"],)
        )
        if cur.fetchone():
            print(f"  [ja carregado] {doc['arquivo_local']}")
            return None

    pdf_path = os.path.join(DATA_DIR, doc["arquivo_local"])
    hash_sha256 = _hash_sha256(pdf_path)

    paginas_normalizadas = normalizar_paginas(doc["paginas"])
    metodo_por_pagina = {p["pagina"]: p["metodo"] for p in paginas_normalizadas}

    texto_bruto = montar_texto_com_marcadores(paginas_normalizadas)
    texto_anonimizado, entidades = anonimizar_documento(texto_bruto, categorias)

    nivel_restricao = _classificar_nivel_restricao(entidades)
    metadados = extrair_metadados(texto_anonimizado)

    try:
        gerado = gerar_titulo_e_sintese(texto_anonimizado)
        titulo, sintese = gerado["titulo"], gerado["sintese"] or None
    except Exception as exc:  # noqa: BLE001 - titulo/sintese nao pode travar a ingestao
        print(f"  [titulo/sintese indisponivel, usando fallback] {doc['arquivo_local']}: {exc}")
        titulo = _nome_legivel(doc["municipio"], metadados["tipo_documento"], doc["data"])
        sintese = None

    qualidade_extracao = {
        "paginas": [
            {
                "pagina": p["pagina"],
                "metodo": p["metodo"],
                "tem_tabela": p["tem_tabela"],
                "colunas": p.get("colunas"),
            }
            for p in paginas_normalizadas
        ]
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            insert into documentos
                (municipio, territory_id, data_publicacao, edicao, url_origem,
                 arquivo_local, hash_sha256, num_paginas, tipo_documento,
                 metodo_extracao_predominante, qualidade_extracao, nivel_restricao,
                 titulo, sintese)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                titulo,
                sintese,
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

    chunks = chunkar_texto(texto_anonimizado, metodo_por_pagina, _VERSAO_METODO)
    if not chunks:
        print(f"  [sem conteudo apos chunking] {doc['arquivo_local']}")
        return None

    embeddings = []
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = [c["texto"] for c in chunks[i:i + EMBED_BATCH_SIZE]]
        embeddings.extend(embed_textos(batch))

    for c in chunks:
        c["hash_normalizado"] = hash_normalizado(c["texto"])

    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into chunks
                (documento_id, indice, pagina, offset_inicio, offset_fim, texto,
                 metodo_extracao, metodo_extracao_versao, embedding_modelo, embedding,
                 hash_normalizado)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
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
                    c["hash_normalizado"],
                )
                for i, c in enumerate(chunks)
            ],
            returning=True,
        )
        ids_inseridos = []
        resultado = cur.fetchone()
        while resultado is not None:
            ids_inseridos.append(resultado["id"])
            resultado = cur.nextset() and cur.fetchone()

    for c, chunk_id in zip(chunks, ids_inseridos):
        c["id"] = chunk_id

    print(
        f"  [ok] {doc['arquivo_local']} -> {len(chunks)} chunks, {len(entidades)} entidades "
        f"mascaradas, restricao={nivel_restricao}, tipo={metadados['tipo_documento']}, "
        f"titulo={titulo!r}"
    )
    return documento_id, chunks


def _marcar_padronizados_no_banco(conn, chunks_por_documento: dict[str, list[dict]]) -> None:
    """Fase 2 (Secao 4.4 do adendo): so pode rodar depois que TODOS os
    documentos foram inseridos - a decisao de "padronizado" depende de ver
    o acervo inteiro de uma vez."""
    total_marcados = marcar_padronizados(chunks_por_documento)
    ids_padronizados = [
        c["id"]
        for chunks in chunks_por_documento.values()
        for c in chunks
        if c.get("eh_padronizado")
    ]
    if ids_padronizados:
        with conn.cursor() as cur:
            cur.execute(
                "update chunks set eh_padronizado = true where id = any(%s)",
                (ids_padronizados,),
            )
    total_chunks = sum(len(c) for c in chunks_por_documento.values())
    print(
        f"\nConteudo padronizado: {total_marcados} de {total_chunks} chunks marcados "
        f"({100 * total_marcados / max(total_chunks, 1):.1f}%) - saem do ranking de busca "
        "por padrao, continuam acessiveis na exploracao livre do acervo."
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
        chunks_por_documento: dict[str, list[dict]] = {}
        for doc in documentos:
            try:
                resultado = carregar_documento(conn, doc, categorias)
            except Exception as exc:  # noqa: BLE001
                print(f"  [erro] {doc['arquivo_local']}: {exc}")
                continue
            if resultado is not None:
                documento_id, chunks = resultado
                chunks_por_documento[documento_id] = chunks

        if chunks_por_documento:
            _marcar_padronizados_no_banco(conn, chunks_por_documento)
    finally:
        conn.close()

    print("Concluido.")


if __name__ == "__main__":
    main()
