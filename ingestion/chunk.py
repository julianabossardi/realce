"""
Chunking por fronteira semantica (adendo tecnico pos-deploy) - substitui o
corte por contagem bruta de caracteres do `index.py` original, que cortava
palavras e tokens de anonimizacao ao meio (ex: "ebimento" em vez de
"recebimento", "PESSOA_FN]" sem colchete de abertura).

Estrategia, em ordem:
    1. dividir o texto (ja normalizado e anonimizado) em paragrafos
    2. agrupar paragrafos consecutivos ate aproximar CHUNK_SIZE_CHARS, sem
       ultrapassar
    3. quando um paragrafo isolado ja excede o alvo, dividir por sentenca
       (nunca dentro de sentenca); se nem sentenca resolver (paragrafo sem
       pontuacao, ex: tabela colada), cai para corte por palavra
    4. em qualquer um dos casos acima, o corte so acontece em fronteira de
       espaco/paragrafo/sentenca - um token `[TIPO_XXX]` nunca tem
       caractere interno correspondendo a essas fronteiras, entao nunca e
       partido (nao ha necessidade de um caso especial para isso: e
       consequencia de nunca cortar no meio de uma "palavra" no sentido
       amplo)
    5. descarta chunks abaixo de MIN_CHUNK_CHARS uteis - tipicamente
       fragmentos de cabecalho que sobraram

Le o texto ja com marcadores de pagina (`<<PAGINA:N>>`), do mesmo jeito
que o `chunkar_texto_anonimizado` que substitui - mantem a rastreabilidade
por pagina/offset (Secao 4.8) inalterada.
"""
from __future__ import annotations

import re

CHUNK_SIZE_CHARS = 2000  # aprox. 500 tokens em portugues - mesmo alvo da versao anterior
MIN_CHUNK_CHARS = 80  # abaixo disso, chunk e descartado (fragmento de cabecalho/rodape residual)

_PAGE_MARKER_RE = re.compile(r"<<PAGINA:(\d+)>>")
_PARAGRAFO_RE = re.compile(r"\n{2,}")
# fim de sentenca: pontuacao [.!?] seguida de espaco e maiuscula/digito/abre-colchete -
# evita quebrar em abreviacoes seguidas de minuscula (aproximacao, nao um
# tokenizador de sentencas completo).
_SENTENCA_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ú0-9\[])")


def _remover_marcadores_de_pagina(texto_com_marcadores: str) -> tuple[str, list[tuple[int, int]]]:
    """Retira `<<PAGINA:N>>` do texto e devolve (texto_limpo, offsets), onde
    offsets e uma lista de (offset_no_texto_limpo, numero_da_pagina) em
    ordem crescente de offset - usada por `_pagina_no_offset`."""
    partes = []
    offsets = []
    cursor = 0
    for match in _PAGE_MARKER_RE.finditer(texto_com_marcadores):
        pagina = int(match.group(1))
        partes.append(texto_com_marcadores[cursor:match.start()])
        offsets.append((sum(len(s) for s in partes), pagina))
        cursor = match.end()
    partes.append(texto_com_marcadores[cursor:])
    return "".join(partes), offsets


def _pagina_no_offset(offset: int, offsets_pagina: list[tuple[int, int]]) -> int:
    pagina = offsets_pagina[0][1] if offsets_pagina else 1
    for off, pag in offsets_pagina:
        if off <= offset:
            pagina = pag
        else:
            break
    return pagina


