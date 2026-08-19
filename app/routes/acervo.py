"""
Exploracao livre do acervo (Secao 4.4 do handoff: visibilidade total,
distinta da busca priorizada) e leitura do documento completo. Extraido
de app/main.py (organizacao de codigo, sem mudanca de comportamento).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.access import desmascarar_texto, documento_visivel, registrar_auditoria, tem_clearance
from app.db import get_connection

router = APIRouter()


@router.get("/acervo")
def listar_acervo(q: str | None = None, tipo: str | None = None, limite: int = 200):
    """Navegacao livre pelo acervo, sem priorizacao por IA (Secao 4.4 do
    handoff: visibilidade total, distinta da busca priorizada)."""
    conn = get_connection()
    try:
        condicoes = []
        params: list = []
        if q:
            condicoes.append("(d.arquivo_local ilike %s or d.municipio ilike %s)")
            params.extend([f"%{q}%", f"%{q}%"])
        if tipo:
            condicoes.append("d.tipo_documento = %s")
            params.append(tipo)
        where_sql = ("where " + " and ".join(condicoes)) if condicoes else ""

        with conn.cursor() as cur:
            cur.execute(
                f"""
                select d.id, d.arquivo_local, d.municipio, d.tipo_documento,
                       d.data_publicacao, d.url_origem, d.nivel_restricao,
                       d.titulo, d.sintese, 'Processado' as status
                from documentos d
                {where_sql}
                order by d.data_publicacao desc nulls last
                limit %s
                """,
                (*params, limite),
            )
            processados = cur.fetchall()

            cur.execute(
                "select arquivo_local, municipio, tipo_erro, mensagem_erro from quarentena order by criado_em desc limit %s",
                (limite,),
            )
            nao_processados = cur.fetchall()

        return {"documentos": processados, "nao_processados": nao_processados}
    finally:
        conn.close()


@router.get("/documentos/{documento_id}/completo")
def documento_completo(documento_id: str, perfil: str = "sem_clearance"):
    """Texto integral do documento (concatenacao dos chunks, na ordem),
    aplicando as mesmas regras de mascaramento/auditoria da busca."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select id, arquivo_local, municipio, tipo_documento, data_publicacao, url_origem, "
                "nivel_restricao, titulo, sintese from documentos where id = %s",
                (documento_id,),
            )
            doc = cur.fetchone()
            if not doc:
                raise HTTPException(404, "Documento nao encontrado.")
            if not documento_visivel(doc["nivel_restricao"], perfil):
                raise HTTPException(403, "Documento sigiloso - perfil sem clearance.")

            cur.execute(
                "select id, indice, pagina, texto from chunks where documento_id = %s order by indice",
                (documento_id,),
            )
            chunks = cur.fetchall()

        entidades: list[dict] = []
        if tem_clearance(perfil):
            with conn.cursor() as cur:
                cur.execute(
                    "select pseudonimo, valor_original from entidades_mascaradas where documento_id = %s",
                    (documento_id,),
                )
                entidades = cur.fetchall()

        texto_completo = "\n\n".join(c["texto"] for c in chunks)
        if tem_clearance(perfil) and entidades:
            texto_completo = desmascarar_texto(texto_completo, entidades)
            registrar_auditoria(conn, perfil, documento_id, [e["pseudonimo"] for e in entidades])

        return {**doc, "texto_completo": texto_completo, "num_chunks": len(chunks)}
    finally:
        conn.close()
