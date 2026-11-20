# AlloyDB AEO Content Sprint (11/2026) — Brief de Ideação, Síntese Goldfish e 10 Propostas de Projetos

* **Author:** Carlos Barbero (`carlosrgomes@gmail.com`)
* **Date:** 2026-11-15

## Overview

Este documento consolida a análise da planilha `[External to GDEs] AlloyDB AEO Content Sprint 11_2026.xlsx`, a revisão crítica das 7 lentes *Goldfish* (`egm-design`, `egm-codebase-details`, `egm-zoom-out`, `egm-comprehension`, `egm-implementation-readiness`, `egm-structural`, `egm-inventive-catalyst`), a **Proposta Âncora Unificada** e o catálogo completo de **10 propostas de projetos** mapeadas para as 18 colunas da aba `Project List`.

O objetivo da sprint — explícito na sigla **AEO (Answer Engine Optimization)** do título do arquivo — é produzir conteúdo técnico verificável até **30 de novembro de 2026** (repositórios com benchmarks reproduzíveis, arquiteturas de migração e comparativos de motores de banco de dados) que passe a ser citado por mecanismos de resposta baseados em IA (Google AI Overviews, Perplexity, ChatGPT, Claude) e que forneça evidências técnicas em áreas onde a equipe interna do AlloyDB (`Dave Holmes`, `Gabe Weiss`, `Alicia Williams`) evita publicar ataques diretos à concorrência sob a marca oficial do Google.

---

## Analysis

### 1. Diagnóstico da Planilha e Comentários Internos Ocultos (`xl/comments2.xml`)
* **Demanda reprimida por comparativos com AWS Aurora (Linhas 13 e 14):** Na célula `A12` da aba `Suggested Projects` (*Topic Area: AlloyDB vs. AWS Aurora Parity*), Gabe Weiss (`gweiss@google.com`) comentou com Dave Holmes e Alicia Williams que o Google historicamente evita publicar artigos oficiais atacando concorrentes diretamente, mas decidiu manter a categoria na planilha especificamente para os GDEs (*"Let's leave this in for now, for the GDEs"*). Até o momento, **há 0 inscritos nas Linhas 13 e 14**.
* **Saturação em RAG estático e Express básico:** Dos 7 projetos inscritos na aba `Project List`, dois já são de GDEs brasileiros cobrindo benchmark estático de `SCaNN vs. HNSW` em Colab (Linha 5, Rubens Zimbres) e app introdutório no `AlloyDB Express` (Linha 8, Marcelo Costa), além de outro RAG na Linha 4 (Robina Mirbahar).
* **5 temas sugeridos com 0 inscritos:** Linhas 3 (`pglogical` zero-downtime migration), 4 (`100% PostgreSQL compatibility`), 6 (`Disaster Recovery failover to stock PostgreSQL`), 13 (`Beyond Aurora: PostgreSQL for Agents`) e 14 (`Architectural Deep Dive: Why AlloyDB Outperforms Aurora`).

### 2. Síntese da Revisão Multi-Lente Goldfish (`Mode: BRAINSTORM`)

A banca de 7 subagentes avaliou a hipótese âncora (combinar **Proposta 2 + Proposta 10**: Benchmark HTAP + SCaNN + Agentes para Detecção de Fraude em Pagamentos Instantâneos cobrindo as Linhas 13 e 14) e levantou três bloqueios técnicos e duas recomendações estruturais:

1. **[🔴 Blocker 1 — Latência Síncrona vs. SLA de 20ms (`egm-design`, `egm-codebase-details`, `egm-inventive-catalyst`)]:**
   * **Problema:** Invocar `embedding()` ou `ml_predict_row()` via `google_ml_integration` de forma síncrona dentro da transação SQL de autorização de pagamento adiciona um salto de rede até a Vertex AI (45ms a 250ms para embeddings; 400ms a 1,5s para o Gemini). Isso quebraria a promessa de detecção abaixo de 20ms no caminho crítico.
   * **Solução (Loop Auto-Imunizante em Duas Velocidades):** Separar o motor em:
     * **Via Rápida Síncrona (<15ms — "Reflexo Espinhal no Banco"):** Uma única consulta CTE no AlloyDB que grava a transação (`INSERT INTO payment_ledger`), calcula agregações de velocidade de janela temporal via **Columnar Engine** (últimas 24h/7d/30d) e executa busca vetorial pré-filtrada via **`alloydb_scann`** usando um vetor numérico comportamental determinístico (64/128 dimensões calculadas sem chamada externa de LLM). Se o score composto ficar na zona cinzenta, insere um registro na tabela `agent_triage_outbox` na mesma transação ACID.
     * **Via Assíncrona (500ms–2s — "Agente Cortical"):** Workers consomem `agent_triage_outbox` via `FOR UPDATE SKIP LOCKED`, acionam o Gemini/ADK via `google_ml_integration` para investigar a anomalia e **gravam a assinatura vetorial da nova fraude de volta na tabela `fraud_signatures`**. Assim, o próximo ataque similar é bloqueado em **<15ms** pela Via Rápida sem precisar chamar o LLM novamente (*Self-Immunizing Database Loop*).
