"""
Busca lexica, vetorial e hibrida (Secao 4.5 do brief, revisao 2).

A hipotese revisada (Secao 2) nao opoe mais semantica a palavra-chave: em
acervo juridico, a busca lexica e insubstituivel para termos exatos
(numero de processo, CNPJ, artigo de lei, nome de operacao) e a semantica
e insubstituivel quando o usuario descreve o que procura com vocabulario
diferente do documento. O modo hibrido funde os dois rankings via
*Reciprocal Rank Fusion* (RRF), que dispensa normalizar escores de
naturezas diferentes (rank de tsquery vs. distancia de cosseno).
"""
from __future__ import annotations

from app.embeddings import embed_consulta

RRF_K = 60
CANDIDATOS_POR_CAMINHO = 30  # top-N de cada perna antes da fusao


def _resolver_pseudonimos(conn, consulta: str) -> list[str]:
    """Indice de entidades (Secao 4.3): resolve nomes/valores citados na
    consulta para os pseudonimos correspondentes em `entidades_mascaradas`,
    sem expor o valor original a quem busca. Sem isso, buscar por uma
    pessoa ou empresa especifica falharia completamente apos a
    anonimizacao (o texto indexado so tem pseudonimos).

    Limitacao conhecida (documentar no README): resolucao por substring
    case-insensitive sobre toda a tabela - funciona bem na escala desta
    PoC, mas nao substitui um indice de nomes tokenizado/fuzzy em escala
    de producao."""
    with conn.cursor() as cur:
        cur.execute("select distinct valor_original, pseudonimo from entidades_mascaradas")
        linhas = cur.fetchall()

    consulta_lower = consulta.lower()
    return [
        linha["pseudonimo"]
        for linha in linhas
        if len(linha["valor_original"]) >= 4 and linha["valor_original"].lower() in consulta_lower
    ]


def _aplicar_filtros_sql(filtro_municipio: str | None, filtro_tipo_documento: str | None) -> tuple[str, list]:
    condicoes = []
    params = []
    if filtro_municipio:
        condicoes.append("d.municipio = %s")
        params.append(filtro_municipio)
    if filtro_tipo_documento:
        condicoes.append("d.tipo_documento = %s")
        params.append(filtro_tipo_documento)
    sql = (" and " + " and ".join(condicoes)) if condicoes else ""
    return sql, params


def busca_lexica(
    conn,
    consulta: str,
    limite: int,
    filtro_municipio: str | None = None,
    filtro_tipo_documento: str | None = None,
) -> list[dict]:
    """Caminho lexico puro: full-text search nativo do Postgres
    (`tsvector`/`websearch_to_tsquery`, dicionario portugues)."""
    pseudonimos = _resolver_pseudonimos(conn, consulta)
    filtro_sql, filtro_params = _aplicar_filtros_sql(filtro_municipio, filtro_tipo_documento)

    campos_linhagem = (
        "c.id, c.documento_id, c.pagina, c.texto, c.metodo_extracao, "
        "c.metodo_extracao_versao, c.embedding_modelo, c.offset_inicio, c.offset_fim"
    )

    with conn.cursor() as cur:
        cur.execute(
            f"""
            select {campos_linhagem},
                   ts_rank(c.tsv, websearch_to_tsquery('portuguese', %s)) as rank
            from chunks c
            join documentos d on d.id = c.documento_id
            where c.tsv @@ websearch_to_tsquery('portuguese', %s) {filtro_sql}
            order by rank desc
            limit %s
            """,
            (consulta, consulta, *filtro_params, limite),
        )
        resultados = cur.fetchall()

    if pseudonimos:
        placeholders = " or ".join(["c.texto ilike %s"] * len(pseudonimos))
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select {campos_linhagem}, 1.0 as rank
                from chunks c
                join documentos d on d.id = c.documento_id
                where ({placeholders}) {filtro_sql}
                limit %s
                """,
                (*[f"%{p}%" for p in pseudonimos], *filtro_params, limite),
            )
            extras = cur.fetchall()
        vistos = {r["id"] for r in resultados}
        resultados.extend(r for r in extras if r["id"] not in vistos)
        resultados.sort(key=lambda r: r["rank"], reverse=True)

    return resultados[:limite]


def busca_vetorial(
    conn,
    consulta: str,
    limite: int,
    filtro_municipio: str | None = None,
    filtro_tipo_documento: str | None = None,
) -> list[dict]:
    """Caminho vetorial puro: embedding da consulta (local) + busca por
    similaridade de cosseno no pgvector."""
    pseudonimos = _resolver_pseudonimos(conn, consulta)
    consulta_enriquecida = consulta + (" " + " ".join(pseudonimos) if pseudonimos else "")
    vetor = embed_consulta(consulta_enriquecida)

    with conn.cursor() as cur:
        cur.execute(
            "select * from match_chunks(%s::vector, %s, %s, %s)",
            (vetor, limite, filtro_municipio, filtro_tipo_documento),
        )
        return cur.fetchall()


def _fusao_rrf(lista_lexica: list[dict], lista_vetorial: list[dict], k: int = RRF_K) -> list[dict]:
    scores: dict[str, float] = {}
    info: dict[str, dict] = {}
    origem: dict[str, set[str]] = {}

    for pos, item in enumerate(lista_lexica, start=1):
        scores[item["id"]] = scores.get(item["id"], 0.0) + 1.0 / (k + pos)
        info[item["id"]] = item
        origem.setdefault(item["id"], set()).add("lexico")

    for pos, item in enumerate(lista_vetorial, start=1):
        scores[item["id"]] = scores.get(item["id"], 0.0) + 1.0 / (k + pos)
        info.setdefault(item["id"], item)
        origem.setdefault(item["id"], set()).add("vetorial")

    ranqueados = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {**info[chunk_id], "rrf_score": score, "encontrado_em": sorted(origem[chunk_id])}
        for chunk_id, score in ranqueados
    ]


def busca_hibrida(
    conn,
    consulta: str,
    limite: int,
    filtro_municipio: str | None = None,
    filtro_tipo_documento: str | None = None,
) -> list[dict]:
    """Modo hibrido (mudanca central desta revisao - Secao 4.5): roda os
    dois caminhos e funde os rankings por RRF antes de cortar o top-K."""
    lista_lexica = busca_lexica(conn, consulta, CANDIDATOS_POR_CAMINHO, filtro_municipio, filtro_tipo_documento)
    lista_vetorial = busca_vetorial(conn, consulta, CANDIDATOS_POR_CAMINHO, filtro_municipio, filtro_tipo_documento)
    fundidos = _fusao_rrf(lista_lexica, lista_vetorial)
    return fundidos[:limite]


MODOS = {
    "lexico": busca_lexica,
    "vetorial": busca_vetorial,
    "hibrido": busca_hibrida,
}


def buscar(
    conn,
    consulta: str,
    modo: str,
    limite: int,
    filtro_municipio: str | None = None,
    filtro_tipo_documento: str | None = None,
) -> list[dict]:
    if modo not in MODOS:
        raise ValueError(f"modo invalido: {modo!r} (esperado: {list(MODOS)})")
    return MODOS[modo](conn, consulta, limite, filtro_municipio, filtro_tipo_documento)
