-- Realce - PoC (revisao 2): schema completo.
-- Roda automaticamente na primeira inicializacao do container (ver
-- docker-compose.yml -> /docker-entrypoint-initdb.d).
--
-- Mudancas desta revisao em relacao ao schema anterior (ver README, Secao
-- "O que mudou nesta revisao"): criterio vira tabela dinamica (era um
-- bundle JSON versionado em criterios_versoes); categoria_sigilo torna a
-- deteccao de dado sensivel configuravel em vez de hardcoded;
-- entidades_mascaradas passa a guardar pseudonimo estavel por entidade
-- (era um contador global [PESSOA_N]); quarentena e auditoria sao tabelas
-- novas; documentos e chunks ganham campos de linhagem obrigatorios.

create extension if not exists vector;
create extension if not exists pgcrypto; -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- documentos
-- ---------------------------------------------------------------------
create table if not exists documentos (
    id uuid primary key default gen_random_uuid(),
    municipio text not null,
    territory_id text not null,
    data_publicacao date,
    edicao text,
    url_origem text not null,
    arquivo_local text not null,
    hash_sha256 text not null,          -- linhagem: hash do PDF original
    num_paginas int,
    tipo_documento text,                -- metadados leves (Portaria, Decreto, Edital, ...) - pre-filtro de busca
    metodo_extracao_predominante text,  -- 'pdfplumber' | 'ocr' | 'ocr_baixa_confianca' | 'misto'
    qualidade_extracao jsonb,           -- {"paginas": [{"pagina":1,"metodo":"pdfplumber"}, ...]}
    nivel_restricao text not null default 'publico'
        check (nivel_restricao in ('publico', 'restrito', 'sigiloso')),
    criado_em timestamptz not null default now()
);

create index if not exists idx_documentos_municipio on documentos (municipio);
create index if not exists idx_documentos_tipo on documentos (tipo_documento);
create index if not exists idx_documentos_restricao on documentos (nivel_restricao);
create unique index if not exists idx_documentos_hash on documentos (hash_sha256);

-- ---------------------------------------------------------------------
-- chunks: fatias de texto ANONIMIZADO (pseudonimos consistentes por
-- entidade - Secao 4.3), com embedding local + tsvector, e campos de
-- linhagem obrigatorios (Secao 4.8) - todo resultado exibido precisa ser
-- reconstituivel ate a pagina/offset/metodo/versao de modelo exatos.
-- ---------------------------------------------------------------------
create table if not exists chunks (
    id uuid primary key default gen_random_uuid(),
    documento_id uuid not null references documentos (id) on delete cascade,
    indice int not null,
    pagina int,
    offset_inicio int not null,         -- posicao no texto anonimizado do documento
    offset_fim int not null,
    texto text not null,                -- texto ANONIMIZADO (versao principal armazenada)
    metodo_extracao text not null,          -- 'pdfplumber' | 'ocr' | 'ocr_baixa_confianca'
    metodo_extracao_versao text not null,   -- ex: 'pdfplumber-0.11.4'
    embedding_modelo text not null,         -- ex: 'BAAI/bge-m3'
    embedding vector(1024),
    tsv tsvector generated always as (to_tsvector('portuguese', texto)) stored,
    criado_em timestamptz not null default now()
);

create index if not exists idx_chunks_documento on chunks (documento_id);
create index if not exists idx_chunks_tsv on chunks using gin (tsv);
create index if not exists idx_chunks_embedding on chunks
    using hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------
