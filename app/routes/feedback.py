"""
Feedback humano por criterio (Secao 4.9) - sim/nao do analista sobre um
resultado, vinculado a um criterio especifico (avaliacao atomica), nao a
uma versao de bundle. Extraido de app/main.py (organizacao de codigo, sem
mudanca de comportamento).
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import get_connection

router = APIRouter()


class FeedbackRequest(BaseModel):
    chunk_id: str
    consulta: str
    criterio_id: int
    criterio_versao: int
    util: bool
    comentario: str | None = None


@router.post("/feedback")
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


@router.get("/feedback/stats")
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
