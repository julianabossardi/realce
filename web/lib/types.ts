export type Caso = {
  id: string;
  nome: string;
  numero_processo: string | null;
  criado_em: string;
};

export type Avaliacao = {
  criterio_id: number;
  criterio_chave: string;
  criterio_versao: number;
  atende: boolean;
  score: number;
  justificativa: string;
  trecho_citado: string;
  citacao_verificada: boolean;
};

export type ResultadoBusca = {
  id: string; // chunk_id
  documento_id: string;
  pagina: number | null;
  texto: string;
  metodo_extracao: string;
  municipio: string;
  data_publicacao: string;
  url_origem: string;
  arquivo_local: string;
  tipo_documento: string | null;
  nivel_restricao: "publico" | "restrito" | "sigiloso";
  titulo: string | null;
  sintese: string | null;
  avaliacoes: Avaliacao[];
  score_criterios: number;
  similaridade?: number;
  rrf_score?: number;
  encontrado_em?: string[];
};

export type DossieItem = {
  id: string;
  chunk_id: string;
  nota: string;
  tema: string | null;
  criado_em: string;
  texto: string;
  pagina: number | null;
  arquivo_local: string;
  municipio: string;
  data_publicacao: string;
  url_origem: string;
};

export type AcervoDoc = {
  id: string;
  arquivo_local: string;
  municipio: string;
  tipo_documento: string | null;
  data_publicacao: string;
  url_origem: string;
  nivel_restricao: string;
  titulo: string | null;
  sintese: string | null;
  status: "Processado";
};

export type AcervoNaoProcessado = {
  arquivo_local: string;
  municipio: string;
  tipo_erro: string;
  mensagem_erro: string | null;
};

export type Perfil = "sem_clearance" | "com_clearance";
export type ModoBusca = "lexico" | "vetorial" | "hibrido";
