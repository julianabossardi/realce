"""
Controle de acesso a dado sensivel - versao simplificada para a demo
(Secao 4.7 do brief, revisao 2).

Nao ha login/senha real nesta PoC: um seletor de "perfil" (com/sem
clearance) e passado explicitamente pelo cliente (Streamlit ou chamada
direta a API). O perfil governa duas coisas:
    1. revelar ou nao o valor original de um pseudonimo
    2. exibir ou ocultar (nao so mascarar) documentos marcados como
       sigilosos (nivel_restricao='sigiloso') - documento sigiloso SOME
       do resultado para quem nao tem clearance, em vez de aparecer com o
       texto mascarado

Toda revelacao de valor original grava registro de auditoria (Secao 4.8) -
quem, qual documento, qual entidade, quando.

O que isso NAO e (documentado tambem no README): autenticacao real,
integracao com identidade institucional (SSO do MPRJ), papeis definidos
por politica de acesso formal.
"""
from __future__ import annotations

PERFIS = ("sem_clearance", "com_clearance")


def tem_clearance(perfil: str) -> bool:
    return perfil == "com_clearance"


def desmascarar_texto(texto: str, entidades: list[dict]) -> str:
    """Substitui cada pseudonimo pelo valor original. So deve ser chamado
    quando `tem_clearance(perfil)` for True."""
    resultado = texto
    for e in entidades:
        resultado = resultado.replace(e["pseudonimo"], e["valor_original"])
    return resultado


def registrar_auditoria(conn, perfil: str, documento_id: str, pseudonimos: list[str]) -> None:
    if not pseudonimos:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into auditoria (perfil, documento_id, pseudonimo) values (%s, %s, %s)",
            [(perfil, documento_id, p) for p in pseudonimos],
        )


def documento_visivel(nivel_restricao: str, perfil: str) -> bool:
    """Documento sigiloso some do resultado para quem nao tem clearance -
    nao aparece nem mascarado (Secao 4.7). Publico/restrito sempre
    aparecem (restrito so mascara os trechos sensiveis, ja tratado por
    `desmascarar_texto`)."""
    if nivel_restricao == "sigiloso":
        return tem_clearance(perfil)
    return True
