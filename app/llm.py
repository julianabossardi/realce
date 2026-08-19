"""
Chamada ao LLM local via Ollama (Secao 4.6 do brief, revisao 2).

**Avaliacao atomica**: um criterio por chamada, com instrucao curta - nao
todos de uma vez. Modelos locais perdem consistencia quando recebem
varios criterios abstratos numa instrucao longa (comportamento observado
durante o desenvolvimento desta PoC com prompts multi-criterio - ver
README). Mais chamadas, porem mais confiavel, e permite atribuir
acerto/erro a um criterio especifico no feedback (Secao 4.9).

Nenhuma chamada externa: o Ollama roda localmente (`ollama serve`,
tipicamente em http://localhost:11434) e o modelo e baixado uma unica vez
(`ollama pull <modelo>`).
"""
from __future__ import annotations

import json
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")

# Schema JSON explicito (nao so "format": "json") - sem isso, o Ollama as
# vezes devolve texto fora do formato esperado quando o trecho de entrada
# e ruidoso (ex: tabelas muito fragmentadas). Suportado desde o Ollama 0.5
# (structured outputs).
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "atende": {"type": "boolean"},
        "score": {"type": "number"},
        "justificativa": {"type": "string"},
        "trecho_citado": {"type": "string"},
    },
    "required": ["atende", "score", "justificativa", "trecho_citado"],
}


def avaliar_criterio_unico(texto_chunk: str, criterio_descricao: str) -> dict:
    """Avalia UM criterio contra um chunk. Retorna
    {atende, score, justificativa, trecho_citado} (sem validar a citacao -
    isso e responsabilidade de app/evaluate.py, que tem acesso ao texto
    original do chunk para comparar)."""
    prompt = f"""Voce e um assistente de analise documental para o Ministerio Publico.
Avalie o trecho de diario oficial abaixo em relacao a UM UNICO criterio.
Responda se o trecho atende ao criterio (true/false), um score de 0 a 1,
uma justificativa curta, e cite o trecho EXATO (copiado literalmente do
texto abaixo, sem alterar nenhum caractere) que fundamenta a resposta. Se
o criterio nao se aplica, use trecho_citado como string vazia e
atende=false. Nomes proprios podem aparecer mascarados como [PESSOA_A],
[PESSOA_B] etc - trate cada pseudonimo como referencia a uma pessoa
fisica distinta.

Criterio: {criterio_descricao}

Trecho:
\"\"\"
{texto_chunk}
\"\"\"

Responda APENAS com um objeto JSON no formato:
{{"atende": true, "score": 0.0, "justificativa": "...", "trecho_citado": "..."}}"""

    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": _RESPONSE_SCHEMA,
            "options": {"temperature": 0.1},
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "{}")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return {"atende": False, "score": 0.0, "justificativa": "resposta do modelo nao pode ser interpretada", "trecho_citado": ""}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"atende": False, "score": 0.0, "justificativa": "resposta do modelo nao pode ser interpretada", "trecho_citado": ""}

    return parsed if isinstance(parsed, dict) else {"atende": False, "score": 0.0, "justificativa": "", "trecho_citado": ""}


_RESPONSE_SCHEMA_TITULO = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "sintese": {"type": "string"},
    },
    "required": ["titulo", "sintese"],
}

# caracteres do inicio do texto anonimizado enviados ao modelo - o suficiente
# para cobrir o cabecalho/ementa do ato (onde titulo/objeto do diario
# normalmente aparecem), sem mandar o documento inteiro. UMA chamada por
# DOCUMENTO (nao por chunk - ver ingestion/index.py), o que mantem o custo
# proporcional ao acervo, nao ao numero de trechos indexados.
CARACTERES_TITULO_SINTESE = 3000


def gerar_titulo_e_sintese(texto_documento: str) -> dict:
    """Gera {titulo, sintese} a partir do inicio do texto (ja normalizado
    e anonimizado) de UM documento. Falha (timeout, resposta invalida,
    Ollama fora do ar) e responsabilidade de quem chama tratar - devolve
    None nesse caso para o chamador recair no nome legivel composto a
    partir de metadado (municipio/tipo/data), sem quebrar a ingestao."""
    trecho = texto_documento[:CARACTERES_TITULO_SINTESE]
    prompt = f"""Voce e um assistente de organizacao documental para o Ministerio Publico.
Leia o inicio de um diario oficial municipal abaixo e devolva:
- um TITULO curto e descritivo (max. 12 palavras) que identifique o ato
  principal deste documento (ex: "Decreto de abertura de credito adicional -
  Niteroi"), nao generico como "Diario Oficial"
- uma SINTESE de uma a duas frases resumindo do que trata o documento

Nomes proprios podem aparecer mascarados como [PESSOA_A], [PESSOA_B] etc -
mantenha esses pseudonimos como estao se precisar citar alguem, nunca
invente um nome.

Texto:
\"\"\"
{trecho}
\"\"\"

Responda APENAS com um objeto JSON no formato:
{{"titulo": "...", "sintese": "..."}}"""

    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": _RESPONSE_SCHEMA_TITULO,
            "options": {"temperature": 0.2},
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "{}")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ValueError(f"resposta do modelo nao pode ser interpretada: {raw!r}")
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict) or not parsed.get("titulo"):
        raise ValueError(f"resposta do modelo sem titulo valido: {parsed!r}")

    return {
        "titulo": str(parsed["titulo"]).strip(),
        "sintese": str(parsed.get("sintese", "")).strip(),
    }
