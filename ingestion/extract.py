"""
Extracao de texto em cascata para os PDFs do acervo (Secao 4.2 do brief,
revisao 2).

Ordem por pagina:
    1. pdfplumber             - PDF com texto nativo/selecionavel (rapido, preserva posicao)
    2. pytesseract+pdf2image  - OCR local quando o texto nativo esta ausente ou de
       baixa qualidade (heuristica: poucos caracteres, muitos caracteres nao
       alfabeticos)

Limitacao conhecida (documentada no README): nao ha fallback de visao
(modelo multimodal) para paginas com graficos, layouts muito complexos ou
extracao de baixissima qualidade - fora de escopo desta PoC (Secao 4.2).
Nesses casos a pagina fica marcada como 'ocr_baixa_confianca'.

**Deteccao de colunas por coordenadas (adendo tecnico pos-deploy).** No
caminho nativo (pdfplumber), a pagina nao usa mais `extract_text()`
diretamente: primeiro roda `_detectar_gap_coluna()` sobre os centros
horizontais das palavras (`page.extract_words()`), procurando um vazio
significativo na faixa central da pagina com volume comparavel de
palavras dos dois lados. Havendo esse vazio, a pagina e tratada como duas
colunas - as palavras de cada lado sao agrupadas em linhas por
proximidade vertical e a coluna esquerda inteira e emitida antes da
direita, que e a ordem de leitura correta e que `extract_text()` (posicao
bruta na pagina, sem noção de coluna) nao reconstitui sozinho. Nao
havendo esse vazio, cai para `extract_text()` normal (pagina de coluna
unica). O numero de colunas detectado fica registrado por pagina em
`qualidade_extracao` (Postgres). Continua sendo uma heuristica -
`--psm 3` no Tesseract (caminho OCR, sem deteccao de coluna por
coordenadas) segue sendo o unico tratamento de coluna nesse caminho.

**Fila de quarentena (nova nesta revisao).** Um documento so e excluido do
indice (nao vira `documentos`/`chunks`) quando falha de forma severa e
classificavel - ver `classificar_documento()`. Falhas pontuais (uma pagina
ruim dentro de um PDF majoritariamente bom) NAO tiram o documento da
quarentena - ficam so registradas por pagina, como antes. Documentos
quarentenados sao escritos em `data/quarentena.json`; quem grava a tabela
`quarentena` no Postgres e o `ingestion/index.py`, que roda depois.

O metodo usado em cada pagina fica registrado em `qualidade_extracao`
(gravado no Postgres por `ingestion/index.py`).

Observacao registrada durante o desenvolvimento: os PDFs do Querido Diario
ja passam por um pipeline de OCR proprio antes de serem publicados (a
maioria carrega uma camada de texto mesmo quando a origem era escaneada).
Por isso a cascata aqui decide o fallback por QUALIDADE do texto extraido,
nao apenas por ausencia de texto - o que tambem e o cenario mais realista
para o acervo do MPRJ. Na amostra coletada (70 documentos), isso se
confirmou: 1521 paginas via pdfplumber, 114 via OCR, 19 (1,1%) como
'ocr_baixa_confianca' - nenhum documento inteiro precisou ir para
quarentena (as paginas problematicas sao anexos/assinaturas isolados
dentro de diarios majoritariamente digitais).

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
from pdf2image.exceptions import PDFPageCountError
from pdfminer.pdfparser import PDFSyntaxError

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(DATA_DIR, "extracted")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")
QUARENTENA_PATH = os.path.join(DATA_DIR, "quarentena.json")

MIN_CHARS_PER_PAGE = 40  # abaixo disso, texto nativo e considerado ausente
MIN_ALPHA_RATIO = 0.5  # abaixo disso, texto nativo/OCR e considerado ruim (garbled)

MIN_CHARS_DOCUMENTO = 100  # abaixo disso no documento inteiro -> quarentena 'texto_vazio'
MIN_CHARS_DOCUMENTO_SUFICIENTE = 300  # abaixo disso -> quarentena 'texto_insuficiente'
LIMIAR_FALHA_OCR = 0.8  # proporcao de paginas 'ocr_baixa_confianca' -> quarentena 'falha_ocr'

TESSERACT_CONFIG = "--psm 3"  # segmentacao automatica de blocos - ajuda em colunas/tabelas

LARGURA_MIN_GAP_COLUNA_RATIO = 0.04  # gap minimo (fracao da largura da pagina) p/ considerar quebra de coluna
MIN_PALAVRAS_POR_COLUNA = 15  # abaixo disso de cada lado, nao ha confianca suficiente p/ tratar como 2 colunas


class ErroClassificado(Exception):
    def __init__(self, tipo_erro: str, mensagem: str, metodo_que_falhou: str = ""):
        super().__init__(mensagem)
        self.tipo_erro = tipo_erro
        self.mensagem = mensagem
        self.metodo_que_falhou = metodo_que_falhou


def alpha_ratio(text: str) -> float:
    letters = sum(1 for c in text if unicodedata.category(c).startswith("L"))
    return letters / max(len(text), 1)


def text_quality_ok(text: str | None) -> bool:
    if not text or len(text.strip()) < MIN_CHARS_PER_PAGE:
        return False
    return alpha_ratio(text) >= MIN_ALPHA_RATIO


def _detectar_gap_coluna(centros: list[float], largura_pagina: float) -> float | None:
    """Procura o maior vazio horizontal entre palavras na faixa central da
    pagina (30%-70% da largura). Devolve a posicao (x) do vazio quando ele
    e largo o suficiente (`LARGURA_MIN_GAP_COLUNA_RATIO`) e ha palavras
    suficientes dos dois lados (`MIN_PALAVRAS_POR_COLUNA`) - ambos
    necessarios para nao classificar como 2 colunas uma pagina de coluna
    unica que so tem uma margem esquerda maior por acaso (ex: pagina de
    rosto, tabela com uma coluna vazia)."""
    if len(centros) < MIN_PALAVRAS_POR_COLUNA * 2:
        return None

    ordenados = sorted(centros)
    faixa_min, faixa_max = largura_pagina * 0.3, largura_pagina * 0.7
    melhor_gap, melhor_pos = 0.0, None
    for a, b in zip(ordenados, ordenados[1:]):
        meio = (a + b) / 2
        if not (faixa_min <= meio <= faixa_max):
            continue
        gap = b - a
        if gap > melhor_gap:
            melhor_gap, melhor_pos = gap, meio

    if melhor_pos is None or melhor_gap < largura_pagina * LARGURA_MIN_GAP_COLUNA_RATIO:
        return None

    esquerda = sum(1 for c in ordenados if c < melhor_pos)
    direita = len(ordenados) - esquerda
    if esquerda < MIN_PALAVRAS_POR_COLUNA or direita < MIN_PALAVRAS_POR_COLUNA:
        return None
    return melhor_pos


def _texto_da_coluna(palavras_coluna: list[dict]) -> str:
    """Agrupa palavras (com coordenadas do pdfplumber) em linhas por
    proximidade vertical, na ordem de leitura de uma unica coluna (topo ->
    base, esquerda -> direita dentro de cada linha)."""
    if not palavras_coluna:
        return ""
    alturas = [w["bottom"] - w["top"] for w in palavras_coluna]
    tolerancia = (sum(alturas) / len(alturas)) * 0.6 or 1.0

    ordenadas = sorted(palavras_coluna, key=lambda w: (w["top"], w["x0"]))
    linhas = [[ordenadas[0]]]
    for w in ordenadas[1:]:
        if abs(w["top"] - linhas[-1][-1]["top"]) <= tolerancia:
            linhas[-1].append(w)
        else:
            linhas.append([w])

    return "\n".join(
        " ".join(w["text"] for w in sorted(linha, key=lambda w: w["x0"]))
        for linha in linhas
    )


def extract_native(page) -> tuple[str | None, list, int]:
    tables = page.extract_tables() or []
    tables_md = []
    for table in tables:
        rows = [" | ".join(cell or "" for cell in row) for row in table]
        tables_md.append("\n".join(rows))

    try:
        palavras = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:  # noqa: BLE001 - pagina sem texto/palavras extraiveis
        palavras = []

    gap_pos = None
    if palavras:
        centros = [(w["x0"] + w["x1"]) / 2 for w in palavras]
        gap_pos = _detectar_gap_coluna(centros, page.width)

    if gap_pos is not None:
        esquerda = [w for w in palavras if (w["x0"] + w["x1"]) / 2 < gap_pos]
        direita = [w for w in palavras if (w["x0"] + w["x1"]) / 2 >= gap_pos]
        text = "\n\n".join(t for t in (_texto_da_coluna(esquerda), _texto_da_coluna(direita)) if t)
        colunas = 2
    else:
        text = page.extract_text()
        colunas = 1

    return text, tables_md, colunas


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
    return pytesseract.image_to_string(images[0], lang="por", config=TESSERACT_CONFIG)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def classificar_documento(paginas: list[dict]) -> str | None:
    """Decide se o documento inteiro deve ir para quarentena. Retorna o
    tipo de erro classificado, ou None se o documento esta ok (mesmo que
    paginas individuais tenham ficado com baixa confianca)."""
    if not paginas:
        return "texto_vazio"

    total_chars = sum(len(p["texto"]) for p in paginas)
    if total_chars < MIN_CHARS_DOCUMENTO:
        return "texto_vazio"
    if total_chars < MIN_CHARS_DOCUMENTO_SUFICIENTE:
        return "texto_insuficiente"

    proporcao_baixa_confianca = sum(
        1 for p in paginas if p["metodo"] == "ocr_baixa_confianca"
    ) / len(paginas)
    if proporcao_baixa_confianca >= LIMIAR_FALHA_OCR:
        return "falha_ocr"

    return None


def process_document(entry: dict) -> dict:
    pdf_path = os.path.join(DATA_DIR, entry["arquivo_local"])
    print(f"-> {entry['arquivo_local']}")

    paginas = []
    metodos_usados = set()

    try:
        pdf = pdfplumber.open(pdf_path)
    except (PDFSyntaxError, PDFPageCountError) as exc:
        raise ErroClassificado("pdf_corrompido", str(exc), "pdfplumber.open") from exc
    except UnicodeDecodeError as exc:
        raise ErroClassificado("encoding_invalido", str(exc), "pdfplumber.open") from exc
    except Exception as exc:  # noqa: BLE001
        raise ErroClassificado("outro", str(exc), "pdfplumber.open") from exc

    try:
        with pdf:
            for i, page in enumerate(pdf.pages, start=1):
                try:
                    native_text, tables_md, colunas = extract_native(page)
                except Exception as exc:  # noqa: BLE001
                    raise ErroClassificado("outro", str(exc), f"pdfplumber pagina {i}") from exc

                metodo = "pdfplumber"
                texto_final = native_text or ""

                if not text_quality_ok(native_text):
                    ocr_text = extract_ocr(pdf_path, i)
                    if text_quality_ok(ocr_text):
                        metodo = "ocr"
                        texto_final = ocr_text
                    else:
                        metodo = "ocr_baixa_confianca"
                        texto_final = ocr_text or native_text or ""
                    colunas = None  # deteccao por coordenadas nao roda no caminho OCR

                if tables_md:
                    texto_final += "\n\n[TABELA]\n" + "\n\n[TABELA]\n".join(tables_md)

                metodos_usados.add(metodo)
                paginas.append(
                    {
                        "pagina": i,
                        "texto": normalize_whitespace(texto_final),
                        "metodo": metodo,
                        "colunas": colunas,
                        "tem_tabela": bool(tables_md),
                    }
                )
                print(f"   pagina {i}: {metodo} ({len(texto_final)} chars)")
    except ErroClassificado:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErroClassificado("outro", str(exc)) from exc

    tipo_erro = classificar_documento(paginas)
    if tipo_erro:
        metodo_que_falhou = max(metodos_usados, default="") or "nenhum"
        raise ErroClassificado(
            tipo_erro,
            f"{len(paginas)} paginas, {sum(len(p['texto']) for p in paginas)} chars no total",
            metodo_que_falhou,
        )

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
    quarentena = []

    for entry in manifest:
        out_path = os.path.join(OUTPUT_DIR, entry["arquivo_local"] + ".json")
        if os.path.exists(out_path):
            print(f"[ja extraido] {entry['arquivo_local']}")
            with open(out_path, encoding="utf-8") as f:
                resultados.append(json.load(f))
            continue

        try:
            resultado = process_document(entry)
        except ErroClassificado as exc:
            print(f"  [QUARENTENA: {exc.tipo_erro}] {entry['arquivo_local']}: {exc.mensagem}")
            quarentena.append(
                {
                    "arquivo_local": entry["arquivo_local"],
                    "municipio": entry.get("municipio"),
                    "territory_id": entry.get("territory_id"),
                    "tipo_erro": exc.tipo_erro,
                    "mensagem_erro": exc.mensagem,
                    "metodo_que_falhou": exc.metodo_que_falhou,
                }
            )
            continue

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        resultados.append(resultado)

    extracted_manifest_path = os.path.join(DATA_DIR, "extracted_manifest.json")
    with open(extracted_manifest_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    with open(QUARENTENA_PATH, "w", encoding="utf-8") as f:
        json.dump(quarentena, f, ensure_ascii=False, indent=2)

    metodos_count = {}
    for r in resultados:
        for p in r["paginas"]:
            metodos_count[p["metodo"]] = metodos_count.get(p["metodo"], 0) + 1
    total_paginas = sum(metodos_count.values())
    baixa_confianca_pct = 100 * metodos_count.get("ocr_baixa_confianca", 0) / max(total_paginas, 1)

    print(f"\nExtracao concluida: {len(resultados)} documentos ok, {len(quarentena)} em quarentena, {total_paginas} paginas.")
    print("Metodos usados por pagina:", metodos_count)
    print(f"% paginas com extracao de baixa confianca: {baixa_confianca_pct:.1f}%")
    if quarentena:
        tipos = {}
        for q in quarentena:
            tipos[q["tipo_erro"]] = tipos.get(q["tipo_erro"], 0) + 1
        print("Quarentena por tipo de erro:", tipos)


if __name__ == "__main__":
    main()
