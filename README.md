# Realce — PoC: identificação de documentos de atenção prioritária

PoC para o desafio técnico Inova/MPRJ. Testa uma hipótese específica, não constrói um produto
completo: **busca semântica (embeddings) + avaliação por critérios via LLM encontra documentos
relevantes com melhor recall e precisão do que busca por palavra-chave**, especialmente quando a
relevância depende de significado e não de correspondência exata de termos.

Arquitetura **100% local**: banco (Postgres + pgvector via Docker), modelo de embeddings
(sentence-transformers) e LLM de avaliação (Ollama) rodam todos no computador de quem executa —
nenhuma chamada de API externa acontece durante o uso normal do sistema. O único tráfego de rede é
o download inicial dos pesos dos modelos (uma vez) e a ingestão inicial dos PDFs do Querido Diário.

## Sumário

- [Setup e reprodução](#setup-e-reprodução)
- [O que foi feito do zero / com IA / reaproveitado](#o-que-foi-feito-do-zero--com-ia--reaproveitado)
- [Decisões técnicas](#decisões-técnicas)
- [Resultado da avaliação da hipótese](#resultado-da-avaliação-da-hipótese)
- [Limitações conhecidas](#limitações-conhecidas)
- [Riscos e evolução para produção](#riscos-e-evolução-para-produção)
- [Fora de escopo](#fora-de-escopo-desta-poc)

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
python ingestion/extract.py                 # extração em cascata (pdfplumber -> OCR)
python ingestion/embed_and_load.py          # anonimização + chunking + embeddings + carga

# 6. Backend + demo
uvicorn app.main:app --reload --port 8000
streamlit run app/demo_ui.py                # em outro terminal
```

Para rodar a avaliação da hipótese (Seção 4.6, o principal artefato de comparação):

```bash
python experiments/compare_recall.py
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

**Gerado com apoio do Claude Code (implementação assistida por IA), revisado manualmente:**
Todo o código deste repositório (`app/`, `ingestion/`, `db/migrations/`, `experiments/`) foi
escrito com apoio do Claude Code a partir do brief técnico da Seção 0. Pontos que exigiram
depuração manual ativa durante a sessão (não só geração direta):
- o bug de mascaramento duplicado em `app/anonymize.py` (o NER do spaCy classificava o próprio
  placeholder `[PESSOA_N]` como um novo nome de pessoa — corrigido com um guard de regex)
- a limitação do NER em nomes inteiramente em MAIÚSCULAS (padrão comum em diários oficiais) —
  mitigada com uma heurística de regex complementar, documentada como heurística e não solução
  definitiva (ver [Limitações](#limitações-conhecidas))
- o diagnóstico do conflito de porta do Postgres (ver nota acima)

**Desenvolvido do zero (decisões de design, não geração de boilerplate):**
- a separação `ingestion/source_querido_diario.py` como módulo de fronteira isolado (Seção 3.1) —
  decisão de arquitetura para não acoplar o pipeline à fonte de dados da PoC
- o conjunto de perguntas de teste e o gabarito manual em `experiments/compare_recall.py`,
  construído inspecionando o texto real extraído da amostra (não são perguntas genéricas)
- os critérios de relevância versionados em `db/migrations/0002_seed_criterios.sql`

---

## Decisões técnicas

### Extração em cascata (Seção 4.1)
`pdfplumber` primeiro (rápido, preserva posição); OCR local (`pytesseract` + `pdf2image`,
português) quando o texto nativo está ausente ou tem baixa qualidade (heurística: menos de 40
caracteres, ou menos de 50% de caracteres alfabéticos). **Sem fallback de visão** (modelo
multimodal) — decisão explícita do brief para esta PoC, já que um modelo de visão local exigiria
mais hardware do que se pode assumir disponível. Páginas que não atingem qualidade mínima nem
depois do OCR ficam marcadas como `ocr_baixa_confianca`.

Achado da amostra real (70 documentos, 1654 páginas): **1521 páginas via pdfplumber, 114 via OCR,
19 (1,1%) como `ocr_baixa_confianca`**. A maior parte das páginas problemáticas está *dentro* de
diários que são majoritariamente nativos — típico de anexos escaneados, assinaturas ou carimbos
embutidos em um documento predominantemente digital, não de diários inteiramente escaneados. Isso
também revelou que o Querido Diário já roda seu próprio pipeline de OCR antes de publicar os PDFs
(a maioria carrega uma camada de texto mesmo quando a origem é escaneada) — a cascata desta PoC
decide o fallback por *qualidade* do texto, não só por ausência, porque esse é o cenário mais
realista para o acervo real do MPRJ também.

### Anonimização (Seção 4.1.1)
Regras/regex para CPF, RG e telefone (padrões estruturados) + NER local (`spaCy pt_core_news_sm`)
para nomes próprios, rodando sobre o texto inteiro de cada documento antes do chunking. Um
mapeamento mascarado→original é gravado em `entidades_mascaradas`, e o texto anonimizado é a
versão principal armazenada em `chunks.texto`.

### Modelo de embeddings — `BAAI/bge-m3`
Multilíngue, bom desempenho em português, roda em CPU em tempo aceitável para o volume desta PoC
(sem GPU dedicada). Dimensão do vetor: 1024. Alternativa considerada: `intfloat/multilingual-e5-large`
(também 1024 dim, mas exige prefixos `query:`/`passage:` nos textos — bge-m3 funciona diretamente).

### Modelo de LLM local — comparação e escolha
Testados dois modelos via Ollama contra o mesmo prompt de avaliação por critérios:

| Modelo | Latência por avaliação (3 critérios) | Confiabilidade do JSON estruturado |
|---|---|---|
| `qwen2.5:7b-instruct` (4.7GB) | ~26s | Consistente — sempre retornou o array esperado, com justificativa e citação coerentes |
| `llama3.2:3b` (2.0GB) | ~5s | Não confiável para este prompt — em teste direto, retornou JSON válido porém vazio (`[]`) em vez do array de avaliações esperado |

**Escolha: `qwen2.5:7b-instruct`**, apesar da latência maior — a confiabilidade do JSON estruturado
é um requisito duro (a resposta alimenta o cache de avaliações e a interface), e llama3.2:3b falhou
nesse requisito no teste direto. Isso é, em si, uma evidência concreta do trade-off qualidade vs.
portabilidade nomeado na Seção 9 do brief: modelos locais menores (mais viáveis para hardware
modesto) tendem a ter confiabilidade de instrução inferior a modelos maiores ou proprietários via
API.

Mesmo com `qwen2.5:7b-instruct`, `"format": "json"` (JSON genérico) não bastava - o modelo às vezes
devolvia um objeto solto em vez do array de avaliações esperado, especialmente para trechos muito
ruidosos (tabelas fragmentadas). A correção foi usar o suporte a *structured outputs* do Ollama
(`"format": <json-schema>`, não só a string `"json"`), passando o schema exato do array esperado -
isso eliminou o problema de forma consistente nos testes. Ver `app/llm.py`.

### Baseline sem IA
Full-text search nativo do Postgres (`tsvector`/`tsquery`, dicionário `portuguese`), no mesmo
banco — sem ferramenta extra, sem custo de infraestrutura adicional.

### Banco de dados
PostgreSQL + `pgvector`, rodando local via Docker (`pgvector/pgvector:pg16` — imagem oficial já
com a extensão compilada). Um único banco guarda documentos, chunks, embeddings, entidades
mascaradas, avaliações e feedback.

**Alternativas descartadas** (documentadas por pedido do brief): Vercel/Supabase cloud e Voyage
AI/API Claude para embeddings/avaliação — usados numa iteração anterior desta PoC e descartados
porque a arquitetura final prioriza rodar 100% local, sem dependência de nuvem de terceiro (ver
nota abaixo); Chroma/Qdrant como vector DB separado (pgvector no mesmo Postgres já resolve).

> **Nota sobre a iteração anterior:** esta pasta já teve uma sessão de desenvolvimento com uma
> arquitetura cloud (Next.js na Vercel, Supabase, embeddings via Voyage AI, avaliação via API
> Claude). Essa versão foi completamente removida no início desta sessão — nenhum desses
> componentes aparece na aplicação final. O que foi reaproveitado da sessão anterior: a amostra de
> PDFs já baixada do Querido Diário e o texto já extraído (a extração em si foi reescrita para
> remover o fallback de visão via API, que não é compatível com a arquitetura 100% local).

---

## Resultado da avaliação da hipótese

Ver [experiments/compare_recall.py](experiments/compare_recall.py) para o script completo e a
metodologia do gabarito. Resultado obtido rodando as 5 perguntas de teste contra os 70 documentos
da amostra, via API local (`qwen2.5:7b-instruct` para a avaliação por critérios):

| Caminho | Recall médio | Precisão média |
|---|---|---|
| A — keyword (baseline) | **0.00** | **0.00** |
| B — semântico + avaliação por IA | **0.48** | **0.18** |

| Pergunta | Documentos relevantes (gabarito) | Recall A | Precisão A | Recall B | Precisão B |
|---|---|---|---|---|---|
| Existe algum servidor com processo de cessão para outro órgão deferido? | 1 | 0.00 | 0.00 | 1.00 | 0.12 |
| Quais processos de auxílio por doença foram deferidos a servidores? | 2 | 0.00 | 0.00 | 0.50 | 0.10 |
| Há concessão de pensão por morte decorrente do falecimento de um servidor ou ex-servidor? | 2 | 0.00 | 0.00 | 0.00 | 0.00 |
| Quais atos nomeiam servidores para cargos em comissão (CC)? | 5 | 0.00 | 0.00 | 0.20 | 0.11 |
| Existem processos de readaptação funcional de servidores? | 7 | 0.00 | 0.00 | 0.71 | 0.56 |

**Por que o Caminho A zerou em todas as perguntas** (e por que isso não é um bug): as 5 perguntas
de teste foram escritas como perguntas em linguagem natural, do jeito que um analista realmente
digitaria — não como uma lista de palavras-chave. `websearch_to_tsquery('portuguese', ...)`
combina os termos restantes (depois de remover *stopwords*) com **E lógico implícito**. Como a
resposta relevante quase nunca contém, no mesmo chunk, todas as palavras de conteúdo da pergunta
(ex: "readaptação" aparece isolado como item de uma lista, sem a palavra "funcional" nem
"servidores" por perto no mesmo trecho), a busca por palavra-chave falha por completo — mesmo que
"readaptação" sozinha, testada isoladamente, retorne resultados corretos (verificado manualmente).
Isso é exatamente o comportamento que a hipótese da Seção 2 previa: busca por palavra-chave é
frágil a variação de formulação, e a diferença fica ainda mais nítida quando a consulta é uma
pergunta real, não uma query já otimizada por um usuário técnico.

O Caminho B acerta pelo menos um documento relevante em 4 das 5 perguntas (recall 0 só na pergunta
sobre pensão por morte/falecimento — amostra muito pequena, 2 documentos-alvo em 70, torna esse
caso particularmente sensível a ruído). A precisão média (0.18) é baixa em termos absolutos porque
o `limite` de resultados retornados (10) é bem maior que o número de documentos realmente
relevantes no gabarito (1 a 7) — em uso real, a camada de avaliação por critérios (score e
justificativa) é o que ajudaria o analista a descartar os falsos positivos entre os candidatos
recuperados, não o recall/precisão bruto do top-10.

---

## Limitações conhecidas

- **Amostra pequena**: 70 documentos de 3 municípios (Niterói, Angra dos Reis, Varre-Sai — ver
  `ingestion/source_querido_diario.py` para a justificativa da escolha), frente aos ~500 mil do
  cenário real do MPRJ. A PoC valida a abordagem, não a escala.
- **Diário oficial ≠ acervo do MPRJ**: natureza, sensibilidade e estrutura dos documentos são
  diferentes. Serve como proxy realista de "documento público, PDF variável, volume alto", não
  como equivalente exato.
- **NER local não é perfeito, em ambas as direções**: `pt_core_news_sm` erra sistematicamente
  nomes escritos inteiramente em MAIÚSCULAS (padrão comum em diários oficiais) — mitigado com uma
  heurística de regex complementar (sequências de 2+ palavras maiúsculas, filtrando termos
  institucionais), mas falsos negativos residuais são esperados e não eliminados. Na direção
  oposta, foi observado **falso positivo (over-masking)** em conteúdo tabular/de lista — em
  páginas com tabelas de inventário (ex: listas de mobiliário), o NER classificou repetidamente
  substantivos comuns como nome de pessoa, mascarando o texto quase por inteiro. Isso é um
  problema de precisão da anonimização a resolver antes de produção (ex: pular NER em regiões
  identificadas como tabela, ou usar um modelo maior), não só de recall.
- **Sem fallback de visão** na extração (Seção 4.1) — páginas com gráficos ou layouts muito
  complexos ficam marcadas como baixa confiança em vez de processadas por um modelo multimodal.
- **Gabarito do `compare_recall.py` é semiautomático**: construído com expressões regulares sobre
  o texto já extraído, com cada acerto conferido por leitura humana do trecho antes de entrar no
  gabarito — não é uma anotação manual completa e independente por múltiplos revisores.
- **Sem reprocessamento automático**: mudar a versão de critérios não reavalia os resultados já em
  cache — o mecanismo de feedback (Seção 4.5) só demonstra o registro do dado, vinculado à versão
  vigente; a reavaliação incremental por versão fica como próximo passo.
- **Controle de acesso simplificado**: seletor de perfil (com/sem clearance) sem autenticação real
  (Seção 4.7) — ver [Riscos](#riscos-e-evolução-para-produção).

---

## Riscos e evolução para produção

- **Escala para 500 mil documentos**: o volume desta PoC (70 documentos, ~1.650 páginas) não testa
  desempenho de busca vetorial nem tempo de ingestão em escala. `pgvector` com índice HNSW escala
  bem para milhões de vetores, mas a ingestão (OCR + anonimização + embeddings) precisaria rodar
  de forma incremental/distribuída, não como um script único sequencial.
- **Qualidade vs. privacidade do modelo local**: nomeado explicitamente na Seção 9 do brief e
  evidenciado nesta PoC pela comparação de modelos acima — modelos locais menores trocam
  qualidade/confiabilidade por rodar sem depender de API externa. Em produção, essa é uma decisão
  a reafirmar com dados reais de uso, não só com a amostra desta PoC.
- **Qualidade da anonimização**: taxa de falso negativo do NER em nomes maiúsculos foi observada
  diretamente durante o desenvolvimento (ver Limitações) — antes de usar com dado real do MP, essa
  taxa precisaria ser medida formalmente contra uma amostra anotada, não só observada de forma
  incidental.
- **Controle de acesso real**: produção exigiria integração com identidade institucional (SSO do
  MPRJ), papéis definidos por política de acesso formal, e log de auditoria de quem acessou qual
  dado desmascarado — nada disso existe nesta PoC, que usa um seletor de perfil sem login.
- **Infraestrutura de produção**: "rodar no computador de quem desenvolve" resolve a PoC; produção
  seria um ambiente self-hosted dentro da infraestrutura do MPRJ (servidor, não laptop), com
  backup, monitoramento e, dependendo do modelo local escolhido, hardware com GPU dedicada para
  desempenho aceitável em escala (nesta PoC, ~26s por avaliação de um único chunk contra 3
  critérios, em CPU/Metal de um MacBook, sem paralelismo).
- **Canal de entrada real**: a obtenção da amostra via API pública do Querido Diário é conveniente
  para a PoC, mas não valida que o MPRJ tem (ou terá) um canal equivalente. Por isso a ingestão
  isola essa etapa em `ingestion/source_querido_diario.py` — trocar por upload manual, integração
  com banco existente, ou API própria do MPRJ é trocar um módulo, não reescrever o pipeline.

---

## Fora de escopo desta PoC

- Reprocessamento automático após mudança de critérios
- Integração com sistema de processos via número de processo (Caminho Y do roadmap)
- Interface visual polida (fica com o Claude Design, à parte)
- Sistema de autenticação/login real (usa seletor de perfil simplificado)
- Integração com sistema de identidade institucional (SSO do MPRJ)
