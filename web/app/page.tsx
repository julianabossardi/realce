"use client";

import { ArrowLeft, ArrowRight, ChevronDown, ChevronUp, Folder, Info, Lock, Search, SlidersHorizontal, Unlock } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { DetailPanel } from "@/components/DetailPanel";
import { DossieDrawer } from "@/components/DossieDrawer";
import { FullDocModal } from "@/components/FullDocModal";
import { ResultCard } from "@/components/ResultCard";
import { Sidebar } from "@/components/Sidebar";
import { api } from "@/lib/api";
import type { AcervoDoc, AcervoNaoProcessado, Caso, DossieItem, ModoBusca, Perfil, ResultadoBusca } from "@/lib/types";

type View = "home" | "busca" | "acervo";

const EXEMPLOS = [
  "Servidores nomeados para cargo em comissão",
  "Contratações por dispensa de licitação",
  "Readaptação funcional de servidores",
];

const MODOS: { value: ModoBusca; label: string }[] = [
  { value: "lexico", label: "Léxica" },
  { value: "vetorial", label: "Semântica" },
  { value: "hibrido", label: "Híbrida" },
];

export default function Page() {
  const [view, setView] = useState<View>("home");
  const [casos, setCasos] = useState<Caso[]>([]);
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [perfil, setPerfil] = useState<Perfil>("sem_clearance");

  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [modo, setModo] = useState<ModoBusca>("hibrido");
  const [resultados, setResultados] = useState<ResultadoBusca[]>([]);
  const [showLower, setShowLower] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filtroTipo, setFiltroTipo] = useState("");
  const [filtroMunicipio, setFiltroMunicipio] = useState("");
  const [tiposDisponiveis, setTiposDisponiveis] = useState<string[]>([]);
  const [municipiosDisponiveis, setMunicipiosDisponiveis] = useState<string[]>([]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dossieItems, setDossieItems] = useState<DossieItem[]>([]);
  const [dossieOpen, setDossieOpen] = useState(false);
  const [avaliacoesRelevancia, setAvaliacoesRelevancia] = useState<Record<string, boolean | null>>({});

  const [acervoDocs, setAcervoDocs] = useState<AcervoDoc[]>([]);
  const [acervoNaoProcessados, setAcervoNaoProcessados] = useState<AcervoNaoProcessado[]>([]);
  const [acervoQuery, setAcervoQuery] = useState("");
  const [acervoTipo, setAcervoTipo] = useState("");

  const [fullDoc, setFullDoc] = useState<{ titulo: string; texto: string | null; carregando: boolean; erro?: string } | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const activeCase = casos.find((c) => c.id === activeCaseId) || null;

  useEffect(() => {
    api.filtros().then((r) => {
      setTiposDisponiveis(r.tipos_documento);
      setMunicipiosDisponiveis(r.municipios);
    }).catch(() => {});
    api.listarCasos().then((r) => setCasos(r.casos)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!activeCaseId) return;
    api.listarDossie(activeCaseId).then((r) => setDossieItems(r.itens)).catch(() => {});
    api
      .listarAvaliacoesRelevancia(activeCaseId)
      .then((r) => {
        const map: Record<string, boolean | null> = {};
        r.avaliacoes.forEach((a) => (map[a.chunk_id] = a.relevante));
        setAvaliacoesRelevancia(map);
      })
      .catch(() => {});
  }, [activeCaseId]);

  useEffect(() => {
    if (view === "acervo") {
      api.acervo(acervoQuery || undefined, acervoTipo || undefined).then((r) => {
        setAcervoDocs(r.documentos);
        setAcervoNaoProcessados(r.nao_processados);
      });
    }
  }, [view, acervoQuery, acervoTipo]);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 2200);
  }

  function resetSearchState() {
    setSearchInput("");
    setQuery("");
    setSearching(false);
    setHasSearched(false);
    setSelectedId(null);
    setShowLower(false);
    setFiltersOpen(false);
    setFiltroTipo("");
    setFiltroMunicipio("");
  }

  function goHome() {
    resetSearchState();
    setActiveCaseId(null);
    setDossieOpen(false);
    setView("home");
  }

  function selectCase(id: string) {
    resetSearchState();
    setActiveCaseId(id);
    setView("busca");
  }

  async function addCase() {
    if (casos.length >= 10) return;
    const novo = await api.criarCaso("Novo caso");
    setCasos((prev) => [...prev, novo]);
    resetSearchState();
    setActiveCaseId(novo.id);
    setView("busca");
  }

  async function renameCase(id: string, nome: string) {
    const atualizado = await api.renomearCaso(id, nome);
    setCasos((prev) => prev.map((c) => (c.id === id ? { ...c, nome: atualizado.nome } : c)));
  }

  async function submitSearch(text?: string) {
    const q = (text ?? searchInput).trim();
    if (!q) return;
    setSearchInput(q);
    setSearching(true);
    setHasSearched(false);
    setSelectedId(null);
    setShowLower(false);
    try {
      const resp = await api.buscar({
        consulta: q,
        modo,
        perfil,
        filtro_municipio: filtroMunicipio || null,
        filtro_tipo_documento: filtroTipo || null,
      });
      setResultados(resp.resultados);
      setQuery(q);
    } finally {
      setSearching(false);
      setHasSearched(true);
    }
  }

  async function toggleSave(chunkId: string) {
    if (!activeCaseId) return;
    const isSaved = dossieItems.some((d) => d.chunk_id === chunkId);
    if (isSaved) {
      await api.removerDossie(activeCaseId, chunkId);
      setDossieItems((prev) => prev.filter((d) => d.chunk_id !== chunkId));
      showToast("Removido do dossiê.");
    } else {
      await api.adicionarDossie(activeCaseId, chunkId);
      const r = await api.listarDossie(activeCaseId);
      setDossieItems(r.itens);
      showToast("Salvo no dossiê.");
    }
  }

  async function setRelevancia(chunkId: string, v: boolean | null) {
    if (!activeCaseId) return;
    await api.avaliarRelevancia(activeCaseId, chunkId, v);
    setAvaliacoesRelevancia((prev) => ({ ...prev, [chunkId]: v }));
  }

  async function openFullDoc(r: ResultadoBusca) {
    setFullDoc({ titulo: r.arquivo_local, texto: null, carregando: true });
    try {
      const doc = await api.documentoCompleto(r.documento_id, perfil);
      setFullDoc({ titulo: doc.arquivo_local, texto: doc.texto_completo, carregando: false });
    } catch (err) {
      const sigiloso = err instanceof Error && err.message.startsWith("403");
      setFullDoc({
        titulo: r.arquivo_local,
        texto: null,
        carregando: false,
        erro: sigiloso
          ? "Documento sigiloso. Troque para o perfil \"Autorizado\" (topo da tela) para visualizar."
          : "Não foi possível carregar o documento.",
      });
    }
  }

  const selected = resultados.find((r) => r.id === selectedId) || null;
  const dossieCount = dossieItems.length;
  const isEmpty = hasSearched && !searching && resultados.length === 0;
  const top = resultados.slice(0, 6);
  const lower = resultados.slice(6);

  return (
    <div style={{ height: "100vh", display: "flex", fontFamily: "var(--font-ui)", color: "var(--text-primary)", overflow: "hidden" }}>
      <Sidebar
        casos={casos}
        activeCaseId={activeCaseId}
        onSelectCase={selectCase}
        onAddCase={addCase}
        onRenameCase={renameCase}
        onGoHome={goHome}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", minWidth: 0 }}>
        {view !== "home" && (
          <div style={{ background: "var(--neutral-100)", flexShrink: 0, boxShadow: "var(--shadow-sm)" }}>
            <div style={{ padding: "0 28px", height: 64, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 11, color: "var(--text-tertiary)", fontWeight: 600 }}>Caso ativo</div>
                <div style={{ fontSize: 14, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 440 }}>
                  {activeCase ? activeCase.nome + (activeCase.numero_processo ? " — " + activeCase.numero_processo : "") : "Nenhum caso selecionado"}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 22, flexShrink: 0 }}>
                <button
                  onClick={() => setPerfil((p) => (p === "com_clearance" ? "sem_clearance" : "com_clearance"))}
                  title="Simulação de demonstração - em produção o perfil viria da sessão autenticada."
                  style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 3, background: "none", border: "none", cursor: "pointer", padding: "4px 2px" }}
                >
                  <span style={{ fontSize: 11, color: "var(--text-tertiary)", fontWeight: 600 }}>Perfil de acesso</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 700, color: perfil === "com_clearance" ? "var(--status-success)" : "var(--text-secondary)" }}>
                    {perfil === "com_clearance" ? <Unlock size={14} /> : <Lock size={14} />}
                    {perfil === "com_clearance" ? "Autorizado" : "Sem autorização"}
                  </span>
                </button>
                <button
                  onClick={() => setDossieOpen(true)}
                  disabled={!activeCaseId}
                  style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 3, background: "none", border: "none", cursor: activeCaseId ? "pointer" : "default", padding: "4px 2px" }}
                >
                  <span style={{ fontSize: 11, color: "var(--text-tertiary)", fontWeight: 600 }}>Dossiê</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 700 }}>
                    <Folder size={14} color="var(--orange-600)" />
                    {dossieCount} documento(s)
                  </span>
                </button>
              </div>
            </div>
          </div>
        )}

        <div style={{ flex: 1, display: "flex", overflowX: "auto", overflowY: "hidden", minWidth: 0 }}>
          <div style={{ flex: 1, overflowY: "auto", background: "var(--surface-page)", minWidth: 480 }}>
            {view === "home" && (
              <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", padding: 32 }}>
                <div style={{ maxWidth: 520, textAlign: "center" }}>
                  <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 26, marginBottom: 10 }}>Realce</div>
                  <div style={{ fontSize: 16, color: "var(--text-secondary)", lineHeight: 1.5, marginBottom: 28 }}>
                    Busque documentos no acervo do MPRJ para fortalecer sua análise.
                  </div>
                  <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
                    <button onClick={addCase} style={{ ...primaryBtn, padding: "0 24px", height: 52 }}>Novo caso</button>
                    <button onClick={() => setView("acervo")} style={{ ...secondaryBtn, padding: "0 24px", height: 52 }}>
                      Pesquisar em todo o acervo
                    </button>
                  </div>
                </div>
              </div>
            )}

            {view === "busca" && (
              <div style={{ maxWidth: 700, margin: "0 auto", padding: "32px 32px 64px" }}>
                {!hasSearched && !searching && (
                  <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 24, lineHeight: 1.3, marginBottom: 20 }}>
                    Busque documentos no acervo do MPRJ para fortalecer sua análise.
                  </div>
                )}

                <div style={{ display: "flex", gap: 10 }}>
                  <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 10, padding: "0 16px", height: 56, background: "var(--neutral-0)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", boxShadow: "var(--shadow-sm)", boxSizing: "border-box" }}>
                    <Search size={18} color="var(--text-tertiary)" />
                    <input
                      value={searchInput}
                      onChange={(e) => setSearchInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && submitSearch()}
                      placeholder="Ex.: servidores nomeados para cargo em comissão"
                      style={{ border: "none", outline: "none", flex: 1, fontSize: 16, background: "transparent", color: "var(--text-primary)" }}
                    />
                  </div>
                  <button onClick={() => submitSearch()} style={{ ...primaryBtn, width: 120, height: 56 }}>
                    Buscar
                  </button>
                </div>

                {!hasSearched && !searching && (
                  <>
                    <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 10 }}>
                      Aceita pergunta em linguagem natural ou termo exato — não é preciso escolher um modo.
                    </div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 14 }}>
                      {EXEMPLOS.map((ex) => (
                        <button key={ex} onClick={() => submitSearch(ex)} style={chipBtn}>
                          {ex}
                        </button>
                      ))}
                    </div>
                  </>
                )}

                {!hasSearched && !searching && dossieItems.length > 0 && (
                  <div style={{ marginTop: 28 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)" }}>Documentos salvos neste caso</div>
                      <button onClick={() => setDossieOpen(true)} style={linkBtn}>Ver dossiê completo</button>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {dossieItems.slice(0, 3).map((it) => (
                        <div key={it.id} style={{ border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", padding: "10px 12px", background: "var(--neutral-0)" }}>
                          <div style={{ fontSize: 12, color: "var(--orange-700)" }}>{it.arquivo_local}</div>
                          <div style={{ fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", marginTop: 2 }}>{it.texto.slice(0, 100)}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {(hasSearched || searching) && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
                      <button onClick={() => setFiltersOpen((v) => !v)} style={{ ...chipBtn, background: filtersOpen ? "var(--orange-50)" : "var(--neutral-0)" }}>
                        <SlidersHorizontal size={14} style={{ marginRight: 6 }} />
                        Filtros
                        {filtersOpen ? <ChevronUp size={14} style={{ marginLeft: 6 }} /> : <ChevronDown size={14} style={{ marginLeft: 6 }} />}
                      </button>
                      <div style={{ marginLeft: "auto", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                        <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>Modo de busca</span>
                        <div style={{ display: "flex", background: "var(--neutral-100)", borderRadius: "var(--radius-pill)", padding: 2 }}>
                          {MODOS.map((m) => (
                            <button
                              key={m.value}
                              onClick={() => setModo(m.value)}
                              style={{
                                padding: "5px 10px",
                                borderRadius: "var(--radius-pill)",
                                border: "none",
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: "pointer",
                                background: modo === m.value ? "var(--orange-600)" : "transparent",
                                color: modo === m.value ? "#fff" : "var(--text-secondary)",
                              }}
                            >
                              {m.label}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>

                    {filtersOpen && (
                      <div style={{ display: "flex", gap: 12, padding: 14, background: "var(--neutral-0)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", marginTop: 12 }}>
                        <select value={filtroTipo} onChange={(e) => setFiltroTipo(e.target.value)} style={selectStyle}>
                          <option value="">Todos os tipos</option>
                          {tiposDisponiveis.map((t) => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>
                        <select value={filtroMunicipio} onChange={(e) => setFiltroMunicipio(e.target.value)} style={selectStyle}>
                          <option value="">Todos os municípios</option>
                          {municipiosDisponiveis.map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      </div>
                    )}

                    {searching && (
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14, padding: "64px 0" }}>
                        <div style={{ width: 26, height: 26, border: "3px solid var(--orange-200)", borderTopColor: "var(--orange-600)", borderRadius: "50%", animation: "realce-spin 1s linear infinite" }} />
                        <div style={{ fontSize: 14, color: "var(--text-secondary)" }}>Buscando e avaliando trechos…</div>
                      </div>
                    )}

                    {!searching && resultados.length > 0 && (
                      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 16 }}>
                        {top.map((r) => (
                          <ResultCard
                            key={r.id}
                            r={r}
                            isSaved={dossieItems.some((d) => d.chunk_id === r.id)}
                            onOpenDetail={() => setSelectedId(r.id)}
                            onToggleSave={() => toggleSave(r.id)}
                          />
                        ))}
                        {lower.length > 0 && (
                          <button onClick={() => setShowLower((v) => !v)} style={{ ...linkBtn, alignSelf: "center", padding: 10 }}>
                            {showLower ? "Ocultar candidatos de menor pontuação" : `Ver candidatos de menor pontuação (${lower.length})`}
                          </button>
                        )}
                        {showLower &&
                          lower.map((r) => (
                            <ResultCard
                              key={r.id}
                              r={r}
                              opacity={0.7}
                              isSaved={dossieItems.some((d) => d.chunk_id === r.id)}
                              onOpenDetail={() => setSelectedId(r.id)}
                              onToggleSave={() => toggleSave(r.id)}
                            />
                          ))}
                      </div>
                    )}

                    {isEmpty && (
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 10, padding: "56px 20px", background: "var(--neutral-0)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-lg)", marginTop: 16 }}>
                        <Search size={26} color="var(--text-tertiary)" />
                        <div style={{ fontSize: 15, fontWeight: 600 }}>Nenhum trecho encontrado para &quot;{query}&quot;.</div>
                        <button onClick={() => setView("acervo")} style={{ ...linkBtn, marginTop: 6 }}>Explorar acervo sem priorização</button>
                      </div>
                    )}
                  </div>
                )}

                <div style={{ marginTop: 56, paddingTop: 20, borderTop: "1px solid var(--border-default)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)" }}>Acervo completo</div>
                    <div style={{ fontSize: 13, color: "var(--text-tertiary)", maxWidth: 480 }}>Navegação livre pelo acervo, sem priorização por IA.</div>
                  </div>
                  <button onClick={() => setView("acervo")} style={{ ...linkBtn, color: "var(--text-secondary)" }}>
                    Explorar acervo <ArrowRight size={14} style={{ marginLeft: 4 }} />
                  </button>
                </div>
              </div>
            )}

            {view === "acervo" && (
              <div style={{ maxWidth: 880, margin: "0 auto", padding: "32px 32px 64px" }}>
                <button onClick={() => setView("busca")} style={{ ...linkBtn, color: "var(--text-secondary)", marginBottom: 16 }}>
                  <ArrowLeft size={14} style={{ marginRight: 6 }} /> Voltar à busca priorizada
                </button>
                <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 22, marginBottom: 4 }}>Explorar acervo</div>
                <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 20, maxWidth: 600 }}>
                  Hoje o analista não consegue enxergar o acervo inteiro. Esta lista dá visibilidade completa, sem priorização por IA.
                </div>

                <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
                  <input
                    value={acervoQuery}
                    onChange={(e) => setAcervoQuery(e.target.value)}
                    placeholder="Buscar por palavra-chave ou nome do documento"
                    style={{ flex: 1, border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", padding: "8px 12px", fontSize: 14 }}
                  />
                  <select value={acervoTipo} onChange={(e) => setAcervoTipo(e.target.value)} style={{ ...selectStyle, width: 220 }}>
                    <option value="">Todos os tipos</option>
                    {tiposDisponiveis.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>

                <div style={{ background: "var(--neutral-0)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-lg)", overflow: "hidden" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "2.4fr 1.2fr 1.2fr .9fr .9fr", padding: "10px 16px", borderBottom: "1px solid var(--border-default)", fontSize: 11, fontWeight: 600, color: "var(--text-tertiary)" }}>
                    <div>Documento</div><div>Tipo</div><div>Município</div><div>Data</div><div>Status</div>
                  </div>
                  {acervoDocs.map((d) => (
                    <div
                      key={d.id}
                      onClick={() => {
                        setFullDoc({ titulo: d.arquivo_local, texto: null, carregando: true });
                        openFullDocFromAcervo(d);
                      }}
                      style={{ display: "grid", gridTemplateColumns: "2.4fr 1.2fr 1.2fr .9fr .9fr", padding: "13px 16px", borderBottom: "1px solid var(--border-subtle)", alignItems: "center", cursor: "pointer" }}
                    >
                      <div style={{ fontSize: 14 }}>{d.arquivo_local}</div>
                      <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>{d.tipo_documento || "—"}</div>
                      <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>{d.municipio}</div>
                      <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>{d.data_publicacao}</div>
                      <div>
                        <span style={{ fontSize: 12, fontWeight: 600, padding: "3px 9px", borderRadius: "var(--radius-pill)", background: "var(--status-success-bg)", color: "var(--status-success)" }}>
                          Processado
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                {acervoNaoProcessados.length > 0 && (
                  <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 16, padding: "12px 14px", background: "var(--surface-sunken)", borderRadius: "var(--radius-md)" }}>
                    <Info size={14} color="var(--text-tertiary)" style={{ flexShrink: 0, marginTop: 2 }} />
                    <div style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                      {acervoNaoProcessados.length} documento(s) do acervo não foram processados automaticamente. Motivos:{" "}
                      {acervoNaoProcessados.map((n) => n.tipo_erro).join("; ")}.
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {selected && (
            <DetailPanel
              r={selected}
              isSaved={dossieItems.some((d) => d.chunk_id === selected.id)}
              relevancia={avaliacoesRelevancia[selected.id] ?? null}
              onClose={() => setSelectedId(null)}
              onToggleSave={() => toggleSave(selected.id)}
              onSetRelevancia={(v) => setRelevancia(selected.id, v)}
              onOpenFullDoc={() => openFullDoc(selected)}
            />
          )}
        </div>
      </div>

      {dossieOpen && (
        <DossieDrawer
          itens={dossieItems}
          onClose={() => setDossieOpen(false)}
          onRemove={async (chunkId) => {
            if (!activeCaseId) return;
            await api.removerDossie(activeCaseId, chunkId);
            setDossieItems((prev) => prev.filter((d) => d.chunk_id !== chunkId));
          }}
          onNotaChange={async (chunkId, nota) => {
            if (!activeCaseId) return;
            await api.anotarDossie(activeCaseId, chunkId, nota);
            setDossieItems((prev) => prev.map((d) => (d.chunk_id === chunkId ? { ...d, nota } : d)));
          }}
        />
      )}

      {fullDoc && (
        <FullDocModal
          titulo={fullDoc.titulo}
          texto={fullDoc.texto}
          carregando={fullDoc.carregando}
          erro={fullDoc.erro}
          onClose={() => setFullDoc(null)}
        />
      )}

      {toast && (
        <div style={{ position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)", background: "var(--neutral-900)", color: "#fff", padding: "10px 18px", borderRadius: "var(--radius-sm)", fontSize: 13, boxShadow: "var(--shadow-lg)", zIndex: 200 }}>
          {toast}
        </div>
      )}
    </div>
  );

  async function openFullDocFromAcervo(d: AcervoDoc) {
    try {
      const doc = await api.documentoCompleto(d.id, perfil);
      setFullDoc({ titulo: doc.arquivo_local, texto: doc.texto_completo, carregando: false });
    } catch (err) {
      const sigiloso = err instanceof Error && err.message.startsWith("403");
      setFullDoc({
        titulo: d.arquivo_local,
        texto: null,
        carregando: false,
        erro: sigiloso
          ? "Documento sigiloso. Troque para o perfil \"Autorizado\" (topo da tela) para visualizar."
          : "Não foi possível carregar o documento.",
      });
    }
  }
}

const primaryBtn: React.CSSProperties = {
  background: "var(--orange-600)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--radius-sm)",
  fontSize: 15,
  fontWeight: 600,
  cursor: "pointer",
};

const secondaryBtn: React.CSSProperties = {
  background: "var(--neutral-0)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--radius-sm)",
  fontSize: 15,
  fontWeight: 600,
  cursor: "pointer",
};

const chipBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  background: "var(--neutral-0)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--radius-pill)",
  padding: "7px 14px",
  fontSize: 13,
  color: "var(--text-primary)",
  cursor: "pointer",
};

const linkBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  background: "none",
  border: "none",
  color: "var(--orange-600)",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};

const selectStyle: React.CSSProperties = {
  flex: 1,
  border: "1px solid var(--border-default)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  fontSize: 14,
  background: "var(--neutral-0)",
};