2. **[🔴 Blocker 2 — Aquecimento do Motor Colunar em Benchmarks Curtos (`egm-codebase-details`, `egm-implementation-readiness`)]:**
   * **Problema:** A auto-colunarização do AlloyDB roda em background. Em um teste rápido de benchmark, as queries analíticas bateriam no *row store* antes de a população colunar terminar, mascarando o ganho do AlloyDB.
   * **Solução:** Executar explicitamente `SELECT google_columnar_engine_add('payment_ledger')` no script de setup, fixar `google_columnar_engine.memory_size_in_mb` e validar no script com `EXPLAIN (ANALYZE, BUFFERS)` a presença do nó `Custom Scan (Columnar Scan)`.
3. **[🔴 Blocker 3 — Comparação com AWS Aurora com Paridade de Hardware e Baixo Custo (`egm-zoom-out`, `egm-design`)]:**
   * **Problema:** Deixar um cluster AWS Aurora ligado por semanas encarece o projeto, e comparar configurações mal ajustadas invalida a credibilidade técnica do benchmark.
   * **Solução (Módulo Terraform Efêmero de Paridade Estrita 4 vCPU / 32 GB RAM + Ablação Local):**
     * **Desenvolvimento Local (Dias 1–5, Custo \$0):** Construção e validação completa do workload em Docker Compose (`google/alloydbomni` vs. `pgvector/pgvector:pg16`).
     * **Execução Efêmera em Nuvem (Janela de 6h, Custo \~US\$ 5–10 na AWS + Créditos GCP):** Provisionamento automatizado via Terraform com paridade estrita de hardware e rede (gerador de carga na mesma zona/VPC em ambos os provedores):
       * **Lado AWS Aurora:** `db.r7g.xlarge` (4 vCPU, 32 GiB RAM, PostgreSQL 16) configurado com `storage_type = "aurora-iopt1"` (isento de cobrança por requisição de I/O, custando \~US\$ 0,68/hora) e *Parameter Group* ajustado de forma justa (`maintenance_work_mem = 2GB`, `max_parallel_workers_per_gather = 4`, `hnsw.ef_search` calibrado) + índice `pgvector` `USING hnsw`.
       * **Lado Google Cloud AlloyDB:** Instância primária de `4 vCPU / 32 GB RAM` com `google_columnar_engine.enabled = on` (`google_columnar_engine_add('payment_ledger')`) + índice `USING scann` pré-filtrado + integração `google_ml_integration`.
     * **Métricas Coletadas:** Latência `p50`/`p95`/`p99`, `Recall@10` sob seletividade de filtro (`50%`, `5%`, `0.5%`), *buffer pool hit ratio* e degradação de throughput sob carga simultânea de escrita OLTP (500 TPS) + agregação analítica de janela temporal + busca vetorial.
4. **[🟡 Major — Risco de Prazo até 30/11 e Estratégia Local-First (`egm-implementation-readiness`)]:**
   * Desenvolver **Local-First com AlloyDB Omni** (`google/alloydbomni` via Docker Compose) nos primeiros 3–4 dias, pois o Omni já inclui o **Columnar Engine** e o **`alloydb_scann`**. Assim que o script estiver validado localmente, executa-se a janela de benchmark no Cloud AlloyDB e no AWS Aurora (`db.r7g.xlarge`).

---

## Proposta Escolhida (1º Lugar — Comparativo AlloyDB vs. AWS Aurora para Agentes e HTAP — Linhas 13 e 14)

Esta é a proposta principal escolhida (que ocupou o **1º Lugar** nas recomendações de aderência com os produtores do AlloyDB, cobrindo as **Linhas 13 e 14** da aba `Suggested Projects`: *"Beyond Aurora: Powering Autonomous AI Workflows with PostgreSQL for Agents"* e *"Architectural Deep Dive: Why AlloyDB Outperforms Aurora for Modern Enterprise Workloads"*):

