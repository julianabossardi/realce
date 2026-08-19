-- Tabelas novas exigidas pelo frontend (handoff de design "Realce - Busca
-- priorizada de documentos"): casos abertos pelo analista, dossie por
-- caso, e avaliacao de relevancia (👍/👎) por trecho dentro de um caso.
create table if not exists casos (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    numero_processo text,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

create table if not exists dossie_items (
    id uuid primary key default gen_random_uuid(),
    caso_id uuid not null references casos (id) on delete cascade,
    chunk_id uuid not null references chunks (id) on delete cascade,
    nota text default '',
    tema text,
    criado_em timestamptz not null default now(),
    unique (caso_id, chunk_id)
);
create index if not exists idx_dossie_caso on dossie_items (caso_id);

create table if not exists avaliacoes_relevancia (
    id uuid primary key default gen_random_uuid(),
    caso_id uuid not null references casos (id) on delete cascade,
    chunk_id uuid not null references chunks (id) on delete cascade,
    relevante boolean,
    criado_em timestamptz not null default now(),
    unique (caso_id, chunk_id)
);
