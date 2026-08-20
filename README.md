# Realce — PoC: identificação de documentos de atenção prioritária

PoC para o desafio técnico Inova/MPRJ. Testa uma hipótese específica, não constrói um produto
completo: **a combinação de busca léxica e busca semântica, seguida de avaliação por critério via
LLM local, recupera documentos relevantes com recall e precisão superiores aos de cada método de
busca isolado.**

**Backend 100% local**: banco (Postgres + pgvector via Docker), modelo de embeddings
(sentence-transformers) e LLM de avaliação (Ollama) rodam todos no computador de quem executa —
nenhuma chamada de API externa acontece durante o uso normal do sistema. O único tráfego de rede é
o download inicial dos pesos dos modelos (uma vez) e a ingestão inicial dos PDFs do Querido Diário.
Um **frontend em Next.js** (`web/`) roda publicado no Vercel — ver [Arquitetura](#arquitetura) para
como essa peça se conecta ao backend local sem abrir mão da arquitetura 100% local dele.

## Sumário

- [Arquitetura](#arquitetura)
- [Pipeline de ingestão](#pipeline-de-ingestão)
- [Setup e reprodução](#setup-e-reprodução)
- [Decisões técnicas](#decisões-técnicas)
- [Resultado da avaliação da hipótese](#resultado-da-avaliação-da-hipótese)
- [Limitações conhecidas](#limitações-conhecidas)
- [Riscos e evolução para produção](#riscos-e-evolução-para-produção)
- [Fora de escopo](#fora-de-escopo-desta-poc)
- [Créditos e stack](#créditos-e-stack)

Histórico de decisões, bugs encontrados/corrigidos e evolução entre versões: [CHANGELOG.md](CHANGELOG.md).

---

## Arquitetura

```
[Vercel: web/ (Next.js)]  --HTTPS-->  [cloudflared tunnel]  -->  [localhost:8000 (FastAPI)]
                                                                        |
                                                          Postgres local + Ollama local
```

- **Frontend** (`web/`, Next.js + React) publicado no Vercel — sidebar de casos, busca priorizada,
  painel de detalhe, dossiê, exploração livre do acervo, documento completo.
- **Backend** (`app/`, FastAPI) roda 100% local — nenhum componente de IA (embeddings, LLM) chama
  API externa. Exposto publicamente via `cloudflared tunnel` para o frontend no Vercel poder
  chamá-lo.
- **Banco**: PostgreSQL + `pgvector` via Docker, local.
- **LLM de avaliação**: Ollama (`qwen2.5:7b-instruct`), local.
- **Embeddings**: `sentence-transformers` (`BAAI/bge-m3`), local.

### Por que o backend não está no Vercel também

Funções serverless do Vercel não seguram um processo `ollama serve` rodando, e recarregar o modelo
de embeddings (~2GB) a cada cold start não é viável — Vercel e "LLM/embeddings 100% local" são
incompatíveis na mesma peça de infraestrutura. A opção escolhida foi publicar só o frontend no
Vercel, apontando para o backend local exposto por um túnel público — mantém Ollama/embeddings
genuinamente locais, ao custo de o link público só funcionar enquanto a máquina que roda o backend
estiver ligada.

**Isso é uma montagem de demonstração, não uma arquitetura de produção**:

- **A URL do túnel é efêmera** — muda a cada reinício do `cloudflared` (máquina dorme, rede cai,
  processo é encerrado), exigindo atualizar a variável de ambiente no Vercel e reimplantar.
- **O link só serve enquanto a máquina estiver ligada**, com Docker/Ollama/`uvicorn`/`cloudflared`
  rodando — não é um serviço 24/7.
- **Domínios `trycloudflare.com` podem ser bloqueados** por bloqueadores/extensões de segurança do
  navegador (heurística comum contra abuso de túneis efêmeros) — um visitante com um bloqueador
  agressivo pode ver a busca falhar silenciosamente mesmo com o backend saudável.
- **CORS liberado para qualquer origem** (`allow_origins=["*"]`) — aceitável para esta demo (dado
  público, backend só acessível via URL efêmera do túnel), não seria a configuração de produção.

### Publicar o frontend

```bash
# expor o backend local publicamente (URL muda a cada reinício)
cloudflared tunnel --url http://localhost:8000

# apontar o frontend para essa URL e publicar
cd web
vercel env add NEXT_PUBLIC_API_URL production   # cole a URL do túnel
vercel --prod
```

---

## Pipeline de ingestão

Da fonte de dados até o chunk pesquisável, o pipeline roda em etapas sequenciais
(`ingestion/*.py`), todas em CPU local:

1. **Extração em cascata** (`ingestion/extract.py`) — `pdfplumber` primeiro (rápido, preserva
   posição); OCR local (`pytesseract` + `pdf2image`, português) quando o texto nativo está ausente
   ou tem baixa qualidade. Detecção de colunas por coordenadas: antes de extrair o texto de uma
   página, analisa a distribuição horizontal dos centros das palavras
   (`page.extract_words()`) procurando um vazio largo o bastante na faixa central da página com
   volume comparável de palavras dos dois lados — havendo esse vazio, a página é tratada como duas
   colunas, cada lado reconstruído em linhas por proximidade vertical e emitido na ordem de leitura
   correta (coluna esquerda inteira antes da direita). Só roda no caminho nativo; o caminho OCR
   depende só de `--psm 3` do Tesseract para colunas.
2. **Fila de quarentena** — um documento só é excluído do índice quando falha de forma severa e
   classificável (`texto_vazio`, `texto_insuficiente`, `falha_ocr`, `encoding_invalido`,
   `pdf_corrompido`, `outro`), não quando só uma página isolada sai ruim dentro de um PDF bom.
3. **Normalização** (`ingestion/normalize.py`) — reúne palavras hifenizadas quebradas por fim de
   linha, converte quebra de linha simples em espaço preservando quebra dupla como separador de
   parágrafo, colapsa espaços/linhas em branco, marca campos de preenchimento de formulário
   (`[CAMPO]`), e remove cabeçalho/rodapé que se repete entre as páginas do mesmo documento.
4. **Anonimização** (`app/anonymize.py`) — regex para CPF, RG e telefone + NER local (`spaCy
   pt_core_news_sm`) para nomes próprios, sobre o texto inteiro do documento antes do chunking.
   Cada entidade distinta recebe um pseudônimo **estável dentro do documento**
   (`[PESSOA_A]`, `[PESSOA_B]`...) — a mesma pessoa citada duas vezes recebe o mesmo pseudônimo nas
   duas ocorrências, preservando a estrutura relacional da frase. Categorias de detecção lidas de
   `categoria_sigilo` (tabela), não hardcoded.
5. **Chunking por fronteira semântica** (`ingestion/chunk.py`) — divide por parágrafo primeiro,
   agrupa parágrafos consecutivos até aproximar ~2000 caracteres sem ultrapassar, e só desce para
   corte por sentença quando um parágrafo isolado excede o alvo (nunca corta dentro de sentença; na
   ausência de pontuação, cai para corte por palavra como último recurso). Um token `[TIPO_XXX]`
   nunca é dividido, consequência de nunca cortar fora de fronteira de espaço/parágrafo/sentença.
   Chunks abaixo de 80 caracteres úteis são descartados.
6. **Embeddings** (`app/embeddings.py`) — um vetor por chunk (`BAAI/bge-m3`, 1024 dimensões).
7. **Título e síntese** (`app/llm.py:gerar_titulo_e_sintese`) — UMA chamada ao LLM local por
   documento (não por chunk), pedindo `{"titulo": "...", "sintese": "..."}` em JSON a partir do
   início do texto normalizado/anonimizado. Em caso de falha, recai sobre um nome legível composto
   a partir de metadado (`município · tipo · data`) — nunca quebra a ingestão nem deixa o campo
   vazio.
8. **Filtragem de conteúdo padronizado** (`ingestion/dedupe.py`) — roda em duas fases sobre o
   acervo inteiro (não por documento isolado): calcula um hash do texto de cada chunk após
   generalizar pseudônimos de anonimização (para que o mesmo formulário preenchido com pessoas
   diferentes em documentos diferentes ainda seja reconhecido como o mesmo template) e marca como
   `eh_padronizado` os chunks cujo hash se repete em 5+ documentos distintos, complementado por uma
   heurística de densidade de campos de preenchimento vazios. **Marca, não exclui** — chunks
   padronizados saem do ranking de busca por padrão, mas continuam acessíveis via
   `/documentos/{id}/completo` e na exploração livre do acervo.

Métricas de quarentena e conteúdo padronizado ficam expostas (`/quarentena/stats`,
`/padronizados/stats`) — o pipeline não esconde o que não conseguiu processar ou o que filtrou.

---

## Setup e reprodução

Pré-requisitos: macOS/Linux, Python 3.12, Docker (ou Colima), [Ollama](https://ollama.com),
`tesseract` e `poppler` (binários de sistema, não instalam via `pip` — usados por `pytesseract`/
`pdf2image` no caminho de OCR da extração):

```bash
# macOS
brew install tesseract poppler
# Debian/Ubuntu
sudo apt-get install tesseract-ocr poppler-utils
```

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
#    Opção A - restaurar o dump (ver "Dump do banco" abaixo para o comando
#    exato e a ORDEM correta em relação às migrations - alguns minutos).
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

# 7. Frontend (Next.js) - em outro terminal
cd web
npm install
cp .env.local.example .env.local            # NEXT_PUBLIC_API_URL=http://localhost:8000 (ver nota abaixo)
npm run dev                                 # http://localhost:3000
```

`web/.env.local` é ignorado pelo git (contém a URL do backend, que muda entre
ambientes - local vs. deploy híbrido no Vercel) - por isso não vem versionado e
precisa ser criado a partir de `web/.env.local.example` em toda instalação nova.

Para rodar a avaliação da hipótese (o principal artefato de comparação):

```bash
python experiments/compare_modes.py
```

### Dump do banco (`db/seed/`)

Rodar o pipeline de ingestão do zero (Opção B acima) processa 30 documentos 100% em CPU local -
extração, OCR quando necessário, anonimização, chunking, embeddings e uma chamada de LLM por
documento para título/síntese - e pode levar de 1 a 2 horas. Para quem só quer ver a interface
funcionando com dado real, `db/seed/realce_seed.sql.gz` é um dump do banco já processado (30
documentos, chunks com embeddings, títulos/sínteses, entidades mascaradas, critérios e avaliações
em cache, um caso de exemplo) - restaura em segundos.

**Ordem correta em relação às migrations**: o Postgres só roda os arquivos de
`/docker-entrypoint-initdb.d` (as migrations) na **primeira inicialização de um volume vazio** —
isso acontece automaticamente e não tem como pular. Por isso a sequência é sempre:

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

### Nota sobre a porta do Postgres

`docker-compose.yml` publica o Postgres do projeto na porta **5433** do host, não 5432 — evita
conflito com uma instalação nativa de Postgres já ocupando a porta padrão em algumas máquinas. Se
sua máquina não tiver esse conflito, a porta 5433 continua funcionando normalmente — só ajuste
`DATABASE_URL` se preferir 5432.

### Nota sobre Colima (macOS) e o diretório do projeto

Se o Postgres sobe (`docker compose up -d`, `healthy`) mas qualquer consulta devolve
`relation "..." does not exist` — as migrations não rodaram, mesmo com os arquivos existindo em
`db/migrations/`. Com [Colima](https://github.com/abiosoft/colima) (comum em macOS como alternativa
ao Docker Desktop), por padrão só o diretório `$HOME` é compartilhado com a VM onde o Docker roda
(`mounts: []` em `~/.colima/default/colima.yaml`, com o comentário "Colima default behaviour: $HOME
is mounted as writable"). Se o projeto estiver clonado **fora** de `$HOME` (ex: `/tmp`, um volume
externo, um diretório de outro usuário), o bind mount `./db/migrations:/docker-entrypoint-initdb.d`
do `docker-compose.yml` aponta para um caminho que a VM não enxerga — o container sobe normalmente
(`healthy`), mas o diretório de migrations chega vazio dentro dele, e o Postgres pula a
inicialização (log mostra `ignoring /docker-entrypoint-initdb.d/*`) sem erro visível em
`docker compose up`. Solução: clonar o projeto dentro de `$HOME`, ou adicionar o caminho em
`mounts:` no `colima.yaml` e reiniciar o Colima (`colima stop && colima start`).

---

## Decisões técnicas

### Extração em cascata e quarentena
`pdfplumber` primeiro (rápido, preserva posição); OCR local (`pytesseract --psm 3` + `pdf2image`,
português) quando o texto nativo está ausente ou tem baixa qualidade (heurística: menos de 40
caracteres, ou menos de 50% de caracteres alfabéticos). **Sem fallback de visão** — fora de escopo
desta PoC por decisão explícita do brief.

O mecanismo de quarentena foi validado com um PDF corrompido sintético (bytes aleatórios),
classificado corretamente como `pdf_corrompido`; a amostra real (30 documentos) não gerou nenhum
caso de quarentena — ver [Resultado da avaliação](#resultado-da-avaliação-da-hipótese).

### Anonimização com pseudônimos consistentes
Ver [Pipeline de ingestão](#pipeline-de-ingestão) para o mecanismo. **Índice de entidades**: para
permitir buscar por um nome específico sem expor o dado a quem não tem permissão, a consulta é
resolvida contra `entidades_mascaradas.valor_original` antes da busca
(`app/search.py::_resolver_pseudonimos`) — os pseudônimos correspondentes entram na busca léxica
(via `ILIKE`) e são anexados à consulta antes do embedding (busca vetorial).

### Categorias de sigilo e nível de restrição do documento
`categoria_sigilo` populada com CPF, RG, TELEFONE (regex) e PESSOA (NER) — lista intencionalmente
incompleta; a capacidade de acomodar novas categorias sem mudar código é o que a PoC demonstra.
Cada documento carrega `nivel_restricao` (`publico`/`restrito`/`sigiloso`), atribuído por uma regra
simples nesta PoC (`ingestion/index.py::_classificar_nivel_restricao`): sem entidade sensível →
público; com nome de pessoa → restrito; com CPF/RG → sigiloso. Documento sigiloso **some** do
resultado para quem não tem clearance, em vez de aparecer mascarado (`app/access.py`).

Essa regra simples classifica **15 dos 30 documentos como sigilosos** (e os outros 15 como
restritos, nenhum público) — basta um único CPF/RG aparecer em qualquer lugar do documento (comum
em editais com lista de candidatos, tabelas de pensionistas, etc.). Consequência honesta da regra
escolhida, não um bug, mas deixa claro que uma regra binária "tem CPF → sigiloso" é grosseira demais
para uso real — o experimento (abaixo) roda com `perfil=com_clearance` para não medir
recall/precisão sobre um acervo quase inteiramente invisível. Ver
[Limitações](#limitações-conhecidas).

### Critérios como dado
`criterio` é uma tabela (chave, descrição, versão, ativo) — incluir, editar ou desativar um
critério é operação sobre dados, não deploy de código. A avaliação lê os critérios ativos e monta a
instrução dinamicamente (`app/evaluate.py`).

**Avaliação atômica**: um critério por chamada ao LLM, não todos de uma vez — mais chamadas (mais
latência total), porém mais confiável e permite atribuir feedback a um critério específico.

**Validação de citação**: `trecho_citado` retornado pelo modelo é verificado programaticamente
contra o texto do chunk (`app/evaluate.py::_citacao_verificada`) — se o trecho não existe
literalmente, a avaliação fica marcada como `citacao_verificada=false`. A taxa de citação não
verificada é reportada no experimento como evidência direta da confiabilidade do modelo local.

### Modelo de embeddings — `BAAI/bge-m3`
Multilíngue, bom desempenho em português, roda em CPU em tempo aceitável para o volume desta PoC.
Dimensão do vetor: 1024. Alternativa considerada: `intfloat/multilingual-e5-large` (também 1024
dim, mas exige prefixos `query:`/`passage:` — bge-m3 funciona diretamente).

### Modelo de LLM local — comparação e escolha
Testados dois modelos via Ollama contra o mesmo prompt de avaliação:

| Modelo | Latência por avaliação (1 critério) | Confiabilidade do JSON estruturado |
|---|---|---|
| `qwen2.5:7b-instruct` (4.7GB) | ~15-25s | Consistente |
| `llama3.2:3b` (2.0GB) | ~5s | Menos confiável para prompts com múltiplos critérios; com avaliação atômica (1 critério por chamada) melhora, mas `qwen2.5:7b-instruct` seguiu sendo a escolha por já ter latência aceitável |

**Escolha: `qwen2.5:7b-instruct`.** A confiabilidade do JSON estruturado é um requisito duro — a
resposta alimenta o cache de avaliações e a interface. Evidência concreta do trade-off qualidade
vs. portabilidade: modelos locais menores tendem a ter confiabilidade de instrução inferior a
modelos maiores.

`"format": <json-schema>` (structured outputs do Ollama, não só `"format": "json"` genérico) é
necessário — sem isso, o modelo às vezes devolve texto fora do formato esperado para trechos muito
ruidosos (tabelas fragmentadas).

### Busca híbrida via Reciprocal Rank Fusion
Os três modos (`lexico`, `vetorial`, `hibrido`) rodam contra o mesmo banco — só o híbrido é exposto
na interface (léxico e vetorial isolados continuam existindo na API e no experimento, para
comparação). O modo híbrido executa as duas buscas (top-30 cada) e funde os rankings por RRF
(`k=60`, valor de referência do artigo original) — `score = Σ 1/(k + posição)` por lista em que o
chunk aparece. RRF foi escolhido em vez de normalizar e somar os escores brutos porque `ts_rank`
(léxico) e distância de cosseno (vetorial) têm escalas e distribuições completamente diferentes;
RRF só usa a *posição* no ranking, não o valor do escore, o que dispensa essa normalização.

Depois da fusão, os resultados são reordenados pela nota da avaliação por critério
(`score_criterios`) antes de chegar à interface — a busca é "priorizada" pela avaliação de
relevância, não só pela recuperação.

### Banco de dados
PostgreSQL + `pgvector`, rodando local via Docker (`pgvector/pgvector:pg16`). Um único banco guarda
documentos, chunks, embeddings, categorias de sigilo, entidades mascaradas, critérios, avaliações,
feedback, quarentena e auditoria (ver `db/migrations/`).

**Alternativas descartadas**: APIs cloud de embeddings/avaliação — a arquitetura final prioriza
rodar 100% local; Chroma/Qdrant como vector DB separado (`pgvector` no mesmo Postgres já resolve);
um *reranker* (cross-encoder) entre a busca e o LLM — não implementado nesta PoC, mas é a evolução
mais provável desta arquitetura (ver [Fora de escopo](#fora-de-escopo-desta-poc)).

---

## Resultado da avaliação da hipótese

Ver [experiments/compare_modes.py](experiments/compare_modes.py) para o script completo e a
metodologia do gabarito (7 perguntas: 5 de descrição semântica, 2 de termo exato). Resultado obtido
rodando as perguntas contra os 30 documentos da amostra, via API local, com o pipeline de ingestão
completo (normalização, chunking semântico, detecção de colunas, filtragem de conteúdo
padronizado — ver [Pipeline de ingestão](#pipeline-de-ingestão)).

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
fora do ranking por padrão).

**A hipótese se confirma, com uma ressalva importante sobre precisão.** No agregado e no
subconjunto semântico, o híbrido supera as duas pontas em recall — exatamente o que a hipótese
previa. No subconjunto de termo exato, híbrido empata com léxico em recall (ambos 1.00), mas
**léxico tem precisão bem maior** (0.58 vs. 0.15): quando o termo é exato, a busca vetorial trazida
pela fusão RRF adiciona candidatos semanticamente relacionados mas irrelevantes ao termo específico
buscado, diluindo a precisão sem ganhar recall adicional. Isso não invalida a hipótese (o objetivo é
recall alto sem perder o léxico como opção), mas contraria a expectativa ingênua de que "híbrido é
sempre melhor nos dois eixos". Em produção, isso sugere valor em deixar o usuário optar por léxico
puro quando já sabe exatamente o termo que procura (nome, número de processo).

Histórico de números de rodadas anteriores (amostra de 70 documentos, antes das correções de
extração) e a metodologia de correção da métrica de citação: ver [CHANGELOG.md](CHANGELOG.md).

---

## Limitações conhecidas

- **Amostra pequena**: 30 documentos de 2 municípios (Niterói, Angra dos Reis — ver
  `ingestion/source_querido_diario.py`), frente aos ~500 mil do cenário real do MPRJ. A PoC valida
  a abordagem, não a escala.
- **Diário oficial ≠ acervo do MPRJ**: natureza, sensibilidade e estrutura diferem. Serve como
  proxy realista de "documento público, PDF variável, volume alto", não como equivalente exato.
- **NER local não é perfeito, em várias direções**: erra sistematicamente nomes em MAIÚSCULAS
  (mitigado com heurística de regex); tem falso positivo em conteúdo tabular (substantivos comuns
  mascarados como pessoa); e pode classificar como pessoa uma palavra real adjacente a um
  placeholder já inserido pelo próprio pipeline (mitigado invertendo a ordem de processamento — ver
  Decisões técnicas). Nenhuma dessas mitigações é uma garantia formal.
- **Resolução de nomes por substring**: `_resolver_pseudonimos` faz `ILIKE`/substring
  case-insensitive sobre toda `entidades_mascaradas` a cada busca — funciona na escala desta PoC,
  não substitui um índice de nomes tokenizado/fuzzy em escala de produção.
- **Sem fallback de visão** na extração — fora de escopo desta PoC (Seção 4.2 do brief).
- **Ordem de leitura em colunas/tabelas**: o caminho nativo detecta colunas por coordenadas e
  reconstitui a ordem de leitura correta, mas continua sendo heurística (gap horizontal + volume de
  palavras dos dois lados), não garantia formal — layouts com 3+ colunas ou tabelas muito complexas
  podem ainda fragmentar o contexto do chunk. O caminho OCR não tem detecção por coordenadas, só
  `--psm 3` do Tesseract.
- **Lista de categorias de sigilo incompleta**: só CPF, RG, telefone e nome de pessoa. Categorias
  que dependem de levantamento jurídico (ex: dado de vítima, segredo de justiça) não estão aqui —
  a tabela `categoria_sigilo` foi desenhada para acomodá-las sem mudança de código, não para já
  cobri-las.
- **Nível de restrição do documento é regra simples**: atribuído automaticamente por presença de
  categoria sensível (ver Decisões técnicas). Não reflete uma análise jurídica real de sensibilidade
  do conteúdo; em produção, precisaria de granularidade por trecho/seção, não por documento inteiro.
- **Gabarito do experimento é semiautomático**: construído com expressões regulares sobre o texto
  já extraído, cada acerto conferido por leitura humana antes de entrar no gabarito — não é uma
  anotação manual completa e independente por múltiplos revisores.
- **Sem reprocessamento automático**: mudar a versão de um critério não reavalia os resultados já
  em cache — o feedback só demonstra o registro do dado, vinculado à versão vigente.
- **Controle de acesso simplificado**: seletor de perfil sem autenticação real.

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

---

## Créditos e stack

- `pdfplumber`, `pytesseract`, `pdf2image` (extração de PDF/OCR)
- `spaCy` + modelo `pt_core_news_sm` (NER em português)
- `sentence-transformers` + modelo `BAAI/bge-m3` (embeddings)
- `Ollama` (servidor de inferência local) + modelos `qwen2.5:7b-instruct` / `llama3.2:3b`
- `FastAPI`, `Streamlit`, `psycopg`, `pgvector` (bibliotecas de infraestrutura)
- `pgvector/pgvector` (imagem Docker do Postgres com a extensão já compilada)
- API pública do [Querido Diário](https://github.com/okfn-brasil/querido-diario) (fonte de dados)
- *Reciprocal Rank Fusion* (RRF) — técnica de fusão de rankings publicada (Cormack et al., 2009),
  implementada em ~15 linhas de Python (`app/search.py`), sem biblioteca externa
- `Next.js`, `React`, `lucide-react` (ícones) — frontend (`web/`)
- `cloudflared` (Cloudflare Tunnel) — expõe o backend local publicamente para o deploy híbrido
- Design tokens (cores/tipografia/espaçamento/efeitos) do handoff de design recebido, copiados sem
  alteração de valores

Todo o código deste repositório foi escrito com apoio do Claude Code a partir do brief técnico,
revisado manualmente. Histórico de decisões de design, bugs encontrados e depuração: ver
[CHANGELOG.md](CHANGELOG.md).
