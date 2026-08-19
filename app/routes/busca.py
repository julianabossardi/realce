"""
Busca priorizada (Secao 4.5/4.6) - lexico/vetorial/hibrido + avaliacao por
criterio via LLM local. Extraido de app/main.py (organizacao de codigo,
sem mudanca de comportamento) - era o maior bloco de um unico arquivo que
misturava busca, casos, dossie, acervo e stats.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.access import desmascarar_texto, documento_visivel, registrar_auditoria, tem_clearance
from app.db import get_connection
from app.evaluate import avaliar_chunk, criterios_ativos
from app.search import buscar

router = APIRouter()


class BuscaRequest(BaseModel):
    consulta: str
    modo: str = "hibrido"  # "lexico" | "vetorial" | "hibrido"
    limite: int = 8
    perfil: str = "sem_clearance"  # "sem_clearance" | "com_clearance"
    filtro_municipio: str | None = None
    filtro_tipo_documento: str | None = None
    avaliar: bool = True  # False = so retrieval, sem chamar o LLM (ver nota abaixo)
    incluir_padronizados: bool = False  # True = inclui chunks marcados como conteudo padronizado (Secao 4.4)


def _anexar_documentos_e_avaliar(conn, chunks: list[dict], perfil: str, avaliar: bool = True) -> list[dict]:
    if not chunks:
        return []
    doc_ids = list({c["documento_id"] for c in chunks})
    with conn.cursor() as cur:
        cur.execute(
            "select id, municipio, data_publicacao, url_origem, arquivo_local, "
            "tipo_documento, nivel_restricao, titulo, sintese from documentos where id = any(%s)",
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
                "titulo": doc["titulo"],
                "sintese": doc["sintese"],
                "avaliacoes": avaliacoes,
                "score_criterios": max((a["score"] for a in avaliacoes), default=0.0),
            }
        )

    if avaliar:
        # busca priorizada (Secao 4.6): a ordem de recuperacao (RRF/lexico/
        # vetorial) nao e a ordem de relevancia - reordena pelo score da
        # avaliacao por criterio, que e o que a interface chama de
        # "priorizacao por IA". Sort estavel: em empate, mantem a ordem de
        # recuperacao original. Com avaliar=False, score_criterios e 0.0
        # para todos e o sort vira um no-op (preserva ordem de retrieval,
        # como antes).
        resultado.sort(key=lambda r: r["score_criterios"], reverse=True)
    return resultado


@router.get("/filtros")
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


@router.post("/search")
def search(req: BuscaRequest):
    """`avaliar=False` pula a chamada ao LLM e devolve so o retrieval - usado
    por `experiments/compare_modes.py` para medir recall/precisao/latencia
    de cada modo sem pagar o custo de ate `limite x criterios ativos`
    avaliacoes por chamada (isso travou o experimento com timeout na
    primeira tentativa - ver README). A demo (Streamlit/Next.js) usa
    avaliar=True, o padrao, para mostrar score/justificativa/citacao ao
    vivo."""
    conn = get_connection()
    try:
        chunks = buscar(
            conn, req.consulta, req.modo, req.limite,
            filtro_municipio=req.filtro_municipio,
            filtro_tipo_documento=req.filtro_tipo_documento,
            incluir_padronizados=req.incluir_padronizados,
        )
        resultados = _anexar_documentos_e_avaliar(conn, chunks, req.perfil, req.avaliar)
        return {"modo": req.modo, "consulta": req.consulta, "resultados": resultados}
    finally:
        conn.close()
