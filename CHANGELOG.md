# Changelog

Histórico de decisões, bugs encontrados/corrigidos e evolução do Realce entre versões. O
[README.md](README.md) descreve o estado atual do projeto; este arquivo existe para quem quiser
entender o "porquê" por trás de uma decisão ou uma correção específica, sem misturar isso com a
documentação de produto.

## v0.4 — normalização/enriquecimento na ingestão, deploy híbrido estabilizado

### Pipeline de ingestão

Diagnóstico com sintomas concretos observados na interface: chunks cortando palavras e tokens de
anonimização ao meio (`ebimento` em vez de `recebimento`, `PESSOA_FN]` sem colchete de abertura);
ordem de leitura fragmentada em páginas diagramadas em colunas; formulários e anexos padronizados
dominando os resultados de busca; ausência de um campo de título (a interface usava a primeira
linha crua do chunk); nome de arquivo com hash como identificação do documento. Causa raiz comum
aos três primeiros: faltava uma camada de normalização/enriquecimento entre a extração de texto e o
chunking — o pipeline ia direto de um para o outro.

Seis correções aplicadas, na ordem do diagnóstico (impacto/esforço): normalização do texto extraído
(`ingestion/normalize.py`); chunking por fronteira semântica (`ingestion/chunk.py`, substitui corte
por contagem bruta de caracteres); nome legível do documento; filtragem de conteúdo padronizado
(`ingestion/dedupe.py`, hash de chunk com pseudônimos generalizados, `[PESSOA_A]`/`[PESSOA_B]` →
`[X]`, marca chunks repetidos em 5+ documentos); título e síntese gerados por LLM, uma chamada por
documento (`app/llm.py:gerar_titulo_e_sintese`); detecção de colunas por coordenadas na extração
(`ingestion/extract.py::_detectar_gap_coluna`). Ver [README.md](README.md#pipeline-de-ingestão)
para como cada etapa funciona hoje.

As correções que mudam o texto indexado (normalização, chunking, dedup, colunas) exigiram
reprocessar o acervo inteiro do zero.

### Amostra reduzida de 70 para 30 documentos

Rodando localmente em CPU (sem GPU dedicada), o custo de reprocessamento por documento —
normalização, chunking, embeddings, e a chamada de LLM para título/síntese — ficou em torno de
100-170s/documento, e o processo foi ainda interrompido uma vez por um problema de permissão de
sistema operacional (macOS revogou o acesso à pasta do projeto a meio do processamento). Diante do
risco real de não concluir um reprocessamento de 70 documentos dentro do prazo, a decisão foi
reduzir para 30 documentos bem processados e verificáveis — 15 de Niterói e 15 de Angra dos Reis
(Varre-Sai saiu desta amostra, não por falha, só por escopo) — garantindo que os 14 documentos
referenciados no gabarito do experimento (`experiments/compare_modes.py`) permanecessem na amostra
final.

Números de recall/precisão de antes desta mudança (amostra de 70 documentos, extração sem as
correções acima) não são comparáveis aos números atuais do README:

| Modo | Recall médio | Precisão média | Latência média de busca (s) |
|---|---|---|---|
| léxico | 0.38 | 0.28 | 0.96 |
| vetorial | 0.22 | 0.10 | 3.39 |
| híbrido | 0.43 | 0.14 | 2.72 |

Citação não verificada: 14,3% (2 de 14). Quarentena: 0% (0 de 70).

O que mudou visivelmente com a extração corrigida: recall médio subiu em todas as linhas (ex:
recall geral do híbrido foi de 0.43 para 0.61) e a latência de busca caiu bastante (retrieval geral
do híbrido: 2.72s → 0.30s) — não por o hardware ter ficado mais rápido, mas porque a amostra ficou
menor (30 vs. 70) e os chunks ficaram mais enxutos e menos redundantes, então cada busca examina
menos candidatos ruidosos. A taxa de citação não verificada também caiu (14,3% → 11,1%). Isso não
isola sozinho o efeito da correção de extração — a amostra também mudou de tamanho e composição ao
mesmo tempo, então a comparação é só indicativa, não uma medição controlada.

### Ajustes pós-demo: prioridade real, custo de avaliação, organização do backend

Testes reais na interface (não só via API) expuseram mais problemas:

- **A busca não priorizava nada de fato**: o resultado ficava na ordem crua de recuperação
  (RRF/léxico/vetorial), não na ordem da nota de avaliação por critério, apesar da interface se
  chamar "busca priorizada". Corrigido em `app/routes/busca.py::_anexar_documentos_e_avaliar`, que
  agora reordena por `score_criterios` antes de devolver.
- **Custo de avaliação inviabilizava o uso interativo**: com `avaliar=true` (padrão) e o limite de
  10 candidatos da interface, uma busca chegava a 40 chamadas sequenciais ao LLM local (minutos de
  espera). Reduzido para 6 candidatos (`web/lib/api.ts`).
- **Perfil padrão "sem clearance" escondia metade da amostra reduzida** (15 dos 30 documentos
  nascem sigilosos pela regra binária de `nivel_restricao`) — o padrão da interface passou para
  "com clearance"; o seletor de perfil continua existindo para simular a troca.
- **Chips de busca de exemplo ficaram obsoletos** com a redução da amostra (buscavam temas
  concentrados em documentos que saíram de 70 para 30) — substituídos por consultas validadas
  contra a amostra atual.
- **Critérios apareciam com a chave crua do banco** (`valores_financeiros` em vez de "Valores
  financeiros") — `web/lib/criterios.ts` adiciona um rótulo legível, com fallback automático
  (snake_case → Title Case) para um critério novo cadastrado via banco.
- **Trecho cru no card de resultado/dossiê** era pouco útil (formatação pobre, fora de contexto,
  só parte do material) — substituído por tags de contexto (critérios de priorização atendidos +
  método de extração quando OCR): `web/lib/tags.ts`, `web/components/TagList.tsx`.
- **Documento completo sem separação visual de título/parágrafo** — heurística de exibição
  (`web/lib/formatarDocumento.ts`) separa cabeçalho de ato/artigo do corpo do texto, sem alterar o
  texto indexado/chunkado.
- **`app/main.py` reorganizado**: tinha ~520 linhas misturando busca, casos/dossiê, acervo,
  feedback e stats de quarentena/padronizados num arquivo só. Dividido em `app/routes/` (um módulo
  por área) sem mudar nenhum comportamento — verificado comparando a lista de rotas antes/depois e
  re-testando cada endpoint.
- **Seletor de modo de busca removido da interface** — híbrido vira o único modo exposto (léxico e
  vetorial isolados continuam na API e no experimento, para comparação).

### Setup e reprodutibilidade

- **Dump do banco** (`db/seed/realce_seed.sql.gz`) — permite restaurar os 30 documentos já
  processados em segundos, sem rodar a ingestão completa (1-2h). Ver
  [README.md](README.md#dump-do-banco-dbseed).
- **Teste de clone limpo, verificado rodando de verdade**: clonado o repositório num diretório novo
  fora do projeto e seguido o README do zero (venv, spaCy, Docker, restauração do dump, backend,
  frontend) até a interface abrir com os dados restaurados. Achados corrigidos: `web/.env.local`
  não tinha instrução de como criar (`web/.env.local.example` adicionado);
  `web/tsconfig.tsbuildinfo` estava versionado por engano (artefato de build, removido e
  gitignorado); dependências de sistema `tesseract`/`poppler` (usadas por `pytesseract`/
  `pdf2image`) não estavam documentadas — `pip install` não as instala.
- **Achado sobre Colima (macOS)**: testado primeiro num diretório fora de `$HOME` e as migrations
  silenciosamente não rodaram — Postgres subiu `healthy`, mas sem nenhuma tabela. Causa: Colima só
  compartilha `$HOME` com a VM do Docker por padrão; o bind mount das migrations chega vazio se o
  projeto estiver fora disso. Documentado como nota de troubleshooting no README.

## v0.3 — frontend Next.js e deploy híbrido (Vercel + backend local)

Um handoff de design pediu uma interface rica — sidebar de casos, busca priorizada em 3 painéis,
dossiê, acervo, documento completo — que não cabia no Streamlit da PoC original.

- **Frontend novo em `web/` (Next.js + React)**, substituindo o Streamlit como interface principal.
  Implementa os 7 estados do handoff (Home, Busca, Acervo, Painel de detalhe, Dossiê, Documento
  completo, Sidebar de casos), usando os design tokens fornecidos. `app/demo_ui.py` (Streamlit)
  continua no repositório como interface alternativa mais simples de rodar sem Node.
- **Duas tabelas novas** (`db/migrations/0005_casos_dossie.sql`): `casos` (casos abertos pelo
  analista) e `dossie_items` (trechos salvos por caso, com anotação). Uma terceira,
  `avaliacoes_relevancia`, registra o 👍/👎 humano por trecho no contexto de um caso — distinto da
  avaliação por critério (LLM).
- **Deploy híbrido**: só o frontend vai para o Vercel; o backend continua local, exposto via
  `cloudflared tunnel` — ver [README.md](README.md#arquitetura) para o porquê e as limitações dessa
  montagem.
- **Reaproveitado do handoff literalmente**: paleta de cores, tipografia, espaçamento, raios de
  borda, sombras, copiados para `web/app/globals.css` como variáveis CSS sem alteração de valores.
- **Adaptado do handoff**: o protótipo revela cada dado mascarado individualmente, por clique; esta
  PoC desmascara o chunk inteiro de uma vez, condicionado ao perfil.
- **Não implementado** (o handoff já marca como fora do fluxo principal): exportar dossiê, anexar
  documentos de apoio.

### Bugs encontrados após o deploy

- **Busca não retornava nada, mesmo para termos básicos.** Causa raiz: o padrão regex de RG usado
  para classificar `categoria_sigilo` (`\d{1,2}\.\d{3}\.\d{3}-?[\dXx]?`, sem word boundaries e com
  sufixo opcional) também casava com códigos de dotação orçamentária municipal, mesmo formato
  dígito.dígito.dígito. Auditoria retroativa encontrou 3337 falsos positivos em 3426 entidades
  marcadas como RG, classificando 69 dos 70 documentos como `sigiloso` — e o perfil padrão
  (`sem_clearance`) esconde documentos sigilosos por completo. Corrigido com padrão mais estrito
  (`\b\d{1,2}\.\d{3}\.\d{3}-[\dXx]\b`, exige dígito verificador e word boundaries — ver
  `db/migrations/0006_fix_rg_regex.sql`), com um script único que restaurou o texto mascarado
  incorretamente e recalculou `nivel_restricao` para todos os documentos.
- **Clicar em um card no "Explorar acervo" não carregava os detalhes.** Mesma causa raiz: a maioria
  dos documentos estava indevidamente `sigiloso`, então `/documentos/{id}/completo` retornava 403 e
  a UI não distinguia esse caso de uma falha genérica. Corrigido em duas partes: o bug de dados
  acima, e `openFullDoc`/`openFullDocFromAcervo` passando a detectar 403 e mostrar uma mensagem
  explícita em vez de erro genérico.
- **Título do card de resultado era um corte cru dos primeiros caracteres do trecho**, às vezes
  começando no meio de uma linha de assinatura ou tabela. Adicionada heurística sem LLM
  (`web/lib/resumo.ts::resumoDe`) — substituída na v0.4 pelo título gerado por LLM na ingestão,
  mantida como fallback.

### Processo de deploy (Vercel)

A CLI do Vercel já estava autenticada numa conta de equipe sem escopo pessoal e com *Deployment
Protection* (SSO) ativa por padrão — o link ficava redirecionando para login em vez de abrir a
página. Resolvido com login numa conta pessoal separada e `vercel project protection disable`.

O túnel `cloudflared` caiu uma vez em poucos minutos de uso (`context canceled` nos logs), exigindo
reinício manual. Separadamente, confirmado que domínios `trycloudflare.com` podem ser bloqueados
por bloqueadores/extensões de segurança do navegador (`ERR_BLOCKED_BY_CLIENT`) mesmo com o túnel
saudável — descoberto comparando `curl` direto (funcionava) com a chamada feita pelo navegador
(bloqueada).

## v0.2 — busca híbrida, pseudônimos consistentes, quarentena, linhagem

Segunda revisão do brief técnico, implementada sobre o código já existente.

| Mudança | O que foi preservado |
|---|---|
| Busca híbrida (léxica + vetorial, fundidas por RRF) substitui a busca puramente semântica | O baseline léxico e a busca vetorial continuam existindo como modos isolados, agora selecionáveis |
| Pseudônimos consistentes por entidade (`[PESSOA_A]`, `[PESSOA_B]`...) substituem o contador global (`[PESSOA_1]`, `[PESSOA_2]`...) | A heurística de MAIÚSCULAS e o guard contra autorreferência de placeholder |
| Campos de linhagem (hash do PDF, offset de caracteres, versão do método/modelo) tornam-se obrigatórios no schema | A estrutura geral de `documentos`/`chunks` |
| Critérios de relevância viram registros em `criterio` (tabela), montados dinamicamente na instrução do modelo | Os 4 critérios originais, agora como linhas versionadas em vez de um bundle JSON |
| Categorias de sigilo (`categoria_sigilo`) tornam a detecção configurável, documentos ganham `nivel_restricao` | As categorias já existentes (CPF, RG, TELEFONE, PESSOA) viram a seed inicial da tabela |
| Fila de quarentena (`quarentena`) com tipo de erro classificado | A cascata de extração (pdfplumber → OCR) continua igual; passa a classificar falhas em vez de deixá-las implícitas |
| Metadados leves (`tipo_documento`) servem de pré-filtro da busca | — (novo) |
| Saída estruturada passa a ser por critério individual (avaliação atômica) | O uso de `"format": <json-schema>` do Ollama |
| Hipótese reformulada (léxico + vetorial + híbrido, não semântico vs. palavra-chave) | O script de comparação manteve as 5 perguntas semânticas e acrescentou 2 de termo exato |

Nada da arquitetura 100% local mudou nesta revisão.

### Bugs encontrados durante o desenvolvimento

- **Mascaramento duplicado** em `app/anonymize.py`: o NER do spaCy classificava o próprio
  placeholder já inserido como um novo nome de pessoa — corrigido com um guard de regex.
- **Segundo bug da mesma família**, ao introduzir pseudônimos letra-baseados: o spaCy passou a
  classificar como pessoa a palavra real *logo antes* de um placeholder já inserido (ex: "CPF" em
  "CPF `[CPF_A]`") — corrigido invertendo a ordem de processamento (nomes de pessoa primeiro, sobre
  o texto ainda intocado; regex estruturados depois).
- **Import incorreto de `PDFSyntaxError`** ao implementar a fila de quarentena — a exceção real vem
  de `pdfminer.pdfparser`, não de `pdf2image.exceptions` (mesmo nome de classe, módulos
  diferentes) — descoberto testando com um PDF corrompido sintético.
- **Experimento estourou timeout de 600s** na primeira tentativa — `/search` chamava avaliação por
  critério (LLM) sobre todo candidato em toda busca, então medir 3 modos × 7 perguntas significava
  até `limite × critérios ativos` avaliações por chamada. Corrigido separando retrieval
  (`avaliar=false`) de avaliação por critério (medida à parte, sobre um número menor de
  candidatos).
- **Métrica de citação não verificada marcava ~100% dos casos** por causa de quebras de linha no
  meio de frases no texto extraído (artefato do `pdfplumber`/OCR) que o modelo naturalmente
  normaliza ao citar — corrigido normalizando espaços em branco dos dois lados antes de comparar
  (`app/evaluate.py::_citacao_verificada`); a taxa real caiu para 14,3%.
- **Conflito de porta do Postgres**: uma instalação nativa de Postgres já ocupava a porta 5432 em
  algumas máquinas de desenvolvimento, causando falhas de autenticação confusas (senha "errada"
  sempre rejeitada, porque o Postgres real por trás da porta nem conhecia o usuário do projeto) —
  `docker-compose.yml` publica na porta 5433 em vez de 5432 desde então.

### Decisões de design desta versão

- Separação `ingestion/source_querido_diario.py` como módulo de fronteira isolado — decisão de
  arquitetura para não acoplar o pipeline à fonte de dados da PoC.
- Conjunto de perguntas de teste e gabarito manual em `experiments/compare_modes.py`, construído
  inspecionando o texto real extraído da amostra.
- Decisão de **não** criar uma tabela separada para o "índice de entidades" — `entidades_mascaradas`
  já tinha as colunas necessárias (`valor_original`, `documento_id`, `pseudonimo`); só faltava o
  índice certo.

## v0.1 — PoC inicial

Primeira versão: busca semântica (embeddings + pgvector) seguida de avaliação por critério via LLM
local, sobre a amostra do Querido Diário. Base sobre a qual as versões seguintes evoluíram.
