"""
Avaliacao da hipotese central da PoC (Secao 5 do brief, revisao 2).

Roda perguntas de teste, com gabarito manual (nivel documento), pelos TRES
modos - lexico, vetorial e hibrido - contra a API FastAPI rodando
localmente, e calcula recall/precisao de cada um. Reporta tambem: taxa de
citacao nao verificada, latencia media por consulta, e % de documentos em
quarentena por tipo de erro.

As perguntas misturam deliberadamente dois tipos (Secao 5, item 1):
    - termo exato (nome de pessoa, numero de portaria) - onde a busca
      lexica deveria ser forte
    - descricao semantica (tema com vocabulario diferente do documento) -
      onde a busca vetorial deveria ser forte
A expectativa e que o hibrido supere as pontas nos dois tipos; o resultado
interessa mesmo se contrariar a expectativa (Secao 5).

O gabarito foi construido inspecionando o texto ja extraido da amostra
(ingestion/data/extracted_manifest.json) com expressoes regulares
verificadas manualmente contra o trecho encontrado - ver README para a
metodologia completa e suas limitacoes.

Pre-requisito: a API FastAPI precisa estar rodando (`uvicorn app.main:app`)
e o banco ja populado (`python ingestion/index.py`).

Uso:
    python experiments/compare_modes.py
"""
from __future__ import annotations

import statistics
import time

import requests

API_URL = "http://localhost:8000"
LIMITE_RESULTADOS = 10

CASOS_DE_TESTE = [
    # --- descricao semantica ---
    {
        "pergunta": "Existe algum servidor com processo de cessão para outro órgão deferido?",
        "tipo": "semantico",
        "relevantes": {"niteroi_2026-08-07_2b1a921a718559974690d0c190d4cb42f394ffbf.pdf"},
    },
    {
        "pergunta": "Quais processos de auxílio por doença foram deferidos a servidores?",
        "tipo": "semantico",
        "relevantes": {
            "niteroi_2026-07-18_f6c705153f876f0ac6d418b34ebd9d8c566d3d01.pdf",
            "niteroi_2026-07-25_89ce407a8339a9d1e4188d21c205d14011327810.pdf",
        },
    },
    {
        "pergunta": "Há concessão de pensão por morte decorrente do falecimento de um servidor ou ex-servidor?",
        "tipo": "semantico",
        "relevantes": {
            "angra-dos-reis_2026-06-24_fa31cc77c239b6e614a7d07655abf1b1cdafcf04.pdf",
            "niteroi_2026-08-15_5795fad11b1337b83f9afca9df91565e952edd62.pdf",
        },
    },
    {
        "pergunta": "Quais atos nomeiam servidores para cargos em comissão (CC)?",
        "tipo": "semantico",
        "relevantes": {
            "angra-dos-reis_2026-06-16_a1ae4887073554cf2a8c9a4fb2c3c2a2091e9d20.pdf",
            "angra-dos-reis_2026-06-18_5cab9c1e0418fe12b82a69c14c0899d90ace8365.pdf",
            "angra-dos-reis_2026-06-23_6f575cf89b918b2e9f938fbb7721de9e74388850.pdf",
            "angra-dos-reis_2026-07-03_69c60ea98f6c5034e8639102f8777fc77ee52afe.pdf",
            "angra-dos-reis_2026-07-06_e20d567e6e0ad4ee79ce9836e7bcd691c80af1a7.pdf",
        },
    },
    {
        "pergunta": "Existem processos de readaptação funcional de servidores?",
        "tipo": "semantico",
        "relevantes": {
            "angra-dos-reis_2026-07-23_d4b604718d804f60f14a3496abba29b9abf1e107.pdf",
            "niteroi_2026-07-14_9005d330a91dfe10359bf2d47ea89827a8e7f39b.pdf",
            "niteroi_2026-07-18_f6c705153f876f0ac6d418b34ebd9d8c566d3d01.pdf",
            "niteroi_2026-07-25_89ce407a8339a9d1e4188d21c205d14011327810.pdf",
            "niteroi_2026-08-01_871a45d4cf8e360b18e58890780b71a70b5cb2a6.pdf",
            "niteroi_2026-08-08_fcede5c681342e02d9096f36e697dca9551d1d36.pdf",
            "niteroi_2026-08-15_5795fad11b1337b83f9afca9df91565e952edd62.pdf",
        },
    },
    # --- termo exato ---
    {
        "pergunta": "Elizabete Mocaiber Freire",
        "tipo": "exato",
        "relevantes": {"niteroi_2026-08-08_fcede5c681342e02d9096f36e697dca9551d1d36.pdf"},
    },
    {
        "pergunta": "Portaria nº 1003/2026",
        "tipo": "exato",
        "relevantes": {"niteroi_2026-08-15_5795fad11b1337b83f9afca9df91565e952edd62.pdf"},
    },
]

