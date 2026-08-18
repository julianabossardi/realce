-- Funcao de busca vetorial (Caminho B), chamada pelo backend FastAPI.
create or replace function match_chunks (
    query_embedding vector(1024),
    match_count int default 8
)
returns table (
    id uuid,
    documento_id uuid,
    pagina int,
    texto text,
    metodo_extracao text,
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
        1 - (c.embedding <=> query_embedding) as similaridade
    from chunks c
    where c.embedding is not null
    order by c.embedding <=> query_embedding
    limit match_count;
$$;
