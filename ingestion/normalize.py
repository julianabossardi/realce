"""
Normalizacao do texto extraido, entre a extracao (`extract.py`) e o
chunking (`chunk.py`) - camada que faltava no pipeline (adendo tecnico
pos-deploy). Sem ela, o chunking por contagem bruta de caracteres cortava
palavras ao meio e a ordem de leitura de paginas diagramadas ficava
implicita no texto cru, sem tratamento.

Roda por DOCUMENTO (sobre a lista de paginas ja extraidas), porque a
deteccao de cabecalho/rodape repetido exige comparar paginas entre si -
uma pagina isolada nao tem como saber se sua primeira linha e um titulo de
ato ou um cabecalho que se repete em todas as outras.

O texto cru de cada pagina (saida de `extract.py`) permanece intacto em
`ingestion/data/extracted/*.json` - essa normalizacao roda em memoria,
sobre uma copia, e so o resultado normalizado segue para anonimizacao/
chunking em `index.py`. Isso e o que o adendo pede por "manter o texto cru
para auditoria": a auditoria e o proprio artefato de extracao em disco,
sem precisar de uma segunda copia no Postgres.
"""
from __future__ import annotations

import re
from collections import Counter

# palavra quebrada por hifen de fim de linha: "recebi-\nmento" -> "recebimento".
# Restrito a letras (nao mexe em hifen de faixa numerica tipo "2024-2025").
_HIFEN_QUEBRADO_RE = re.compile(r"(?<=[a-zà-ú])-\s*\n\s*(?=[a-zà-ú])")

# sequencias de sublinhado/ponto/traco (isoladas ou misturadas) usadas como
# campo de preenchimento em formularios ("____________", ". . . . .",
# "----------"). Um marcador unico no lugar preserva a informacao de "aqui
# havia um campo a preencher" (usada depois pela heuristica de conteudo
# padronizado - ver ingestion/dedupe.py) sem que o ruido de pontuacao
# domine o texto do chunk.
_CAMPO_PREENCHIMENTO_RE = re.compile(r"[_.\-]{4,}")
MARCADOR_CAMPO_PREENCHIMENTO = "[CAMPO]"

_ESPACOS_HORIZONTAIS_RE = re.compile(r"[ \t]+")
_LINHAS_EM_BRANCO_RE = re.compile(r"\n{3,}")
_QUEBRA_SIMPLES_RE = re.compile(r"(?<!\n)\n(?!\n)")

# limiar de recorrencia para considerar uma linha cabecalho/rodape do
# documento: precisa aparecer em pelo menos metade das paginas (e o
# documento precisar ter paginas suficientes para o padrao ser
# significativo - 1 pagina repetindo "a primeira linha" nao e cabecalho).
MIN_PAGINAS_PARA_DETECTAR_CABECALHO = 3
LIMIAR_RECORRENCIA_CABECALHO = 0.5


def _juntar_hifenizacao(texto: str) -> str:
    return _HIFEN_QUEBRADO_RE.sub("", texto)


def _colapsar_quebras_de_linha(texto: str) -> str:
    """Quebra dupla (ou mais) = separador de paragrafo, preservada como
    "\\n\\n". Quebra simples dentro de paragrafo (artefato de wrap do PDF,
    nao pontuacao real) vira espaco."""
    paragrafos = _LINHAS_EM_BRANCO_RE.split(texto)
    paragrafos = [_QUEBRA_SIMPLES_RE.sub(" ", p) for p in paragrafos]
    return "\n\n".join(paragrafos)


def _colapsar_espacos(texto: str) -> str:
    texto = _ESPACOS_HORIZONTAIS_RE.sub(" ", texto)
    linhas = [linha.strip() for linha in texto.split("\n")]
    return "\n".join(linhas).strip()


def _marcar_campos_preenchimento(texto: str) -> str:
    return _CAMPO_PREENCHIMENTO_RE.sub(MARCADOR_CAMPO_PREENCHIMENTO, texto)


