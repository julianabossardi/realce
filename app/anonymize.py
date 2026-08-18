"""
Anonimizacao na ingestao (Secao 4.3 do brief, revisao 2).

Roda sobre o texto de CADA documento, antes do chunking/embedding. Duas
mudancas centrais desta revisao em relacao a versao anterior:

1. **Pseudonimos consistentes por entidade** (`[PESSOA_A]`, `[PESSOA_B]`,
   `[CPF_A]`, ...) em vez de um contador global (`[PESSOA_1]`,
   `[PESSOA_2]`, ...). Mascarar todas as pessoas com o mesmo rotulo
   destroi a distincao entre partes (quem fez o que a quem) e degrada a
   busca semantica, que perde a estrutura relacional da frase.
2. **Categorias configuraveis**: em vez de regex/NER fixos no codigo, as
   categorias (CPF, RG, TELEFONE, PESSOA, ...) sao lidas da tabela
   `categoria_sigilo` e passadas como parametro - ver `ingestion/index.py`
   para quem monta essa lista a partir do banco.

Devolve o texto com os dados sensiveis substituidos por pseudonimos e a
lista de entidades mascaradas (com o valor original e o offset no texto),
gravada em `entidades_mascaradas` - tabela sensivel, com acesso
condicionado ao perfil (app/access.py).

Limitacao conhecida a documentar no README: NER local para portugues nao
e perfeito. Falsos negativos (nome nao detectado) E falsos positivos
(substantivo comum mascarado como pessoa, sobretudo em conteudo tabular)
sao riscos reais, nao escondidos - ver README para o que foi observado na
amostra desta PoC.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass

import spacy

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("pt_core_news_sm")
    return _nlp


@dataclass
class Categoria:
    id: int
    nome: str
    tipo_deteccao: str  # 'regex' | 'ner' | 'documento_inteiro'
    padrao: str | None
    nivel_restricao: str


@dataclass
class EntidadeMascarada:
    categoria_id: int
    categoria_nome: str
    pseudonimo: str
    valor_original: str
    offset_inicio: int


def _letra_sequencial(n: int) -> str:
    """0->'A', 25->'Z', 26->'AA', 27->'AB', ... (estilo coluna de planilha)."""
    n += 1
    letras = ""
    while n > 0:
        n, resto = divmod(n - 1, 26)
        letras = string.ascii_uppercase[resto] + letras
    return letras


# Nomes de pessoa em diarios oficiais costumam vir inteiramente em
# MAIUSCULAS, um padrao que o NER do spaCy (treinado majoritariamente em
# texto com capitalizacao normal) erra sistematicamente (falso negativo -
# ver README). Este regex complementa o NER para esse caso especifico,
# aplicado somente sob a categoria PESSOA. Continua sendo uma heuristica,
# nao uma garantia - falsos negativos residuais sao esperados.
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
_PLACEHOLDER_RE = re.compile(r"^\[?[A-Z]+_[A-Z]+\]?$")


def _parece_nome_de_pessoa(tokens: list[str]) -> bool:
    reais = [t for t in tokens if t not in _CONECTORES]
    if len(reais) < 2:
        return False
    if any(t in _BLOQUEIO_INSTITUCIONAL for t in reais):
        return False
    return all(len(t) >= 2 for t in reais)


def anonimizar_documento(
    texto: str, categorias: list[Categoria]
) -> tuple[str, list[EntidadeMascarada]]:
    """Retorna (texto_anonimizado, entidades_mascaradas), usando as
    categorias de sigilo ativas (lidas de `categoria_sigilo`)."""
    entidades: list[EntidadeMascarada] = []
    # pseudonimo estavel por (categoria, valor original) dentro do documento
    contador_por_categoria: dict[str, int] = {}
    pseudonimo_por_valor: dict[tuple[str, str], str] = {}

    def registrar(categoria: Categoria, valor: str, offset: int) -> str:
        chave = (categoria.nome, valor)
        if chave not in pseudonimo_por_valor:
            n = contador_por_categoria.get(categoria.nome, 0)
            pseudonimo = f"[{categoria.nome}_{_letra_sequencial(n)}]"
            contador_por_categoria[categoria.nome] = n + 1
            pseudonimo_por_valor[chave] = pseudonimo
            entidades.append(
                EntidadeMascarada(categoria.id, categoria.nome, pseudonimo, valor, offset)
            )
        return pseudonimo_por_valor[chave]

    categorias_regex = [c for c in categorias if c.tipo_deteccao == "regex" and c.padrao]
    categorias_ner = [c for c in categorias if c.tipo_deteccao == "ner"]

    # 1) nomes de pessoa PRIMEIRO (NER + heuristica de MAIUSCULAS), sobre o
    # texto ainda intocado. Rodar isso DEPOIS dos regex de CPF/RG/telefone
    # foi tentado e descartado: o spaCy passou a classificar como PER a
    # palavra literal logo antes de um placeholder ja inserido (ex: "CPF"
    # em "CPF [CPF_A]"), um artefato do proprio mascaramento contaminando
    # o contexto do NER - ver README. Processar nomes primeiro evita isso.
    categoria_pessoa = next((c for c in categorias_ner if c.nome == "PESSOA"), None)
    if categoria_pessoa:
        def replace_maiusculo(m: re.Match) -> str:
            valor = m.group(0)
            if not _parece_nome_de_pessoa(valor.split()):
                return valor
            return registrar(categoria_pessoa, valor, m.start())

        texto = _NOME_MAIUSCULO_RE.sub(replace_maiusculo, texto)

        nlp = _get_nlp()
        doc = nlp(texto)
        partes = []
        cursor = 0
        for ent in doc.ents:
            if ent.label_ != "PER" or _PLACEHOLDER_RE.match(ent.text):
                continue
            partes.append(texto[cursor:ent.start_char])
            partes.append(registrar(categoria_pessoa, ent.text, ent.start_char))
            cursor = ent.end_char
        partes.append(texto[cursor:])
        texto = "".join(partes)

    # 2) padroes estruturados (regex) - ordem da lista determina prioridade
    # quando padroes se sobrepoem (ex: CPF antes de RG).
    for categoria in categorias_regex:
        pattern = re.compile(categoria.padrao)

        def replace(m: re.Match, categoria=categoria) -> str:
            return registrar(categoria, m.group(0), m.start())

        texto = pattern.sub(replace, texto)

    return texto, entidades
