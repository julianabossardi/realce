// Formatacao de exibicao do documento completo (nao mexe no texto
// indexado/chunkado - so no que a interface mostra). O texto que chega da
// API ja tem paragrafo real separado por linha em branco dupla (Revisao
// 4 - ver ingestion/normalize.py), mas cabecalhos de ato ("DECRETO N°
// 911/2026") e artigos ("Art. 1º") costumam vir grudados no mesmo
// paragrafo do corpo do texto no PDF de origem (quebra de linha simples,
// nao dupla) - por isso a normalizacao de indexacao os funde numa unica
// frase continua, correto para chunking/embedding mas ruim para leitura
// humana. Aqui insere quebra antes desses marcadores estruturais so para
// exibicao, e classifica cada bloco resultante como titulo (cabecalho de
// ato, curto e predominantemente maiusculo) ou paragrafo comum.

export type BlocoDocumento = { tipo: "titulo" | "paragrafo"; texto: string };

// "LEI" fica de fora do gatilho de proposito: e citada inline o tempo
// todo em texto de justificativa ("a Lei Municipal nº 162 de...", "nos
// termos da Lei nº X") - quebrar nesses pontos fragmentaria frase no meio,
// nao so paragrafo. DECRETO/PORTARIA/EDITAL/etc tambem podem aparecer em
// citacao inline ("pela Portaria DG n.º 527/2025"), por isso o lookbehind
// negativo: so quebra quando o marcador NAO vem logo depois de um
// conector tipico de citacao ("a", "pela", "conforme", ...).
const NAO_PRECEDIDO_DE_CONECTOR = String.raw`(?<!\b(?:a|o|d[ao]|pel[ao]|n[ao]|conforme)\s)`;
const CABECALHO_ATO_RE = new RegExp(
  NAO_PRECEDIDO_DE_CONECTOR +
    String.raw`\b(?:DECRETO|PORTARIA|EDITAL|RESOLU[ÇC][ÃA]O|ANEXO|OF[ÍI]CIO|AVISO|EXTRATO\s+DE\s+(?:CONTRATO|TERMO)|HOMOLOGA[ÇC][ÃA]O)\s+N[ºO°]?\s*[\d\.]+`,
  "gi"
);
const ARTIGO_RE = /\bArt\.\s*\d+/g;

function inserirQuebrasEstruturais(texto: string): string {
  return texto.replace(CABECALHO_ATO_RE, (m) => `\n\n${m}`).replace(ARTIGO_RE, (m) => `\n\n${m}`);
}

const PREFIXO_TITULO_RE = /^(DECRETO|PORTARIA|LEI(?:\s+MUNICIPAL)?|EDITAL|RESOLU[ÇC][ÃA]O|ANEXO|OF[ÍI]CIO|AVISO|EXTRATO)\b/i;

function pareceTitulo(bloco: string): boolean {
  const linha = bloco.trim();
  if (!linha || linha.length > 140) return false;
  if (PREFIXO_TITULO_RE.test(linha)) return true;
  const letras = linha.replace(/[^a-zA-ZÀ-ÿ]/g, "");
  if (letras.length < 6) return false;
  const maiusculas = linha.replace(/[^A-ZÀ-Ü]/g, "").length;
  return maiusculas / letras.length > 0.85;
}

export function formatarDocumento(texto: string): BlocoDocumento[] {
  return inserirQuebrasEstruturais(texto)
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter(Boolean)
    .map((b): BlocoDocumento => ({ tipo: pareceTitulo(b) ? "titulo" : "paragrafo", texto: b }));
}
