"""
Avaliacao por criterios via LLM local, servido pelo Ollama (Secao 4.4/5).

Nenhuma chamada externa: o Ollama roda localmente (`ollama serve`,
tipicamente em http://localhost:11434) e o modelo e baixado uma unica vez
(`ollama pull <modelo>`). Ver README para a comparacao entre os modelos
testados (qwen2.5:7b-instruct vs. llama3.2:3b) e o motivo da escolha final.
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

Criterio = dict  # {"chave": str, "descricao": str}

# Schema JSON explicito (nao so "format": "json") - sem isso, o Ollama as
# vezes devolve um objeto solto em vez do array esperado quando o trecho
# de entrada e ruidoso (ex: tabelas muito fragmentadas), quebrando o
# parsing. Suportado desde o Ollama 0.5 (structured outputs).
_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "criterio_chave": {"type": "string"},
            "atende": {"type": "boolean"},
            "score": {"type": "number"},
            "justificativa": {"type": "string"},
            "trecho_citado": {"type": "string"},
        },
        "required": ["criterio_chave", "atende", "score", "justificativa", "trecho_citado"],
    },
}


def avaliar_criterios(texto_chunk: str, criterios: list[Criterio]) -> list[dict]:
    """Aplica o conjunto de criterios de relevancia vigente sobre um chunk
    candidato (Secao 4.4). Retorna uma avaliacao por criterio, com citacao
    do trecho de origem para rastreabilidade."""
    lista_criterios = "\n".join(f"- {c['chave']}: {c['descricao']}" for c in criterios)

    prompt = f"""Voce e um assistente de analise documental para o Ministerio Publico.
Avalie o trecho de diario oficial abaixo em relacao a CADA um dos criterios listados.
Para cada criterio, responda se o trecho atende (true/false), um score de 0 a 1,
uma justificativa curta, e cite o trecho EXATO (copiado literalmente do texto
abaixo) que fundamenta a resposta. Se o criterio nao se aplica, use trecho_citado
como string vazia e atende=false. Alguns nomes proprios podem aparecer mascarados
como [PESSOA_N] - trate isso normalmente como referencia a uma pessoa fisica.

Criterios:
{lista_criterios}

Trecho:
\"\"\"
{texto_chunk}
\"\"\"

Responda APENAS com um JSON array, sem texto adicional, no formato:
[{{"criterio_chave": "...", "atende": true, "score": 0.0, "justificativa": "...", "trecho_citado": "..."}}]"""

    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": _RESPONSE_SCHEMA,
            "options": {"temperature": 0.1},
        },
        timeout=180,
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "[]")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", raw)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

    if isinstance(parsed, dict):
        parsed = [parsed]
    return parsed if isinstance(parsed, list) else []
