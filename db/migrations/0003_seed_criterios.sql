-- Criterios de relevancia iniciais (Secao 4.6) - cada linha e um
-- criterio independente, avaliado em chamada separada ao LLM (avaliacao
-- atomica). Para a PoC, tres a cinco criterios plausiveis para o
-- dataset (diarios oficiais municipais). Em producao, esse conjunto
-- nasce de oficina com os usuarios do MPRJ, nao de decisao tecnica.
insert into criterio (chave, descricao, versao) values
    ('valores_financeiros', 'Menciona valores financeiros (R$) acima de R$ 100.000,00, isoladamente ou em soma de itens do mesmo ato.', 1),
    ('contratacao_licitacao', 'Menciona processo de contratacao publica, licitacao, dispensa ou inexigibilidade de licitacao, ou aditivo contratual.', 1),
    ('nomeacao_exoneracao', 'Menciona nomeacao ou exoneracao de pessoa fisica para cargo publico (mesmo que o nome esteja mascarado como [PESSOA_X]).', 1),
    ('penalidade_beneficio', 'Menciona penalidade administrativa ou beneficio individual concedido a uma pessoa fisica especifica.', 1)
on conflict (chave, versao) do nothing;
