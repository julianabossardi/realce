-- Realce - PoC 100% local: schema inicial (Postgres + pgvector)
-- Roda automaticamente na primeira inicializacao do container (ver
-- docker-compose.yml -> /docker-entrypoint-initdb.d).

create extension if not exists vector;
create extension if not exists pgcrypto; -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- documentos: um registro por PDF do acervo (diario oficial baixado)
-- ---------------------------------------------------------------------
create table if not exists documentos (
    id uuid primary key default gen_random_uuid(),
    municipio text not null,
    territory_id text not null,
    data_publicacao date,
    edicao text,
    url_origem text not null,
    arquivo_local text not null,
    num_paginas int,
    metodo_extracao_predominante text, -- 'pdfplumber' | 'ocr' | 'ocr_baixa_confianca' | 'misto'
    qualidade_extracao jsonb, -- {"paginas": [{"pagina":1,"metodo":"pdfplumber"}, ...]}
    criado_em timestamptz not null default now()
);

create index if not exists idx_documentos_municipio on documentos (municipio);

-- ---------------------------------------------------------------------
-- chunks: fatias de texto ANONIMIZADO de cada documento (Secao 4.1.1 -
-- a anonimizacao acontece antes do chunking/embedding, na ingestao, para
-- todo documento). Guarda embedding local (pgvector) e coluna full-text
-- (Postgres nativo) para o baseline sem IA (Caminho A).
-- ---------------------------------------------------------------------
create table if not exists chunks (
    id uuid primary key default gen_random_uuid(),
    documento_id uuid not null references documentos (id) on delete cascade,
    indice int not null, -- posicao do chunk dentro do documento
    pagina int,
    texto text not null, -- texto ANONIMIZADO (versao principal armazenada)
    metodo_extracao text not null, -- 'pdfplumber' | 'ocr' | 'ocr_baixa_confianca'
    embedding vector(1024), -- modelo local (bge-m3 / multilingual-e5-large) -> 1024 dim
    tsv tsvector generated always as (to_tsvector('portuguese', texto)) stored,
    criado_em timestamptz not null default now()
);

create index if not exists idx_chunks_documento on chunks (documento_id);
create index if not exists idx_chunks_tsv on chunks using gin (tsv);
create index if not exists idx_chunks_embedding on chunks
    using hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------
-- entidades_mascaradas: mapeamento mascarado -> valor original, gerado na
-- anonimizacao (Secao 4.1.1). Tabela sensivel - na PoC o acesso e
-- controlado na camada de aplicacao (app/access.py, perfil "com
-- clearance"); em producao seria protegida por Postgres RLS/roles
-- amarrados a identidade institucional real (ver README, Secao 4.7/9).
-- ---------------------------------------------------------------------
create table if not exists entidades_mascaradas (
    id uuid primary key default gen_random_uuid(),
    documento_id uuid not null references documentos (id) on delete cascade,
    tipo_entidade text not null, -- 'PESSOA' | 'CPF' | 'RG' | 'TELEFONE'
    placeholder text not null,   -- ex: '[PESSOA_1]'
    valor_original text not null,
    criado_em timestamptz not null default now()
);

create index if not exists idx_entidades_documento on entidades_mascaradas (documento_id);

-- ---------------------------------------------------------------------
-- criterios_versoes: cada linha e uma "versao" do conjunto de criterios
-- de relevancia usado na avaliacao por LLM local. Nunca se edita uma
-- versao existente - uma mudanca de criterio cria uma nova versao.
-- ---------------------------------------------------------------------
create table if not exists criterios_versoes (
    id serial primary key,
    descricao text not null,
    criterios jsonb not null, -- [{"chave":"valores_financeiros","descricao":"..."}, ...]
    criado_em timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- avaliacoes: cache da avaliacao por criterios feita pelo LLM local sobre
-- um chunk candidato. Chave de cache = (chunk, criterio, versao).
-- ---------------------------------------------------------------------
create table if not exists avaliacoes (
    id uuid primary key default gen_random_uuid(),
    chunk_id uuid not null references chunks (id) on delete cascade,
    criterios_versao_id int not null references criterios_versoes (id),
    criterio_chave text not null,
    atende boolean not null,
    score numeric(4, 3) not null,
    justificativa text not null,
    trecho_citado text not null,
    modelo text not null, -- ex: 'qwen2.5:7b-instruct' (via Ollama)
    criado_em timestamptz not null default now(),
    unique (chunk_id, criterios_versao_id, criterio_chave)
);

create index if not exists idx_avaliacoes_chunk on avaliacoes (chunk_id);

-- ---------------------------------------------------------------------
-- feedback: sim/nao humano sobre um resultado de busca, vinculado a
-- versao de criterios vigente no momento. Nao dispara reprocessamento
-- automatico nesta PoC - so registra o dado.
-- ---------------------------------------------------------------------
create table if not exists feedback (
    id uuid primary key default gen_random_uuid(),
    chunk_id uuid not null references chunks (id) on delete cascade,
    consulta text not null,
    criterios_versao_id int not null references criterios_versoes (id),
    util boolean not null,
    comentario text,
    criado_em timestamptz not null default now()
);

create index if not exists idx_feedback_chunk on feedback (chunk_id);
