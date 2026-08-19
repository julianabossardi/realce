"""
Metricas agregadas expostas para nao esconder o que o pipeline filtra ou
nao consegue processar: quarentena (Secao 4.2) e conteudo padronizado
(Secao 4.4, adendo tecnico). Extraido de app/main.py (organizacao de
codigo, sem mudanca de comportamento).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.db import get_connection

router = APIRouter()


@router.get("/padronizados/stats")
def padronizados_stats():
    """% de chunks marcados como conteudo padronizado (Secao 4.4 do
    adendo tecnico) - formularios/anexos que se repetem entre documentos e
    saem do ranking de busca por padrao. Mesma logica de exposicao da
    quarentena: nao esconder o que foi filtrado, mostrar quanto e por
    que."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) filter (where eh_padronizado) as padronizados, count(*) as total from chunks"
            )
            row = cur.fetchone()
        total = row["total"] or 0
        padronizados = row["padronizados"] or 0
        percentual = (100 * padronizados / total) if total else 0.0
        return {
            "total_chunks": total,
            "total_padronizados": padronizados,
            "percentual_padronizados": percentual,
        }
    finally:
        conn.close()


@router.get("/quarentena/stats")
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