MODOS = ["lexico", "vetorial", "hibrido"]


def buscar(consulta: str, modo: str, avaliar: bool = False, limite: int = LIMITE_RESULTADOS) -> tuple[list[str], float, list[bool]]:
    """Retorna (documentos recuperados em ordem, latencia em segundos,
    lista de citacao_verificada das avaliacoes retornadas).

    `avaliar=False` por padrao: a primeira versao deste experimento pedia
    avaliacao por criterio (via LLM) em TODA chamada de busca, para as 3
    modos x 7 perguntas - isso significa ate `limite x criterios ativos`
    avaliacoes por chamada (aqui, 10 x 4 = 40), o suficiente para estourar
    o timeout de 600s numa maquina sob carga. Recall/precisao/latencia sao
    medidos com avaliar=False (retrieval puro, o que essas metricas
    realmente medem); a taxa de citacao nao verificada e medida a parte,
    uma unica vez por pergunta (`medir_citacoes`), com avaliar=True."""
    inicio = time.perf_counter()
    resp = requests.post(
        f"{API_URL}/search",
        # perfil com_clearance: a regra simples de nivel_restricao desta PoC
        # (ver README) marca a grande maioria dos documentos da amostra
        # como 'sigiloso' (basta ter um CPF/RG em qualquer lugar - comum em
        # editais com lista de candidatos). Um analista autorizado
        # investigando o acervo teria clearance; o experimento simula essa
        # persona, nao o usuario sem permissao nenhuma.
        json={
            "consulta": consulta, "modo": modo, "limite": limite,
            "perfil": "com_clearance", "avaliar": avaliar,
        },
        timeout=900,
    )
    latencia = time.perf_counter() - inicio
    resp.raise_for_status()
    resultados = resp.json()["resultados"]

    vistos = []
    for r in resultados:
        if r["arquivo_local"] not in vistos:
            vistos.append(r["arquivo_local"])

    citacoes_verificadas = [
        a["citacao_verificada"] for r in resultados for a in r.get("avaliacoes", []) if a["trecho_citado"]
    ]
    return vistos, latencia, citacoes_verificadas


LIMITE_AVALIACAO = 4  # menor que LIMITE_RESULTADOS: so para manter o custo de
# LLM tratavel na medicao da taxa de citacao (4 candidatos x 4 criterios =
# no maximo 16 avaliacoes por pergunta, em vez de 40)


def medir_citacoes(pergunta: str) -> list[bool]:
    """Roda o modo hibrido com avaliacao ligada (uma unica vez por
    pergunta, sobre um numero menor de candidatos - ver LIMITE_AVALIACAO)
    so para medir a taxa de citacao nao verificada - nao entra no calculo
    de recall/precisao/latencia de busca."""
    _, _, citacoes = buscar(pergunta, "hibrido", avaliar=True, limite=LIMITE_AVALIACAO)
    return citacoes


def recall_precisao(recuperados: list[str], relevantes: set[str]) -> tuple[float, float]:
    recuperados_set = set(recuperados)
    acertos = recuperados_set & relevantes
    recall = len(acertos) / len(relevantes) if relevantes else 0.0
    precisao = len(acertos) / len(recuperados_set) if recuperados_set else 0.0
    return recall, precisao


