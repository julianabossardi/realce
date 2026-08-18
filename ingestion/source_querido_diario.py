"""
Fonte de dados brutos: Querido Diario (API publica).

Isolado num modulo proprio de proposito (Secao 3.1 do brief): a obtencao da
amostra da PoC via API do Querido Diario e uma conveniencia do experimento,
NAO uma validacao de que o MPRJ tem (ou tera) um canal equivalente. Essa e
uma incerteza em aberto da proposta (upload manual vs. integracao com banco
existente vs. API propria).

Para nao acoplar o pipeline a essa fonte especifica, este modulo expoe uma
unica funcao de fronteira - `obter_documentos()` - que devolve uma lista de
metadados de documentos brutos, cada um com um `arquivo_local` ja baixado em
disco. O resto do pipeline (extract.py, embed_and_load.py) so conhece esse
contrato. Se depois se confirmar outra fonte (API propria do MPRJ, banco
existente, upload manual), a troca e feita escrevendo um novo modulo
`source_<outra_fonte>.py` com a mesma funcao `obter_documentos()` - nenhuma
outra parte do pipeline precisa mudar.

API: https://docs.queridodiario.ok.org.br/en/latest/using/public-api.html
Base URL: https://api.queridodiario.ok.org.br

Uso:
    python source_querido_diario.py

Municipios escolhidos (ver README para justificativa):
    - Niteroi/RJ         (3303302) - grande, publicacao digital nativa
    - Angra dos Reis/RJ  (3300100) - medio porte
    - Varre-Sai/RJ       (3306156) - pequeno porte (~9 mil hab.)
"""
from __future__ import annotations

import json
import os
import time
import unicodedata

import requests

API_BASE = "https://api.queridodiario.ok.org.br"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

MUNICIPIOS = [
    {"territory_id": "3303302", "nome": "Niteroi", "docs_por_municipio": 25},
    {"territory_id": "3300100", "nome": "Angra dos Reis", "docs_por_municipio": 25},
    {"territory_id": "3306156", "nome": "Varre-Sai", "docs_por_municipio": 20},
]

REQUEST_INTERVAL_SECONDS = 1.0  # a API pede ritmo de referencia de 60 req/min


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return value.lower().replace(" ", "-")


def _fetch_gazettes(territory_id: str, size: int) -> list[dict]:
    resp = requests.get(
        f"{API_BASE}/gazettes",
        params={
            "territory_ids": territory_id,
            "size": size,
            "sort_by": "descending_date",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("gazettes", [])


def _download_pdf(url: str, dest_path: str) -> int:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)
    return len(resp.content)


def obter_documentos(forcar_novo_download: bool = False) -> list[dict]:
    """Contrato de fronteira desta fonte: baixa (se necessario) e devolve a
    lista de documentos brutos, cada um com metadados + `arquivo_local`
    apontando para o PDF em disco (relativo a ingestion/data/)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    manifest = []

    for municipio in MUNICIPIOS:
        slug = slugify(municipio["nome"])
        print(f"\n=== {municipio['nome']} ({municipio['territory_id']}) ===")
        gazettes = _fetch_gazettes(municipio["territory_id"], municipio["docs_por_municipio"])
        print(f"  {len(gazettes)} diarios encontrados")

        for g in gazettes:
            filename = f"{slug}_{g['date']}_{os.path.basename(g['url'])}"
            dest_path = os.path.join(DATA_DIR, filename)

            if os.path.exists(dest_path) and not forcar_novo_download:
                print(f"  [ja existe] {filename}")
            else:
                try:
                    size = _download_pdf(g["url"], dest_path)
                    print(f"  [ok] {filename} ({size} bytes)")
                    time.sleep(REQUEST_INTERVAL_SECONDS)
                except Exception as exc:  # noqa: BLE001 - registra e segue
                    print(f"  [erro] {filename}: {exc}")
                    continue

            manifest.append(
                {
                    "municipio": municipio["nome"],
                    "territory_id": municipio["territory_id"],
                    "data": g["date"],
                    "edicao": g.get("edition", ""),
                    "url_origem": g["url"],
                    "arquivo_local": filename,
                }
            )

    return manifest


def main():
    manifest = obter_documentos()
    manifest_path = os.path.join(DATA_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\nManifest salvo em {manifest_path} ({len(manifest)} documentos)")


if __name__ == "__main__":
    main()
