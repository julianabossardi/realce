"""
Interface minima de demonstracao (Streamlit) - Secao 6/9 do brief,
revisao 2. Nao e a experiencia de produto final (Claude Design cuida
disso, a parte); serve para demonstrar ao vivo a busca nos tres modos, a
avaliacao por criterio, o controle de acesso simplificado, e os paineis
de quarentena/feedback que sustentam a narrativa da PoC.

Uso:
    streamlit run app/demo_ui.py
"""
import requests
import streamlit as st

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Realce - PoC", layout="centered")
st.title("Realce — PoC de busca no acervo")
st.caption(
    "Busca hibrida (lexica + vetorial, fundidas por Reciprocal Rank Fusion) + "
    "avaliacao por criterio via LLM local. Roda 100% local."
)

try:
    filtros_resp = requests.get(f"{API_URL}/filtros", timeout=10).json()
except Exception:
    filtros_resp = {"municipios": [], "tipos_documento": []}

with st.expander("Filtros de metadados (pre-filtro da busca)"):
    col_f1, col_f2 = st.columns(2)
    filtro_municipio = col_f1.selectbox("Municipio", ["(todos)"] + filtros_resp["municipios"])
    filtro_tipo = col_f2.selectbox("Tipo de documento", ["(todos)"] + filtros_resp["tipos_documento"])

col1, col2 = st.columns([3, 1])
with col1:
    consulta = st.text_input("Consulta", placeholder="ex: servidor cedido para outro orgao")
with col2:
    perfil = st.selectbox("Perfil", ["sem_clearance", "com_clearance"])

modo = st.radio("Modo de busca", ["hibrido", "lexico", "vetorial"], horizontal=True)
limite = st.slider("Numero de resultados", 3, 15, 8)

if st.button("Buscar", disabled=not consulta):
    with st.spinner("Buscando..."):
        resp = requests.post(
            f"{API_URL}/search",
            json={
                "consulta": consulta,
                "modo": modo,
                "limite": limite,
                "perfil": perfil,
                "filtro_municipio": None if filtro_municipio == "(todos)" else filtro_municipio,
                "filtro_tipo_documento": None if filtro_tipo == "(todos)" else filtro_tipo,
            },
            timeout=300,
        )
    if resp.status_code != 200:
        st.error(resp.text)
    else:
        data = resp.json()
        st.session_state["resultados"] = data["resultados"]
        st.session_state["consulta_atual"] = consulta

resultados = st.session_state.get("resultados", [])
st.subheader(f"{len(resultados)} resultado(s)")

for r in resultados:
    with st.container(border=True):
        meta = (
            f"{r['municipio']} — {r['data_publicacao']} — {r.get('tipo_documento') or 'tipo desconhecido'} — "
            f"pagina {r['pagina']} — metodo: {r['metodo_extracao']} — restricao: {r['nivel_restricao']}"
        )
        if "similaridade" in r:
            meta += f" — similaridade: {r['similaridade']:.3f}"
        if "rrf_score" in r:
            meta += f" — RRF: {r['rrf_score']:.4f} (encontrado em: {', '.join(r['encontrado_em'])})"
        st.caption(meta)
        st.write(r["texto"][:600] + ("…" if len(r["texto"]) > 600 else ""))
        st.markdown(f"[fonte original]({r['url_origem']})")

        if r.get("avaliacoes"):
            with st.expander("Avaliacao por criterio"):
                for a in r["avaliacoes"]:
                    status = "✅ atende" if a["atende"] else "❌ nao atende"
                    citacao_flag = "" if a["citacao_verificada"] else " ⚠️ citacao nao verificada"
                    st.markdown(f"**{a['criterio_chave']}** — {status} (score {a['score']:.2f}){citacao_flag}")
                    st.write(a["justificativa"])
                    if a["trecho_citado"]:
                        st.markdown(f"> {a['trecho_citado']}")

                    fb1, fb2 = st.columns(2)
                    consulta_atual = st.session_state.get("consulta_atual", consulta)
                    if fb1.button("👍 relevante", key=f"up_{r['id']}_{a['criterio_id']}"):
                        requests.post(
                            f"{API_URL}/feedback",
                            json={
                                "chunk_id": r["id"],
                                "consulta": consulta_atual,
                                "criterio_id": a["criterio_id"],
                                "criterio_versao": a["criterio_versao"],
                                "util": True,
                            },
                        )
                        st.toast("Feedback registrado")
                    if fb2.button("👎 nao relevante", key=f"down_{r['id']}_{a['criterio_id']}"):
                        requests.post(
                            f"{API_URL}/feedback",
                            json={
                                "chunk_id": r["id"],
                                "consulta": consulta_atual,
                                "criterio_id": a["criterio_id"],
                                "criterio_versao": a["criterio_versao"],
                                "util": False,
                            },
                        )
                        st.toast("Feedback registrado")

st.divider()
st.subheader("Painéis operacionais")

col_q, col_f = st.columns(2)

with col_q:
    st.markdown("**Quarentena (% do acervo inacessível, por causa)**")
    try:
        q = requests.get(f"{API_URL}/quarentena/stats", timeout=10).json()
        st.metric("% em quarentena", f"{q['percentual_quarentena']:.1f}%")
        if q["por_tipo_erro"]:
            st.table(q["por_tipo_erro"])
        else:
            st.caption("Nenhum documento em quarentena nesta amostra.")
    except Exception as exc:
        st.caption(f"Indisponível: {exc}")

with col_f:
    st.markdown("**Taxa de aprovação por critério (feedback)**")
    try:
        f = requests.get(f"{API_URL}/feedback/stats", timeout=10).json()
        if f["stats"]:
            st.table(f["stats"])
        else:
            st.caption("Nenhum feedback registrado ainda.")
    except Exception as exc:
        st.caption(f"Indisponível: {exc}")
