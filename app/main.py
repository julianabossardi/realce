"""
Backend FastAPI (Secao 5/6 do brief, revisao 2) - busca (lexico/vetorial/
hibrido), avaliacao por criterio, feedback, e as visoes agregadas que
sustentam a demo (quarentena por tipo de erro, aprovacao por criterio).
Roda 100% local; a unica dependencia externa e o Postgres local
(docker-compose) - LLM e embeddings sao chamados localmente.
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.access import desmascarar_texto, documento_visivel, registrar_auditoria, tem_clearance
from app.db import get_connection
from app.evaluate import avaliar_chunk, criterios_ativos
from app.search import buscar

app = FastAPI(title="Realce - PoC (100% local, busca hibrida)")


class BuscaRequest(BaseModel):
    consulta: str
    modo: str = "hibrido"  # "lexico" | "vetorial" | "hibrido"
    limite: int = 8
    perfil: str = "sem_clearance"  # "sem_clearance" | "com_clearance"
    filtro_municipio: str | None = None
    filtro_tipo_documento: str | None = None
    avaliar: bool = True  # False = so retrieval, sem chamar o LLM (ver nota abaixo)


class FeedbackRequest(BaseModel):
    chunk_id: str
    consulta: str
    criterio_id: int
    criterio_versao: int
    util: bool
    comentario: str | None = None


def _anexar_documentos_e_avaliar(conn, chunks: list[dict], perfil: str, avaliar: bool = True) -> list[dict]:
    if not chunks:
        return []
    doc_ids = list({c["documento_id"] for c in chunks})
    with conn.cursor() as cur:
        cur.execute(
            "select id, municipio, data_publicacao, url_origem, arquivo_local, "
            "tipo_documento, nivel_restricao from documentos where id = any(%s)",
            (doc_ids,),
        )
        documentos = {d["id"]: d for d in cur.fetchall()}

    entidades_por_doc: dict[str, list[dict]] = {}
    if tem_clearance(perfil):
        with conn.cursor() as cur:
            cur.execute(
                "select documento_id, pseudonimo, valor_original from entidades_mascaradas "
                "where documento_id = any(%s)",
                (doc_ids,),
            )
            for row in cur.fetchall():
                entidades_por_doc.setdefault(row["documento_id"], []).append(row)

    criterios = criterios_ativos(conn) if avaliar else []

    resultado = []
    for c in chunks:
        doc = documentos.get(c["documento_id"])
        if doc is None or not documento_visivel(doc["nivel_restricao"], perfil):
            continue  # documento sigiloso some do resultado para quem nao tem clearance

        texto = c["texto"]
        entidades_doc = entidades_por_doc.get(c["documento_id"], [])
        if tem_clearance(perfil) and entidades_doc:
            texto = desmascarar_texto(texto, entidades_doc)
            registrar_auditoria(conn, perfil, c["documento_id"], [e["pseudonimo"] for e in entidades_doc])

        avaliacoes = avaliar_chunk(conn, c, criterios) if avaliar else []

        resultado.append(
            {
                **c,
                "texto": texto,
                "municipio": doc["municipio"],
                "data_publicacao": str(doc["data_publicacao"]),
                "url_origem": doc["url_origem"],
                "arquivo_local": doc["arquivo_local"],
                "tipo_documento": doc["tipo_documento"],
                "nivel_restricao": doc["nivel_restricao"],
                "avaliacoes": avaliacoes,
                "score_criterios": max((a["score"] for a in avaliacoes), default=0.0),
            }
        )
    return resultado


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/filtros")
def filtros():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("select distinct municipio from documentos order by municipio")
            municipios = [r["municipio"] for r in cur.fetchall()]
            cur.execute(
                "select distinct tipo_documento from documentos where tipo_documento is not null order by tipo_documento"
            )
            tipos_documento = [r["tipo_documento"] for r in cur.fetchall()]
        return {"municipios": municipios, "tipos_documento": tipos_documento}
    finally:
        conn.close()


@app.post("/search")
def search(req: BuscaRequest):
    """`avaliar=False` pula a chamada ao LLM e devolve so o retrieval - usado
    por `experiments/compare_modes.py` para medir recall/precisao/latencia
    de cada modo sem pagar o custo de ate `limite x criterios ativos`
    avaliacoes por chamada (isso travou o experimento com timeout na
    primeira tentativa - ver README). A demo (Streamlit) usa avaliar=True,
    o padrao, para mostrar score/justificativa/citacao ao vivo."""
    conn = get_connection()
    try:
        chunks = buscar(
            conn, req.consulta, req.modo, req.limite,
            filtro_municipio=req.filtro_municipio,
            filtro_tipo_documento=req.filtro_tipo_documento,
        )
        resultados = _anexar_documentos_e_avaliar(conn, chunks, req.perfil, req.avaliar)
        return {"modo": req.modo, "consulta": req.consulta, "resultados": resultados}
    finally:
        conn.close()


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into feedback (chunk_id, consulta, criterio_id, criterio_versao, util, comentario)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (req.chunk_id, req.consulta, req.criterio_id, req.criterio_versao, req.util, req.comentario),
            )
        return {"ok": True}
    finally:
        conn.close()


@app.get("/feedback/stats")
def feedback_stats():
    """Taxa de aprovacao por criterio (Secao 4.9) - sustenta a narrativa
    do ciclo de refinamento na demo. Sem retreinamento automatico."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select cr.chave as criterio_chave,
                       count(*) filter (where f.util) as aprovados,
                       count(*) as total
                from feedback f
                join criterio cr on cr.id = f.criterio_id
                group by cr.chave
                order by cr.chave
                """
            )
            return {"stats": cur.fetchall()}
    finally:
        conn.close()


@app.get("/quarentena/stats")
def quarentena_stats():
    """% do acervo inacessivel, por tipo de erro (Secao 4.2) - exposto na
    demo para nao esconder o que a extracao nao conseguiu processar."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("select count(*) as total from documentos")
            total_ok = cur.fetchone()["total"]
            cur.execute(
                "select tipo_erro, count(*) as total from quarentena group by tipo_erro order by total desc"
            )
            por_tipo = cur.fetchall()
            total_quarentena = sum(r["total"] for r in por_tipo)
        total_acervo = total_ok + total_quarentena
        percentual = (100 * total_quarentena / total_acervo) if total_acervo else 0.0
        return {
            "total_documentos_ok": total_ok,
            "total_quarentena": total_quarentena,
            "percentual_quarentena": percentual,
            "por_tipo_erro": por_tipo,
        }
    finally:
        conn.close()
