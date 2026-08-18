-- Versao inicial (v1) do conjunto de criterios de relevancia usado na
-- avaliacao por LLM local (Secao 4.4 do brief). Trocar de criterio =
-- inserir nova linha aqui, nunca editar a v1.
insert into criterios_versoes (descricao, criterios)
values (
    'v1 - criterios financeiros, licitacao e pessoa fisica',
    '[
        {
            "chave": "valores_financeiros",
            "descricao": "Menciona valores financeiros (R$) acima de R$ 100.000,00, isoladamente ou em soma de itens do mesmo ato."
        },
        {
            "chave": "contratacao_licitacao",
            "descricao": "Menciona processo de contratacao publica, licitacao, dispensa ou inexigibilidade de licitacao, ou aditivo contratual."
        },
        {
            "chave": "pessoa_fisica_nomeada",
            "descricao": "Cita pessoa fisica associada a nomeacao, exoneracao, penalidade, ou beneficio individual (mesmo que o nome esteja mascarado como [PESSOA_N])."
        }
    ]'::jsonb
)
on conflict do nothing;
