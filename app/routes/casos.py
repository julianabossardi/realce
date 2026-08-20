"""
Casos e dossie (Secao "Interactions" do handoff de design) - organizacao
do trabalho do analista em torno de uma investigacao: agrupar trechos
salvos, anotar, avaliar relevancia manualmente (distinto da avaliacao por
criterio via LLM). Extraido de app/main.py (organizacao de codigo, sem
mudanca de comportamento).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import get_connection

router = APIRouter(prefix="/casos")


class CasoCreateRequest(BaseModel):
    nome: str = "Novo caso"
    numero_processo: str | None = None


class CasoRenameRequest(BaseModel):
    nome: str


class DossieAddRequest(BaseModel):
    chunk_id: str
    tema: str | None = None


class DossieNotaRequest(BaseModel):
    nota: str


class AvaliacaoRelevanciaRequest(BaseModel):
    chunk_id: str
    relevante: bool | None  # None = remove a avaliacao (toggle)


@router.get("")
def listar_casos():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("select id, nome, numero_processo, criado_em from casos order by criado_em")
            return {"casos": cur.fetchall()}
    finally:
        conn.close()


@router.post("")
def criar_caso(req: CasoCreateRequest):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("select count(*) as total from casos")
            if cur.fetchone()["total"] >= 10:
                raise HTTPException(400, "Limite de 10 casos abertos simultaneamente.")
            cur.execute(
                "insert into casos (nome, numero_processo) values (%s, %s) returning id, nome, numero_processo, criado_em",
                (req.nome, req.numero_processo),
            )
            return cur.fetchone()
    finally:
        conn.close()


@router.patch("/{caso_id}")
def renomear_caso(caso_id: str, req: CasoRenameRequest):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "update casos set nome = %s, atualizado_em = now() where id = %s returning id, nome, numero_processo",
                (req.nome.strip() or "Novo caso", caso_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Caso nao encontrado.")
            return row
    finally:
        conn.close()


@router.get("/{caso_id}/dossie")
def listar_dossie(caso_id: str):
    """Alem dos metadados do chunk salvo, anexa as avaliacoes por criterio
    JA EM CACHE (Secao 4.6) - sem chamar o LLM aqui, so reaproveita o que
    a busca ja avaliou quando o item foi salvo. Usado pela interface para
    marcar tags de criterio no card do dossie, no lugar de mostrar um
    pedaco cru do trecho (ver README, Revisao 4 - ajustes pos-demo)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select di.id, di.chunk_id, di.nota, di.tema, di.criado_em,
                       c.texto, c.pagina, c.metodo_extracao, d.arquivo_local, d.municipio,
                       d.data_publicacao, d.url_origem, d.titulo, d.tipo_documento
                from dossie_items di
                join chunks c on c.id = di.chunk_id
                join documentos d on d.id = c.documento_id
                where di.caso_id = %s
                order by di.criado_em
                """,
                (caso_id,),
            )
            itens = cur.fetchall()

            chunk_ids = [it["chunk_id"] for it in itens]
            avaliacoes_por_chunk: dict[str, list[dict]] = {}
            if chunk_ids:
                cur.execute(
                    """
                    select a.chunk_id, a.atende, cr.chave as criterio_chave
                    from avaliacoes a
                    join criterio cr on cr.id = a.criterio_id and cr.versao = a.criterio_versao
                    where cr.ativo = true and a.chunk_id = any(%s)
                    """,
                    (chunk_ids,),
                )
                for row in cur.fetchall():
                    avaliacoes_por_chunk.setdefault(row["chunk_id"], []).append(
                        {"atende": row["atende"], "criterio_chave": row["criterio_chave"]}
                    )

        for it in itens:
            it["avaliacoes"] = avaliacoes_por_chunk.get(it["chunk_id"], [])
        return {"itens": itens}
    finally:
        conn.close()


@router.post("/{caso_id}/dossie")
def adicionar_ao_dossie(caso_id: str, req: DossieAddRequest):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into dossie_items (caso_id, chunk_id, tema) values (%s, %s, %s)
                on conflict (caso_id, chunk_id) do nothing
                returning id
                """,
                (caso_id, req.chunk_id, req.tema),
            )
            row = cur.fetchone()
        return {"ok": True, "id": row["id"] if row else None, "ja_existia": row is None}
    finally:
        conn.close()


@router.delete("/{caso_id}/dossie/{chunk_id}")
def remover_do_dossie(caso_id: str, chunk_id: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "delete from dossie_items where caso_id = %s and chunk_id = %s",
                (caso_id, chunk_id),
            )
        return {"ok": True}
    finally:
        conn.close()


@router.patch("/{caso_id}/dossie/{chunk_id}")
def anotar_dossie(caso_id: str, chunk_id: str, req: DossieNotaRequest):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "update dossie_items set nota = %s where caso_id = %s and chunk_id = %s returning id",
                (req.nota, caso_id, chunk_id),
            )
            if not cur.fetchone():
                raise HTTPException(404, "Item nao encontrado no dossie.")
        return {"ok": True}
    finally:
        conn.close()


@router.post("/{caso_id}/avaliacao-relevancia")
def avaliar_relevancia(caso_id: str, req: AvaliacaoRelevanciaRequest):
    """👍/👎 do analista sobre um trecho, no contexto de um caso - distinto
    da avaliacao por criterio (LLM); esta e humana, exibida so no painel de
    detalhe (Secao 'Interactions' do handoff de design)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if req.relevante is None:
                cur.execute(
                    "delete from avaliacoes_relevancia where caso_id = %s and chunk_id = %s",
                    (caso_id, req.chunk_id),
                )
            else:
                cur.execute(
                    """
                    insert into avaliacoes_relevancia (caso_id, chunk_id, relevante)
                    values (%s, %s, %s)
                    on conflict (caso_id, chunk_id) do update set relevante = excluded.relevante
                    """,
                    (caso_id, req.chunk_id, req.relevante),
                )
        return {"ok": True}
    finally:
        conn.close()


@router.get("/{caso_id}/avaliacoes")
def listar_avaliacoes_relevancia(caso_id: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select chunk_id, relevante from avaliacoes_relevancia where caso_id = %s",
                (caso_id,),
            )
            return {"avaliacoes": cur.fetchall()}
    finally:
        conn.close()
