"""
Backend FastAPI - rotas de busca (keyword/semantica), avaliacao por
criterios e feedback (Secao 5 do brief). Roda 100% local; a unica
dependencia externa e o Postgres local (docker-compose) - LLM e embeddings
sao chamados localmente (Ollama / sentence-transformers).
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.access import desmascarar_texto, tem_clearance
from app.db import get_connection
from app.embeddings import embed_consulta
from app.llm import avaliar_criterios

app = FastAPI(title="Realce - PoC (100% local)")


class BuscaRequest(BaseModel):
    consulta: str
    caminho: str = "semantico"  # "keyword" | "semantico"
    limite: int = 8
    perfil: str = "sem_clearance"  # "sem_clearance" | "com_clearance"


class FeedbackRequest(BaseModel):
    chunk_id: str
    consulta: str
    criterios_versao_id: int
    util: bool
    comentario: str | None = None


def _anexar_documentos(conn, chunks: list[dict], perfil: str) -> list[dict]:
    if not chunks:
        return []
    doc_ids = list({c["documento_id"] for c in chunks})
    with conn.cursor() as cur:
        cur.execute(
            "select id, municipio, data_publicacao, url_origem, arquivo_local "
            "from documentos where id = any(%s)",
            (doc_ids,),
        )
        documentos = {d["id"]: d for d in cur.fetchall()}

    entidades_por_doc: dict = {}
    if tem_clearance(perfil):
        with conn.cursor() as cur:
            cur.execute(
                "select documento_id, placeholder, valor_original from entidades_mascaradas "
                "where documento_id = any(%s)",
                (doc_ids,),
            )
            for row in cur.fetchall():
                entidades_por_doc.setdefault(row["documento_id"], []).append(row)

    resultado = []
    for c in chunks:
        doc = documentos.get(c["documento_id"], {})
        texto = c["texto"]
        if tem_clearance(perfil):
            texto = desmascarar_texto(texto, entidades_por_doc.get(c["documento_id"], []))
        resultado.append(
            {
                **c,
                "texto": texto,
                "municipio": doc.get("municipio", ""),
                "data_publicacao": str(doc.get("data_publicacao", "")),
                "url_origem": doc.get("url_origem", ""),
                "arquivo_local": doc.get("arquivo_local", ""),
            }
        )
    return resultado


def _busca_keyword(conn, consulta: str, limite: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, documento_id, pagina, texto, metodo_extracao,
                   ts_rank(tsv, websearch_to_tsquery('portuguese', %s)) as rank
            from chunks
            where tsv @@ websearch_to_tsquery('portuguese', %s)
            order by rank desc
            limit %s
            """,
            (consulta, consulta, limite),
        )
        return cur.fetchall()


def _versao_criterios_atual(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "select id, criterios from criterios_versoes order by id desc limit 1"
        )
        return cur.fetchone()


def _busca_semantica(conn, consulta: str, limite: int) -> tuple[list[dict], int]:
    vetor = embed_consulta(consulta)
    with conn.cursor() as cur:
        cur.execute("select * from match_chunks(%s::vector, %s)", (vetor, limite))
        candidatos = cur.fetchall()

    versao = _versao_criterios_atual(conn)
    criterios = versao["criterios"]

    for candidato in candidatos:
        with conn.cursor() as cur:
            cur.execute(
                "select criterio_chave, atende, score, justificativa, trecho_citado "
                "from avaliacoes where chunk_id = %s and criterios_versao_id = %s",
                (candidato["id"], versao["id"]),
            )
            avaliacoes = cur.fetchall()

        if not avaliacoes:
            novas = avaliar_criterios(candidato["texto"], criterios)
            if novas:
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        insert into avaliacoes
                            (chunk_id, criterios_versao_id, criterio_chave, atende,
                             score, justificativa, trecho_citado, modelo)
                        values (%s, %s, %s, %s, %s, %s, %s, %s)
                        on conflict (chunk_id, criterios_versao_id, criterio_chave) do nothing
                        """,
                        [
                            (
                                candidato["id"],
                                versao["id"],
                                a["criterio_chave"],
                                a["atende"],
                                a["score"],
                                a["justificativa"],
                                a["trecho_citado"],
                                "qwen2.5:7b-instruct",
                            )
                            for a in novas
                        ],
                    )
            avaliacoes = novas

        candidato["avaliacoes"] = avaliacoes
        candidato["score_criterios"] = max((a["score"] for a in avaliacoes), default=0)
        candidato["criterios_versao_id"] = versao["id"]

    return candidatos, versao["id"]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search")
def search(req: BuscaRequest):
    conn = get_connection()
    try:
        if req.caminho == "keyword":
            chunks = _busca_keyword(conn, req.consulta, req.limite)
        else:
            chunks, _ = _busca_semantica(conn, req.consulta, req.limite)

        resultados = _anexar_documentos(conn, chunks, req.perfil)
        return {"caminho": req.caminho, "consulta": req.consulta, "resultados": resultados}
    finally:
        conn.close()


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into feedback (chunk_id, consulta, criterios_versao_id, util, comentario)
                values (%s, %s, %s, %s, %s)
                """,
                (req.chunk_id, req.consulta, req.criterios_versao_id, req.util, req.comentario),
            )
        return {"ok": True}
    finally:
        conn.close()
