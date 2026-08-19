// Extrai uma linha "limpa" do chunk para servir de resumo/título do card -
// heurística simples (sem LLM): pula linhas vazias, cabeçalhos de tabela,
// e linhas dominadas por sublinhados/pontuação (comuns em campos de
// assinatura de formulários), preferindo a primeira frase com conteúdo
// real. Não é uma síntese semântica (isso exigiria um LLM por resultado,
// caro demais para rodar em toda busca) - é só uma seleção melhor do que
// cortar os primeiros N caracteres crus.
export function resumoDe(texto: string, maxLen = 160): string {
  const linhas = texto
    .split(/\n+/)
    .map((l) => l.trim())
    .filter(Boolean);

  const pareceRuido = (l: string) => {
    const semEspaco = l.replace(/\s/g, "");
    if (semEspaco.length < 20) return true;
    const naoAlfa = semEspaco.replace(/[a-zA-ZÀ-ÿ0-9]/g, "").length;
    if (naoAlfa / semEspaco.length > 0.4) return true; // muita pontuação/underscore
    if (/^\[TABELA\]/.test(l)) return true;
    return false;
  };

  const boaLinha = linhas.find((l) => !pareceRuido(l)) || linhas[0] || texto;
  const limpo = boaLinha.replace(/\s+/g, " ").trim();
  return limpo.length > maxLen ? limpo.slice(0, maxLen).trim() + "…" : limpo;
}
