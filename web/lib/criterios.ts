// Rótulo legível para os critérios de relevância (tabela `criterio` -
// ver db/migrations/0003_seed_criterios.sql). Critérios são dado, não
// código (Seção 4.6) - um critério novo cadastrado no banco não quebra a
// interface, só cai no fallback (snake_case -> Title Case) em vez de um
// rótulo com curadoria manual.
const ROTULOS: Record<string, string> = {
  valores_financeiros: "Valores financeiros",
  contratacao_licitacao: "Contratação / licitação",
  nomeacao_exoneracao: "Nomeação / exoneração",
  penalidade_beneficio: "Penalidade / benefício",
};

export function rotuloCriterio(chave: string): string {
  if (ROTULOS[chave]) return ROTULOS[chave];
  return chave
    .split("_")
    .map((p) => (p ? p[0].toUpperCase() + p.slice(1) : p))
    .join(" ");
}
