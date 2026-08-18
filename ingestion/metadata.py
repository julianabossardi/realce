"""
Metadados leves, sem LLM (Secao 4.4 do brief).

Extrai campos baratos que servem de PRE-FILTRO da busca (reduz o conjunto
antes da etapa cara de avaliacao por criterios) - municipio, data e
territory_id ja vem do proprio manifest da fonte (Secao 4.1); este modulo
so acrescenta `tipo_documento`, inferido por regex sobre os rotulos que os
proprios diarios oficiais usam nos titulos dos atos.

Isso NAO e a mesma coisa que a avaliacao por criterios (Secao 4.6, cara,
via LLM, sob demanda) - e uma classificacao barata rodada para todo
documento na ingestao, exatamente porque e barata.
"""
from __future__ import annotations

import re
from collections import Counter

# Ordem nao importa para a contagem, mas o rotulo mais especifico vence em
# empate (ver _TIPO_PRIORIDADE) - por exemplo, um diario que soma mais
# "portaria" que "decreto" mas o decreto e o ato de abertura do dia.
_PADROES_TIPO_DOCUMENTO = {
    "Portaria": r"\bPORTARIA\b",
    "Decreto": r"\bDECRETO\b",
    "Edital": r"\bEDITAL\b",
    "Lei": r"\bLEI\s+(?:MUNICIPAL\s+)?N[ºO°]",
    "Resolução": r"\bRESOLU[ÇC][ÃA]O\b",
    "Aviso": r"\bAVISO\b",
    "Ofício": r"\bOF[ÍI]CIO\b",
    "Homologação": r"\bHOMOLOGA[ÇC][ÃA]O\b",
    "Extrato de Contrato": r"\bEXTRATO DE (?:CONTRATO|TERMO)\b",
}

_TIPO_PRIORIDADE = list(_PADROES_TIPO_DOCUMENTO.keys())


def extrair_metadados(texto_documento: str) -> dict:
    """Recebe o texto completo (ja anonimizado ou nao, tanto faz - os
    rotulos de tipo de ato nao sao dado sensivel) e devolve metadados
    leves. Por ora, so `tipo_documento` (o tipo de ato predominante no
    diario) - outros campos baratos podem ser adicionados aqui no futuro
    sem exigir LLM."""
    contagem = Counter()
    for tipo, padrao in _PADROES_TIPO_DOCUMENTO.items():
        ocorrencias = len(re.findall(padrao, texto_documento, re.IGNORECASE))
        if ocorrencias:
            contagem[tipo] = ocorrencias

    if not contagem:
        return {"tipo_documento": "Outro"}

    maior = max(contagem.values())
    empatados = [t for t, c in contagem.items() if c == maior]
    tipo_predominante = min(empatados, key=_TIPO_PRIORIDADE.index)

    return {"tipo_documento": tipo_predominante}
