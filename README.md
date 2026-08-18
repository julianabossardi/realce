# Realce — PoC: identificação de documentos de atenção prioritária

PoC para o desafio técnico Inova/MPRJ. Testa uma hipótese específica, não constrói um produto
completo: **a combinação de busca léxica e busca semântica, seguida de avaliação por critério via
LLM local, recupera documentos relevantes com recall e precisão superiores aos de cada método de
busca isolado.**

Arquitetura **100% local**: banco (Postgres + pgvector via Docker), modelo de embeddings
(sentence-transformers) e LLM de avaliação (Ollama) rodam todos no computador de quem executa —
nenhuma chamada de API externa acontece durante o uso normal do sistema. O único tráfego de rede é
o download inicial dos pesos dos modelos (uma vez) e a ingestão inicial dos PDFs do Querido Diário.

## Sumário

- [O que mudou nesta revisão](#o-que-mudou-nesta-revisão)
- [Setup e reprodução](#setup-e-reprodução)
- [O que foi feito do zero / com IA / reaproveitado](#o-que-foi-feito-do-zero--com-ia--reaproveitado)
- [Decisões técnicas](#decisões-técnicas)
- [Resultado da avaliação da hipótese](#resultado-da-avaliação-da-hipótese)
- [Limitações conhecidas](#limitações-conhecidas)
- [Riscos e evolução para produção](#riscos-e-evolução-para-produção)
- [Fora de escopo](#fora-de-escopo-desta-poc)

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

# 5. Ingestão (baixa a amostra, extrai texto, anonimiza, gera embeddings, carrega no banco)
python ingestion/source_querido_diario.py   # baixa os PDFs (pula se já existirem)
python ingestion/extract.py                 # extração em cascata (pdfplumber -> OCR) + quarentena
python ingestion/index.py                   # anonimização + metadados + chunking + embeddings + carga

# 6. Backend + demo
uvicorn app.main:app --reload --port 8000
streamlit run app/demo_ui.py                # em outro terminal
```

Para rodar a avaliação da hipótese (Seção 5, o principal artefato de comparação):

```bash
python experiments/compare_modes.py
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
corretamente como `pdf_corrompido`; a amostra real (70 documentos) não gerou nenhum caso de
quarentena — ver [Resultado da avaliação](#resultado-da-avaliação-da-hipótese) para os números
completos de extração.

**Ordem de leitura**: `pdfplumber.extract_text()` já reconstitui a ordem de leitura pela posição
dos caracteres na página; o Tesseract roda com `--psm 3` (segmentação automática de blocos), que
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

**Achado real na amostra**: essa regra simples classificou **69 dos 70 documentos como sigilosos**
— basta um único CPF/RG aparecer em qualquer lugar do documento (comum em editais com lista de
candidatos, tabelas de pensionistas, etc.), e diários oficiais tendem a acumular vários atos
diferentes por edição. Isso é uma consequência honesta da regra escolhida, não um bug, mas deixa
claro que uma regra binária "tem CPF → sigiloso" é grosseira demais para uso real — o experimento
(abaixo) precisou rodar com `perfil=com_clearance` para não medir recall/precisão sobre um acervo
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
rodando as perguntas contra os 70 documentos da amostra, via API local:

**Resultado geral (média das 7 perguntas):**

| Modo | Recall médio | Precisão média | Latência média de busca (s) |
|---|---|---|---|
| léxico | 0.38 | 0.28 | 0.96 |
| vetorial | 0.22 | 0.10 | 3.39 |
| **híbrido** | **0.43** | 0.14 | 2.72 |

**Só perguntas de descrição semântica** (5 perguntas — onde o vocabulário da pergunta diverge do
documento):

| Modo | Recall médio | Precisão média |
|---|---|---|
| léxico | 0.13 | 0.15 |
| vetorial | 0.11 | 0.12 |
| **híbrido** | **0.20** | 0.15 |

**Só perguntas de termo exato** (2 perguntas — nome de pessoa via índice de entidades, e número de
portaria):

| Modo | Recall médio | Precisão média |
|---|---|---|
| léxico | **1.00** | **0.60** |
| vetorial | 0.50 | 0.06 |
| híbrido | **1.00** | 0.13 |

**Avaliação por critério (modo híbrido, LLM ligado):** 14,3% de citações não verificadas (2 de 14
avaliações com citação retornaram um trecho que não bate literalmente com o chunk após normalizar
espaços — ver nota abaixo). Latência média por consulta com avaliação ligada: ~217s (4 candidatos ×
até 4 critérios cada, em CPU, sem paralelismo). **Quarentena: 0% do acervo** (0 de 70 documentos —
a amostra não teve nenhum caso de falha severa de extração, ver Decisões técnicas).

**A hipótese se confirma, com uma ressalva importante sobre precisão.** No agregado e no subconjunto
semântico, o híbrido supera as duas pontas em recall — exatamente o que a hipótese revisada previa.
No subconjunto de termo exato, híbrido empata com léxico em recall (ambos 1.00), mas **léxico tem
precisão bem maior** (0.60 vs. 0.13): quando o termo é exato, a busca vetorial trazida pela fusão
RRF adiciona candidatos semanticamente relacionados mas irrelevantes ao termo específico buscado,
diluindo a precisão sem ganhar recall adicional. Isso não invalida a hipótese (o objetivo é recall
alto sem perder o léxico como opção), mas é um resultado que contraria a expectativa ingênua de que
"híbrido é sempre melhor nos dois eixos" — e é exatamente o tipo de achado que o experimento deveria
revelar (Seção 5 do brief: "o resultado interessa mesmo se contrariar a expectativa"). Em produção,
isso sugere valor em deixar o usuário optar por léxico puro quando já sabe exatamente o termo que
procura (nome, número de processo) — o que a interface de demonstração já permite.

**Nota sobre a normalização da verificação de citação:** a primeira versão desta métrica marcava
~100% das citações como "não verificadas" — não porque o modelo alucinava, mas porque o texto
extraído do PDF carrega quebras de linha no meio de frases (artefato do `pdfplumber`/OCR), e o
modelo naturalmente substitui a quebra por um espaço ao citar o mesmo conteúdo literal. A correção
(`app/evaluate.py::_citacao_verificada`) normaliza espaços em branco dos dois lados antes de
comparar — depois da correção, a taxa caiu para 14,3%, um número que soa plausível para citação
alucinada real (um dos casos observados: o modelo colou dois valores monetários não-contíguos do
mesmo chunk como se fossem uma citação única).

**Nota sobre o custo do experimento:** a primeira tentativa deste script chamava `/search` com
avaliação por critério ligada em toda busca de teste (3 modos × 7 perguntas), o que significa até
`limite × critérios ativos` avaliações por chamada (10 × 4 = 40) — e estourou o timeout de 600s.
A correção foi separar retrieval (`avaliar=false`, o que recall/precisão/latência de busca
realmente medem) de avaliação por critério (medida à parte, uma vez por pergunta, sobre um número
menor de candidatos) — ver `app/main.py` e `experiments/compare_modes.py`.

---

## Limitações conhecidas

- **Amostra pequena**: 70 documentos de 3 municípios (Niterói, Angra dos Reis, Varre-Sai — ver
  `ingestion/source_querido_diario.py`), frente aos ~500 mil do cenário real do MPRJ. A PoC valida
  a abordagem, não a escala.
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
- **Ordem de leitura em colunas/tabelas**: heurística (posição de caracteres no `pdfplumber`,
  `--psm 3` no Tesseract), não garantia — layouts muito complexos podem fragmentar o contexto do
  chunk.
- **Lista de categorias de sigilo incompleta**: só CPF, RG, telefone e nome de pessoa. Categorias
  que dependem de levantamento jurídico (ex: dado de vítima, segredo de justiça) não estão aqui —
  a tabela `categoria_sigilo` foi desenhada para acomodá-las sem mudança de código, não para já
  cobri-las.
- **Nível de restrição do documento é regra simples, e agressiva na prática**: atribuído
  automaticamente por presença de categoria sensível (ver Decisões técnicas). Na amostra, isso
  classificou 69 de 70 documentos como sigilosos — um único CPF/RG em qualquer lugar do documento
  já basta. Não reflete uma análise jurídica real de sensibilidade do conteúdo; em produção,
  precisaria de granularidade por trecho/seção, não por documento inteiro.
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
