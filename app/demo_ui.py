"""
Interface minima de demonstracao (Streamlit) - Secao 5/10 do brief.

Nao e a experiencia de produto final (isso fica com o Claude Design,
a parte); serve so para demonstrar a busca/avaliacao funcionando ao vivo.

Uso:
    streamlit run app/demo_ui.py
"""
import requests
import streamlit as st

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Realce - PoC", layout="centered")
st.title("Realce — PoC de busca no acervo")
st.caption(
    "Compara busca por palavra-chave (Caminho A) com busca semantica + "
    "avaliacao por criterios via LLM local (Caminho B). Roda 100% local."
)

col1, col2 = st.columns([3, 1])
with col1:
    consulta = st.text_input("Consulta", placeholder="ex: servidor cedido para outro orgao")
with col2:
    perfil = st.selectbox("Perfil", ["sem_clearance", "com_clearance"])

caminho = st.radio("Caminho de busca", ["semantico", "keyword"], horizontal=True)
limite = st.slider("Numero de resultados", 3, 15, 8)

if st.button("Buscar", disabled=not consulta):
    with st.spinner("Buscando..."):
        resp = requests.post(
            f"{API_URL}/search",
            json={"consulta": consulta, "caminho": caminho, "limite": limite, "perfil": perfil},
            timeout=180,
        )
    if resp.status_code != 200:
        st.error(resp.text)
    else:
        data = resp.json()
        st.session_state["resultados"] = data["resultados"]
        st.session_state["consulta_atual"] = consulta

resultados = st.session_state.get("resultados", [])
for r in resultados:
    with st.container(border=True):
        meta = f"{r['municipio']} — {r['data_publicacao']} — pagina {r['pagina']} — metodo: {r['metodo_extracao']}"
        if "similaridade" in r:
            meta += f" — similaridade: {r['similaridade']:.3f}"
        st.caption(meta)
        st.write(r["texto"][:600] + ("…" if len(r["texto"]) > 600 else ""))
        st.markdown(f"[fonte original]({r['url_origem']})")

        if r.get("avaliacoes"):
            with st.expander("Avaliacao por criterios"):
                for a in r["avaliacoes"]:
                    status = "✅ atende" if a["atende"] else "❌ nao atende"
                    st.markdown(f"**{a['criterio_chave']}** — {status} (score {a['score']:.2f})")
                    st.write(a["justificativa"])
                    if a["trecho_citado"]:
                        st.markdown(f"> {a['trecho_citado']}")

        if r.get("criterios_versao_id"):
            fb1, fb2 = st.columns(2)
            consulta_atual = st.session_state.get("consulta_atual", consulta)
            if fb1.button("👍 relevante", key=f"up_{r['id']}"):
                requests.post(
                    f"{API_URL}/feedback",
                    json={
                        "chunk_id": r["id"],
                        "consulta": consulta_atual,
                        "criterios_versao_id": r["criterios_versao_id"],
                        "util": True,
                    },
                )
                st.toast("Feedback registrado")
            if fb2.button("👎 nao relevante", key=f"down_{r['id']}"):
                requests.post(
                    f"{API_URL}/feedback",
                    json={
                        "chunk_id": r["id"],
                        "consulta": consulta_atual,
                        "criterios_versao_id": r["criterios_versao_id"],
                        "util": False,
                    },
                )
                st.toast("Feedback registrado")
