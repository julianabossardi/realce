"""
Anonimizacao na ingestao (Secao 4.1.1 do brief).

Roda sobre o texto de CADA documento, antes do chunking/embedding - nao e
uma etapa sob demanda como a avaliacao por criterios. Combina:
    - regras/regex para padroes estruturados (CPF, RG, telefone)
    - NER local em portugues (spaCy `pt_core_news_sm`) para nomes proprios

Devolve o texto com os dados sensiveis substituidos por placeholders
(`[PESSOA_1]`, `[CPF_1]`, ...) e a lista de entidades mascaradas (com o
valor original), que e gravada em `entidades_mascaradas` - tabela sensivel,
mantida separada do texto principal (ver app/access.py e db/migrations).

Limitacao conhecida a documentar no README: NER local para portugues nao e
perfeito. Falsos negativos (nome nao detectado, permanece no texto) sao um
risco real, nao escondido - a taxa observada na amostra fica registrada
como parte da avaliacao desta PoC.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import spacy

_CPF_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_RG_RE = re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-?[\dXx]?\b")
_TELEFONE_RE = re.compile(r"\(?\b\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b")

# Diarios oficiais escrevem nomes de pessoa fisica inteiramente em
# MAIUSCULAS, um padrao que o NER do spaCy (treinado majoritariamente em
# texto com capitalizacao normal) erra sistematicamente (falso negativo -
# ver README). Esse regex complementa o NER para esse caso especifico:
# sequencias de 2+ palavras em maiusculas, excluindo nomes de orgaos/
# instituicoes (lista de bloqueio abaixo). Continua sendo uma heuristica,
# nao uma garantia - falsos negativos residuais sao esperados e
# documentados.
_NOME_MAIUSCULO_RE = re.compile(r"\b[A-ZÀ-Ü]{2,}(?:\s+[A-ZÀ-Ü]{1,}){1,5}\b")
_CONECTORES = {"DA", "DE", "DO", "DOS", "DAS", "E"}
_BLOQUEIO_INSTITUCIONAL = {
    "PREFEITURA", "MUNICIPAL", "MUNICIPIO", "SECRETARIA", "GOVERNO",
    "ESTADO", "DEPARTAMENTO", "DIRETORIA", "COORDENADORIA",
    "SUPERINTENDENCIA", "PROCURADORIA", "DIARIO", "OFICIAL", "PORTARIA",
    "DECRETO", "EDITAL", "PODER", "EXECUTIVO", "LEGISLATIVO", "CAMARA",
    "GABINETE", "ADMINISTRACAO", "FUNDACAO", "AUTARQUIA", "COMPANHIA",
    "INSTITUTO", "CONSELHO", "COMISSAO", "TRIBUNAL", "MINISTERIO",
}


def _parece_nome_de_pessoa(tokens: list[str]) -> bool:
    reais = [t for t in tokens if t not in _CONECTORES]
    if len(reais) < 2:
        return False
    if any(t in _BLOQUEIO_INSTITUCIONAL for t in reais):
        return False
    return all(len(t) >= 2 for t in reais)


_PLACEHOLDER_RE = re.compile(r"^[A-Z]+_\d+$")

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("pt_core_news_sm")
    return _nlp


@dataclass
class EntidadeMascarada:
    tipo_entidade: str
    placeholder: str
    valor_original: str


def _mascarar_por_regex(texto: str, pattern: re.Pattern, tipo: str, contador: dict, entidades: list[EntidadeMascarada]) -> str:
    valor_para_placeholder: dict[str, str] = {}

    def replace(m: re.Match) -> str:
        valor = m.group(0)
        if valor not in valor_para_placeholder:
            contador[tipo] = contador.get(tipo, 0) + 1
            placeholder = f"[{tipo}_{contador[tipo]}]"
            valor_para_placeholder[valor] = placeholder
            entidades.append(EntidadeMascarada(tipo, placeholder, valor))
        return valor_para_placeholder[valor]

    return pattern.sub(replace, texto)


def anonimizar_documento(texto: str) -> tuple[str, list[EntidadeMascarada]]:
    """Retorna (texto_anonimizado, entidades_mascaradas)."""
    entidades: list[EntidadeMascarada] = []
    contador: dict[str, int] = {}

    # 1) padroes estruturados primeiro (CPF antes de RG - CPF e mais especifico)
    texto = _mascarar_por_regex(texto, _CPF_RE, "CPF", contador, entidades)
    texto = _mascarar_por_regex(texto, _RG_RE, "RG", contador, entidades)
    texto = _mascarar_por_regex(texto, _TELEFONE_RE, "TELEFONE", contador, entidades)

    # 2) nomes em MAIUSCULAS (padrao comum em diarios oficiais que o NER
    # do spaCy costuma perder - ver comentario acima da regex).
    valor_para_placeholder_pessoa: dict[str, str] = {e.valor_original: e.placeholder for e in entidades if e.tipo_entidade == "PESSOA"}

    def _replace_maiusculo(m: re.Match) -> str:
        valor = m.group(0)
        if not _parece_nome_de_pessoa(valor.split()):
            return valor
        if valor not in valor_para_placeholder_pessoa:
            contador["PESSOA"] = contador.get("PESSOA", 0) + 1
            placeholder = f"[PESSOA_{contador['PESSOA']}]"
            valor_para_placeholder_pessoa[valor] = placeholder
            entidades.append(EntidadeMascarada("PESSOA", placeholder, valor))
        return valor_para_placeholder_pessoa[valor]

    texto = _NOME_MAIUSCULO_RE.sub(_replace_maiusculo, texto)

    # 3) nomes proprios em capitalizacao normal via NER local. Roda sobre
    # o texto ja mascarado nos passos anteriores. O spaCy as vezes
    # classifica o proprio placeholder (ex: "PESSOA_1" dentro de
    # "[PESSOA_1]") como um nome - o guard `_PLACEHOLDER_RE` evita
    # mascarar o mascaramento.
    nlp = _get_nlp()
    doc = nlp(texto)

    valor_para_placeholder: dict[str, str] = {}
    partes = []
    cursor = 0
    for ent in doc.ents:
        if ent.label_ != "PER":
            continue
        if _PLACEHOLDER_RE.match(ent.text):
            continue
        valor = ent.text
        if valor not in valor_para_placeholder:
            contador["PESSOA"] = contador.get("PESSOA", 0) + 1
            placeholder = f"[PESSOA_{contador['PESSOA']}]"
            valor_para_placeholder[valor] = placeholder
            entidades.append(EntidadeMascarada("PESSOA", placeholder, valor))
        partes.append(texto[cursor:ent.start_char])
        partes.append(valor_para_placeholder[valor])
        cursor = ent.end_char
    partes.append(texto[cursor:])
    texto_anonimizado = "".join(partes)

    return texto_anonimizado, entidades
