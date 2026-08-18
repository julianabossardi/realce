"""
Avaliacao da hipotese central da PoC (Secao 4.6 do brief).

Roda um pequeno conjunto de perguntas de teste, com gabarito manual (nivel
documento), pelos dois caminhos - Caminho A (keyword/tsvector) e Caminho B
(semantico + avaliacao por criterios via LLM local) - contra a API FastAPI
rodando localmente, e calcula recall/precisao de cada um.

O gabarito foi construido inspecionando o texto ja extraido da amostra
(ingestion/data/extracted_manifest.json) com expressoes regulares
verificadas manualmente contra o trecho encontrado (nao e uma anotacao
totalmente manual, mas cada acerto foi conferido por leitura humana do
trecho antes de entrar no gabarito - ver README para a metodologia
completa e suas limitacoes).

Pre-requisito: a API FastAPI precisa estar rodando (`uvicorn app.main:app`)
e o banco ja populado (`python ingestion/embed_and_load.py`).

Uso:
    python experiments/compare_recall.py
"""
from __future__ import annotations

import requests

API_URL = "http://localhost:8000"

# Perguntas de teste com gabarito manual (nivel documento, por
# `arquivo_local`). Deliberadamente variam a "distancia semantica" entre a
# pergunta em linguagem natural e as palavras literais usadas no diario -
# isso e o que deve favorecer o Caminho B sobre o Caminho A, conforme a
# hipotese da Secao 2 do brief.
CASOS_DE_TESTE = [
    {
        "pergunta": "Existe algum servidor com processo de cessão para outro órgão deferido?",
        "relevantes": {
            "niteroi_2026-08-07_2b1a921a718559974690d0c190d4cb42f394ffbf.pdf",
        },
    },
    {
        "pergunta": "Quais processos de auxílio por doença foram deferidos a servidores?",
        "relevantes": {
            "niteroi_2026-07-18_f6c705153f876f0ac6d418b34ebd9d8c566d3d01.pdf",
            "niteroi_2026-07-25_89ce407a8339a9d1e4188d21c205d14011327810.pdf",
        },
    },
    {
        "pergunta": "Há concessão de pensão por morte decorrente do falecimento de um servidor ou ex-servidor?",
        "relevantes": {
            "angra-dos-reis_2026-06-24_fa31cc77c239b6e614a7d07655abf1b1cdafcf04.pdf",
            "niteroi_2026-08-15_5795fad11b1337b83f9afca9df91565e952edd62.pdf",
        },
    },
    {
        "pergunta": "Quais atos nomeiam servidores para cargos em comissão (CC)?",
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
]

LIMITE_RESULTADOS = 10


def buscar(consulta: str, caminho: str) -> list[str]:
    resp = requests.post(
        f"{API_URL}/search",
        json={"consulta": consulta, "caminho": caminho, "limite": LIMITE_RESULTADOS},
        timeout=600,
    )
    resp.raise_for_status()
    resultados = resp.json()["resultados"]
    # deduplica por documento, preservando ordem de relevancia
    vistos = []
    for r in resultados:
        if r["arquivo_local"] not in vistos:
            vistos.append(r["arquivo_local"])
    return vistos


def recall_precisao(recuperados: list[str], relevantes: set[str]) -> tuple[float, float]:
    recuperados_set = set(recuperados)
    acertos = recuperados_set & relevantes
    recall = len(acertos) / len(relevantes) if relevantes else 0.0
    precisao = len(acertos) / len(recuperados_set) if recuperados_set else 0.0
    return recall, precisao


def main():
    linhas = []
    for caso in CASOS_DE_TESTE:
        pergunta = caso["pergunta"]
        relevantes = caso["relevantes"]

        docs_keyword = buscar(pergunta, "keyword")
        recall_a, precisao_a = recall_precisao(docs_keyword, relevantes)

        docs_semantico = buscar(pergunta, "semantico")
        recall_b, precisao_b = recall_precisao(docs_semantico, relevantes)

        linhas.append(
            {
                "pergunta": pergunta,
                "n_relevantes": len(relevantes),
                "recall_a": recall_a,
                "precisao_a": precisao_a,
                "recall_b": recall_b,
                "precisao_b": precisao_b,
            }
        )
        print(f"\n=== {pergunta} ===")
        print(f"  gabarito: {len(relevantes)} documento(s)")
        print(f"  Caminho A (keyword)   -> recall {recall_a:.2f}, precisao {precisao_a:.2f}  ({docs_keyword})")
        print(f"  Caminho B (semantico) -> recall {recall_b:.2f}, precisao {precisao_b:.2f}  ({docs_semantico})")

    media_recall_a = sum(l["recall_a"] for l in linhas) / len(linhas)
    media_precisao_a = sum(l["precisao_a"] for l in linhas) / len(linhas)
    media_recall_b = sum(l["recall_b"] for l in linhas) / len(linhas)
    media_precisao_b = sum(l["precisao_b"] for l in linhas) / len(linhas)

    print("\n\n## Comparacao final (media das perguntas)\n")
    print("| Caminho | Recall medio | Precisao media |")
    print("|---|---|---|")
    print(f"| A - keyword (baseline) | {media_recall_a:.2f} | {media_precisao_a:.2f} |")
    print(f"| B - semantico + IA | {media_recall_b:.2f} | {media_precisao_b:.2f} |")

    print("\n| Pergunta | Relevantes | Recall A | Precisao A | Recall B | Precisao B |")
    print("|---|---|---|---|---|---|")
    for l in linhas:
        print(
            f"| {l['pergunta']} | {l['n_relevantes']} | {l['recall_a']:.2f} | "
            f"{l['precisao_a']:.2f} | {l['recall_b']:.2f} | {l['precisao_b']:.2f} |"
        )


if __name__ == "__main__":
    main()
