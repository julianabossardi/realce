"""
Avaliacao por criterio sobre os candidatos de uma busca (Secao 4.6 do
brief, revisao 2). Roda apenas sobre o top-K retornado por `app/search.py`
- nunca sobre o acervo inteiro (a arquitetura consultiva e premissa fixada
do brief, Secao 1).

Mudancas desta revisao: criterios sao lidos de uma tabela (`criterio`,
nao mais um bundle fixo), a avaliacao e ATOMICA (um criterio por chamada -
ver `app/llm.py`), e a citacao retornada pelo modelo e verificada
programaticamente contra o texto do chunk.
"""
from __future__ import annotations

from app.llm import OLLAMA_MODEL, avaliar_criterio_unico


def criterios_ativos(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "select id, chave, descricao, versao from criterio where ativo = true order by id"
        )
        return cur.fetchall()


def _citacao_verificada(trecho_citado: str, texto_chunk: str) -> bool:
    """A taxa de citacao NAO verificada e uma metrica a reportar (Secao
    4.6) - evidencia direta da confiabilidade do modelo local: ele pode
    alegar um trecho que nao existe literalmente no chunk (alucinacao de
    citacao)."""
    if not trecho_citado:
        return True  # nada a verificar (criterio nao se aplica)
    return trecho_citado in texto_chunk


def avaliar_chunk(conn, chunk: dict, criterios: list[dict]) -> list[dict]:
    """Avalia um chunk contra todos os criterios ativos, reaproveitando o
    cache (chunk, criterio, versao) quando existir."""
    resultado: list[dict] = []

    for criterio in criterios:
        with conn.cursor() as cur:
            cur.execute(
                """
                select criterio_id, atende, score, justificativa, trecho_citado, citacao_verificada
                from avaliacoes
                where chunk_id = %s and criterio_id = %s and criterio_versao = %s
                """,
                (chunk["id"], criterio["id"], criterio["versao"]),
            )
            avaliacao = cur.fetchone()

        if avaliacao is None:
            bruto = avaliar_criterio_unico(chunk["texto"], criterio["descricao"])
            trecho_citado = bruto.get("trecho_citado", "") or ""
            citacao_ok = _citacao_verificada(trecho_citado, chunk["texto"])

            avaliacao = {
                "criterio_id": criterio["id"],
                "atende": bool(bruto.get("atende", False)),
                "score": float(bruto.get("score", 0.0)),
                "justificativa": bruto.get("justificativa", ""),
                "trecho_citado": trecho_citado,
                "citacao_verificada": citacao_ok,
            }

            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into avaliacoes
                        (chunk_id, criterio_id, criterio_versao, atende, score,
                         justificativa, trecho_citado, citacao_verificada, modelo)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (chunk_id, criterio_id, criterio_versao) do nothing
                    """,
                    (
                        chunk["id"],
                        criterio["id"],
                        criterio["versao"],
                        avaliacao["atende"],
                        avaliacao["score"],
                        avaliacao["justificativa"],
                        avaliacao["trecho_citado"],
                        avaliacao["citacao_verificada"],
                        OLLAMA_MODEL,
                    ),
                )

        resultado.append({**avaliacao, "criterio_chave": criterio["chave"], "criterio_versao": criterio["versao"]})

    return resultado
