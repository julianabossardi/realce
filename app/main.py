"""
Backend FastAPI (Secao 5/6 do brief, revisao 2) - busca (lexico/vetorial/
hibrido), avaliacao por criterio, feedback, e as visoes agregadas que
sustentam a demo (quarentena por tipo de erro, aprovacao por criterio).
Roda 100% local; a unica dependencia externa e o Postgres local
(docker-compose) - LLM e embeddings sao chamados localmente.

Este arquivo so monta a aplicacao (CORS + rotas). Os endpoints em si
vivem em `app/routes/` (um modulo por area: busca, casos/dossie, acervo,
feedback, stats de quarentena/padronizados) - antes de dividir, este
arquivo tinha ~520 linhas misturando as 5 areas, dificultando navegar. A
divisao nao muda nenhum comportamento (mesma URL, mesmo request/response
em cada endpoint) - so onde o codigo mora.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import acervo, busca, casos, feedback, stats

app = FastAPI(title="Realce - PoC (100% local, busca hibrida)")

# CORS liberado (GET/POST de qualquer origem) - necessario porque o
# frontend passa a rodar no Vercel (origem diferente), chamando este
# backend local via tunel. Aceitavel para esta demo (dado publico,
# service local so acessivel via URL efemera do tunel); nao seria a
# configuracao de producao (ver README).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(busca.router)
app.include_router(casos.router)
app.include_router(acervo.router)
app.include_router(feedback.router)
app.include_router(stats.router)


@app.get("/health")
def health():
    return {"status": "ok"}