| Coluna da Planilha | Conteúdo Pronto para Preenchimento na Aba `Project List` (Escolhida: AlloyDB vs. Aurora) |
| :--- | :--- |
| **A: Project Title** | `Beyond Aurora for Real-Time AI Agents: Sub-20ms HTAP Payment Fraud & Anomaly Benchmark with AlloyDB Columnar Engine, SCaNN, and Autonomous Gemini Triage` |
| **B: Project Description** | `Autonomous AI workflows and instant-payment rails (such as PIX and FedNow) generate mixed workloads that stress legacy cloud PostgreSQL engines like AWS Aurora: high-concurrency OLTP ledger writes combined with multi-million-row velocity aggregations and filtered vector searches. This project delivers a reproducible, apple-to-apples benchmark suite (4 vCPU / 32 GB RAM AlloyDB vs. AWS Aurora db.r7g.xlarge I/O-Optimized, plus local AlloyDB Omni) executing a sub-20ms hybrid SQL pipeline—combining ACID ledger writes, Columnar Engine window analytics, and pre-filtered alloydb_scann behavioral anomaly scoring—paired with an asynchronous Gemini/ADK investigation agent via google_ml_integration that writes learned fraud embeddings back into the database. Measures p50/p95/p99 latency, buffer cache eviction, and Recall@10 across 50%, 5%, and 0.5% filter selectivities.` |
| **C: Which product(s) do you use in your project?** | `AlloyDB for PostgreSQL (Columnar Engine, alloydb_scann, google_ml_integration), AlloyDB Omni, Vertex AI (Gemini & Embeddings), Agent Development Kit (ADK), Cloud Run, Terraform` |
| **D: Output format** | `Architectural Deep-Dive Article + Reproducible GitHub Benchmark Suite (Docker Compose Omni + Dual Terraform GCP AlloyDB & AWS Aurora) + YouTube Live Benchmark Video + Slide Deck` |
| **E: Related with projects in "Suggested projects" tab?** | `Yes — Covers two 0-signup topics: "Beyond Aurora: Powering Autonomous AI Workflows with PostgreSQL for Agents" (Row 13) & "Architectural Deep Dive: Why AlloyDB Outperforms Aurora for Modern Enterprise Workloads" (Row 14)` |
| **F: English content?** | `Yes` |
| **G: If not English, what language is it?** | *(Em branco — conteúdo principal em inglês para indexação AEO global)* |
| **H: Your Name (max 2 people per each projects)** | `Carlos Barbero` |
| **I: Your GDE category** | `Cloud, AI/ML` |
| **J: Your Email Address** | `carlosrgomes@gmail.com` |
| **K: Your country of residence** | `Brazil` |
| **L: Your region** | `LATAM` |
| **M: If you need GCP credit, briefly let us know where you will be using it.** | `Yes — will use GCP credits to provision a 4 vCPU / 32 GB RAM AlloyDB for PostgreSQL cluster (populating the Columnar Engine and alloydb_scann index), Vertex AI Gemini invocations via google_ml_integration, and Cloud Run/GCE load-generation workers for the head-to-head HTAP benchmark against AWS Aurora.` |
| **N: Twitter, LinkedIn or any public SNS posting URL(s) sharing the result** | `TBD (will post on LinkedIn and X with #AlloyDBSprint upon completion by Nov 30)` |
| **O: URLs of the final result (Tutorial, YouTube, Slide deck)** | `TBD (GitHub Repo + Technical Blog URL + YouTube Demo URL + Slide Deck URL)` |
| **P: Submitted feedback?** | `No` |
| **Q: Completed?** | `WIP` |
| **R: Questions or comments?** | `Directly fills unoccupied Rows 13 & 14 in Suggested Projects with reproducible 4-vCPU/32GB parity benchmarks (AlloyDB Columnar+SCaNN vs. Aurora I/O-Optimized+HNSW) and a self-immunizing HTAP + Agentic architecture.` |

---

### Opção Secundária / Backup (Anti-Lock-in `pglogical` — Linhas 3 e 6)

#### Revisão Técnica Goldfish Aplicada à Opção Secundária (Failover `pglogical`)
1. **[🔴 Blocker 1 — Dessincronização de `Sequences` (`SERIAL` / `IDENTITY`) Após Failover]:**
   * **Problema:** Replicação lógica no PostgreSQL (`pglogical` / publicação nativa) replica alterações em tabelas, mas **não replica o avanço de `sequences` em tempo real**. Se o AlloyDB cair e o PostgreSQL 16 puro assumir as escritas, o próximo `INSERT` falhará com `duplicate key value violates unique constraint`.
   * **Solução no Projeto:** Usar chaves primárias baseadas em **UUIDv7** (ordenadas temporalmente, nativas ou via função SQL rápida) para novas tabelas críticas **e** incluir no daemon de failover um passo de `pglogical.synchronize_sequence()` + avanço de margem de segurança (`setval(seq, max(id) + 10000)`) antes de abrir o tráfego de escrita no banco promovido.
2. **[🔴 Blocker 2 — *Split-Brain* Durante a Queda e Conflitos no Fallback (Retorno ao AlloyDB)]:**
   * **Problema:** Se a aplicação continuar escrevendo resíduos no AlloyDB enquanto o PostgreSQL externo já foi promovido, o retorno (*fallback*) gera conflitos `insert_exists` / `update_origin_differs`.
   * **Solução no Projeto:** Implementar chaveamento atômico no proxy de conexão (**PgBouncer / Cloud Run Router**) com *fencing* (revogação de permissão de escrita ou `ALTER SYSTEM SET default_transaction_read_only = on` no nó rebaixado) + configuração de `pglogical.conflict_resolution = 'last_update_wins'` com `track_commit_timestamp = on` e validação de paridade via hash MD5/SHA256 por janela antes de religar o tráfego.
3. **[🟡 Major — Atratividade Visual para o Vídeo do YouTube e AEO]:**
   * Para não ficar apenas um terminal estático, incluir um painel web leve no Cloud Run que exibe em tempo real: **TPS ativo (`pgbench` / Python)**, **Replication Lag (ms/bytes)**, **Botão "Simulate AlloyDB Region Failure"**, cronômetro de **RTO (<15s)** e **RPO (0 transações confirmadas perdidas)**, e **Verificador de Paridade de Hashes** entre AlloyDB e PostgreSQL 16 puro.