def buscar_quarentena() -> dict:
    resp = requests.get(f"{API_URL}/quarentena/stats", timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    linhas = []
    latencias_por_modo = {modo: [] for modo in MODOS}

    for caso in CASOS_DE_TESTE:
        pergunta = caso["pergunta"]
        relevantes = caso["relevantes"]
        linha = {"pergunta": pergunta, "tipo": caso["tipo"], "n_relevantes": len(relevantes)}

        print(f"\n=== [{caso['tipo']}] {pergunta} ===")
        print(f"  gabarito: {len(relevantes)} documento(s)")

        for modo in MODOS:
            docs, latencia, _ = buscar(pergunta, modo)  # avaliar=False (retrieval puro)
            recall, precisao = recall_precisao(docs, relevantes)
            linha[f"recall_{modo}"] = recall
            linha[f"precisao_{modo}"] = precisao
            latencias_por_modo[modo].append(latencia)
            print(f"  {modo:10s} -> recall {recall:.2f}, precisao {precisao:.2f}, latencia {latencia:.2f}s  ({docs})")

        linhas.append(linha)

    print("\n\n## Comparacao final (media das perguntas)\n")
    print("| Modo | Recall médio | Precisão média | Latência média de busca (s) |")
    print("|---|---|---|---|")
    for modo in MODOS:
        recall_medio = statistics.mean(l[f"recall_{modo}"] for l in linhas)
        precisao_media = statistics.mean(l[f"precisao_{modo}"] for l in linhas)
        latencia_media = statistics.mean(latencias_por_modo[modo])
        print(f"| {modo} | {recall_medio:.2f} | {precisao_media:.2f} | {latencia_media:.2f} |")

    print("\n### Avaliação por critério (modo híbrido, com LLM ligado)\n")
    citacoes_todas = []
    latencias_com_avaliacao = []
    for caso in CASOS_DE_TESTE:
        inicio = time.perf_counter()
        citacoes = medir_citacoes(caso["pergunta"])
        latencias_com_avaliacao.append(time.perf_counter() - inicio)
        citacoes_todas.extend(citacoes)
        pct = 100 * (1 - sum(citacoes) / len(citacoes)) if citacoes else 0.0
        print(f"  {caso['pergunta'][:60]:60s} -> {len(citacoes)} avaliação(ões) com citação, {pct:.0f}% não verificada")

    pct_nao_verificada_total = (
        100 * (1 - sum(citacoes_todas) / len(citacoes_todas)) if citacoes_todas else 0.0
    )
    latencia_media_avaliacao = statistics.mean(latencias_com_avaliacao) if latencias_com_avaliacao else 0.0
    print(f"\n**% citação não verificada (geral): {pct_nao_verificada_total:.1f}%**")
    print(f"**Latência média por consulta com avaliação por critério ligada: {latencia_media_avaliacao:.1f}s**")

    for tipo in ("semantico", "exato"):
        subset = [l for l in linhas if l["tipo"] == tipo]
        if not subset:
            continue
        print(f"\n### Só perguntas tipo '{tipo}'\n")
        print("| Modo | Recall médio | Precisão média |")
        print("|---|---|---|")
        for modo in MODOS:
            recall_medio = statistics.mean(l[f"recall_{modo}"] for l in subset)
            precisao_media = statistics.mean(l[f"precisao_{modo}"] for l in subset)
            print(f"| {modo} | {recall_medio:.2f} | {precisao_media:.2f} |")

    print("\n### Detalhe por pergunta\n")
    print("| Pergunta | Tipo | Relevantes | Recall L | Prec L | Recall V | Prec V | Recall H | Prec H |")
    print("|---|---|---|---|---|---|---|---|---|")
    for l in linhas:
        print(
            f"| {l['pergunta']} | {l['tipo']} | {l['n_relevantes']} | "
            f"{l['recall_lexico']:.2f} | {l['precisao_lexico']:.2f} | "
            f"{l['recall_vetorial']:.2f} | {l['precisao_vetorial']:.2f} | "
            f"{l['recall_hibrido']:.2f} | {l['precisao_hibrido']:.2f} |"
        )

    try:
        q = buscar_quarentena()
        print(f"\n### Quarentena\n")
        print(f"{q['percentual_quarentena']:.1f}% do acervo em quarentena ({q['total_quarentena']} de "
              f"{q['total_documentos_ok'] + q['total_quarentena']} documentos)")
        for item in q["por_tipo_erro"]:
            print(f"  - {item['tipo_erro']}: {item['total']}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[nao foi possivel obter stats de quarentena: {exc}]")


if __name__ == "__main__":
    main()
