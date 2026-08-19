"""
Backend FastAPI (Secao 5/6 do brief, revisao 2) - busca (lexico/vetorial/
hibrido), avaliacao por criterio, feedback, e as visoes agregadas que
sustentam a demo (quarentena por tipo de erro, aprovacao por criterio).
Roda 100% local; a unica dependencia externa e o Postgres local
(docker-compose) - LLM e embeddings sao chamados localmente.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.access import desmascarar_texto, documento_visivel, registrar_auditoria, tem_clearance
from app.db import get_connection
from app.evaluate import avaliar_chunk, criterios_ativos
from app.search import buscar

app = FastAPI(title="Realce - PoC (100% local, busca hibrida)")

# CORS liberado (GET/POST de qualquer origem) - necessario porque o
# frontend passa a rodar no Vercel (origem diferente), chamando este
# backend local via tunel. Aceitavel para esta demo (dado publico,
# service local so acessivel via URL efemera do tunel); nao seria a
# configuracao de producao (ver README).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class BuscaRequest(BaseModel):
    consulta: str
    modo: str = "hibrido"  # "lexico" | "vetorial" | "hibrido"
    limite: int = 8
    perfil: str = "sem_clearance"  # "sem_clearance" | "com_clearance"
    filtro_municipio: str | None = None
    filtro_tipo_documento: str | None = None
    avaliar: bool = True  # False = so retrieval, sem chamar o LLM (ver nota abaixo)
    incluir_padronizados: bool = False  # True = inclui chunks marcados como conteudo padronizado (Secao 4.4)


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
            incluir_padronizados=req.incluir_padronizados,
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


@app.get("/casos")
def listar_casos():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("select id, nome, numero_processo, criado_em from casos order by criado_em")
            return {"casos": cur.fetchall()}
    finally:
        conn.close()


@app.post("/casos")
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


@app.patch("/casos/{caso_id}")
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


@app.get("/casos/{caso_id}/dossie")
def listar_dossie(caso_id: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select di.id, di.chunk_id, di.nota, di.tema, di.criado_em,
                       c.texto, c.pagina, d.arquivo_local, d.municipio, d.data_publicacao, d.url_origem,
                       d.titulo, d.tipo_documento
                from dossie_items di
                join chunks c on c.id = di.chunk_id
                join documentos d on d.id = c.documento_id
                where di.caso_id = %s
                order by di.criado_em
                """,
                (caso_id,),
            )
            return {"itens": cur.fetchall()}
    finally:
        conn.close()


@app.post("/casos/{caso_id}/dossie")
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


@app.delete("/casos/{caso_id}/dossie/{chunk_id}")
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


@app.patch("/casos/{caso_id}/dossie/{chunk_id}")
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


@app.post("/casos/{caso_id}/avaliacao-relevancia")
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


@app.get("/casos/{caso_id}/avaliacoes")
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


@app.get("/acervo")
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


@app.get("/documentos/{documento_id}/completo")
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


@app.get("/padronizados/stats")
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