def _dividir_paragrafo_grande(paragrafo: str) -> list[str]:
    """Um paragrafo isolado maior que o alvo: divide por sentenca,
    agrupando sentencas consecutivas ate aproximar o alvo. Se o paragrafo
    nao tem nenhuma fronteira de sentenca (ex: bloco de tabela colado sem
    pontuacao), cai para corte por palavra - ainda assim nunca no meio de
    um token."""
    sentencas = _SENTENCA_RE.split(paragrafo)
    if len(sentencas) == 1:
        palavras = paragrafo.split(" ")
        sentencas = []
        atual = []
        tamanho = 0
        for palavra in palavras:
            if tamanho + len(palavra) + 1 > CHUNK_SIZE_CHARS and atual:
                sentencas.append(" ".join(atual))
                atual, tamanho = [], 0
            atual.append(palavra)
            tamanho += len(palavra) + 1
        if atual:
            sentencas.append(" ".join(atual))

    grupos = []
    atual = []
    tamanho = 0
    for sentenca in sentencas:
        if tamanho + len(sentenca) + 1 > CHUNK_SIZE_CHARS and atual:
            grupos.append(" ".join(atual))
            atual, tamanho = [], 0
        atual.append(sentenca)
        tamanho += len(sentenca) + 1
    if atual:
        grupos.append(" ".join(atual))
    return grupos


def _agrupar_paragrafos(paragrafos: list[str]) -> list[str]:
    grupos: list[str] = []
    atual: list[str] = []
    tamanho = 0
    for paragrafo in paragrafos:
        if not paragrafo.strip():
            continue
        if len(paragrafo) > CHUNK_SIZE_CHARS:
            if atual:
                grupos.append("\n\n".join(atual))
                atual, tamanho = [], 0
            grupos.extend(_dividir_paragrafo_grande(paragrafo))
            continue
        if tamanho + len(paragrafo) + 2 > CHUNK_SIZE_CHARS and atual:
            grupos.append("\n\n".join(atual))
            atual, tamanho = [], 0
        atual.append(paragrafo)
        tamanho += len(paragrafo) + 2
    if atual:
        grupos.append("\n\n".join(atual))
    return grupos


def chunkar_texto(texto_com_marcadores: str, metodo_por_pagina: dict[int, str], versao_por_metodo: dict[int, str] | dict[str, str]) -> list[dict]:
    """Divide o texto (anonimizado, com marcadores `<<PAGINA:N>>`) em
    chunks por fronteira semantica. Cada chunk preserva pagina de origem e
    offset de caracteres no texto sem marcadores (linhagem - Secao 4.8),
    igual ao chunking anterior por contagem de caracteres substituido."""
    texto_limpo, offsets_pagina = _remover_marcadores_de_pagina(texto_com_marcadores)

    paragrafos_com_offset = []
    cursor = 0
    for match in _PARAGRAFO_RE.finditer(texto_limpo):
        paragrafos_com_offset.append((cursor, texto_limpo[cursor:match.start()]))
        cursor = match.end()
    paragrafos_com_offset.append((cursor, texto_limpo[cursor:]))

    # offset de cada paragrafo se perde ao re-agrupar em `_agrupar_paragrafos`
    # (que so trabalha com o texto). Em vez de propagar offset por
    # paragrafo pelas funcoes de agrupamento, localizamos cada grupo
    # resultante de volta no texto limpo, na ordem (busca sequencial a
    # partir do cursor anterior - o grupo e sempre uma substring contigua
    # do texto original, entao a busca nunca "anda para tras").
    grupos = _agrupar_paragrafos([p for _, p in paragrafos_com_offset])

    chunks = []
    cursor_busca = 0
    for grupo in grupos:
        trecho = grupo.strip()
        if not trecho:
            continue
        offset_inicio = texto_limpo.find(trecho, cursor_busca)
        if offset_inicio == -1:  # nao deveria acontecer, mas nao trava a ingestao por isso
            offset_inicio = cursor_busca
        cursor_busca = offset_inicio + len(trecho)

        if len(trecho) < MIN_CHUNK_CHARS:
            continue

        pagina = _pagina_no_offset(offset_inicio, offsets_pagina)
        metodo = metodo_por_pagina.get(pagina, "pdfplumber")
        chunks.append(
            {
                "texto": trecho,
                "pagina": pagina,
                "metodo_extracao": metodo,
                "metodo_extracao_versao": versao_por_metodo.get(metodo, metodo),
                "offset_inicio": offset_inicio,
                "offset_fim": offset_inicio + len(trecho),
            }
        )

    return chunks
