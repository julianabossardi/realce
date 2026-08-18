"""
Controle de acesso a dado sensivel - versao simplificada para a demo
(Secao 4.7 do brief).

Nao ha login/senha real nesta PoC: um seletor de "perfil" (com/sem
clearance) e passado explicitamente pelo cliente (Streamlit ou chamada
direta a API). Se o perfil tiver clearance, o texto anonimizado pode ser
"desmascarado" consultando `entidades_mascaradas`.

O que isso NAO e (documentado tambem no README): autenticacao real,
integracao com identidade institucional (SSO do MPRJ), papeis definidos
por politica de acesso formal, ou log de auditoria de quem acessou qual
dado desmascarado. Tudo isso fica como ponto em aberto para producao.
"""
from __future__ import annotations

PERFIS = ("sem_clearance", "com_clearance")


def tem_clearance(perfil: str) -> bool:
    return perfil == "com_clearance"


def desmascarar_texto(texto: str, entidades: list[dict]) -> str:
    """Substitui cada placeholder pelo valor original. So deve ser chamado
    quando `tem_clearance(perfil)` for True."""
    resultado = texto
    for e in entidades:
        resultado = resultado.replace(e["placeholder"], e["valor_original"])
    return resultado