-- categoria_sigilo: torna a deteccao de dado sensivel dado, nao codigo
-- (Secao 4.3). A lista populada em 0002 e intencionalmente incompleta -
-- a capacidade de acomodar novas categorias (inclusive as que dependem de
-- levantamento juridico) e o que a PoC demonstra, nao a lista em si.
-- ---------------------------------------------------------------------
create table if not exists categoria_sigilo (
    id serial primary key,
    nome text not null unique,          -- 'CPF', 'RG', 'TELEFONE', 'PESSOA', ...
    tipo_deteccao text not null check (tipo_deteccao in ('regex', 'ner', 'documento_inteiro')),
    padrao text,                        -- regex quando tipo_deteccao = 'regex'
    nivel_restricao text not null default 'restrito',
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- entidades_mascaradas: mapeamento pseudonimo -> valor original (Secao
-- 4.3) E, ao mesmo tempo, o "indice de entidades" que permite resolver
-- uma busca por nome especifico para os pseudonimos correspondentes sem
-- expor o dado (indice em valor_original abaixo) - decisao de design:
-- nao criamos uma segunda tabela redundante para o indice, ja que esta
-- tabela ja tem exatamente as colunas necessarias (valor_original,
-- documento_id, pseudonimo); so adicionamos o indice certo (ver README).
-- Tabela sensivel - acesso condicionado ao perfil (app/access.py).
-- ---------------------------------------------------------------------
create table if not exists entidades_mascaradas (
    id uuid primary key default gen_random_uuid(),
    documento_id uuid not null references documentos (id) on delete cascade,
    categoria_id int not null references categoria_sigilo (id),
    pseudonimo text not null,           -- ex: '[PESSOA_A]' - estavel por entidade dentro do documento
    valor_original text not null,
    offset_inicio int,
    criado_em timestamptz not null default now()
);

create index if not exists idx_entidades_documento on entidades_mascaradas (documento_id);
create index if not exists idx_entidades_valor_original on entidades_mascaradas (valor_original);

-- ---------------------------------------------------------------------
-- criterio: criterios de relevancia como DADO (Secao 4.6), nao mais um
-- bundle JSON versionado. Cada linha e um criterio; uma mudanca de texto
-- cria uma nova versao (mesma `chave`, `versao` incrementada, a antiga
-- marcada ativo=false) - o cache de avaliacoes (chunk, criterio, versao)
-- se invalida naturalmente.
-- ---------------------------------------------------------------------
create table if not exists criterio (
    id serial primary key,
    chave text not null,
    descricao text not null,
    versao int not null default 1,
    ativo boolean not null default true,
    criado_em timestamptz not null default now(),
    unique (chave, versao)
);

create index if not exists idx_criterio_ativo on criterio (ativo);

-- ---------------------------------------------------------------------
-- avaliacoes: avaliacao ATOMICA (um criterio por chamada ao LLM local -
-- Secao 4.6), com saida estruturada e validacao programatica da citacao.
-- ---------------------------------------------------------------------
create table if not exists avaliacoes (
    id uuid primary key default gen_random_uuid(),
    chunk_id uuid not null references chunks (id) on delete cascade,
    criterio_id int not null references criterio (id),
    criterio_versao int not null,
    atende boolean not null,
    score numeric(4, 3) not null,
    justificativa text not null,
    trecho_citado text not null,
    citacao_verificada boolean not null,   -- trecho_citado existe literalmente no chunk?
    modelo text not null,                  -- ex: 'qwen2.5:7b-instruct' (via Ollama)
    criado_em timestamptz not null default now(),
    unique (chunk_id, criterio_id, criterio_versao)
);

create index if not exists idx_avaliacoes_chunk on avaliacoes (chunk_id);

-- ---------------------------------------------------------------------
-- feedback: sim/nao humano por resultado, agora vinculado a um criterio
-- especifico (avaliacao atomica) em vez de a uma versao de bundle.
-- ---------------------------------------------------------------------
create table if not exists feedback (
    id uuid primary key default gen_random_uuid(),
    chunk_id uuid not null references chunks (id) on delete cascade,
    consulta text not null,
    criterio_id int not null references criterio (id),
    criterio_versao int not null,
    util boolean not null,
    comentario text,
    criado_em timestamptz not null default now()
);

create index if not exists idx_feedback_chunk on feedback (chunk_id);
create index if not exists idx_feedback_criterio on feedback (criterio_id);

-- ---------------------------------------------------------------------
-- quarentena: documentos que falham na cascata de extracao nao sao
-- descartados (Secao 4.2). O tipo de erro CLASSIFICADO e o que importa -
-- permite corrigir em grupo e produz a metrica de "% do acervo
-- inacessivel, por causa", exposta na demo.
-- ---------------------------------------------------------------------
create table if not exists quarentena (
    id uuid primary key default gen_random_uuid(),
    arquivo_local text not null,
    municipio text,
    territory_id text,
    tipo_erro text not null check (
        tipo_erro in ('texto_vazio', 'texto_insuficiente', 'falha_ocr', 'encoding_invalido', 'pdf_corrompido', 'outro')
    ),
    mensagem_erro text,
    metodo_que_falhou text,
    criado_em timestamptz not null default now()
);

create index if not exists idx_quarentena_tipo on quarentena (tipo_erro);

-- ---------------------------------------------------------------------
-- auditoria: toda revelacao de valor original (perfil com clearance)
-- grava registro (Secao 4.7) - quem viu o que, quando.
-- ---------------------------------------------------------------------
create table if not exists auditoria (
    id uuid primary key default gen_random_uuid(),
    perfil text not null,
    documento_id uuid references documentos (id) on delete set null,
    pseudonimo text not null,
    criado_em timestamptz not null default now()
);

create index if not exists idx_auditoria_documento on auditoria (documento_id);
