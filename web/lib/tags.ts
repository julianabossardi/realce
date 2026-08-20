// Tags que complementam o titulo do card/documento - no lugar de um
// pedaco cru do trecho (formatacao pobre fora de contexto, so parte do
// material, sem muita utilidade sozinho). Reune o que emergiu do proprio
// processamento: criterios de priorizacao atendidos (Secao 4.6) e o
// metodo de extracao quando foi OCR (sinal de confianca mais baixo no
// texto - Secao 4.2).
import { rotuloCriterio } from "./criterios";

export type Tag = { texto: string; tom: "criterio" | "info" };

export function tagsDeAvaliacoes(avaliacoes: { atende: boolean; criterio_chave: string }[]): Tag[] {
  return avaliacoes
    .filter((a) => a.atende)
    .map((a) => ({ texto: rotuloCriterio(a.criterio_chave), tom: "criterio" as const }));
}

const ROTULO_METODO_EXTRACAO: Record<string, string> = {
  ocr: "Extraído via OCR",
  ocr_baixa_confianca: "OCR de baixa confiança",
};

export function tagDeMetodoExtracao(metodo: string): Tag | null {
  const texto = ROTULO_METODO_EXTRACAO[metodo];
  return texto ? { texto, tom: "info" } : null;
}

export function tagsDoResultado(r: {
  avaliacoes: { atende: boolean; criterio_chave: string }[];
  metodo_extracao: string;
}): Tag[] {
  const tags = tagsDeAvaliacoes(r.avaliacoes);
  const metodo = tagDeMetodoExtracao(r.metodo_extracao);
  return metodo ? [...tags, metodo] : tags;
}