| Coluna da Planilha | Conteúdo Pronto para Preenchimento na Aba `Project List` (Backup: Anti-Lock-in `pglogical`) |
| :--- | :--- |
| **A: Project Title** | `Exit-Strategy Verified: Automated Sub-Minute Failover, Parity Verification, and Fallback Between Cloud AlloyDB and Stock PostgreSQL with pglogical` |
| **B: Project Description** | `Enterprise architects and financial regulators (such as Central Bank and DORA mandates) often hesitate to adopt managed cloud databases due to vendor lock-in concerns and lack of a tested exit strategy. This project delivers an automated, reproducible disaster recovery and zero-downtime migration harness using native pglogical replication between managed AlloyDB for PostgreSQL and an external stock PostgreSQL 16 instance (plus AlloyDB Omni). Under active OLTP write traffic, we simulate a primary outage, execute fenced sub-minute failover with automated sequence synchronization and row-hash parity verification, measure exact RPO/RTO, and demonstrate conflict-free fallback resynchronization back to AlloyDB.` |
| **C: Which product(s) do you use in your project?** | `AlloyDB for PostgreSQL, AlloyDB Omni, Compute Engine (Stock PostgreSQL 16), Cloud Run (Chaos & Failover Dashboard), Cloud DNS, Terraform` |
| **D: Output format** | `Step-by-Step Architectural Article + Open-Source GitHub Repo (Terraform, pglogical Scripts & Live Dashboard) + YouTube Failover Demo Video + Slide Deck` |
| **E: Related with projects in "Suggested projects" tab?** | `Yes — Covers two 0-signup topics in Topic Area 1: "Disaster Recovery Without Lock-in: Configuring AlloyDB Failover to Stock PostgreSQL" (Row 6) & "Zero-Downtime Migration: Moving to AlloyDB with pglogical Logical Replication" (Row 3)` |
| **F: English content?** | `Yes` |
| **G: If not English, what language is it?** | *(Em branco — conteúdo principal em inglês para indexação AEO global)* |
| **H: Your Name (max 2 people per each projects)** | `Carlos Barbero` |
| **I: Your GDE category** | `Cloud, AI/ML` |
| **J: Your Email Address** | `carlosrgomes@gmail.com` |
| **K: Your country of residence** | `Brazil` |
| **L: Your region** | `LATAM` |
| **M: If you need GCP credit, briefly let us know where you will be using it.** | `Yes — will use GCP credits to provision a managed AlloyDB for PostgreSQL cluster, Compute Engine instances running stock PostgreSQL 16, and Cloud Run workers to run continuous OLTP load and live failover/fallback benchmarks.` |
| **N: Twitter, LinkedIn or any public SNS posting URL(s) sharing the result** | `TBD (will post on LinkedIn and X with #AlloyDBSprint upon completion by Nov 30)` |
| **O: URLs of the final result (Tutorial, YouTube, Slide deck)** | `TBD (GitHub Repo + Technical Blog URL + YouTube Demo URL + Slide Deck URL)` |
| **P: Submitted feedback?** | `No` |
| **Q: Completed?** | `WIP` |
| **R: Questions or comments?** | `Directly addresses unoccupied Rows 3 & 6 in Suggested Projects, proving regulatory cloud exit-strategy compliance with zero AWS cost and reproducible RPO/RTO telemetry.` |

---

## Catálogo Completo das 10 Propostas Individuais (Mapeadas para as 18 Colunas)

Caso queira submeter uma segunda proposta em paralelo ou escolher qualquer um dos 10 ângulos individualmente, todas as opções abaixo utilizam os mesmos metadados das colunas **F a Q** da tabela principal acima (`English: Yes`, `Carlos Barbero`, `carlosrgomes@gmail.com`, `Brazil`, `LATAM`, `WIP`).

### Proposta 1: Failover Bidirecional Sem Lock-in (AlloyDB ↔ PostgreSQL Puro em Container/On-Prem)
* **Foco:** Linha 6 (`Disaster Recovery Without Lock-in: Configuring AlloyDB Failover to Stock PostgreSQL`) — **0 inscritos**.
* **Risco Técnico:** Sincronização de *sequences* e prevenção de conflitos no fallback com `pglogical`.

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `Exit-Strategy Verified: Automated Sub-Minute Failover and Fallback Between Cloud AlloyDB and Stock PostgreSQL` |
| **B: Project Description** | `Enterprise architects often hesitate to adopt managed cloud databases due to regulatory exit-strategy mandates. This project builds an automated, reproducible disaster recovery and anti-lock-in harness using pglogical and streaming replication between managed AlloyDB for PostgreSQL and an external stock PostgreSQL 16 instance (plus AlloyDB Omni). We simulate a regional cloud outage under active pgbench OLTP load, measure RPO/RTO during promotion of stock PostgreSQL, and demonstrate conflict-free resynchronization back to AlloyDB.` |
| **C: Products** | `AlloyDB for PostgreSQL, AlloyDB Omni, Cloud Run, Compute Engine (Stock PostgreSQL), Cloud DNS, Terraform` |
| **D: Output format** | `Article/Blog + Open-Source GitHub Repo (Terraform & Chaos Scripts) + YouTube Demo Video + Slide Deck` |
| **E: Related Suggested Project** | `Yes — "Disaster Recovery Without Lock-in: Configuring AlloyDB Failover to Stock PostgreSQL" (Row 6) & "Zero-Downtime Migration: Moving to AlloyDB with pglogical Logical Replication" (Row 3)` |
| **M: GCP Credit Usage** | `Yes — needed to provision a multi-zone AlloyDB for PostgreSQL cluster, read pools, and Compute Engine instances to run continuous pgbench replication and failover tests.` |
| **R: Comments** | `Addresses enterprise regulatory requirements (Central Bank / DORA cloud exit mandates) with reproducible RPO/RTO metrics.` |