def normalizar_texto_pagina(texto: str) -> str:
    """Pipeline de normalizacao aplicado ao texto de UMA pagina, na ordem:
    hifenizacao -> campos de preenchimento -> quebras de linha -> espacos.
    Marcar campos de preenchimento antes de colapsar quebras evita que uma
    sequencia de sublinhados que atravessa uma quebra de linha vire duas
    marcacoes em vez de uma."""
    texto = _juntar_hifenizacao(texto)
    texto = _marcar_campos_preenchimento(texto)
    texto = _colapsar_quebras_de_linha(texto)
    texto = _colapsar_espacos(texto)
    return texto


def _linha_significativa(linha: str) -> str | None:
    """Normaliza uma linha para fins de comparacao entre paginas (chave de
    deduplicacao de cabecalho/rodape) - ignora diferencas de espaco e
    numeros isolados (numero de pagina muda a cada pagina, mas o resto do
    rodape - ex: "Diario Oficial de Niteroi - pagina X" - se repete)."""
    chave = re.sub(r"\d+", "#", linha.strip().lower())
    chave = re.sub(r"\s+", " ", chave)
    return chave if len(chave) >= 6 else None  # linhas curtas demais nao sao confiaveis como chave


def remover_cabecalhos_rodapes_repetidos(paginas_texto: list[str]) -> list[str]:
    """Recebe o texto ja normalizado de cada pagina do documento e remove a
    primeira/ultima linha quando ela se repete (mesma chave normalizada)
    em `LIMIAR_RECORRENCIA_CABECALHO` ou mais das paginas - sinal de
    cabecalho/rodape institucional fixo, nao conteudo do ato em si."""
    if len(paginas_texto) < MIN_PAGINAS_PARA_DETECTAR_CABECALHO:
        return paginas_texto

    primeiras = Counter()
    ultimas = Counter()
    for texto in paginas_texto:
        linhas = [l for l in texto.split("\n") if l.strip()]
        if not linhas:
            continue
        chave_primeira = _linha_significativa(linhas[0])
        if chave_primeira:
            primeiras[chave_primeira] += 1
        if len(linhas) > 1:
            chave_ultima = _linha_significativa(linhas[-1])
            if chave_ultima:
                ultimas[chave_ultima] += 1

    limiar = max(MIN_PAGINAS_PARA_DETECTAR_CABECALHO, round(len(paginas_texto) * LIMIAR_RECORRENCIA_CABECALHO))
    cabecalhos_repetidos = {chave for chave, n in primeiras.items() if n >= limiar}
    rodapes_repetidos = {chave for chave, n in ultimas.items() if n >= limiar}

    if not cabecalhos_repetidos and not rodapes_repetidos:
        return paginas_texto

    resultado = []
    for texto in paginas_texto:
        linhas = texto.split("\n")
        nao_vazias = [(i, l) for i, l in enumerate(linhas) if l.strip()]
        indices_remover = set()
        if nao_vazias:
            i0, primeira = nao_vazias[0]
            if _linha_significativa(primeira) in cabecalhos_repetidos:
                indices_remover.add(i0)
            if len(nao_vazias) > 1:
                i_ult, ultima = nao_vazias[-1]
                if _linha_significativa(ultima) in rodapes_repetidos:
                    indices_remover.add(i_ult)
        linhas_finais = [l for i, l in enumerate(linhas) if i not in indices_remover]
        resultado.append(_LINHAS_EM_BRANCO_RE.sub("\n\n", "\n".join(linhas_finais)).strip())

    return resultado


def normalizar_paginas(paginas: list[dict]) -> list[dict]:
    """Normaliza todas as paginas de um documento (`paginas` no formato de
    `extract.py`: lista de {pagina, texto, metodo, tem_tabela, ...}).
    Devolve uma NOVA lista de dicts (copia rasa + `texto` substituido) -
    nao muda o dict original, que permanece como registro cru em
    `ingestion/data/extracted/*.json`."""
    normalizadas = [normalizar_texto_pagina(p["texto"]) for p in paginas]
    normalizadas = remover_cabecalhos_rodapes_repetidos(normalizadas)
    return [{**p, "texto": t} for p, t in zip(paginas, normalizadas)]
