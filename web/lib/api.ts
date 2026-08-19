// Cliente do backend FastAPI local (ver README - roda 100% local, exposto
// via tunel efemero para o frontend hospedado no Vercel poder chama-lo).
import type { AcervoDoc, AcervoNaoProcessado, Caso, DossieItem, ModoBusca, Perfil, ResultadoBusca } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${path}: ${body}`);
  }
  return resp.json();
}

export const api = {
  buscar: (params: {
    consulta: string;
    modo: ModoBusca;
    limite?: number;
    perfil: Perfil;
    filtro_municipio?: string | null;
    filtro_tipo_documento?: string | null;
  }) =>
    req<{ resultados: ResultadoBusca[] }>("/search", {
      method: "POST",
      body: JSON.stringify({ limite: 10, ...params }),
    }),

  filtros: () => req<{ municipios: string[]; tipos_documento: string[] }>("/filtros"),

  listarCasos: () => req<{ casos: Caso[] }>("/casos"),
  criarCaso: (nome: string) => req<Caso>("/casos", { method: "POST", body: JSON.stringify({ nome }) }),
  renomearCaso: (id: string, nome: string) =>
    req<Caso>(`/casos/${id}`, { method: "PATCH", body: JSON.stringify({ nome }) }),

  listarDossie: (casoId: string) => req<{ itens: DossieItem[] }>(`/casos/${casoId}/dossie`),
  adicionarDossie: (casoId: string, chunkId: string, tema?: string | null) =>
    req(`/casos/${casoId}/dossie`, { method: "POST", body: JSON.stringify({ chunk_id: chunkId, tema }) }),
  removerDossie: (casoId: string, chunkId: string) =>
    req(`/casos/${casoId}/dossie/${chunkId}`, { method: "DELETE" }),
  anotarDossie: (casoId: string, chunkId: string, nota: string) =>
    req(`/casos/${casoId}/dossie/${chunkId}`, { method: "PATCH", body: JSON.stringify({ nota }) }),

  listarAvaliacoesRelevancia: (casoId: string) =>
    req<{ avaliacoes: { chunk_id: string; relevante: boolean | null }[] }>(`/casos/${casoId}/avaliacoes`),
  avaliarRelevancia: (casoId: string, chunkId: string, relevante: boolean | null) =>
    req(`/casos/${casoId}/avaliacao-relevancia`, {
      method: "POST",
      body: JSON.stringify({ chunk_id: chunkId, relevante }),
    }),

  acervo: (q?: string, tipo?: string) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (tipo) params.set("tipo", tipo);
    return req<{ documentos: AcervoDoc[]; nao_processados: AcervoNaoProcessado[] }>(`/acervo?${params}`);
  },

  documentoCompleto: (id: string, perfil: Perfil) =>
    req<{ arquivo_local: string; texto_completo: string; url_origem: string }>(
      `/documentos/${id}/completo?perfil=${perfil}`
    ),

  feedback: (payload: {
    chunk_id: string;
    consulta: string;
    criterio_id: number;
    criterio_versao: number;
    util: boolean;
  }) => req("/feedback", { method: "POST", body: JSON.stringify(payload) }),

  quarentenaStats: () =>
    req<{ percentual_quarentena: number; total_quarentena: number; total_documentos_ok: number }>(
      "/quarentena/stats"
    ),
};