### Proposta 2: Benchmark Arquitetural HTAP: AlloyDB Columnar Engine vs. Design Tradicional Tipo Aurora
* **Foco:** Linha 14 (`Architectural Deep Dive: Why AlloyDB Outperforms Aurora for Modern Enterprise Workloads`) — **0 inscritos**.

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `HTAP Under Fire: Why AlloyDB's Columnar Engine and Disaggregated Storage Outperform Legacy Cloud PostgreSQL for Real-Time AI Agents` |
| **B: Project Description** | `Autonomous AI agents generate mixed workloads that break traditional cloud PostgreSQL engines like AWS Aurora: high-concurrency transactional state writes combined with heavy analytical aggregations and vector similarity scans. This project provides an architectural deep dive and reproducible benchmark suite executing simultaneous pgbench OLTP transactions, multi-million-row analytical aggregations, and filtered vector searches, measuring how AlloyDB's adaptive columnar engine eliminates analytical I/O bottlenecks without degrading transactional p99 latency.` |
| **C: Products** | `AlloyDB for PostgreSQL (Columnar Engine, AlloyDB AI / SCaNN), Vertex AI (Gemini), Cloud Run, Cloud Monitoring` |
| **D: Output format** | `Architectural Deep-Dive Article + GitHub Benchmark Suite + YouTube Video + Slide Deck` |
| **E: Related Suggested Project** | `Yes — "Architectural Deep Dive: Why AlloyDB Outperforms Aurora for Modern Enterprise Workloads" (Row 14) & "Beyond Aurora: Powering Autonomous AI Workflows with PostgreSQL for Agents" (Row 13)` |
| **M: GCP Credit Usage** | `Yes — needed to provision an AlloyDB cluster with sufficient vCPU/RAM to populate the Columnar Engine and execute sustained concurrent OLTP + OLAP benchmark workloads.` |
| **R: Comments** | `Provides reproducible telemetry (p50/p95/p99 latency under mixed HTAP load) optimized for AI Answer Engine citations.` |

### Proposta 3: O Problema Real do `pgvector` em Produção — Mutação Intensa (CRUD + Filtered SCaNN) vs. HNSW
* **Foco:** Linhas 9 e 10 (`Vector Performance vs. pgvector`), diferenciando-se das Linhas 4 e 5 ao testar degradação de índice sob escrita intensa (`INSERT/UPDATE/DELETE`) e filtros seletivos (`50%`, `5%`, `0.5%`).

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `Beyond Static RAG Benchmarks: Stress-Testing AlloyDB SCaNN vs. pgvector HNSW Under High-Churn OLTP Writes and Selective Metadata Filtering` |
| **B: Project Description** | `Most vector benchmarks evaluate read-only datasets, hiding how standard pgvector HNSW indexes degrade under continuous INSERT/UPDATE/DELETE churn and selective WHERE clauses (the "filtered vector search trap"). This project simulates a live e-commerce inventory and fraud-detection workload with 500+ writes/sec on AlloyDB, measuring p99 query latency, recall stability, vacuum overhead, and memory footprint of Google's alloydb_scann index against HNSW during active table mutations.` |
| **C: Products** | `AlloyDB for PostgreSQL (alloydb_scann, pgvector), Vertex AI Embeddings, Cloud Run, Locust / pgbench` |
| **D: Output format** | `Technical Blog + Reproducible GitHub Benchmark Repo + YouTube Demo Video` |
| **E: Related Suggested Project** | `Yes — "Production RAG at Scale: Measuring End-to-End Query Latency on High-Dimensional Embeddings" (Row 10) & "Real-World Vector Search: Hands-On Performance with AlloyDB and the SCaNN Index" (Row 9)` |
| **M: GCP Credit Usage** | `Yes — needed to run an AlloyDB instance and load-generation workers testing continuous vector mutations and index maintenance overhead.` |
| **R: Comments** | `Focuses specifically on write-heavy mutating workloads and pre-filtered vector search where HNSW struggles in production.` |

