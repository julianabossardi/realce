-- Funcao de busca vetorial pura, usada pelo modo "vetorial" e como uma das
-- duas pernas da busca hibrida (Secao 4.5). A fusao dos rankings (RRF)
-- acontece em Python (app/search.py), nao aqui - mais simples de depurar
-- e de medir cada perna isoladamente no experimento.
create or replace function match_chunks (
    query_embedding vector(1024),
    match_count int default 30,
    filtro_municipio text default null,
    filtro_tipo_documento text default null
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
    order by c.embedding <=> query_embedding
    limit match_count;
$$;
