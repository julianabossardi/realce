-- O padrao original de RG ('\d{1,2}\.\d{3}\.\d{3}-?[\dXx]?', sem word
-- boundaries e com sufixo opcional) capturava tambem codigos de dotacao
-- orcamentaria municipal (mesmo formato digito.digito.digito), gerando
-- falsos positivos massivos: em uma auditoria retroativa, 3337 de 3426
-- entidades marcadas como RG eram na verdade codigos orcamentarios, o
-- que classificou 69 de 70 documentos como 'sigiloso' indevidamente e
-- os escondeu por completo de buscas com perfil sem clearance.
update categoria_sigilo
set padrao = '\b\d{1,2}\.\d{3}\.\d{3}-[\dXx]\b'
where nome = 'RG';