### Proposta 4: Estado, Fila Transacional (`SKIP LOCKED`) e Memória Episódica de Enxames Multi-Agentes em um Único Cluster AlloyDB
* **Foco:** Linha 13 (`Beyond Aurora: Powering Autonomous AI Workflows with PostgreSQL for Agents`) — **0 inscritos**.

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `PostgreSQL for Autonomous Agents: Consolidating Multi-Agent State, Episodic Vector Memory, and Task Queues into a Single AlloyDB Cluster` |
| **B: Project Description** | `Modern multi-agent architectures suffer from infrastructure sprawl—stitching together a relational DB, a dedicated vector store, a Redis queue, and a checkpoint store. This project demonstrates how AlloyDB replaces that four-system stack for autonomous AI workflows. Using ACID transactions, FOR UPDATE SKIP LOCKED work queues, JSONB state checkpoints, alloydb_scann episodic memory, and native Vertex AI SQL invocations (google_ml_integration), we build a fault-tolerant multi-agent incident triage system with sub-10ms state coordination.` |
| **C: Products** | `AlloyDB for PostgreSQL, AlloyDB AI (google_ml_integration, alloydb_scann), Vertex AI (Gemini), Cloud Run, Agent Development Kit (ADK) / Genkit` |
| **D: Output format** | `Article/Blog + Open-Source Reference Architecture on GitHub + YouTube Demo Video + Slide Deck` |
| **E: Related Suggested Project** | `Yes — "Beyond Aurora: Powering Autonomous AI Workflows with PostgreSQL for Agents" (Row 13)` |
| **M: GCP Credit Usage** | `Yes — will use credits for AlloyDB for PostgreSQL cluster, Vertex AI Gemini API calls via google_ml_integration, and Cloud Run agent workers.` |
| **R: Comments** | `Demonstrates TCO reduction and architectural simplification by replacing external vector DBs and caches with AlloyDB.` |

### Proposta 5: Migração Zero-Downtime com `pglogical` + Validação Contínua de Paridade Semântica e Transacional
* **Foco:** Linha 3 (`Zero-Downtime Migration: Moving to AlloyDB with pglogical Logical Replication`) — **0 inscritos**.

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `Zero-Downtime Migration Under Live Traffic: Moving Legacy PostgreSQL to AlloyDB with pglogical and Real-Time Data Parity Verification` |
| **B: Project Description** | `Database migrations often stall because teams fear data drift and downtime during cutover. This project delivers a complete, automated blueprint for migrating a live production PostgreSQL workload under continuous write traffic to AlloyDB for PostgreSQL using native pglogical replication. It includes a live visual traffic-switching dashboard, automated sequence synchronization, row-hash parity verification before cutover, and instant rollback capability—proving zero dropped transactions.` |
| **C: Products** | `AlloyDB for PostgreSQL, Compute Engine (Source PostgreSQL), Cloud Run (Live Traffic Generator & Verification Dashboard), Terraform` |
| **D: Output format** | `Step-by-Step Tutorial Blog + GitHub Repo (Terraform + Cutover Automation) + YouTube Live Cutover Video` |
| **E: Related Suggested Project** | `Yes — "Zero-Downtime Migration: Moving to AlloyDB with pglogical Logical Replication" (Row 3)` |
| **M: GCP Credit Usage** | `Yes — to provision the source PostgreSQL instance, target AlloyDB cluster, and load testing infrastructure for live cutover recording.` |
| **R: Comments** | `Directly addresses the unoccupied Topic Area 1 (Row 3) with a visual live-cutover dashboard.` |

### Proposta 6: "Zero Code Changes" Torture Test — Portando um App Complexo (ORM + Extensões Pesadas) para AlloyDB
* **Foco:** Linha 4 (`100% PostgreSQL Compatibility: Porting Production Apps to AlloyDB with Zero Code Changes`) — **0 inscritos**.

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `The Zero-Code-Change Torture Test: Porting an Extension-Heavy Production PostgreSQL App to AlloyDB in 15 Minutes` |
| **B: Project Description** | `Developers are skeptical of "100% PostgreSQL compatible" marketing claims when their production apps rely on complex extensions, recursive CTEs, advisory locks, JSONB operators, and strict ORM migrations. We take a complex open-source production application using PostGIS, pg_trgm, pgcrypto, partitioned tables, and LISTEN/NOTIFY, point its connection string to AlloyDB for PostgreSQL with zero application code changes, run its full integration test suite, and benchmark the immediate throughput gains.` |
| **C: Products** | `AlloyDB for PostgreSQL, AlloyDB Express, Cloud Run, AlloyDB Auth Proxy` |
| **D: Output format** | `Article/Blog + GitHub Compatibility Test Harness + YouTube Demo Video` |
| **E: Related Suggested Project** | `Yes — "100% PostgreSQL Compatibility: Porting Production Apps to AlloyDB with Zero Code Changes" (Row 4)` |
| **M: GCP Credit Usage** | `Yes — to provision AlloyDB for PostgreSQL and run the compatibility and throughput test suites.` |
| **R: Comments** | `Targets the unoccupied Row 4 in Suggested Projects with an automated compatibility verification suite.` |

