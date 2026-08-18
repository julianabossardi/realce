"""
Extracao de texto em cascata para os PDFs do acervo (Secao 4.1 do brief).

Ordem por pagina:
    1. pdfplumber             - PDF com texto nativo/selecionavel (rapido, preserva posicao)
    2. pytesseract+pdf2image  - OCR local quando o texto nativo esta ausente ou de
       baixa qualidade (heuristica: poucos caracteres, muitos caracteres nao
       alfabeticos)

Limitacao conhecida (documentada no README): nao ha fallback de visao
(modelo multimodal) para paginas com graficos, layouts muito complexos ou
extracao de baixissima qualidade - um modelo de visao local exigiria mais
hardware do que se pode assumir disponivel para esta PoC. Nesses casos a
pagina fica marcada como 'ocr_baixa_confianca' em vez de se tentar uma
terceira via, e "% de paginas com extracao de baixa confianca" vira, ela
mesma, uma metrica a reportar.

O metodo usado em cada pagina fica registrado em `qualidade_extracao`
(gravado no Postgres pelo embed_and_load.py).

Observacao registrada durante o desenvolvimento: os PDFs do Querido Diario
ja passam por um pipeline de OCR proprio antes de serem publicados (a
maioria carrega uma camada de texto mesmo quando a origem era escaneada).
Por isso a cascata aqui decide o fallback por QUALIDADE do texto extraido,
nao apenas por ausencia de texto - o que tambem e o cenario mais realista
para o acervo do MPRJ, onde documentos digitalizados provavelmente ja terao
algum texto via OCR de terceiros, de qualidade variavel. Na amostra
coletada, isso se confirmou: a maioria das paginas tem texto nativo via
pdfplumber, mas paginas individuais dentro de diarios (anexos escaneados,
assinaturas, carimbos) caem no fallback de OCR.

Uso:
    python extract.py
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

import pdfplumber
import pytesseract
from pdf2image import convert_from_path

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(DATA_DIR, "extracted")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")

MIN_CHARS_PER_PAGE = 40  # abaixo disso, texto nativo e considerado ausente
MIN_ALPHA_RATIO = 0.5  # abaixo disso, texto nativo/OCR e considerado ruim (garbled)


def alpha_ratio(text: str) -> float:
    letters = sum(1 for c in text if unicodedata.category(c).startswith("L"))
    return letters / max(len(text), 1)


def text_quality_ok(text: str | None) -> bool:
    if not text or len(text.strip()) < MIN_CHARS_PER_PAGE:
        return False
    return alpha_ratio(text) >= MIN_ALPHA_RATIO


def extract_native(page) -> tuple[str | None, list]:
    text = page.extract_text()
    tables = page.extract_tables() or []
    tables_md = []
    for table in tables:
        rows = [" | ".join(cell or "" for cell in row) for row in table]
        tables_md.append("\n".join(rows))
    return text, tables_md


def extract_ocr(pdf_path: str, page_number: int) -> str | None:
    try:
        images = convert_from_path(
            pdf_path, first_page=page_number, last_page=page_number, dpi=300
        )
    except Exception as exc:  # noqa: BLE001
        print(f"    [ocr erro ao rasterizar] {exc}")
        return None
    if not images:
        return None
    return pytesseract.image_to_string(images[0], lang="por")


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def process_document(entry: dict) -> dict:
    pdf_path = os.path.join(DATA_DIR, entry["arquivo_local"])
    print(f"-> {entry['arquivo_local']}")

    paginas = []
    metodos_usados = set()

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            native_text, tables_md = extract_native(page)
            metodo = "pdfplumber"
            texto_final = native_text or ""

            if not text_quality_ok(native_text):
                ocr_text = extract_ocr(pdf_path, i)
                if text_quality_ok(ocr_text):
                    metodo = "ocr"
                    texto_final = ocr_text
                else:
                    # nem texto nativo nem OCR local atingiram um minimo de
                    # confianca - sem fallback de visao nesta PoC (ver
                    # docstring do modulo). Registra o melhor que se tem.
                    metodo = "ocr_baixa_confianca"
                    texto_final = ocr_text or native_text or ""

            if tables_md:
                texto_final += "\n\n[TABELA]\n" + "\n\n[TABELA]\n".join(tables_md)

            metodos_usados.add(metodo)
            paginas.append(
                {
                    "pagina": i,
                    "texto": normalize_whitespace(texto_final),
                    "metodo": metodo,
                    "tem_tabela": bool(tables_md),
                }
            )
            print(f"   pagina {i}: {metodo} ({len(texto_final)} chars)")

    metodo_predominante = max(metodos_usados, key=lambda m: sum(1 for p in paginas if p["metodo"] == m))

    return {
        **entry,
        "num_paginas": len(paginas),
        "metodo_extracao_predominante": metodo_predominante,
        "paginas": paginas,
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    resultados = []
    for entry in manifest:
        out_path = os.path.join(OUTPUT_DIR, entry["arquivo_local"] + ".json")
        if os.path.exists(out_path):
            print(f"[ja extraido] {entry['arquivo_local']}")
            with open(out_path, encoding="utf-8") as f:
                resultados.append(json.load(f))
            continue

        resultado = process_document(entry)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        resultados.append(resultado)

    extracted_manifest_path = os.path.join(DATA_DIR, "extracted_manifest.json")
    with open(extracted_manifest_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    metodos_count = {}
    for r in resultados:
        for p in r["paginas"]:
            metodos_count[p["metodo"]] = metodos_count.get(p["metodo"], 0) + 1
    total_paginas = sum(metodos_count.values())
    baixa_confianca_pct = 100 * metodos_count.get("ocr_baixa_confianca", 0) / max(total_paginas, 1)

    print(f"\nExtracao concluida: {len(resultados)} documentos, {total_paginas} paginas.")
    print("Metodos usados por pagina:", metodos_count)
    print(f"% paginas com extracao de baixa confianca: {baixa_confianca_pct:.1f}%")


if __name__ == "__main__":
    main()
