# Realce — PoC: identificação de documentos de atenção prioritária

PoC para o desafio técnico Inova/MPRJ. Testa uma hipótese específica, não constrói um produto
completo: **a combinação de busca léxica e busca semântica, seguida de avaliação por critério via
LLM local, recupera documentos relevantes com recall e precisão superiores aos de cada método de
busca isolado.**

**Backend 100% local**: banco (Postgres + pgvector via Docker), modelo de embeddings
(sentence-transformers) e LLM de avaliação (Ollama) rodam todos no computador de quem executa —
nenhuma chamada de API externa acontece durante o uso normal do sistema. O único tráfego de rede é
o download inicial dos pesos dos modelos (uma vez) e a ingestão inicial dos PDFs do Querido Diário.
Um **frontend novo (Next.js, `web/`)**, implementando o handoff de design recebido, roda publicado
no Vercel — ver [Revisão 3](#revisão-3--frontend-novo-e-deploy-hibrido-vercel--backend-local) para
como essa peça se conecta ao backend local sem abrir mão da arquitetura 100% local dele.

## Sumário

- [Revisão 4 — normalização e enriquecimento na ingestão](#revisão-4--normalização-e-enriquecimento-na-ingestão-adendo-técnico)
- [Revisão 3 — frontend novo e deploy híbrido](#revisão-3--frontend-novo-e-deploy-hibrido-vercel--backend-local)
- [O que mudou na revisão 2](#o-que-mudou-nesta-revisão)
- [Setup e reprodução](#setup-e-reprodução)
- [O que foi feito do zero / com IA / reaproveitado](#o-que-foi-feito-do-zero--com-ia--reaproveitado)
- [Decisões técnicas](#decisões-técnicas)
- [Resultado da avaliação da hipótese](#resultado-da-avaliação-da-hipótese)
- [Limitações conhecidas](#limitações-conhecidas)
- [Riscos e evolução para produção](#riscos-e-evolução-para-produção)
- [Fora de escopo](#fora-de-escopo-desta-poc)

---

## Revisão 3 — frontend novo e deploy híbrido (Vercel + backend local)

Um handoff de design (`design_handoff_realce_busca_documentos/`) pediu uma interface rica —
sidebar de casos, busca priorizada em 3 painéis, dossiê, acervo, documento completo — que não cabe
no Streamlit da PoC original. Isso trouxe duas mudanças:

**1. Frontend novo em `web/` (Next.js + React), substituindo o Streamlit como interface principal.**
Implementa os 7 estados descritos no handoff (Home, Busca, Acervo, Painel de detalhe, Dossiê,
Documento completo, Sidebar de casos), usando os design tokens fornecidos
(`_ds_tokens/colors.css`, `typography.css`, `spacing.css`, `effects.css`). `app/demo_ui.py`
(Streamlit) continua no repositório como interface alternativa mais simples de rodar sem Node.

**2. Duas tabelas novas no Postgres local** (`db/migrations/0005_casos_dossie.sql`), exigidas pelo
handoff e sem equivalente na revisão anterior: `casos` (casos abertos pelo analista) e
`dossie_items` (trechos salvos por caso, com anotação). Uma terceira, `avaliacoes_relevancia`,
registra o 👍/👎 humano por trecho **no contexto de um caso** — distinto da avaliação por critério
(LLM), que já existia. `app/main.py` ganhou os endpoints CRUD correspondentes
(`/casos`, `/casos/{id}/dossie`, `/casos/{id}/avaliacao-relevancia`, `/acervo`,
`/documentos/{id}/completo`) e CORS liberado (`allow_origins=["*"]`), necessário porque o frontend
passa a rodar numa origem diferente do backend.

### O conflito real: Vercel é serverless, Ollama não é

Funções serverless do Vercel não seguram um processo `ollama serve` rodando, e recarregar o modelo
de embeddings local (~2GB) a cada cold start não é viável. **Vercel e "LLM/embeddings 100% local"
são incompatíveis na mesma peça de infraestrutura.** Havia três saídas: (a) reescrever
embeddings/avaliação para APIs cloud (Voyage + Claude) — reverteria a decisão de arquitetura já
tomada nas revisões anteriores; (b) desistir do Vercel e ficar só local; (c) publicar **só o
frontend** no Vercel, apontando para o backend local exposto por um túnel público. A pessoa
responsável pelo projeto escolheu (c) — mantém Ollama/embeddings genuinamente locais, ao custo de o
link público só funcionar enquanto o Mac que roda o backend estiver ligado.

**Link atual**: https://web-julianabossardi-8591s-projects.vercel.app — só responde de verdade
(busca funcionando) enquanto o backend local + túnel estiverem no ar na máquina de quem
desenvolveu. Fora isso, a interface carrega mas as chamadas à API falham.

### Como está montado

```
[Vercel: web/ (Next.js)]  --HTTPS-->  [cloudflared tunnel]  -->  [localhost:8000 (FastAPI)]
                                                                        |
                                                          Postgres local + Ollama local
```

- `web/` publicado no Vercel (conta pessoal, não a mesma usada em outros projetos — ver nota
  abaixo), com a variável `NEXT_PUBLIC_API_URL` apontando para a URL do túnel.
- Backend local exposto via `cloudflared tunnel --url http://localhost:8000` (quick tunnel, sem
  conta Cloudflare — `brew install cloudflared`).
- `app/main.py` ganhou CORS liberado para aceitar chamadas vindas do domínio do Vercel.

**Isso é uma montagem de demonstração, não uma arquitetura de produção** — documentado
explicitamente como tal:

- **A URL do túnel é efêmera.** Cada vez que `cloudflared` reinicia (Mac dorme, rede cai, o
  processo é encerrado), a URL muda e a variável de ambiente no Vercel precisa ser atualizada e o
  frontend, re-implantado. Isso aconteceu durante o próprio desenvolvimento desta revisão — o
  túnel caiu uma vez em poucos minutos de uso (`context canceled` nos logs do cloudflared), exigindo
  reinício manual.
- **O link só serve enquanto o Mac estiver ligado, com Docker/Ollama/`uvicorn`/`cloudflared`
  rodando.** Não é um serviço 24/7.
- **Domínios `trycloudflare.com` são bloqueados por alguns bloqueadores/extensões de segurança do
  navegador** (heurística comum contra abuso de túneis efêmeros) — confirmado durante o próprio
  desenvolvimento, quando o navegador usado para testar a interface bloqueou a chamada de rede
  para o túnel (`ERR_BLOCKED_BY_CLIENT`) enquanto `curl` direto funcionava normalmente. Um visitante
  real com um bloqueador agressivo pode ver a busca falhar silenciosamente.
- **CORS liberado para qualquer origem** (`allow_origins=["*"]`) — aceitável para esta demo (dado
  público, backend só acessível via URL efêmera do túnel), não seria a configuração de produção.

### Conta Vercel usada — nota sobre o processo, não sobre arquitetura

A CLI do Vercel já estava autenticada (login prévio, de outro projeto não relacionado ao MPRJ) numa
conta de equipe que não permite escopo pessoal e tinha *Deployment Protection* (SSO) ligada por
padrão — o link ficava redirecionando para login em vez de abrir a página. Foi feito login numa
conta pessoal separada (`julianabossardi`, via GitHub) especificamente para este projeto, e a
proteção SSO foi desativada no projeto (`vercel project protection disable web --sso`) para o link
poder ser compartilhado sem exigir login na Vercel de quem for abrir. Projeto e Supabase de uma
tentativa anterior desta mesma sessão (antes de se decidir por manter o backend local) foram
pausados, não usados — ver histórico de commits.

### O que foi reaproveitado do handoff de design vs. adaptado

- **Reaproveitado literalmente**: paleta de cores, tipografia (Inter/JetBrains Mono), espaçamento,
  raios de borda, sombras — copiados de `_ds_tokens/*.css` para `web/app/globals.css` como
  variáveis CSS, sem alteração de valores.
- **Adaptado**: o protótipo revela cada dado mascarado individualmente, por clique, com timestamp
  por revelação (`toggleReveal` no protótipo). O backend desta PoC desmascara o chunk **inteiro**
  de uma vez, condicionado ao perfil (não por entidade individual) — o frontend reflete isso
  mostrando o texto já revelado por completo quando o perfil tem clearance, em vez de um clique por
  máscara. Documentado como simplificação, não como o comportamento final desejado.
- **Não implementado** (o próprio handoff já marca como fora do fluxo principal): exportar dossiê
  (botão desabilitado, como no protótipo); anexar documentos de apoio (idem).

### Bugs encontrados após o deploy e correções

Depois do primeiro deploy, testes reais no frontend publicado (não só via `curl`) expuseram três
problemas:

- **Busca não retornava nada, mesmo para termos básicos.** A causa raiz não estava na busca em
  si: o padrão regex de RG usado para classificar `categoria_sigilo`
  (`\d{1,2}\.\d{3}\.\d{3}-?[\dXx]?`, sem word boundaries e com sufixo opcional) também casava com
  códigos de dotação orçamentária municipal, que têm o mesmo formato dígito.dígito.dígito. Uma
  auditoria retroativa encontrou 3337 falsos positivos em 3426 entidades marcadas como RG, o que
  havia classificado 69 dos 70 documentos como `sigiloso` — e o perfil padrão do frontend
  (`sem_clearance`) esconde documentos sigilosos por completo, tanto da busca quanto da leitura
  completa. Corrigido com um padrão mais estrito (`\b\d{1,2}\.\d{3}\.\d{3}-[\dXx]\b`, exige o
  dígito verificador e word boundaries — ver `db/migrations/0006_fix_rg_regex.sql`), um script
  único que restaurou o texto dos 3337 spans mascarados incorretamente e recalculou
  `nivel_restricao` para todos os documentos (distribuição corrigida: 25 sigiloso / 45 restrito /
  0 público).
- **Clicar em um card no "Explorar acervo" não carregava os detalhes.** Mesma causa raiz do item
  acima: a maioria dos documentos estava indevidamente `sigiloso`, então a chamada a
  `/documentos/{id}/completo` retornava 403 e a UI não distinguia esse caso de uma falha genérica
  — o modal parecia simplesmente não abrir. Corrigido em duas partes: (1) o bug de dados acima; (2)
  `openFullDoc`/`openFullDocFromAcervo` (`web/app/page.tsx`) agora detectam a resposta 403 e
  mostram uma mensagem explícita ("Documento sigiloso. Troque para o perfil 'Autorizado'…") em vez
  de um erro genérico — para os casos, bem mais raros agora, em que o documento é legitimamente
  sigiloso.
- **Título do card de resultado era um corte cru dos primeiros caracteres do trecho**, o que às
  vezes começava no meio de uma linha de assinatura (`____________`) ou de uma tabela, dificultando
  identificar o documento à primeira vista. Adicionada uma heurística simples sem LLM
  (`web/lib/resumo.ts`, função `resumoDe`) que pula linhas vazias, cabeçalhos de tabela e linhas
  dominadas por pontuação/sublinhado, preferindo a primeira linha com conteúdo real do próprio
  chunk — não é uma síntese semântica do documento inteiro (exigiria um LLM por resultado), só uma
  seleção melhor do que os primeiros N caracteres crus.

---

## Revisão 4 — normalização e enriquecimento na ingestão (adendo técnico)

Diagnóstico recebido após a Revisão 3, com sintomas concretos observados na interface: chunks
cortando palavras e tokens de anonimização ao meio (`ebimento` em vez de `recebimento`,
`PESSOA_FN]` sem colchete de abertura); ordem de leitura fragmentada em páginas diagramadas em
colunas; formulários e anexos padronizados dominando os resultados de busca; ausência de um campo
de título (a interface usava a primeira linha crua do chunk); e nome de arquivo com hash como
identificação do documento. Causa raiz comum aos três primeiros: faltava uma camada de
normalização/enriquecimento entre a extração de texto e o chunking — o pipeline ia direto de um
para o outro.

Seis correções, aplicadas nesta ordem (a mesma do diagnóstico, por relação impacto/esforço):

1. **Normalização do texto extraído** (`ingestion/normalize.py`, nova etapa entre `extract.py` e o
   chunking): reúne palavras hifenizadas quebradas por fim de linha, converte quebra de linha
   simples em espaço preservando quebra dupla como separador de parágrafo, colapsa espaços/linhas
   em branco, substitui sequências de sublinhado/ponto/traço (campo de preenchimento de formulário)
   por um marcador único (`[CAMPO]`), e remove cabeçalho/rodapé que se repete entre as páginas do
   mesmo documento (comparação de linha normalizada — número vira `#` — entre páginas, ver
   `remover_cabecalhos_rodapes_repetidos`). Roda por documento (não por página isolada), porque
   detectar cabeçalho/rodapé repetido exige comparar páginas entre si.
2. **Chunking por fronteira semântica** (`ingestion/chunk.py`, substitui o corte por contagem bruta
   de caracteres): divide por parágrafo primeiro, agrupa parágrafos consecutivos até aproximar
   ~2000 caracteres sem ultrapassar, e só desce para corte por sentença quando um parágrafo isolado
   já excede o alvo (nunca corta dentro de sentença; na ausência de qualquer pontuação, cai para
   corte por palavra como último recurso). Um token `[TIPO_XXX]` nunca é dividido — consequência
   direta de nunca cortar fora de fronteira de espaço/parágrafo/sentença, não um caso especial à
   parte. Chunks abaixo de 80 caracteres úteis são descartados (tipicamente fragmento residual de
   cabeçalho).
3. **Nome legível do documento**: os campos de origem/data/edição já vinham do manifest da fonte
   (`municipio`, `data_publicacao`, `edicao` já existiam em `documentos` desde a Revisão 2) — o que
   faltava era um título de fato. Resolvido junto com o item 5 abaixo (`documentos.titulo`); o nome
   de arquivo com hash permanece no registro, exposto só via API/rastreabilidade, não como rótulo
   principal na interface.
4. **Filtragem de conteúdo padronizado** (`ingestion/dedupe.py`, roda em duas fases porque a
   decisão depende do acervo inteiro, não de um documento isolado): calcula um hash do texto de
   cada chunk após generalizar pseudônimos de anonimização (`[PESSOA_A]`/`[PESSOA_B]` → `[X]`, para
   que o mesmo formulário preenchido com pessoas diferentes em documentos diferentes ainda seja
   reconhecido como o mesmo template) e marca como `eh_padronizado` os chunks cujo hash se repete em
   5+ documentos distintos, complementado por uma heurística de densidade (chunk dominado por
   marcadores `[CAMPO]` em vez de texto útil). **Marca, não exclui** — chunks padronizados saem do
   ranking de busca por padrão (`app/search.py`, `incluir_padronizados=False`) mas continuam
   acessíveis via `/documentos/{id}/completo` e na exploração livre do acervo. Métrica exposta em
   `/padronizados/stats`, mesma lógica de transparência da quarentena.
5. **Título e síntese gerados na ingestão** (`app/llm.py:gerar_titulo_e_sintese`): UMA chamada ao
   LLM local por DOCUMENTO (não por chunk), enviando os primeiros ~3000 caracteres do texto já
   normalizado/anonimizado, pedindo `{"titulo": "...", "sintese": "..."}` em JSON. Gravado em
   `documentos.titulo`/`documentos.sintese` (migration `0007`). Em caso de falha (timeout, resposta
   inválida), recai sobre um nome legível composto a partir de metadado
   (`município · tipo · data`) — nunca quebra a ingestão nem deixa o campo vazio. A interface usa o
   título como cabeçalho do card, a síntese na camada de detalhe, e o trecho recuperado como corpo
   — substituindo a heurística `resumoDe` da Revisão 3 (que continua como fallback para dados
   ingeridos antes desta camada existir).
6. **Ordem de leitura em páginas com colunas** (`ingestion/extract.py`): antes de extrair o texto de
   uma página, `_detectar_gap_coluna` analisa a distribuição horizontal dos centros das palavras
   (`page.extract_words()`) procurando um vazio largo o bastante na faixa central da página com
   volume comparável de palavras dos dois lados. Havendo esse vazio, a página é tratada como duas
   colunas — cada lado é reconstruído em linhas por proximidade vertical e a coluna esquerda inteira
   é emitida antes da direita (ordem de leitura correta, que `extract_text()` sozinho não
   reconstitui). Sem esse vazio, cai para `extract_text()` normal. O número de colunas detectado
   fica registrado por página em `qualidade_extracao`. Só roda no caminho nativo (pdfplumber); o
   caminho OCR continua dependendo só de `--psm 3` do Tesseract para colunas, como antes.

### Reprocessamento

As correções 1, 2, 4 e 6 mudam o texto indexado — depois de aplicá-las, o acervo inteiro foi
reprocessado do zero (cache de extração apagado, tabelas `documentos`/`chunks`/
`entidades_mascaradas` truncadas, `extract.py` + `index.py` rodados de novo). As correções 3 e 5 só
alteram a tabela `documentos`, sem exigir reindexação de vetores — mas como o reprocessamento
completo já estava acontecendo por causa das outras quatro, entraram juntas. Números de
recall/precisão de antes desta revisão não são comparáveis aos de depois; ver
[Resultado da avaliação da hipótese](#resultado-da-avaliação-da-hipótese) para a rodada pós-correção
(a rodada anterior fica só como referência histórica de que a extração pobre pesava no resultado).

**Amostra reduzida de 70 para 30 documentos, no meio do reprocessamento**: rodando localmente em
CPU (sem GPU dedicada), o custo por documento — normalização, chunking, embeddings, e a chamada de
LLM para título/síntese — ficou em torno de 100-170s/documento, e o processo foi ainda interrompido
uma vez por um problema de permissão de sistema operacional (macOS revogou o acesso à pasta do
projeto a meio do processamento; ver histórico de commits). Diante do risco real de não concluir um
reprocessamento de 70 documentos dentro do prazo, a decisão foi reduzir para 30 documentos bem
processados e verificáveis — 15 de Niterói e 15 de Angra dos Reis (Varre-Sai saiu desta amostra,
não por falha, só por escopo) — garantindo que os 14 documentos referenciados no gabarito do
experimento (`experiments/compare_modes.py`) permanecessem na amostra final. Escala vs.
confiabilidade dentro do prazo é exatamente o tipo de troca que apareceria em produção também,
numa forma maior (ver Riscos e evolução para produção).

### Ajustes pós-reprocessamento: prioridade real, custo de avaliação e organização do backend

Depois do reprocessamento, testes reais na interface (não só via API) expuseram mais alguns
problemas, todos corrigidos:

- **A busca não priorizava nada de fato**: o resultado ficava na ordem crua de recuperação
  (RRF/léxico/vetorial), não na ordem da nota de avaliação por critério — apesar da interface se
  chamar "busca priorizada". Corrigido em `app/routes/busca.py::_anexar_documentos_e_avaliar`, que
  agora reordena por `score_criterios` antes de devolver.
- **Custo de avaliação inviabilizava o uso interativo**: com `avaliar=true` (padrão) e o limite de
  10 candidatos da interface, uma busca chegava a 40 chamadas sequenciais ao LLM local (minutos de
  espera). Reduzido para 6 candidatos (`web/lib/api.ts`).
- **Perfil padrão "sem clearance" escondia metade da amostra reduzida** (15 dos 30 documentos
  nascem sigilosos pela regra binária de `nivel_restricao`) — o padrão da interface passou para
  "com clearance" (`web/app/page.tsx`); o seletor de perfil continua existindo para simular a troca.
- **Chips de busca de exemplo ficaram obsoletos** com a redução da amostra (buscavam temas
  concentrados em documentos que saíram de 70 para 30) — substituídos por três consultas validadas
  contra a amostra atual.
- **Critérios apareciam com a chave crua do banco** (`valores_financeiros` em vez de "Valores
  financeiros") — `web/lib/criterios.ts` adiciona um rótulo legível, com fallback automático
  (snake_case → Title Case) para um critério novo cadastrado via banco que ainda não tenha rótulo
  com curadoria manual.
- **`app/main.py` reorganizado**: tinha ~520 linhas misturando busca, casos/dossiê, acervo,
  feedback e stats de quarentena/padronizados num arquivo só. Dividido em `app/routes/` (um módulo
  por área) sem mudar nenhum comportamento — mesma URL, mesmo request/response em cada endpoint,
  verificado comparando a lista de rotas antes/depois e re-testando cada endpoint.

---

## O que mudou nesta revisão

Esta é a segunda revisão do brief técnico, implementada sobre o código já existente (não
reescrita do zero). Mudanças aplicadas:

| # | Mudança | O que foi preservado |
|---|---|---|
| 1 | Busca híbrida (léxica + vetorial, fundidas por *Reciprocal Rank Fusion*) substitui a busca puramente semântica | O baseline léxico (`tsvector`/`websearch_to_tsquery`) e a busca vetorial (`pgvector`) continuam existindo como modos isolados, agora selecionáveis |
| 2 | Pseudônimos consistentes por entidade (`[PESSOA_A]`, `[PESSOA_B]`, ...) substituem o contador global (`[PESSOA_1]`, `[PESSOA_2]`, ...) | A heurística de MAIÚSCULAS e o guard contra autorreferência de placeholder (ver Decisões técnicas) |
| 3 | Campos de linhagem (hash do PDF, offset de caracteres, versão do método/modelo) tornam-se obrigatórios no schema | A estrutura geral de `documentos`/`chunks` |
| 4 | Critérios de relevância viram registros em `criterio` (tabela), montados dinamicamente na instrução do modelo | Os 4 critérios originais (financeiro, licitação, nomeação/exoneração, penalidade/benefício), agora como linhas versionadas em vez de um bundle JSON |
| 5 | Categorias de sigilo (`categoria_sigilo`) tornam a detecção configurável, e documentos ganham `nivel_restricao` | As categorias já existentes (CPF, RG, TELEFONE, PESSOA) viram a seed inicial da tabela |
| 6 | Fila de quarentena (`quarentena`) com tipo de erro classificado | A cascata de extração (pdfplumber → OCR) continua igual; só passa a classificar falhas em vez de deixá-las implícitas |
| 7 | Metadados leves (`tipo_documento`) servem de pré-filtro da busca | — (novo) |
| 8 | Saída estruturada (JSON com schema explícito) já era usada; passa a ser **por critério individual** (avaliação atômica) em vez de um array com todos os critérios de uma vez | O uso de `"format": <json-schema>` do Ollama, que já havia substituído `"format": "json"` genérico na revisão anterior |
| 9 | Hipótese reformulada (léxico + vetorial + híbrido, não semântico vs. palavra-chave) | O script de comparação (`experiments/compare_modes.py`, antes `compare_recall.py`) manteve as 5 perguntas semânticas do experimento anterior e acrescentou 2 perguntas de termo exato |

Nada da arquitetura 100% local (Postgres/pgvector via Docker, Ollama, sentence-transformers) mudou
— essa era uma premissa fixada desde a revisão anterior e continua sendo.

---

## Setup e reprodução

Pré-requisitos: macOS/Linux, Python 3.12, Docker (ou Colima), [Ollama](https://ollama.com).

```bash
# 1. Ambiente Python (compartilhado entre ingestion/ e app/)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download pt_core_news_sm

# 2. Banco local (Postgres + pgvector)
docker compose up -d
# as migrations em db/migrations/ rodam automaticamente na primeira
# inicialização do container (Postgres executa *.sql em
# /docker-entrypoint-initdb.d em ordem alfabética)

# 3. Modelo de LLM local (avaliação por critérios)
ollama pull qwen2.5:7b-instruct
# ollama serve roda como serviço em background (brew services start ollama,
# ou apenas `ollama serve` num terminal)

# 4. Variáveis de ambiente
cp .env.example .env
# nenhuma chave de API é necessária - só configuração de conexão local

# 5. Dados: restaurar o dump pronto (recomendado) OU rodar a ingestão do zero
#
#    Opção A - restaurar o dump (ver "Dump do banco (db/seed/)" abaixo para
#    o comando exato e a ORDEM correta em relação às migrations - alguns
#    minutos).
#
#    Opção B - rodar o pipeline completo (extração + OCR + anonimização +
#    chunking + embeddings + título/síntese por LLM sobre os 30 PDFs da
#    amostra) - só em CPU local, pode levar de 1 a 2 horas:
python ingestion/source_querido_diario.py   # baixa os PDFs (pula se já existirem)
python ingestion/extract.py                 # extração em cascata (pdfplumber -> OCR) + quarentena
python ingestion/index.py                   # normalização + anonimização + chunking + embeddings + título/síntese + carga

# 6. Backend + demo
uvicorn app.main:app --reload --port 8000
streamlit run app/demo_ui.py                # em outro terminal, interface alternativa simples

# 7. Frontend novo (Next.js, revisão 3) - em outro terminal
cd web
npm install
cp .env.local.example .env.local            # NEXT_PUBLIC_API_URL=http://localhost:8000 (ver nota abaixo)
npm run dev                                 # http://localhost:3000
```

`web/.env.local` é ignorado pelo git (contém a URL do backend, que muda entre
ambientes - local vs. deploy híbrido no Vercel) - por isso não vem versionado e
precisa ser criado a partir de `web/.env.local.example` em toda instalação nova.

Para rodar a avaliação da hipótese (Seção 5, o principal artefato de comparação):

```bash
python experiments/compare_modes.py
```

### Nota sobre migrations adicionadas depois do primeiro `docker compose up`

`db/migrations/0005_casos_dossie.sql` (tabelas `casos`/`dossie_items`/`avaliacoes_relevancia`,
revisão 3) foi adicionada depois do primeiro `docker compose up -d` desta instalação. Postgres só
roda os arquivos de `/docker-entrypoint-initdb.d` na **primeira** inicialização de um volume vazio
— quem já tinha o banco rodando precisa aplicar essa migration manualmente:

```bash
docker exec -i realce-db psql -U realce -d realce < db/migrations/0005_casos_dossie.sql
```

Uma instalação nova (`docker compose up -d` num volume vazio) já roda todas as migrations,
incluindo a 0005, automaticamente.

### Dump do banco (`db/seed/`)

Rodar o pipeline de ingestão do zero (Opção B acima) processa 30 documentos 100% em CPU local -
extração, OCR quando necessário, anonimização, chunking, embeddings e uma chamada de LLM por
documento para título/síntese - e pode levar de 1 a 2 horas. Para quem só quer ver a interface
funcionando com dado real, `db/seed/realce_seed.sql.gz` é um dump do banco já processado (30
documentos, chunks com embeddings, títulos/sínteses, entidades mascaradas, critérios e avaliações
em cache, um caso de exemplo) - restaura em segundos.

**Ordem correta em relação às migrations**: o Postgres só roda os arquivos de
`/docker-entrypoint-initdb.d` (as migrations) na **primeira inicialização de um volume vazio** (ver
nota acima) - isso acontece automaticamente e não tem como pular. Por isso a sequência é sempre:

```bash
# 1. Sobe o container - dispara as migrations automaticamente se o volume for novo
docker compose up -d

# 2. Restaura o dump por cima - o dump é gerado com --clean --if-exists, então ele
#    mesmo derruba e recria schema (tabelas, função match_chunks, extensões) e dados;
#    não precisa (nem faz mal) as migrations terem rodado antes
gunzip -c db/seed/realce_seed.sql.gz | docker exec -i realce-db psql -U realce -d realce
```

Se o volume já existia de uma instalação anterior com dado diferente, rode `docker compose down -v`
antes do passo 1 para garantir um volume limpo (isso apaga qualquer dado local que não esteja no
dump).

Depois de restaurado, pule a Opção B (ingestão) e vá direto para o passo 6 (backend + demo).

**Por que versionar um dump de banco é aceitável aqui, e não seria em produção**: o conteúdo é
público (diários oficiais de Niterói e Angra dos Reis, já publicados oficialmente pelos municípios
- ver `ingestion/source_querido_diario.py`) e os dados mascarados (CPF, RG, telefone, nome) são
pseudônimos, não os valores originais - o dump não expõe nada que já não estivesse público. Com o
acervo real do MPRJ isso não seria aceitável: um dump versionado no git fica no histórico
permanentemente (mesmo que a linha seja removida depois), então dado sensível real precisaria de um
mecanismo de distribuição fora do controle de versão (storage com controle de acesso, backup
criptografado), nunca comprometido a um repositório.

### Publicar o frontend (deploy híbrido - ver Revisão 3 para o porquê)

```bash
# expor o backend local publicamente (URL muda a cada reinício)
cloudflared tunnel --url http://localhost:8000

# apontar o frontend para essa URL e publicar
cd web
vercel env add NEXT_PUBLIC_API_URL production   # cole a URL do tunel
vercel --prod
```

### Nota sobre a porta do Postgres

`docker-compose.yml` publica o Postgres do projeto na porta **5433** do host, não 5432. Durante o
desenvolvimento desta PoC, a máquina usada já tinha um PostgreSQL 18 nativo (instalação separada,
não relacionada a este projeto) ocupando a porta 5432 — o container Docker nunca chegava a receber
as conexões, que eram respondidas por esse outro Postgres, causando falhas de autenticação
confusas (a senha "errada" era sempre rejeitada, mesmo estando correta, porque o Postgres real por
trás da porta 5432 nem conhecia o usuário do projeto). Se sua máquina não tiver esse conflito, a
porta 5433 continua funcionando normalmente — só ajuste `DATABASE_URL` se preferir 5432.

---

## O que foi feito do zero / com IA / reaproveitado

**Reaproveitado de bibliotecas/projetos existentes:**
- `pdfplumber`, `pytesseract`, `pdf2image` (extração de PDF/OCR)
- `spaCy` + modelo `pt_core_news_sm` (NER em português)
- `sentence-transformers` + modelo `BAAI/bge-m3` (embeddings)
- `Ollama` (servidor de inferência local) + modelos `qwen2.5:7b-instruct` / `llama3.2:3b`
- `FastAPI`, `Streamlit`, `psycopg`, `pgvector` (bibliotecas de infraestrutura)
- `pgvector/pgvector` (imagem Docker do Postgres com a extensão já compilada)
- API pública do [Querido Diário](https://github.com/okfn-brasil/querido-diario) (fonte de dados)
- *Reciprocal Rank Fusion* (RRF) — técnica de fusão de rankings publicada (Cormack et al., 2009),
  implementada aqui em ~15 linhas de Python (`app/search.py`), sem biblioteca externa
- `Next.js`, `React`, `lucide-react` (ícones) — infraestrutura do frontend novo (`web/`)
- `cloudflared` (Cloudflare Tunnel) — expõe o backend local publicamente para o deploy híbrido
- design tokens (cores/tipografia/espaçamento/efeitos) do handoff de design recebido
  (`_ds_tokens/*.css`), copiados sem alteração de valores

**Gerado com apoio do Claude Code (implementação assistida por IA), revisado manualmente:**
Todo o código deste repositório (`app/`, `ingestion/`, `db/migrations/`, `experiments/`) foi
escrito com apoio do Claude Code a partir do brief técnico. Pontos que exigiram depuração manual
ativa durante a sessão (não só geração direta):
- o bug de mascaramento duplicado em `app/anonymize.py` (o NER do spaCy classificava o próprio
  placeholder como um novo nome de pessoa — corrigido com um guard de regex)
- um segundo bug da mesma família, encontrado nesta revisão ao introduzir pseudônimos
  letra-baseados: o spaCy passou a classificar como pessoa a palavra real *logo antes* de um
  placeholder já inserido (ex: "CPF" em "CPF `[CPF_A]`") — corrigido invertendo a ordem de
  processamento (nomes de pessoa primeiro, sobre o texto ainda intocado; regex estruturados depois)
- a limitação do NER em nomes inteiramente em MAIÚSCULAS (padrão comum em diários oficiais) —
  mitigada com uma heurística de regex complementar, documentada como heurística e não solução
  definitiva (ver [Limitações](#limitações-conhecidas))
- o diagnóstico do conflito de porta do Postgres (ver nota acima)
- a correção do import incorreto de `PDFSyntaxError` ao implementar a fila de quarentena (a
  exceção real vem de `pdfminer.pdfparser`, não de `pdf2image.exceptions` — mesmo nome de classe,
  módulos diferentes; descoberto testando com um PDF corrompido sintético)
- todo o frontend (`web/`), reimplementando os 7 estados do handoff de design em React/Next.js a
  partir do protótipo HTML e da documentação de handoff (`design_handoff_realce_busca_documentos/`)
- o diagnóstico e resolução do deploy no Vercel: descoberta de que a CLI estava autenticada numa
  conta de equipe sem escopo pessoal e com *Deployment Protection* (SSO) ativa por padrão
  (bloqueava o link com redirect de login); resolvido com login em conta separada e
  `vercel project protection disable`
- o diagnóstico de que o túnel cloudflared caiu durante os próprios testes (`context canceled` nos
  logs) e de que o navegador de teste bloqueava o domínio `trycloudflare.com`
  (`ERR_BLOCKED_BY_CLIENT`) mesmo com o túnel saudável — confirmado comparando `curl` direto
  (funcionava) com a chamada feita pelo navegador (bloqueada)
- o experimento (`experiments/compare_modes.py`) estourou timeout de 600s na primeira tentativa —
  o endpoint `/search` chamava avaliação por critério (LLM) sobre todo candidato em toda busca,
  então medir 3 modos × 7 perguntas significava até `limite × critérios ativos` avaliações por
  chamada. Corrigido separando retrieval (o que recall/precisão/latência de busca medem) de
  avaliação por critério (medida à parte, ver `avaliar=false` em `app/main.py`)
- a métrica de citação não verificada marcava ~100% dos casos como não verificados por causa de
  quebras de linha no meio de frases no texto extraído (artefato do `pdfplumber`/OCR) que o modelo
  naturalmente normaliza ao citar — corrigido normalizando espaços em branco dos dois lados antes
  de comparar (`app/evaluate.py::_citacao_verificada`); a taxa real caiu para 14,3%

**Desenvolvido do zero (decisões de design, não geração de boilerplate):**
- a separação `ingestion/source_querido_diario.py` como módulo de fronteira isolado (Seção 3) —
  decisão de arquitetura para não acoplar o pipeline à fonte de dados da PoC
- o conjunto de perguntas de teste e o gabarito manual em `experiments/compare_modes.py`,
  construído inspecionando o texto real extraído da amostra (não são perguntas genéricas),
  incluindo as 2 perguntas de termo exato desta revisão
- os critérios de relevância em `db/migrations/0003_seed_criterios.sql`
- a regra de classificação de `nivel_restricao` do documento (`ingestion/index.py`) e os limiares
  de classificação de quarentena (`ingestion/extract.py`)
- a decisão de **não** criar uma tabela separada para o "índice de entidades" pedido na Seção 4.3 —
  `entidades_mascaradas` já tem as colunas necessárias (`valor_original`, `documento_id`,
  `pseudonimo`); só faltava o índice certo, documentada em `db/migrations/0001_init.sql`

---

## Decisões técnicas

### Extração em cascata e quarentena (Seção 4.2)
`pdfplumber` primeiro (rápido, preserva posição); OCR local (`pytesseract --psm 3` + `pdf2image`,
português) quando o texto nativo está ausente ou tem baixa qualidade (heurística: menos de 40
caracteres, ou menos de 50% de caracteres alfabéticos). **Sem fallback de visão** — fora de escopo
desta PoC por decisão explícita do brief.

**Fila de quarentena**: um documento só é excluído do índice quando falha de forma severa e
classificável (`texto_vazio`, `texto_insuficiente`, `falha_ocr`, `encoding_invalido`,
`pdf_corrompido`, `outro`) — não quando só uma página isolada sai ruim dentro de um PDF bom. O
mecanismo foi validado com um PDF corrompido sintético (bytes aleatórios), classificado
corretamente como `pdf_corrompido`; a amostra real (30 documentos) não gerou nenhum caso de
quarentena — ver [Resultado da avaliação](#resultado-da-avaliação-da-hipótese) para os números
completos de extração.

**Ordem de leitura**: desde a Revisão 4, o caminho nativo detecta colunas por coordenadas antes de
chamar `extract_text()` (ver adendo técnico) em vez de depender só da posição bruta de caracteres;
o Tesseract (caminho OCR) continua rodando com `--psm 3` (segmentação automática de blocos), que
ajuda em colunas/tabelas mas continua sendo heurística — ver [Limitações](#limitações-conhecidas).

### Anonimização com pseudônimos consistentes (Seção 4.3)
Regex para CPF, RG e telefone + NER local (`spaCy pt_core_news_sm`) para nomes próprios, rodando
sobre o texto inteiro de cada documento antes do chunking. Diferente da revisão anterior, cada
entidade distinta recebe um pseudônimo **estável dentro do documento** (`[PESSOA_A]`,
`[PESSOA_B]`, ...) em vez de um contador global — a mesma pessoa citada duas vezes no mesmo
documento recebe o mesmo pseudônimo nas duas ocorrências (testado manualmente, ver
`app/anonymize.py`). Isso preserva a estrutura relacional da frase (quem fez o quê a quem), que a
versão anterior destruía.

As categorias de detecção (CPF, RG, TELEFONE, PESSOA) agora são lidas de `categoria_sigilo`, não
mais hardcoded — `anonimizar_documento()` recebe a lista de categorias ativas como parâmetro.

**Índice de entidades**: para permitir buscar por um nome específico sem expor o dado a quem não
tem permissão, a consulta é resolvida contra `entidades_mascaradas.valor_original` antes da busca
(`app/search.py::_resolver_pseudonimos`) — os pseudônimos correspondentes entram na busca léxica
(via `ILIKE`) e são anexados à consulta antes do embedding (busca vetorial). Testado com uma
pergunta de termo exato no experimento (ver resultado abaixo).

### Categorias de sigilo e nível de restrição do documento (Seção 4.3)
`categoria_sigilo` populada com CPF, RG, TELEFONE (regex) e PESSOA (NER) — lista intencionalmente
incompleta; a capacidade de acomodar novas categorias sem mudar código é o que a PoC demonstra.
Cada documento carrega `nivel_restricao` (`publico`/`restrito`/`sigiloso`), atribuído por uma regra
simples nesta PoC (`ingestion/index.py::_classificar_nivel_restricao`): sem entidade sensível →
público; com nome de pessoa → restrito; com CPF/RG → sigiloso. Documento sigiloso **some** do
resultado para quem não tem clearance, em vez de aparecer mascarado (`app/access.py`).

**Achado real na amostra**: essa regra simples classifica **15 dos 30 documentos como sigilosos**
(e os outros 15 como restritos, nenhum público) — basta um único CPF/RG aparecer em qualquer lugar
do documento (comum em editais com lista de candidatos, tabelas de pensionistas, etc.), e diários
oficiais tendem a acumular vários atos diferentes por edição. Isso é uma consequência honesta da
regra escolhida, não um bug, mas deixa claro que uma regra binária "tem CPF → sigiloso" é grosseira
demais para uso real — o experimento (abaixo) precisou rodar com `perfil=com_clearance` para não
medir recall/precisão sobre um acervo
quase inteiramente invisível. Ver [Limitações](#limitações-conhecidas).

### Critérios como dado (Seção 4.6)
`criterio` é uma tabela (chave, descrição, versão, ativo) — incluir, editar ou desativar um
critério é operação sobre dados, não deploy de código. A avaliação lê os critérios ativos e monta
a instrução dinamicamente (`app/evaluate.py`).

**Avaliação atômica**: um critério por chamada ao LLM, não todos de uma vez. A versão anterior
mandava os 3-5 critérios numa única instrução; nesta revisão, cada critério vira uma chamada
separada, mais curta. Mais chamadas (mais latência total), porém mais confiável e permite atribuir
feedback a um critério específico.

**Validação de citação**: `trecho_citado` retornado pelo modelo é verificado programaticamente
contra o texto do chunk (`app/evaluate.py::_citacao_verificada`) — se o trecho não existe
literalmente, a avaliação fica marcada como `citacao_verificada=false`. A taxa de citação não
verificada é reportada no experimento (ver abaixo) como evidência direta da confiabilidade do
modelo local.

### Modelo de embeddings — `BAAI/bge-m3`
Multilíngue, bom desempenho em português, roda em CPU em tempo aceitável para o volume desta PoC.
Dimensão do vetor: 1024. Alternativa considerada: `intfloat/multilingual-e5-large` (também 1024
dim, mas exige prefixos `query:`/`passage:` — bge-m3 funciona diretamente).

### Modelo de LLM local — comparação e escolha
Testados dois modelos via Ollama contra o mesmo prompt de avaliação:

| Modelo | Latência por avaliação (1 critério) | Confiabilidade do JSON estruturado |
|---|---|---|
| `qwen2.5:7b-instruct` (4.7GB) | ~15-25s | Consistente |
| `llama3.2:3b` (2.0GB) | ~5s | Não confiável para prompts com múltiplos critérios (testado na revisão anterior); com avaliação atômica (1 critério por chamada) a confiabilidade melhora, mas `qwen2.5:7b-instruct` seguiu sendo a escolha por já ter latência aceitável na demo |

**Escolha: `qwen2.5:7b-instruct`.** A confiabilidade do JSON estruturado é um requisito duro — a
resposta alimenta o cache de avaliações e a interface. Isso é evidência concreta do trade-off
qualidade vs. portabilidade nomeado na Seção 9 do brief anterior (mantido nesta revisão):
modelos locais menores tendem a ter confiabilidade de instrução inferior a modelos maiores.

`"format": <json-schema>` (structured outputs do Ollama, não só `"format": "json"` genérico)
continua sendo necessário — sem isso, o modelo às vezes devolve texto fora do formato esperado
para trechos muito ruidosos (tabelas fragmentadas).

### Busca híbrida via Reciprocal Rank Fusion (Seção 4.5)
Os três modos (`lexico`, `vetorial`, `hibrido`) rodam contra o mesmo banco. O modo híbrido executa
as duas buscas (top-30 cada) e funde os rankings por RRF (`k=60`, valor de referência do artigo
original) — `score = Σ 1/(k + posição)` por lista em que o chunk aparece. RRF foi escolhido em vez
de normalizar e somar os escores brutos porque `ts_rank` (léxico) e distância de cosseno (vetorial)
têm escalas e distribuições completamente diferentes; RRF só usa a *posição* no ranking, não o
valor do escore, o que dispensa essa normalização.

### Banco de dados
PostgreSQL + `pgvector`, rodando local via Docker (`pgvector/pgvector:pg16`). Um único banco guarda
documentos, chunks, embeddings, categorias de sigilo, entidades mascaradas, critérios, avaliações,
feedback, quarentena e auditoria — 9 tabelas (ver `db/migrations/0001_init.sql`).

**Alternativas descartadas**: Vercel/Supabase cloud e Voyage AI/API Claude para embeddings/
avaliação — usados numa iteração ainda mais antiga desta PoC (duas revisões atrás) e descartados
porque a arquitetura final prioriza rodar 100% local; Chroma/Qdrant como vector DB separado
(pgvector no mesmo Postgres já resolve); um *reranker* (cross-encoder) entre a busca e o LLM — não
implementado nesta PoC, mas é a evolução mais provável desta arquitetura (ver
[Fora de escopo](#fora-de-escopo-desta-poc)).

---

## Resultado da avaliação da hipótese

Ver [experiments/compare_modes.py](experiments/compare_modes.py) para o script completo e a
metodologia do gabarito (7 perguntas: 5 de descrição semântica, 2 de termo exato). Resultado obtido
rodando as perguntas contra os 30 documentos da amostra pós-Revisão 4 (normalização + chunking
semântico + detecção de colunas + filtragem de conteúdo padronizado — ver adendo técnico), via API
local. **Números de antes da Revisão 4 (70 documentos, extração sem essas correções) não são
comparáveis a estes** — ficam só como nota de rodapé no fim desta seção.

**Resultado geral (média das 7 perguntas):**

| Modo | Recall médio | Precisão média | Latência média de busca (s) |
|---|---|---|---|
| léxico | 0.59 | 0.30 | 0.16 |
| vetorial | 0.36 | 0.11 | 1.26 |
| **híbrido** | **0.61** | 0.16 | 0.30 |

**Só perguntas de descrição semântica** (5 perguntas — onde o vocabulário da pergunta diverge do
documento):

| Modo | Recall médio | Precisão média |
|---|---|---|
| léxico | 0.43 | 0.19 |
| vetorial | 0.30 | 0.12 |
| **híbrido** | **0.45** | 0.16 |

**Só perguntas de termo exato** (2 perguntas — nome de pessoa via índice de entidades, e número de
portaria):

| Modo | Recall médio | Precisão média |
|---|---|---|
| léxico | **1.00** | **0.58** |
| vetorial | 0.50 | 0.08 |
| híbrido | **1.00** | 0.15 |

**Avaliação por critério (modo híbrido, LLM ligado):** 11,1% de citações não verificadas (1 de 9
avaliações com citação retornou um trecho que não bate literalmente com o chunk após normalizar
espaços). Latência média por consulta com avaliação ligada: ~214s (4 candidatos × até 4 critérios
cada, em CPU, sem paralelismo). **Quarentena: 0% do acervo** (0 de 30 documentos). **Conteúdo
padronizado: 0,5% dos chunks** (13 de 2821 — formulários/anexos que se repetem entre documentos,
fora do ranking por padrão, ver adendo técnico).

**A hipótese se confirma, com a mesma ressalva sobre precisão observada antes da Revisão 4.** No
agregado e no subconjunto semântico, o híbrido continua superando as duas pontas em recall —
exatamente o que a hipótese revisada previa, e o padrão se manteve depois da correção da extração.
No subconjunto de termo exato, híbrido empata com léxico em recall (ambos 1.00), mas **léxico tem
precisão bem maior** (0.58 vs. 0.15): quando o termo é exato, a busca vetorial trazida pela fusão
RRF adiciona candidatos semanticamente relacionados mas irrelevantes ao termo específico buscado,
diluindo a precisão sem ganhar recall adicional. Isso não invalida a hipótese (o objetivo é recall
alto sem perder o léxico como opção), mas é um resultado que contraria a expectativa ingênua de que
"híbrido é sempre melhor nos dois eixos" — e é exatamente o tipo de achado que o experimento deveria
revelar (Seção 5 do brief: "o resultado interessa mesmo se contrariar a expectativa"). Em produção,
isso sugere valor em deixar o usuário optar por léxico puro quando já sabe exatamente o termo que
procura (nome, número de processo) — o que a interface de demonstração já permite.

**O que mudou visivelmente com a extração corrigida**: recall médio subiu em todas as linhas (ex:
recall geral do híbrido foi de 0.43 para 0.61; precisão geral do léxico, de 0.28 para 0.30);
precisão de termo exato ficou estável (léxico: 0.60 → 0.58, dentro da variação esperada para 2
perguntas) e a latência de busca caiu bastante (retrieval geral do híbrido: 2.72s → 0.30s) — não por o hardware ter
ficado mais rápido, mas porque a amostra ficou menor (30 vs. 70 documentos) E os chunks ficaram mais
enxutos e menos redundantes (chunking semântico + filtragem de padronizados), então cada busca
examina menos candidatos ruidosos. A taxa de citação não verificada também caiu (14,3% → 11,1%,
amostras pequenas demais para tratar como tendência forte, mas na direção esperada de chunks mais
limpos gerando citações mais fiéis). **Isso não isola sozinho o efeito da correção de extração** —
a amostra também mudou de tamanho (70→30, ver Revisão 4) e composição (perdeu Varre-Sai) ao mesmo
tempo, então a comparação direta dos números é só indicativa, não uma medição controlada de "quanto
da melhora veio de cada mudança".

**Nota sobre a normalização da verificação de citação:** a primeira versão desta métrica (antes da
Revisão 3) marcava ~100% das citações como "não verificadas" — não porque o modelo alucinava, mas
porque o texto extraído do PDF carregava quebras de linha no meio de frases (artefato do
`pdfplumber`/OCR), e o modelo naturalmente substituía a quebra por um espaço ao citar o mesmo
conteúdo literal. A correção (`app/evaluate.py::_citacao_verificada`) normaliza espaços em branco
dos dois lados antes de comparar.

<details>
<summary>Números de antes da Revisão 4 (70 documentos, sem normalização/chunking semântico/detecção
de colunas) — não comparáveis aos de cima, mantidos só como referência histórica</summary>

| Modo | Recall médio | Precisão média | Latência média de busca (s) |
|---|---|---|---|
| léxico | 0.38 | 0.28 | 0.96 |
| vetorial | 0.22 | 0.10 | 3.39 |
| híbrido | 0.43 | 0.14 | 2.72 |

Citação não verificada: 14,3% (2 de 14). Quarentena: 0% (0 de 70).

</details>

**Nota sobre o custo do experimento:** a primeira tentativa deste script chamava `/search` com
avaliação por critério ligada em toda busca de teste (3 modos × 7 perguntas), o que significa até
`limite × critérios ativos` avaliações por chamada (10 × 4 = 40) — e estourou o timeout de 600s.
A correção foi separar retrieval (`avaliar=false`, o que recall/precisão/latência de busca
realmente medem) de avaliação por critério (medida à parte, uma vez por pergunta, sobre um número
menor de candidatos) — ver `app/main.py` e `experiments/compare_modes.py`.

---

## Limitações conhecidas

- **Amostra pequena**: 30 documentos de 2 municípios (Niterói, Angra dos Reis — ver
  `ingestion/source_querido_diario.py`), frente aos ~500 mil do cenário real do MPRJ. Reduzida de
  70 para 30 na Revisão 4 (adendo técnico) — o reprocessamento completo do acervo (normalização +
  chunking semântico + detecção de colunas, tudo em CPU local) tornava 70 documentos um risco real
  de não terminar dentro do prazo; 30 bem processados foi a troca deliberada. Varre-Sai (pequeno
  porte) ficou de fora desta rodada, não por ter falhado — fica para uma amostra futura. A PoC
  valida a abordagem, não a escala.
- **Diário oficial ≠ acervo do MPRJ**: natureza, sensibilidade e estrutura diferem. Serve como
  proxy realista de "documento público, PDF variável, volume alto", não como equivalente exato.
- **NER local não é perfeito, em várias direções**: erra sistematicamente nomes em MAIÚSCULAS
  (mitigado com heurística de regex); tem falso positivo em conteúdo tabular (substantivos comuns
  mascarados como pessoa); e, descoberto nesta revisão, pode classificar como pessoa uma palavra
  real adjacente a um placeholder já inserido pelo próprio pipeline (mitigado invertendo a ordem de
  processamento — ver Decisões técnicas). Nenhuma dessas mitigações é uma garantia formal.
- **Resolução de nomes por substring**: `_resolver_pseudonimos` faz `ILIKE`/substring
  case-insensitive sobre toda `entidades_mascaradas` a cada busca — funciona na escala desta PoC,
  não substitui um índice de nomes tokenizado/fuzzy em escala de produção.
- **Sem fallback de visão** na extração — fora de escopo desta PoC (Seção 4.2 do brief).
- **Ordem de leitura em colunas/tabelas**: o caminho nativo (pdfplumber) agora detecta colunas por
  coordenadas e reconstitui a ordem de leitura correta (Revisão 4 — ver `_detectar_gap_coluna` em
  `ingestion/extract.py`), mas continua sendo heurística (gap horizontal + volume de palavras dos
  dois lados), não garantia formal — layouts com 3+ colunas ou tabelas muito complexas podem ainda
  fragmentar o contexto do chunk. O caminho OCR não tem detecção por coordenadas, só `--psm 3` do
  Tesseract.
- **Lista de categorias de sigilo incompleta**: só CPF, RG, telefone e nome de pessoa. Categorias
  que dependem de levantamento jurídico (ex: dado de vítima, segredo de justiça) não estão aqui —
  a tabela `categoria_sigilo` foi desenhada para acomodá-las sem mudança de código, não para já
  cobri-las.
- **Nível de restrição do documento é regra simples**: atribuído automaticamente por presença de
  categoria sensível (ver Decisões técnicas). Na amostra pós-correção do regex de RG (Revisão 3),
  isso classifica 15 de 30 documentos como sigilosos e 15 como restritos — um único CPF/RG em
  qualquer lugar do documento já basta para sigiloso. Não reflete uma análise jurídica real de
  sensibilidade do conteúdo; em produção, precisaria de granularidade por trecho/seção, não por
  documento inteiro.
- **Gabarito do experimento é semiautomático**: construído com expressões regulares sobre o texto
  já extraído, cada acerto conferido por leitura humana antes de entrar no gabarito — não é uma
  anotação manual completa e independente por múltiplos revisores.
- **Sem reprocessamento automático**: mudar a versão de um critério não reavalia os resultados já
  em cache — o feedback (Seção 4.9) só demonstra o registro do dado, vinculado à versão vigente.
- **Controle de acesso simplificado**: seletor de perfil sem autenticação real (Seção 4.7).

---

## Riscos e evolução para produção

- **Escala para 500 mil documentos**: `pgvector` com índice HNSW escala bem para milhões de
  vetores, mas a ingestão (OCR + anonimização + embeddings + avaliação) precisaria rodar de forma
  incremental/distribuída, não como um script único sequencial.
- **Reranker (cross-encoder) entre a busca e o LLM**: não implementado nesta PoC. Filtraria um
  top-100 (barato, léxico+vetorial) para um top-5 (com custo bem menor que o do modelo generativo)
  antes da avaliação por critério, reduzindo latência e ruído — é a evolução mais provável desta
  arquitetura.
- **Qualidade vs. privacidade do modelo local**: modelos locais menores trocam qualidade/
  confiabilidade por rodar sem depender de API externa (evidenciado pela comparação de modelos
  acima). Em produção, essa é uma decisão a reafirmar com dados reais de uso.
- **Qualidade da anonimização**: as taxas de falso positivo/negativo do NER foram observadas
  diretamente durante o desenvolvimento (ver Limitações), não medidas formalmente contra uma
  amostra anotada — necessário antes de usar com dado real do MP.
- **Controle de acesso real**: produção exigiria integração com identidade institucional (SSO do
  MPRJ) e papéis definidos por política de acesso formal — a auditoria de revelação (`auditoria`)
  já está implementada nesta PoC, mas vinculada a um perfil autodeclarado, não a uma identidade
  real.
- **Infraestrutura de produção**: "rodar no computador de quem desenvolve" resolve a PoC; produção
  seria um ambiente self-hosted dentro da infraestrutura do MPRJ, com backup, monitoramento e,
  dependendo do modelo local escolhido, hardware com GPU dedicada para desempenho em escala.
- **Canal de entrada real**: a obtenção da amostra via API do Querido Diário não valida que o MPRJ
  tem (ou terá) um canal equivalente — por isso isolada em `ingestion/source_querido_diario.py`.

---

## Fora de escopo desta PoC

- Reranker (cross-encoder) entre a busca e o LLM — ver Riscos acima
- Modelo de visão local para tabelas e gráficos
- Autenticação real e integração com identidade institucional
- Reprocessamento automático após mudança de critério
- Integração com sistema de gestão processual por número de processo