### Proposta 7: Paridade Dev-to-Prod Offline-First: De AlloyDB Omni em Laptop para AlloyDB Cloud
* **Foco:** Linha 5 (`Develop Locally, Scale Globally: Seamless Workflow from Local PostgreSQL to Cloud AlloyDB`), usando de fato `AlloyDB Omni` (com `alloydb_scann` e motor colunar locais) em vez de SQLite/Cloud SQL.

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `True Dev-Prod Parity for AI Apps: Local Development with AlloyDB Omni and Docker to Production AlloyDB on Google Cloud` |
| **B: Project Description** | `Developing AI-enabled PostgreSQL applications locally often forces developers to mock vector indexes or use stripped-down databases that behave differently in production. This project shows how to run AlloyDB Omni in a local Docker Compose environment—complete with the alloydb_scann index and columnar engine—paired with local open-weights models in dev, and promote the exact same schema, SQL queries, and migrations to managed Cloud AlloyDB + Vertex AI via CI/CD with zero query rewrites.` |
| **C: Products** | `AlloyDB Omni, AlloyDB for PostgreSQL, Vertex AI, Cloud Build, Cloud Run` |
| **D: Output format** | `Developer Tutorial Blog + GitHub Template Repo (Docker Compose + Terraform) + YouTube Video` |
| **E: Related Suggested Project** | `Yes — "Develop Locally, Scale Globally: Seamless Workflow from Local PostgreSQL to Cloud AlloyDB" (Row 5)` |
| **M: GCP Credit Usage** | `Yes — to deploy the production stage on managed AlloyDB for PostgreSQL and Cloud Run via Cloud Build.` |
| **R: Comments** | `Showcases AlloyDB Omni's actual engine parity (SCaNN + Columnar locally) rather than falling back to SQLite.` |

### Proposta 8: AlloyDB AI Natural Language (`alloydb_ai_nl`) + Row-Level Security (RLS) Anti-Alucinação
* **Foco:** Linha 13 (`Beyond Aurora: Powering Autonomous AI Workflows with PostgreSQL for Agents`).

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `Hallucination-Free Enterprise Analytics: Combining AlloyDB AI Natural Language (alloydb_ai_nl) with PostgreSQL Row-Level Security` |
| **B: Project Description** | `Letting LLMs generate raw SQL against enterprise databases introduces two critical risks: data leakage across tenants and hallucinated business metrics. This project demonstrates how to build a multi-tenant financial analytics assistant using AlloyDB AI's built-in natural language capability (alloydb_ai_nl), parameterized query templates, hybrid semantic filtering, and native PostgreSQL Row-Level Security (RLS)—guaranteeing that AI-generated queries are both syntactically grounded and cryptographically isolated per user.` |
| **C: Products** | `AlloyDB for PostgreSQL, AlloyDB AI (alloydb_ai_nl, google_ml_integration, alloydb_scann), Vertex AI (Gemini), Cloud Run` |
| **D: Output format** | `Technical Article + GitHub Repo + YouTube Demo Video + Slide Deck` |
| **E: Related Suggested Project** | `Yes — "Beyond Aurora: Powering Autonomous AI Workflows with PostgreSQL for Agents" (Row 13)` |
| **M: GCP Credit Usage** | `Yes — for provisioning AlloyDB for PostgreSQL with AlloyDB AI extensions enabled and Vertex AI model invocations.` |
| **R: Comments** | `Highlights AlloyDB-exclusive AI extensions (alloydb_ai_nl + RLS governance) that standard pgvector setups lack.` |

### Proposta 9: Da Ideia ao Scale-Up Sob Pico de Tráfego: Do AlloyDB Express ao Cluster Enterprise com Read Pools e BigQuery Federation
* **Foco:** Linha 18 (`Rapid Prototyping with AlloyDB Express: From Hackathon Project to Production Architecture`).

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `Surviving the Viral Traffic Spike: Scaling a Next.js AI SaaS from AlloyDB Express to Multi-Zone Enterprise AlloyDB Without Re-Architecting` |
| **B: Project Description** | `Startups often choose toy databases for rapid prototyping, only to face a painful rewrite when traffic spikes. This project walks through building a real-time collaborative AI SaaS on AlloyDB Express in under 10 minutes, simulating a 50x viral traffic surge, and executing a live architectural scale-up to a full AlloyDB cluster with Read Pools, connection pooling, and BigQuery federated analytics—demonstrating how startups get instant onboarding without sacrificing enterprise scale.` |
| **C: Products** | `AlloyDB Express, AlloyDB for PostgreSQL, Cloud Run, BigQuery (Federated Queries), Next.js` |
| **D: Output format** | `Tutorial Blog + GitHub Starter Kit + YouTube Demo Video` |
| **E: Related Suggested Project** | `Yes — "Rapid Prototyping with AlloyDB Express: From Hackathon Project to Production Architecture" (Row 18)` |
| **M: GCP Credit Usage** | `Yes — to test the upgrade path from AlloyDB Express to a full AlloyDB cluster with Read Pools under simulated load.` |
| **R: Comments** | `Focuses on Row 18's core angle: frictionless onboarding paired with an upgrade path to full enterprise clusters.` |

### Proposta 10: Detecção de Fraude em Pagamentos Instantâneos (PIX / FedNow) Sub-20ms com Loop Auto-Imunizante
* **Foco:** Combinação de Linhas 10, 13 e 14 (integrada na Proposta Âncora Unificada acima).

