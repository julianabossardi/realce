-- Categorias de sigilo iniciais (Secao 4.3). Lista intencionalmente
-- incompleta - em producao, categorias adicionais (ex: dados de vitima,
-- informacao sob segredo de justica) nascem de levantamento juridico, nao
-- de decisao tecnica. O que a PoC demonstra e a capacidade de acomodar
-- categorias novas como dado, sem alterar codigo.
insert into categoria_sigilo (nome, tipo_deteccao, padrao, nivel_restricao) values
    ('CPF', 'regex', '\d{3}\.\d{3}\.\d{3}-\d{2}', 'restrito'),
    ('RG', 'regex', '\d{1,2}\.\d{3}\.\d{3}-?[\dXx]?', 'restrito'),
    ('TELEFONE', 'regex', '\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}', 'restrito'),
    ('PESSOA', 'ner', null, 'restrito')
on conflict (nome) do nothing;
