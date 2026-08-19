-- Adendo tecnico pos-deploy: camada de normalizacao/enriquecimento entre
-- extracao e chunking (ver README). Colunas novas:
--
--   documentos.titulo / documentos.sintese: gerados por UMA chamada ao LLM
--   local por DOCUMENTO (nao por chunk - ver app/llm.py e ingestion/index.py),
--   usados como cabecalho do card e camada de detalhe na interface, no
--   lugar do nome de arquivo com hash ou de um corte cru do primeiro chunk.
--
--   chunks.hash_normalizado: sha256 do texto do chunk apos normalizar
--   pseudonimos para uma forma generica (ver ingestion/dedupe.py) - usado
--   para agrupar chunks estruturalmente identicos entre documentos
--   diferentes (formularios/anexos padrao).
--
--   chunks.eh_padronizado: marcado quando o chunk se repete em muitos
--   documentos distintos (hash_normalizado) OU tem alta densidade de
--   campos de preenchimento vazios - sai do ranking de busca por padrao,
--   mas continua acessivel (marcado, nao excluido).

alter table documentos add column if not exists titulo text;
alter table documentos add column if not exists sintese text;

alter table chunks add column if not exists hash_normalizado text;
alter table chunks add column if not exists eh_padronizado boolean not null default false;

create index if not exists idx_chunks_hash_normalizado on chunks (hash_normalizado);
create index if not exists idx_chunks_padronizado on chunks (eh_padronizado);

-- match_chunks ganha um parametro novo no final, com default - chamadas
-- existentes (posicionais, 4 argumentos) continuam funcionando sem
-- mudanca; passar true inclui chunks padronizados no resultado (usado so
-- pela exploracao livre do acervo, nao pela busca priorizada).
create or replace function match_chunks (
    query_embedding vector(1024),
    match_count int default 30,
    filtro_municipio text default null,
    filtro_tipo_documento text default null,
    incluir_padronizados boolean default false
)
returns table (
    id uuid,
    documento_id uuid,
    pagina int,
    texto text,
    metodo_extracao text,
    metodo_extracao_versao text,
    embedding_modelo text,
    offset_inicio int,
    offset_fim int,
    similaridade float
)
language sql stable
as $$
    select
        c.id,
        c.documento_id,
        c.pagina,
        c.texto,
        c.metodo_extracao,
        c.metodo_extracao_versao,
        c.embedding_modelo,
        c.offset_inicio,
        c.offset_fim,
        1 - (c.embedding <=> query_embedding) as similaridade
    from chunks c
    join documentos d on d.id = c.documento_id
    where c.embedding is not null
        and (filtro_municipio is null or d.municipio = filtro_municipio)
        and (filtro_tipo_documento is null or d.tipo_documento = filtro_tipo_documento)
        and (incluir_padronizados or c.eh_padronizado = false)
    order by c.embedding <=> query_embedding
    limit match_count;
$$;