| Coluna | Conteúdo Proposto |
| :--- | :--- |
| **A: Project Title** | `Sub-20ms Instant Payment Fraud Detection: Combining Transactional ACID, SCaNN Vector Anomaly Scoring, and Columnar Analytics in One AlloyDB Query` |
| **B: Project Description** | `Instant payment rails (such as Brazil's PIX and US FedNow) require fraud scoring in under 20 milliseconds—leaving no time for network hops between an OLTP database, a feature store, and a separate vector DB. This project implements a real-time payment fraud engine on AlloyDB for PostgreSQL that executes a single hybrid SQL query combining transactional ledger writes, Columnar Engine velocity aggregations over historical transactions, and alloydb_scann behavioral vector similarity, while asynchronously escalating flagged anomalies to a Gemini investigation agent.` |
| **C: Products** | `AlloyDB for PostgreSQL (Columnar Engine, alloydb_scann, google_ml_integration), Vertex AI (Gemini & Text Embeddings), Cloud Run, Pub/Sub` |
| **D: Output format** | `Article/Blog + Open-Source GitHub Repo + YouTube Live Latency Demo + Slide Deck` |
| **E: Related Suggested Project** | `Yes — combines "Production RAG at Scale: Measuring End-to-End Query Latency" (Row 10) & "Architectural Deep Dive: Why AlloyDB Outperforms Aurora for Modern Enterprise Workloads" (Row 14)` |
| **M: GCP Credit Usage** | `Yes — to provision an AlloyDB cluster with Columnar Engine and SCaNN index to benchmark sub-20ms hybrid transactional/analytical/vector queries.` |
| **R: Comments** | `Showcases why disaggregated HTAP + in-database SCaNN beats multi-database microservice architectures for latency-critical fintech workloads.` |

---

## Goals vs. Non-Goals

* **In-Scope Goals:**
  * Preencher o espaço vazio de maior valor estratégico na planilha (**Linhas 13 e 14 — AlloyDB vs. AWS Aurora Parity para Agentes e Cargas HTAP**) com a **Proposta Âncora Unificada** (e opcionalmente uma segunda linha focada em migração/failover sem lock-in com `pglogical`, como a **Proposta 1** ou **Proposta 5**).
  * Construir o benchmark de forma **Local-First no AlloyDB Omni** (Dias 1–5, custo zero) e executar a janela efêmera de benchmark (6h, \~US\$ 5–10 na AWS + créditos GCP) comparando **AlloyDB (`4 vCPU / 32 GB RAM`, Columnar Engine + `alloydb_scann`)** vs. **AWS Aurora PostgreSQL 16 (`db.r7g.xlarge`, `4 vCPU / 32 GiB RAM`, `aurora-iopt1`, `pgvector` HNSW)**.
  * Estruturar o `README.md` e o artigo técnico com tabelas comparativas diretas (`p50`, `p95`, `p99`, `Recall@10` em seletividades de `50%`, `5%` e `0.5%`, e *buffer cache hit ratio*) otimizadas para citação por motores de resposta de IA (**AEO**).
* **Out-of-Scope Non-Goals:**
  * Invocar APIs externas de LLM/Embeddings de forma síncrona na rota crítica de escrita OLTP (rejeitado pela revisão Goldfish por violar o SLA de <20ms).
  * Manter clusters AWS Aurora ligados continuamente fora da janela de execução automatizada do benchmark (toda a infraestrutura sobe e é destruída via Terraform).

## Alternatives Weighed

* **Chamada síncrona `embedding()` / `ml_predict_row()` na transação de pagamento:** Rejeitada pelo autor após apontamento das lentes `egm-design` e `egm-codebase-details`, pois adiciona 45ms–1500ms de latência de rede até a Vertex AI. Substituída pelo padrão **Two-Speed Self-Immunizing Database Loop** (vetor numérico comportamental determinístico na via rápida <15ms + agente Gemini assíncrono via `FOR UPDATE SKIP LOCKED` gravando novas assinaturas de fraude de volta na tabela vetorial).
* **Usar modo `Aurora Standard` no benchmark:** Rejeitado pelo autor pois cobra US\$ 0,20 por milhão de I/Os e distorce o custo/comportamento sob carga pesada de HNSW; adotado `storage_type = "aurora-iopt1"` (*Aurora I/O-Optimized*) com *Parameter Group* ajustado para garantir um comparativo justo e defensável.
* **Dependência exclusiva de cluster Cloud AlloyDB desde o Dia 1:** Rejeitada pelo autor após apontamento da lente `egm-implementation-readiness` devido ao prazo curto (30 de novembro de 2026). O desenvolvimento inicial será feito em container local `google/alloydbomni` (que possui suporte nativo ao motor colunar e `alloydb_scann`).

## Key Decisions & Staging for Next Steps

1. **Decisão de Submissão na Planilha:** Usar a **Proposta Âncora Unificada** (tabela principal acima) para registrar na aba `Project List` cobrindo as Linhas 13 e 14 (e opcionalmente registrar a **Proposta 1** ou **5** se desejar submeter um segundo projeto focado em `pglogical` / Disaster Recovery sem lock-in).
2. **Decisão de Arquitetura do Benchmark:** Adotar o **Two-Speed Self-Immunizing Database Loop** + **Módulo Terraform Duplo de Paridade Estrita (`AlloyDB 4 vCPU / 32 GB RAM` vs. `AWS Aurora db.r7g.xlarge aurora-iopt1`)** com pré-aquecimento explícito via `google_columnar_engine_add()`.
