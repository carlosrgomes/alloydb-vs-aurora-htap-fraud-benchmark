# Além do Aurora para Agentes de IA em Tempo Real: Benchmark HTAP de Fraude em Pagamentos Sub-20ms com AlloyDB Columnar Engine, SCaNN e Triagem Autônoma com Gemini 4 Hydrogen

> **Idioma / Language:** **[Read in English (`README.md`)](./README.md)** | **Português do Brasil (`README-ptbr.md`)**

---

## 1. Começando do Zero: O Mistério do Café em 50 Milissegundos

Imagine que você está no balcão de uma padaria e paga o seu café fazendo um **PIX** pelo celular (ou usando o **FedNow**, o sistema de pagamentos instantâneos dos Estados Unidos).

Entre o instante em que o seu dedo toca em "Enviar" e o momento em que a maquininha apita com **"Pagamento Aprovado"**, passa menos de um vigésimo de segundo (cerca de **50 milissegundos**). Para ter uma ideia de como isso é rápido, **um único piscar de olhos seu demora 300 milissegundos**. Ou seja: o pagamento inteiro precisa acontecer seis vezes mais rápido do que uma piscada!

Dentro dessa fração de piscar de olhos, sobram apenas **15 a 20 milissegundos** para o banco de dados fazer **três trabalhos totalmente diferentes ao mesmo tempo**:

1. **Anotar a transferência no cofre com segurança total:** Gravar quem enviou, quem recebeu e o valor exato, garantindo que nenhum centavo suma ou seja duplicado mesmo que alguém puxe o fio da tomada no meio do caminho.
2. **Conferir o histórico das últimas 24 horas naquele ramo de atividade (o "corredor financeiro"):** Dar uma olhada em cerca de `40.000` transferências recentes daquele tipo de comércio (`merchant_category`, como padarias versus concessionárias de carros), somar os valores e tirar a média para descobrir se o valor atual faz sentido ou se um invasor está tentando esvaziar a conta.
3. **Caçar golpes já conhecidos em tempo real:** Quadrilhas usam robôs que deixam "impressões digitais" sutis (modelo do celular, horário da madrugada, troca de aparelhos, rede de internet). O banco precisa comparar o pagamento atual contra um catálogo de **500.000 fraudes confirmadas**, enquanto outras **50 novas fraudes por segundo** entram nesse catálogo ao mesmo tempo.

![O Que Acontece em Menos de Um Piscar de Olhos Quando Você Paga um Café no PIX](./docs/assets/illustration-bakery-pix-3-jobs-ptbr.png)

> **Não Existem Perguntas Bobas**
>
> **P: Espera aí... se o Gemini é tão inteligente, por que o banco não pergunta direto para a IA em todo PIX?**
> **R:** Porque pensar fundo demora! No nosso teste real no **Google Cloud Vertex AI** (a plataforma gerenciada de IA do Google Cloud, endpoint `locations/global`), pedir para o **Gemini 4 Hydrogen** analisar uma transação levou **`3.543,6 ms` (~3,5 segundos)**. Se o banco esperasse 3,5 segundos em cada café na padaria, a fila daria volta no quarteirão e o pagamento cairia por tempo esgotado (timeout).
>
> **P: Então qual é o problema dos bancos de dados tradicionais na nuvem, como o AWS Aurora?**
> **R:** Congestionamento de CPU e memória! Bancos tradicionais guardam todos os dados em linha numa mesma área compartilhada de RAM. Quando o banco tenta varrer 40.000 pagamentos das últimas 24 horas enquanto faz buscas vetoriais filtradas, o processador entope e o volume de pagamentos por segundo despenca.

### 1.1 A Grande Sacada: Arquitetura de Duas Velocidades (Igual ao Seu Corpo!)

Você já encostou a mão sem querer em uma panela quente? Sua mão puxa o braço para trás **antes mesmo de o seu cérebro pensar "ai, está quente!"**. Isso acontece porque seu corpo tem **duas velocidades**: um reflexo ultrarrápido na medula e um pensamento profundo no cérebro.

Construímos exatamente isso dentro do **Google Cloud AlloyDB for PostgreSQL** e testamos lado a lado contra o **AWS Aurora PostgreSQL 16.14** em máquinas idênticas de **`4 vCPU / 32 GB`** (4 núcleos virtuais de processador e 32 gigabytes de memória) com 2.500.000 linhas:

1. **Velocidade 1 (`~5,1 ms` por consulta — O Reflexo da Medula):** O próprio banco de dados faz a conta das últimas 24 horas, compara o pagamento com os 500.000 golpes conhecidos e grava o PIX em **`~5,1 ms`** (medido no `EXPLAIN ANALYZE`, o "raio-X com cronômetro" interno do PostgreSQL — bem abaixo do orçamento de 15–20 ms). Pagamento honesto passa na hora; golpe conhecido é bloqueado no ato.
2. **Velocidade 2 (`~3,5 s` em segundo plano — O Cérebro Detetive):** Quando um pagamento cai na "zona cinzenta" (não parece 100% honesto, mas também não é idêntico a nenhum golpe antigo), o banco deixa uma cópia dele em uma bandeja interna. Um robô em segundo plano pega esse caso sem atrasar nenhum cliente, pede para o **Gemini 4 Hydrogen** no Vertex AI (`locations/global`) investigar e, se o Gemini confirmar um golpe inédito, grava a "impressão digital" matemática dele de volta no banco. Segundos depois, a Velocidade 1 já bloqueia esse novo golpe sozinha — o banco literalmente se **autoimuniza**!

---

## 2. Entendendo Cada Conceito Antes de Olhar os Números

Antes de abrir as tabelas de resultados, vamos destrinchar cada peça técnica usando analogias do dia a dia — sem nenhum jargão sem explicação.

### 2.1 Milissegundos (`ms`), Volume por Segundo (`TPS`) e Escritas Seguras (`ACID`)

Um **milissegundo (`ms`)** é um segundo dividido em mil partes (`1.000 ms = 1 segundo`). Nossa meta máxima para o banco de dados responder é **abaixo de 20 ms**. Já **Transações Por Segundo (`TPS`)** mede quantas operações chegam ao banco a cada segundo. Durante todo o nosso teste, disparamos **500 operações por segundo (`500 TPS`)** sem pausa: são 450 autorizações completas de pagamento por segundo somadas a 50 novas assinaturas de fraude inseridas por segundo.

Cada transferência é gravada na tabela `payment_ledger` (o livro-razão do banco) usando **transações ACID**. A sigla **ACID** significa *Atomicidade, Consistência, Isolamento e Durabilidade*, que é a garantia de segurança "tudo ou nada" do banco de dados: ou a transferência inteira é salva até o fim sem erros, ou nada é alterado. Nos bastidores, o PostgreSQL garante isso com dois mecanismos: o **WAL (*Write-Ahead Log*)**, que é um diário sequencial de recuperação gravado em disco antes de qualquer alteração nas tabelas, e o **MVCC (*Multi-Version Concurrency Control*)**, que mantém versões separadas das linhas para que leituras e escritas ocorram ao mesmo tempo sem travar umas às outras.

### 2.2 OLTP, OLAP, HTAP e Consultas SQL em Viagem Única (`CTE`)

No mundo de bancos de dados, as tarefas costumam ser divididas em dois tipos:
- **OLTP (Processamento de Transações Online)** é como o caixa do supermercado passando um único pacote de café pelo leitor de código de barras: gravações pequenas, rápidas e individuais (`INSERT` de um PIX).
- **OLAP (Processamento Analítico Online)** é como o diretor do supermercado pedindo a média de valor de 40.000 compras feitas nas últimas 24 horas (`SUM` e `AVG` varrendo 40.000 linhas).
- **HTAP (Processamento Híbrido Transacional e Analítico)** é a capacidade de fazer o trabalho rápido do caixa (OLTP) e o cálculo pesado do diretor (OLAP) ao mesmo tempo, dentro do mesmo banco de dados, sem precisar copiar os dados para outro servidor analítico antes.

Normalmente, um aplicativo conversa com o banco de dados fazendo várias viagens de ida e volta pela rede: primeiro pede a soma das últimas 24h, espera a resposta, depois pede a busca de golpes parecidos, espera de novo e, por fim, manda salvar o PIX. Cada viagem pela rede consome milissegundos valiosos. Neste projeto, usamos uma **CTE (`Common Table Expression`, escrita com o comando `WITH ... AS`)** no arquivo [`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql) para juntar todas as 5 etapas em uma única instrução SQL. O aplicativo faz uma só viagem ao banco e já recebe o veredito final.

![OLTP, OLAP, HTAP e Viagem Única CTE Explicados no Supermercado](./docs/assets/illustration-kid-htap-cte-ptbr.png)

### 2.3 Memória RAM, Taxa de Acerto de Cache (`Shared Buffer Hit Ratio`) e o Motor Colunar do AlloyDB (`SIMD`)

Pense na **Memória RAM** como a bancada da sua cozinha, e no **Disco (Armazenamento)** como uma despensa que fica no porão, dois lances de escada abaixo. Pegar um ingrediente que já está em cima da bancada é instantâneo; descer até o porão demora muito mais. O PostgreSQL organiza os dados mais acessados em blocos de 8 kilobytes em cima dessa bancada, chamada **Shared Buffer Pool (`shared_buffers`)**.

A métrica **Shared Buffer Hit Ratio (`%`)** mostra quantas vezes, de cada 100 leituras, o dado já estava na bancada (RAM) sem precisar descer ao porão (Disco). No nosso teste real na nuvem com `32 GB` de RAM, os 2,5 milhões de linhas couberam na memória nos dois bancos (**`99,99%–100,0%`** de acerto). Mesmo assim, o AWS Aurora travou em `92,2 TPS` (`p99 = 567,21 ms`), enquanto o AlloyDB voou em `486,0 TPS` (`p99 = 95,54 ms`)!

Por quê? Pela diferença estrutural entre um **Banco em Linha (*Row-Store*)** e o **AlloyDB Columnar Engine (Motor Colunar)**:

Imagine um caderno com `40.050` linhas, onde cada linha guarda 10 informações (*ID do PIX, Pagador, Recebedor, Celular, Categoria, Data, Valor, Vetor de 64 números...*):
- **Banco em Linha (AWS Aurora):** O PostgreSQL tradicional lê **a linha inteira** só para somar a coluna *Valor*. Mesmo com tudo na RAM, o processador queima energia pulando IDs, códigos de aparelho e vetores em `40.050` linhas a cada pagamento — e, em bases maiores que a RAM, essas varreduras ainda expulsam os dados quentes do PIX da memória.
- **Motor Colunar do AlloyDB (`google_columnar_engine`):** O AlloyDB separa um **cache colunar exclusivo na RAM** (`8 GB` na nuvem; `4 GB` no Docker local) guardando *apenas* as colunas numéricas (`amount_cents`, `merchant_category`, `tx_timestamp`) empilhadas em pé, lado a lado.
- **Superpoder `SIMD`:** Com os números enfileirados, a CPU usa instruções **SIMD (*Single Instruction, Multiple Data*)** — circuitos paralelos (como **AVX-512** em chips Intel/AMD e **ARM NEON** em Apple Silicon/Graviton) que somam 8 a 16 valores em um único pulso. No `EXPLAIN ANALYZE` real em 2,5M linhas, o AlloyDB somou `40.050` linhas em **`4,24 ms`** com **`0` acessos ao `shared_buffers`**!

![Comparativo de Memória: Buffer Único em Linha vs AlloyDB Columnar Engine](./docs/assets/illustration-htap-memory-ptbr.png)

### 2.4 Vetores de 64 Dimensões (`vector(64)`) e Similaridade de Cosseno (`<=>`)

Como um banco de dados descobre se um pagamento novo tem o mesmo "jeito" de um golpe? Nós extraímos pistas comportamentais da transferência (como o valor em relação à média do usuário, o horário da madrugada, a frequência de troca de aparelho, a velocidade física de deslocamento e a categoria do recebedor) e transformamos essas pistas em uma lista de **64 números**. Essa lista numérica é chamada de **Vetor de 64 Dimensões (`vector(64)`)**.

Geometricamente, você pode imaginar essa lista de 64 números como uma seta apontando para uma direção específica no espaço. Quando comparamos a seta do pagamento atual com a seta de uma fraude confirmada usando o operador de **Distância de Cosseno (`<=>`)** do PostgreSQL, o banco mede o ângulo entre as duas setas. Convertemos essa distância em **Similaridade de Cosseno (`1.0 - distância`)**: uma nota `1,0` significa que as duas transações apontam exatamente para a mesma direção comportamental (100% parecidas), enquanto `0,0` indica vetores ortogonais (sem relação).

### 2.5 O Que É o `alloydb_scann` e Por Que o `pgvector` HNSW Sofre Quando Filtramos os Dados?

Em um banco real, você nunca procura golpes soltos no meio de todos os vetores; você combina a busca vetorial com um **Filtro SQL** (por exemplo: *"Compare este PIX apenas com fraudes da categoria de comércio nº 3 e dentro da faixa de risco `<= 5`"*).

A fração da tabela que sobrevive a esse filtro SQL é chamada de **Seletividade**:
- Na **Seletividade de 50% (`selectivity_bucket <= 500`)**, metade da tabela passa pelo filtro.
- Na **Seletividade de 5% (`selectivity_bucket <= 50`)**, apenas 1 em cada 20 linhas passa.
- Na **Seletividade de 0,5% (`selectivity_bucket <= 5`)**, apenas **1 em cada 200 linhas** passa pelo filtro.

Conferir centenas de milhares de vetores um por um demoraria demais, então os bancos usam um atalho chamado **Índice Vetorial**. É exatamente aqui que o **AWS Aurora (`pgvector` HNSW)** e o **Google Cloud AlloyDB (`alloydb_scann`)** seguem caminhos opostos:

![Busca Vetorial Filtrada: pgvector HNSW vs AlloyDB SCaNN](./docs/assets/illustration-scann-vs-hnsw-ptbr.png)

#### O Que É o `pgvector` HNSW, Como Ele Funciona e Onde Ele Quebra?

Antes de comparar os dois índices, vamos entender exatamente o que significam **`pgvector`** e **`HNSW`**:
- **`pgvector`** é a extensão aberta mais conhecida do mercado para adicionar colunas de vetores (`vector(64)`) e busca por similaridade ao PostgreSQL padrão e ao AWS Aurora.
- **`HNSW` (*Hierarchical Navigable Small World*):** Imagine o HNSW como um metrô de vários andares construído por cima dos seus vetores:
  - **Vários Andares:** No andar mais alto ficam poucas "estações expressas" (`m = 16` conexões por ponto); no térreo, cada fraude se liga às vizinhas como ruas de um bairro.
  - **Navegação Rápida:** O banco salta pelas estações expressas até chegar perto do seu pagamento e desce ao térreo para pegar os 10 vizinhos mais parecidos.
- **Por Que o HNSW Quebra sob Filtros SQL Restritivos (`0,5%`) e Escritas Intensas (`50 TPS`):**
  1. **Cegueira ao Filtro SQL (Pós-Filtragem):** A teia do HNSW só conhece ângulos — ela **não sabe** a qual `merchant_category` ou `selectivity_bucket` cada ponto pertence. No filtro de `0,5%`, **99,5% dos pontos visitados vão para o lixo**. Sua fila de candidatos (`ef_search = 40`) seca antes de juntar 10 fraudes válidas: no nosso teste real no AWS Aurora, o `Recall@10` caiu para **`67,3%` (`0,6733`)** com `p99 = 567,21 ms` (e ligar `hnsw.iterative_scan` para forçá-lo a andar ainda mais pelo grafo degrada ainda mais a latência).
  2. **Travas a `50 TPS`:** Cada nova fraude inserida obriga o HNSW a vasculhar os andares (parâmetro de construção `ef_construction = 64`), travar os vizinhos ao redor e religar até `m = 16` conexões.

#### O Que É o `alloydb_scann` e Como Ele Resolve Esses Dois Problemas na Raiz

O **`alloydb_scann`** é o índice vetorial nativo do AlloyDB baseado no **SCaNN (*Scalable Nearest Neighbors*)**, o algoritmo do Google Research usado na Pesquisa Google, no YouTube e no Google Play. Ele se apoia em três pilares:

1. **Particionamento em Árvore (`num_leaves`):** Em vez de amarrar os vetores numa teia difícil de atualizar, o `alloydb_scann` divide tudo em pastas organizadas ("folhas" ou *leaves*, como `num_leaves = 100` para 500k vetores) ao redor de centros geométricos (*centroids*) aprendidos por **agrupamento *k-means***. Uma nova fraude cai direto na sua pasta, sem religar teia nenhuma.

   ![Particionamento em Árvore no AlloyDB SCaNN: Pastas Organizadas vs Teia Emaranhada](./docs/assets/illustration-scann-tree-partitioning-ptbr.png)

2. **Quantização Vetorial Anisotrópica e Compressão `sq8`:** A *quantização anisotrópica* preserva o **ângulo** da seta (o que importa na Similaridade de Cosseno `<=>`), em vez de arredondar tudo igual. Já o `sq8` comprime cada número de 32 bits em 8 bits — vetores **4x menores**, cabendo direto no cache SIMD da CPU.

   ![Quantização Vetorial Anisotrópica e Compressão sq8 4x Menor na CPU](./docs/assets/illustration-scann-sq8-quantization-ptbr.png)

3. **Pré-Filtro por Bitmap em Estágio Único:** As colunas `merchant_category` e `selectivity_bucket` usam um índice **B-Tree** (árvore ordenada padrão do PostgreSQL). O `alloydb_scann` pega o **bitmap** da B-Tree (lista binária `1 = passa, 0 = pula`) e cruza com as pastas SCaNN *antes* de medir qualquer ângulo — ignorando 99,5% dos registros fora do filtro e entregando **`100%` de `Recall@10`** em **`0,29 ms`** no nosso teste real de 2,5M linhas.

   ![Pré-Filtro por Bitmap em Estágio Único no AlloyDB SCaNN](./docs/assets/illustration-scann-bitmap-prefilter-ptbr.png)

### 2.6 Fila Sem Travas (`FOR UPDATE SKIP LOCKED`) e `google_ml_integration`

Quando um pagamento suspeito cai na tabela `agent_triage_outbox`, vários robôs de IA em segundo plano buscam tarefas ao mesmo tempo. Cada linha guarda o dossiê forense em **`JSONB`** (JSON binário indexado do PostgreSQL). Com **`FOR UPDATE SKIP LOCKED`**, nenhum robô trava o outro: se o Worker nº 1 pegou a Linha nº 1, o Worker nº 2 pula para a Linha nº 2 em zero microssegundos. Depois, o worker chama o **Gemini 4 Hydrogen** no **Vertex AI** via **`google_ml_integration`** (`google_ml.predict_row`) ou pelo **SDK** (*kit de desenvolvimento*) Python do Google GenAI.

> **Resumo no Bolso (O Que Você Acabou de Dominar na Seção 2)**
> - **HTAP + CTE:** fazer o papel do *caixa* (gravar 1 PIX) e do *gerente* (somar 40.000 notas) ao mesmo tempo, em **uma única viagem** ao banco.
> - **Motor Colunar SIMD:** guarda só as colunas de cálculo em pé na RAM e soma de 8 a 16 números por pulso do processador, sem entupir a memória do PIX.
> - **`alloydb_scann` vs. HNSW:** o HNSW caminha às cegas e joga fora 99% dos pontos no filtro SQL; o `alloydb_scann` aplica um *bitmap* de pré-filtro antes de medir os ângulos.
> - **`FOR UPDATE SKIP LOCKED`:** fila sem engarrafamento para vários robôs de IA pegarem casos em paralelo.

---

## 3. Explicação Completa do Modelo Matemático e Vetorial Usado para Detectar Fraudes

Uma pergunta central tanto para cientistas de dados quanto para engenheiros é: **Qual é o modelo matemático exato que constrói os vetores de 64 dimensões, como as variações de ataques são calculadas e quais equações decidem se um PIX é fraude?**

Não usamos números aleatórios sem sentido. Nos arquivos [`src/benchmark/feature_generator.py`](./src/benchmark/feature_generator.py) e [`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql), a detecção de fraude é regida por **cinco etapas matemáticas explícitas** que rodam em `< 0,2 ms` na aplicação e `~5,1 ms` por consulta isolada (`< 15 ms` em produção com `8 vCPU`) dentro do banco de dados.

![Como um PIX Vira uma Seta Matemática de 64 Números](./docs/assets/illustration-math-6-to-64d-ptbr.png)

### 3.1 Passo Matemático 1: As 6 Variáveis Comportamentais de Entrada (`TransactionContext`)

Antes mesmo de o pagamento chegar ao banco, extraímos **6 sinais matemáticos fundamentais** (representados na notação matemática como $\mathbf{x} \in \mathbb{R}^6$, o que significa uma lista $\mathbf{x}$ contendo 6 números reais com casas decimais) que resumem a física e o comportamento da transferência:

1. **$x_1$ = `velocity_ratio` (Aceleração de Gasto em 24h):** Razão entre a velocidade de gasto atual da conta e o padrão histórico diário daquele cliente (Cliente normal: `0,1 a 1,2`; Ataque de fraude: `2,5 a 6,0`).
2. **$x_2 = \sin\left(2\pi \cdot \frac{\text{hora}}{24}\right)$ e $x_3 = \cos\left(2\pi \cdot \frac{\text{hora}}{24}\right)$ (Codificação Cíclica do Horário no Círculo Trigonométrico):**
   - *Por que usar Seno e Cosseno para a hora do dia?* Se usássemos apenas o número da hora (`0` a `23`), um PIX feito às `23:59` (hora 23) e outro feito às `00:01` (hora 0) pareceriam estar a **23 horas de distância** para o computador, quando na verdade aconteceram na mesma madrugada, com apenas 2 minutos de diferença. Ao projetar o relógio em um círculo usando $(\sin \theta, \cos \theta)$, garantimos que `23h` e `00h` fiquem lado a lado geometricamente.
3. **$x_4$ = `amount_zscore` (Escore-Z Estatístico do Valor em Relação ao Ramo de Comércio / "Corredor"):**
   - *O que significa "Corredor" (`corridor`)?* No jargão bancário, um **corredor de pagamento** (representado no nosso banco pela coluna `merchant_category`, de `1` a `50`) é simplesmente o **ramo de atividade ou canal comercial** por onde o dinheiro está passando: por exemplo, no ramo de **Padarias e Cafeterias**, a média normal de um PIX nas últimas 24h ($\mu_{\text{corredor}}$) é **R\$ 25,00**; já no ramo de **Concessionárias de Veículos**, a média normal é **R\$ 45.000,00**. Enviar R\$ 15.000,00 é esperado em uma concessionária, mas é uma anomalia grave em uma padaria.
   - O **Escore-Z** mede quantos desvios-padrão ($\sigma$, a variação típica dos valores ao redor da média) o valor do PIX atual está acima da média normal das últimas 24 horas ($\mu_{\text{corredor}}$) daquele ramo de comércio específico:

   $$
   Z = \frac{\text{Valor} - \mu_{\text{corredor}}}{\sigma_{\text{corredor}}}
   $$

   (Cliente normal: `-0,8 a +1,1`; Ataque de fraude: `+2,0 a +5,5` desvios-padrão acima do normal daquele ramo).

   ![Relógio no Círculo com Seno e Cosseno e Escore-Z na Padaria vs Concessionária](./docs/assets/illustration-math-clock-zscore-ptbr.png)

4. **$x_5$ = `geo_velocity_delta` (Velocidade Física de Deslocamento / "Viagem Impossível" em km/h):** Calcula a velocidade física implícita (distância dividida pelo tempo) entre a localização (IP/GPS) do último pagamento e a localização do pagamento atual (Cliente normal: `0 a 40 km/h`; Golpista usando VPN ou emulador em outro estado/país: `300 a 950 km/h`).
5. **$x_6$ = `graph_degree` (Grau de Dispersão no Grafo em 24h):** Quantos aparelhos celulares e contas recebedoras diferentes interagiram com esta conta nas últimas 24 horas (Cliente normal: `1,0 a 2,5`; Conta laranja ou invasão de conta: `4,0 a 12,0`).

### 3.2 Passo Matemático 2: Expansão Não-Linear para 64 Dimensões (`BehavioralVectorProjector.project`)

Pense neste passo como um **equalizador musical**: pegamos 6 notas simples (as 6 pistas acima) e combinamos essas notas em **64 acordes ricos**. Por quê? Porque as quadrilhas se escondem na *combinação* das pistas (como um valor absurdo *às 3h da madrugada* *somado* a uma viagem impossível). Expandindo para 64 números ($\mathbf{v} \in \mathbb{R}^{64}$), inspirados em **Random Fourier Features (RFF)** e **Expansão Polinomial de Segunda Ordem**, uma simples comparação de ângulo (`<=>`) no PostgreSQL consegue "ouvir" essas combinações sem chamar uma rede neural pesada:

1. **Posições `0..47` (48 Harmônicos de Fourier em Múltiplas Frequências):**
   Para cada uma das 4 frequências harmônicas de onda $f \in \{1, 2, 3, 4\}$, calculamos o seno e o cosseno de todos os 6 sinais escalados por $0.5 \cdot f$:

   $$
   \mathbf{h}_f = \Big[\sin(0.5 \cdot f \cdot \mathbf{x}),\; \cos(0.5 \cdot f \cdot \mathbf{x})\Big] \in \mathbb{R}^{12} \quad \Longrightarrow \quad 4 \times 12 = 48\text{ dimensões}
   $$

   *Por que isso funciona na matemática:* Pelo Teorema de Bochner, expandir números em ondas de seno e cosseno faz com que o produto escalar simples (Similaridade de Cosseno) aproxime um *Kernel Gaussiano RBF* (uma fronteira curva suave usada em Machine Learning), transformando curvas complexas em ângulos retos fáceis de medir.

   ![Equalizador de Fourier: 6 Pistas do PIX Viram 48 Ondas](./docs/assets/illustration-math-fourier-waves-ptbr.png)

2. **Posições `48..63` (16 Termos Polinomiais Cruzados e Ativações de Tangente Hiperbólica):**
   - **6 Produtos Cruzados de Segunda Ordem (`Posições 48..53`):** Multiplicam os fatores de risco dois a dois para capturar picos simultâneos:

      $$
      \text{velocity} \times \text{zscore},\quad \text{velocity} \times \text{geo},\quad \text{velocity} \times \text{degree},\quad \text{zscore} \times \text{geo},\quad \text{zscore} \times \text{degree},\quad \text{geo} \times \text{degree}
      $$

   - **6 Modulações de Horário Noturno (`Posições 54..59`):** Cruzam o seno e o cosseno da hora da transação com a velocidade de gasto, o Escore-Z do valor e a velocidade geográfica:

      $$
      \sin(\text{hora})\cdot\text{velocity},\; \cos(\text{hora})\cdot\text{velocity},\; \sin(\text{hora})\cdot\text{zscore},\; \cos(\text{hora})\cdot\text{zscore},\; \sin(\text{hora})\cdot\text{geo},\; \cos(\text{hora})\cdot\text{geo}
      $$

   - **4 Ativações Não-Lineares de Saturação (`Posições 60..63`):** Aplicam a Tangente Hiperbólica ($\tanh$, uma curva suave em "S" que comprime qualquer número extremo para a faixa `[-1.0, +1.0]`) para que um único valor gigante não domine todas as 64 dimensões:

      $$
      \tanh(\text{velocity} + \text{zscore}),\quad \tanh(\text{geo} + \text{degree}),\quad \sin(\text{velocity}\cdot\text{degree}),\quad \cos(\text{zscore}\cdot\text{geo})
      $$

   ![Cruzamentos de Pistas e o Funil Mágico tanh nas Posições 48..63](./docs/assets/illustration-math-cross-tanh-ptbr.png)

3. **Normalização L2 na Hiperesfera Unitária (Todas as Setas com Tamanho `1.0`):**
   Imagine encolher ou esticar todas as setas para que tenham **exatamente o mesmo comprimento (`1.0`)**, assim só a *direção* importa na hora de comparar. Dividimos o vetor $\mathbf{r}$ pelo seu comprimento euclidiano $\lVert \mathbf{r} \rVert_2$:

   $$
   \hat{\mathbf{v}} = \frac{\mathbf{r}}{\lVert \mathbf{r} \rVert_2} = \frac{\mathbf{r}}{\sqrt{\sum_{i=1}^{64} r_i^2}}, \quad \lVert \hat{\mathbf{v}} \rVert_2 = 1.0
   $$

   Com comprimento `1.0`, a **Similaridade de Cosseno** entre o PIX atual $\hat{\mathbf{v}}$ e uma fraude $\hat{\mathbf{s}}$ dentro do `alloydb_scann` é o próprio cosseno do ângulo $\theta$ entre eles:

   $$
   \text{Similaridade de Cosseno}(\hat{\mathbf{v}}, \hat{\mathbf{s}}) = 1.0 - d_{\cos}(\hat{\mathbf{v}}, \hat{\mathbf{s}}) = \hat{\mathbf{v}} \cdot \hat{\mathbf{s}} = \cos(\theta) \in [-1.0, 1.0]
   $$

   ![Normalização L2: Todas as Setas no Círculo de Raio 1,0](./docs/assets/illustration-math-l2-normalize-ptbr.png)

### 3.3 Passo Matemático 3: Ortogonalização de Gram-Schmidt para Simular Mutação de Fraudes (`BehavioralVectorProjector.perturb`)

Como testar se o banco pega um golpista que muda levemente o robô dele para ficar exatamente `96%` (`0.96`) ou `78%` (`0.78`) parecido com um golpe antigo $\hat{\mathbf{u}}$? Pense no desenho abaixo como usar um **esquadro de 90° e um transferidor**: primeiro achamos uma seta perpendicular ($\hat{\mathbf{u}}_{\perp}$) e depois misturamos as duas na proporção exata para girar a seta até o ângulo desejado!

![Ortogonalização de Gram-Schmidt: Como Girar Uma Seta no Ângulo Exato](./docs/assets/illustration-kid-gram-schmidt-ptbr.png)

Em vez de somar ruído aleatório imprevisível, o método `BehavioralVectorProjector.perturb(base_vec, target_cosine_similarity)` aplica a **Ortogonalização de Gram-Schmidt** em 3 passos:
1. Sorteia um vetor aleatório de 64 números $\mathbf{z} \sim \mathcal{N}(\mathbf{0}, \mathbf{I}_{64})$ (64 números sorteados de uma curva normal padrão com média `0` e desvio-padrão `1`).
2. Subtrai a projeção de $\mathbf{z}$ sobre $\hat{\mathbf{u}}$ e normaliza para obter uma seta unitária $\hat{\mathbf{u}}_{\perp}$ a exatos **90 graus** ($\hat{\mathbf{u}} \cdot \hat{\mathbf{u}}_{\perp} = 0$):

   $$
   \mathbf{p} = \mathbf{z} - (\mathbf{z} \cdot \hat{\mathbf{u}})\hat{\mathbf{u}}, \quad \hat{\mathbf{u}}_{\perp} = \frac{\mathbf{p}}{\lVert \mathbf{p} \rVert_2}
   $$

3. Mistura as duas setas usando o cosseno alvo exato $\alpha = \cos(\theta)$:

   $$
   \hat{\mathbf{v}}_{\text{mutado}} = \alpha \cdot \hat{\mathbf{u}} + \sqrt{1 - \alpha^2} \cdot \hat{\mathbf{u}}_{\perp}
   $$

   Como $\cos^2\theta + \sin^2\theta = 1$, o vetor $\hat{\mathbf{v}}_{\text{mutado}}$ mantém comprimento `1.0` e tem **Similaridade de Cosseno exata igual a $\alpha$** (com precisão de 6 casas decimais) em relação a $\hat{\mathbf{u}}$.

### 3.4 Passo Matemático 4: A Equação Híbrida de Risco e o Disjuntor Não-Linear (`hot_path_authorize.sql` e `RiskScoringPolicy`)

![Como o Banco Calcula a Nota de Risco e o Disjuntor de Emergência 0,92](./docs/assets/illustration-math-risk-breaker-ptbr.png)

No Estágio 3 (`risk_eval`) da query [`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql), o banco de dados combina as agregações de 24 horas do Motor Colunar com a similaridade das 10 fraudes mais próximas do `alloydb_scann` na nota final de risco $R \in [0.0, 1.0]$ usando uma **Equação Linear por Partes com Disjuntor Não-Linear**:

$$
R = \min\left(1.0,\; \max\Big(\mathbb{I}(S_{\text{vec}} \ge 0.92) \cdot S_{\text{vec}},\;\; 0.35 \cdot V_{24h} + 0.15 \cdot D_{24h} + 0.50 \cdot S_{\text{vec}}\Big)\right)
$$

Onde cada termo é definido por:
- **$V_{24h} = \min\left(1.0,\; \frac{\text{gasto}_{24h}}{5.000.000}\right)$ (`sum_24h_cents`, Peso `0,35`):** Atinge o teto `1.0` quando o acumulado enviado pela conta nas últimas 24 horas naquele corredor comercial chega a R\$ 50.000 (`5.000.000` centavos).
- **$D_{24h} = \min\left(1.0,\; \frac{\text{aparelhos}_{24h}}{5.0}\right)$ (`distinct_devices_24h`, Peso `0,15`):** Atinge o teto `1.0` quando 5 ou mais aparelhos distintos operam a conta em 24 horas.
- **$S_{\text{vec}} = \max_{k \in 1..10} \Big(1.0 - d_{\cos}(\mathbf{v}_{\text{tx}},\; \mathbf{v}_{\text{sig},k})\Big)$ (`1.0 - (behavioral_vec <=> sig_k)`, Peso `0,50`):** A maior similaridade de cosseno encontrada entre as 10 assinaturas de fraude pré-filtradas pelo `alloydb_scann`.
- **$\mathbb{I}(S_{\text{vec}} \ge 0.92) \cdot S_{\text{vec}}$ (O Disjuntor de Autoimunização):**
  Aqui o símbolo $\mathbb{I}(\text{condição})$ é uma **função indicadora** (uma chave liga/desliga matemática que vale `1` quando a condição dentro dos parênteses é verdadeira e `0` quando é falsa). Veja por que essa chave é essencial: imagine uma conta "laranja" recém-aberta que gastou R\$ 0 nas últimas 24 horas ($V_{24h} = 0$) e usou apenas 1 aparelho ($D_{24h} = 0.2$). Sem o disjuntor, mesmo que o vetor do PIX batesse com uma fraude confirmada em $S_{\text{vec}} = 0.95$, a soma ponderada sozinha daria $0.35(0) + 0.15(0.2) + 0.50(0.95) = 0.505$, aprovando a fraude por engano. Com a sobreposição $\max(\mathbb{I}(S_{\text{vec}} \ge 0.92) \cdot S_{\text{vec}}, \dots)$, qualquer semelhança vetorial $\ge 0.92$ ignora os pesos baixos do histórico e eleva a nota diretamente para $R = 0.95 \ge 0.85$ (`BLOCKED`).

**Limites de Decisão (`inserted_tx` CTE):**
- **$R < 0.60 \implies$ `'APPROVED'`** (Tráfego legítimo aprovado em `~5,1 ms` por consulta isolada).
- **$0.60 \le R < 0.85 \implies$ `'FLAGGED_GREY_ZONE'`** (Enfileirado na `agent_triage_outbox` para o **Gemini 4 Hydrogen**).
- **$R \ge 0.85 \implies$ `'BLOCKED'`** (Fraude conhecida ou imunizada bloqueada em `~5,1 ms` por consulta isolada).

> **Afiando o Lápis (Desafio Relâmpago de 15 Segundos!)**
>
> Imagine que um golpista abre uma **conta laranja novinha** hoje. Ele ainda gastou **R\$ 0** nas últimas 24h ($V_{24h} = 0$) e está usando **1 celular** ($D_{24h} = 1/5 = 0.2$), mas o jeito dele agir bate **95%** com uma fraude que o Gemini descobriu ontem ($S_{\text{vec}} = 0.95$).
> 1. Qual seria a nota **sem** o disjuntor de `0,92`?
> 2. Qual é a nota **com** o disjuntor de `0,92`?
>
> <details>
> <summary><strong>Clique aqui para ver a resposta</strong></summary>
>
> 1. **Sem o disjuntor:** $0.35(0) + 0.15(0.2) + 0.50(0.95) = 0 + 0.03 + 0.475 = \mathbf{0.505}$. Como `0,505 < 0,60`, o banco **aprovaria o golpe por engano**!
> 2. **Com o disjuntor ($\ge 0.92$):** como $0.95 \ge 0.92$, o disjuntor dispara e eleva a nota direto para **$\mathbf{0.95}$ (`BLOCKED`)**, bloqueando a conta laranja na primeira tentativa!
>
> </details>

### 3.5 Passo Matemático 5: Como o Gemini 4 Hydrogen Avalia os Casos Suspeitos e Imuniza o Banco

![Como o Gemini Investiga Casos Suspeitos e Vacina o Banco em 3 Passos](./docs/assets/illustration-math-gemini-vaccine-ptbr.png)

Quando um pagamento cai na zona cinzenta ($0.60 \le R < 0.85$), como funciona a avaliação do **Gemini 4 Hydrogen (`gemini-4-hydrogen`)** sem travar o banco de dados?

No arquivo [`src/agent/triage_worker.py`](./src/agent/triage_worker.py), a avaliação roda em **Três Fases Sem Bloqueio (Lock-Free)**:

#### Fase 1 (Transação de `< 2 ms` no Banco): Reserva Sem Travas (`FOR UPDATE SKIP LOCKED`)

O método `OutboxRepository.claim_pending_batch` busca até 5 registros `PENDING` na tabela `agent_triage_outbox`, altera o status para `'PROCESSING'` e **executa `commit` na transação imediatamente**. Como a transação no banco é encerrada antes da chamada ao modelo de IA, **nenhuma linha fica bloqueada** durante os **`~3,5 segundos` (`3.543,6 ms`)** da inferência do Gemini (e, se um worker falhar, `reclaim_stale_leases` devolve registros presos há mais de 30 segundos para `'PENDING'`).

#### Fase 2 (Inferência Vertex AI Sem Estado — Medido ao Vivo em `~3,5 s`): O Prompt Forense e o Raciocínio em JSON Estruturado

O método `FraudInferenceStrategy.build_prompt` constrói um dossiê forense a partir dos 12 campos do `JSONB` gravados no instante do PIX:

```text
You are an autonomous instant-payment fraud triage agent analyzing a grey-zone PIX/FedNow transaction (tx_id=...).
- Sender Account: 48291
- Merchant Category: 14 (Selectivity Bucket: 5)
- Transaction Amount (cents): 850000 vs 24h Corridor Avg: 12500.00
- Account 24h Velocity: 2450000 cents across 9 txs and 4 distinct devices
- Closest Known Fraud Signature Cosine Similarity: 0.8120
- Synchronous Composite Risk Score: 0.7410

Return strict JSON with keys: verdict ('CONFIRMED_FRAUD' or 'FALSE_POSITIVE'),
confidence_score (float 0.0..1.0), and rationale (concise forensic explanation).
```

O worker invoca o **Gemini 4 Hydrogen** no endpoint **`locations/global`** do Vertex AI (`https://aiplatform.googleapis.com/v1/projects/<PROJECT_ID>/locations/global/publishers/google/models/gemini-4-hydrogen:generateContent`) com **`temperature = 0.0`** (raciocínio analítico determinístico) e **`response_mime_type = "application/json"`**, utilizando:
- **SQL Nativo Dentro do Banco (`InDatabaseVertexAIStrategy`):**
  ```sql
  CALL google_ml.create_model(
      model_id => 'gemini-4-hydrogen',
      model_request_url => 'https://aiplatform.googleapis.com/v1/projects/<PROJECT_ID>/locations/global/publishers/google/models/gemini-4-hydrogen:generateContent',
      model_provider => 'google',
      model_type => 'generic',
      model_auth_type => 'alloydb_service_agent_iam'
  );
  SELECT google_ml.predict_row(model_id => 'gemini-4-hydrogen', request_body => $json_payload::json);
  ```
- **SDK Python Google GenAI (`GenAISDKStrategy`):** `client.models.generate_content(model="gemini-4-hydrogen", ...)`

**O Que o Gemini 4 Hydrogen Avalia e Devolve (`AgentAssessment`):**
O Gemini correlaciona três sinais cruzados que, isoladamente, haviam ficado abaixo de `0,85`:
1. **Razão de Discrepância no Corredor (`amount_cents / corridor_avg_cents`):** $\frac{850.000}{12.500} = 68\times$ acima do gasto médio daquele ramo comercial nas últimas 24 horas;
2. **Velocidade de Drenagem da Conta e Troca de Aparelhos:** `9` transferências operando a mesma conta a partir de `4` aparelhos de hardware diferentes (`distinct_devices_24h = 4`);
3. **Mutação de Script Vetorial Abaixo do Limiar:** Uma similaridade de cosseno de `0,8120` mostra que o comportamento da transação é 81,2% semelhante a uma quadrilha catalogada, indicando que o atacante alterou parâmetros do script para passar abaixo do disjuntor automático de `0,92`.

Na nossa chamada real ao vivo no Vertex AI (`3.543,6 ms`), o **Gemini 4 Hydrogen** devolveu exatamente este JSON estrito, validado pelo modelo `AgentAssessment` da biblioteca **Pydantic** (validador automático de formatos de dados em Python):

```json
{
  "verdict": "CONFIRMED_FRAUD",
  "confidence_score": 0.88,
  "rationale": "Transaction amount (850000 cents) is 68x the 24h corridor average, occurring amid extreme 24h velocity (2450000 cents across 9 transactions) spanning 4 distinct devices indicative of account takeover or mule activity, reinforced by high cosine similarity (0.812) to known fraud signatures and an elevated composite risk score (0.741)."
}
```

*Em bom português:* *"O valor da transação (850.000 centavos) é 68x maior que a média de 24h do ramo, acontecendo em meio a uma correria extrema (9 transações em 4 celulares diferentes, sinal clássico de invasão ou conta laranja), reforçado por 81,2% de semelhança com fraudes conhecidas e nota de risco elevada (0,741)."*

#### Fase 3 (Transação de `< 5 ms` no Banco): Deduplicação Vetorial e Autoimunização

Quando `verdict == 'CONFIRMED_FRAUD'` e `confidence_score >= 0.85`, o método `OutboxRepository.complete_triage_and_immunize` marca o item da fila como `'COMPLETED'` e insere o vetor de 64 dimensões (`behavioral_vec`) na tabela `fraud_signatures` (`source = 'GEMINI_AGENT_IMMUNIZED'`) com uma **proteção automática de deduplicação por cosseno (`>= 0,98`)**:

```sql
INSERT INTO fraud_signatures (
    signature_id, merchant_category, selectivity_bucket,
    source, behavioral_vec, pattern_description
)
SELECT $1::UUID, $2, $3, 'GEMINI_AGENT_IMMUNIZED', $4::vector(64), $5
WHERE NOT EXISTS (
    SELECT 1 FROM fraud_signatures
    WHERE merchant_category = $2
      AND 1.0 - (behavioral_vec <=> $4::vector(64)) >= 0.98
);
```

Essa verificação `WHERE NOT EXISTS` garante que o índice `alloydb_scann` nunca seja poluído com vetores duplicados. Na tentativa seguinte daquela quadrilha meio segundo depois, $S_{\text{vec}} \to 1.00 \ge 0.92$, acionando o disjuntor do Passo 4 em `~5,1 ms` por consulta isolada sem precisar chamar o Gemini novamente.

> **Não Existem Perguntas Bobas**
>
> **P: Por que transformar 6 pistas em 64 números se 6 números já parecem suficientes?**
> **R:** Porque golpes se escondem na *combinação* das pistas (por exemplo, gastar muito *às 3h da manhã* *somado* a uma viagem impossível de 900 km/h). Quando expandimos para 64 dimensões com ondas de seno/cosseno e produtos cruzados, até uma simples comparação de ângulo no banco de dados consegue enxergar essas combinações complexas sem chamar uma rede neural pesada!
>
> **P: E o banco fica travado esperando os ~3,5 segundos do Gemini?**
> **R:** Nunca! Na Fase 1 (`< 2 ms`), o worker marca a linha como `'PROCESSING'` e fecha a transação no banco *antes* de falar com o Gemini. Enquanto o Gemini pensa na nuvem, nenhuma linha fica presa e o fluxo de PIX segue livre.

> **Resumo no Bolso (A Matemática da Seção 3 em 3 Linhas)**
> - **6 pistas → 64 números (tamanho `1.0`):** transforma comportamento em uma seta direcional pronta para medir ângulos no banco.
> - **Disjuntor `0,92`:** impede que uma conta laranja novinha escape por ter histórico zerado.
> - **Vacina do Gemini (`~3,5 s` offline):** investiga a zona cinzenta sem travar o banco e grava o novo golpe com deduplicação `>= 0,98`.

---

## 4. O Que É Analisado no Benchmark? (`p50`, `p95`, `p99`, `Recall@10` e `Buffer Hit Ratio`)

Ao comparar o **Google Cloud AlloyDB** com o **AWS Aurora PostgreSQL 16**, nunca usamos a "média simples" de tempo de resposta. A média esconde picos de lentidão: se 99 pessoas pagam seu café em 5 milissegundos e a 100ª pessoa fica travada por 5 segundos inteiros, a média parece baixa, mas os clientes enfrentam quedas por tempo esgotado.

Por isso, o nosso executor de benchmark ([`src/benchmark/runner.py`](./src/benchmark/runner.py)) coleta e analisa cinco indicadores concretos em cada bateria:

![O Que São p50, p95, p99 e Recall@10 Explicado Sem Mistério](./docs/assets/illustration-kid-p50-p99-recall-ptbr.png)

1. **Latência `p50` (O Cliente Mediano):** Imagine colocar 100 pagamentos em fila, do mais rápido (nº 1) até o mais demorado (nº 100). **O `p50` é o tempo exato do pagamento nº 50, bem no meio da fila.** Quando `p50 = 5,60 ms` (AlloyDB Omni local) ou `26,71 ms` (teste de estresse na nuvem em 4 vCPUs a 486 TPS), metade de todos os pagamentos terminou nesse tempo ou menos.
2. **Latência `p95` (Estabilidade em Horário de Pico):** **O `p95` é o pagamento nº 95 dessa fila de 100.** Quando `p95 = 9,09 ms` (AlloyDB Omni local) ou `73,99 ms` (teste de estresse na nuvem em 4 vCPUs), 95 de cada 100 pagamentos terminaram nesse tempo ou menos.
3. **Latência `p99` (O Pior 1% / Latência de Cauda Exigida pelo Banco Central):** **O `p99` é o pagamento nº 99 de 100**, representando o 1% mais lento quando o banco está sob carga máxima de `500 TPS`. Redes de pagamento instantâneo como o PIX cobram metas rigorosas sobre o `p99`.
4. **`Recall@10` (Precisão na Captura de Golpes):** Após o teste de carga, o avaliador roda as buscas vetoriais filtradas duas vezes: uma vez usando o índice vetorial (`alloydb_scann` ou `pgvector` HNSW) e outra vez desligando os índices (`SET LOCAL enable_indexscan = off`) para o PostgreSQL conferir todas as linhas e encontrar as **10 fraudes verdadeiramente mais próximas**. O `Recall@10` mede a sobreposição entre as duas listas: **`1,00` significa que o índice encontrou 10 de cada 10 golpes reais**, enquanto **`0,67` significa que o índice perdeu cerca de 1 em cada 3 golpes reais**.
5. **`Shared Buffer Hit Ratio` (Eficiência de Memória RAM):** Medido direto do catálogo `pg_stat_database` (`blks_hit` contra `blks_read`), mostrando qual percentual das leituras de página veio direto da memória RAM sem tocar no disco.

> **Resumo no Bolso (Como Ler Qualquer Benchmark Como Um Craque)**
> - **Esqueça a média simples:** olhe sempre para o **`p99`** — é ele quem mostra se o 1% mais azarado dos clientes está sofrendo na fila do caixa.
> - **Velocidade sem precisão não serve:** de nada adianta responder em 5 ms se o **`Recall@10`** for `0,67` e deixar 1 em cada 3 golpes passar pela rede!

---

## 5. Qual Banco Ficou Melhor e Por Quê?

Para garantir uma disputa 100% justa, os dois clusters gerenciados rodaram na **mesma versão (`PostgreSQL 16.14`)** e no **mesmo porte de hardware (`4 vCPU / 32 GB` de RAM — `32 GiB` na notação binária da AWS)**.

Ambos receberam exatamente os mesmos **2.500.000 registros** (`2.000.000` pagamentos na `payment_ledger` + `500.000` vetores 64-D na `fraud_signatures`), estressados por uma máquina de `4 vCPU` na mesma rede privada (`c3-standard-4` no GCP e `c7g.xlarge` na AWS) mirando **`500 TPS`** (`--duration 20` nas baterias arquivadas em nuvem e `--duration 10` no Docker local; 90% autorizações HTAP + 10% inserções ao vivo de novas fraudes).

![Comparativo Arquitetural: AlloyDB vs AWS Aurora](./docs/assets/comparativo-arquitetural-alloydb-vs-aurora-ptbr.png)

Para provar *qual tecnologia específica* gera cada ganho, executamos um **Estudo de Ablação** ao vivo (ligando um recurso de cada vez) em **4 configurações progressivas** nas três larguras de filtro (`50%`, `5%` e `0,5%`). Todos os 12 JSONs reais da nuvem estão arquivados em [`results/gcp_live/`](./results/gcp_live) e [`results/aws_live/`](./results/aws_live), consolidados em [`results/benchmark_summary.md`](./results/benchmark_summary.md) e [`results/raw_telemetry.csv`](./results/raw_telemetry.csv).

### 5.1 Resultados Reais na Nuvem no Cenário Mais Rigoroso (Filtro de `0,5%`, 2,5M Linhas, Alvo 500 TPS)

| Configuração Real na Nuvem (`PostgreSQL 16.14`) | Especificação da Máquina | Build do Índice (500k vetores) | TPS Atingido (Meta: 500) | `p50` (Mediana) | `p95` (95% do tráfego) | `p99` (Cauda) | `Recall@10` (Precisão Antifraude) | Buffer Hit Ratio | O Que Aconteceu na Execução Real em Nuvem? |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1. AWS Aurora PG 16.14** (`aurora-iopt1` + `pgvector` HNSW) | `db.r7g.xlarge` (4 vCPU / 32 GiB) | 97 s | 92,2 TPS | 377,93 ms | 510,10 ms | **567,21 ms** | **0,6733** (67,3%) | 100,0% | **CPU saturou em 18% do alvo:** varreduras em linha + pós-filtro do HNSW perdem 32,7% das fraudes reais. |
| **2. GCP AlloyDB (Só Linha)** (Colunar Desligado + `pgvector` HNSW) | `4 vCPU / 32 GB` | ~9 min | 53,9 TPS | 667,27 ms | 918,37 ms | **1.058,39 ms** | **0,6733** (67,3%) | 100,0% | Sem Motor Colunar e sem SCaNN, o AlloyDB esbarra no mesmo gargalo de Row-Store e HNSW. |
| **3. GCP AlloyDB + Motor Colunar** (Colunar Ligado + `pgvector` HNSW) | `4 vCPU / 32 GB` | ~9 min | 466,5 TPS | 32,70 ms | 95,26 ms | **133,39 ms** | **0,6733** (67,3%) | 100,0% | **Motor Colunar multiplica TPS em 8,6x e derruba `p99` em 7,9x**, mas o HNSW segue perdendo 32,7% das fraudes. |
| **4. GCP AlloyDB + Colunar + `alloydb_scann` (Vencedor)** | `4 vCPU / 32 GB` | **7 s** | **486,0 TPS** | **26,71 ms** | **73,99 ms** | **95,54 ms** | **1,0000** (100%) | 100,0% | **5,3x mais TPS, `p50` 14,1x menor e `p99` 5,9x menor que o Aurora** com **100% de precisão antifraude**. |

**Raio-X rápido desses números:**
- **Consulta isolada (`EXPLAIN ANALYZE` em 2,5M linhas):** **`~5,1 ms`** ponta a ponta (`4,24 ms` no Scan Colunar SIMD com `0` acessos ao `shared_buffers` + `0,11 ms` na velocidade do pagador + `0,29 ms` no pré-filtro `alloydb_scann` + `0,4 ms` na gravação ACID).
- **Dimensionamento para `p99 < 20 ms`:** Sob `500 TPS` contínuos em `4 vCPU`, a fila de CPU gera `p99 = 95,54 ms` no AlloyDB (vs. `567,21 ms` no Aurora). Em produção, `8 vCPU` (ou `200 TPS` em `4 vCPU`) mantém `p99 < 20 ms`.
- **Docker Compose local (`225k` linhas, [`results/docker_live/`](./results/docker_live)):** AlloyDB Omni entregou **`p99 = 9,49–13,63 ms`** (`100%` Recall@10) contra **`p99 = 33,21–37,21 ms`** (`67,33–68,67%` Recall@10) no PostgreSQL 16 + `pgvector` HNSW.

### 5.2 Por Que a Configuração nº 4 (`AlloyDB + Motor Colunar + alloydb_scann`) Venceu em Todas as Métricas

1. **Mediana `p50` 14,1x menor (`26,71 ms` vs. `377,93 ms`) e `p99` 5,9x menor (`95,54 ms` vs. `567,21 ms`):** Comparando a Linha nº 2 (`1.058,39 ms`) com a Linha nº 3 (`133,39 ms`), isolamos o **Motor Colunar**: empurrar as `40.050` linhas da janela de 24h para stripes SIMD cortou o `p99` em **7,9x** e multiplicou o throughput em **8,6x**.
2. **100,0% de Precisão Antifraude contra 67,33% no AWS Aurora (`Recall@10`):** Comparando a Linha nº 3 (`0,6733`) com a Linha nº 4 (`1,0000`), isolamos o **`alloydb_scann`**: o pré-filtro por bitmap rodou em **`0,29 ms`** (`Num Filtered: 0`), derrubou o `p99` para **`95,54 ms`** e resgatou 100% das fraudes.
3. **Throughput 5,3x maior e Build de Índice 13,9x mais rápido:** Mesmo usando o armazenamento mais veloz da AWS (**`aurora-iopt1`**), o Aurora estacionou em **92,2 TPS** varrendo páginas de *heap* (a área principal onde o PostgreSQL guarda linhas) e disputando travas no HNSW. O índice `alloydb_scann` (`sq8`) de 500k vetores levou **`7 s`** para construir contra **`97 s`** no HNSW do Aurora (`134,67 s` vs. `252,84 s` de carga total).

### 5.3 Matriz Real Completa na Nuvem nos 3 Níveis de Seletividade (`50%`, `5%` e `0,5%` em 2,5M Linhas)

Observe como todas as três configurações baseadas em `pgvector` HNSW (`aurora_io_hnsw`, `alloydb_row_hnsw`, `alloydb_col_hnsw`) ficam presas em torno de **`67%–71%` de `Recall@10`** em todas as faixas filtradas, enquanto o **`alloydb_col_scann` entrega `93,3%–100,0%` de `Recall@10` e fica *mais rápido* conforme o filtro SQL fica mais restritivo** (o `p99` cai de `212,31 ms` em `50%` para `95,54 ms` em `0,5%` porque o bitmap de pré-filtro reduz o conjunto de candidatos):

| Modo (`PostgreSQL 16.14`, `4 vCPU / 32 GB`) | Seletividade do Filtro | Predicado SQL (`selectivity_bucket`) | TPS Atingido | `p50` (ms) | `p95` (ms) | `p99` (ms) | `Recall@10` (Precisão) | Scan Colunar | Índice Vetorial |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `aurora_io_hnsw` (AWS Aurora I/O-Opt) | `50,0%` (Amplo) | `<= 500` | 92,5 | 378,72 | 508,00 | 554,21 | 0,7000 (70,0%) | `false` | `pgvector_hnsw` |
| `aurora_io_hnsw` (AWS Aurora I/O-Opt) | `5,0%` (Médio) | `<= 50` | 92,7 | 375,61 | 508,32 | 561,66 | 0,6867 (68,7%) | `false` | `pgvector_hnsw` |
| `aurora_io_hnsw` (AWS Aurora I/O-Opt) | `0,5%` (Restrito) | `<= 5` | 92,2 | 377,93 | 510,10 | 567,21 | 0,6733 (67,3%) | `false` | `pgvector_hnsw` |
| `alloydb_row_hnsw` (GCP Só Linha) | `50,0%` (Amplo) | `<= 500` | 56,7 | 614,14 | 828,15 | 927,20 | 0,7067 (70,7%) | `false` | `pgvector_hnsw` |
| `alloydb_row_hnsw` (GCP Só Linha) | `5,0%` (Médio) | `<= 50` | 51,6 | 692,19 | 1.003,10 | 1.114,98 | 0,7000 (70,0%) | `false` | `pgvector_hnsw` |
| `alloydb_row_hnsw` (GCP Só Linha) | `0,5%` (Restrito) | `<= 5` | 53,9 | 667,27 | 918,37 | 1.058,39 | 0,6733 (67,3%) | `false` | `pgvector_hnsw` |
| `alloydb_col_hnsw` (GCP Colunar + HNSW) | `50,0%` (Amplo) | `<= 500` | 253,9 | 38,89 | 692,51 | 946,02 | 0,7133 (71,3%) | `true` | `pgvector_hnsw` |
| `alloydb_col_hnsw` (GCP Colunar + HNSW) | `5,0%` (Médio) | `<= 50` | 485,0 | 27,79 | 75,39 | 96,80 | 0,6800 (68,0%) | `true` | `pgvector_hnsw` |
| `alloydb_col_hnsw` (GCP Colunar + HNSW) | `0,5%` (Restrito) | `<= 5` | 466,5 | 32,70 | 95,26 | 133,39 | 0,6733 (67,3%) | `true` | `pgvector_hnsw` |
| **`alloydb_col_scann` (Vencedor GCP)** | **`50,0%` (Amplo)** | **`<= 500`** | **317,2** | **91,19** | **177,74** | **212,31** | **0,9333 (93,3%)** | **`true`** | **`alloydb_scann`** |
| **`alloydb_col_scann` (Vencedor GCP)** | **`5,0%` (Médio)** | **`<= 50`** | **470,2** | **37,94** | **88,29** | **120,03** | **1,0000 (100%)** | **`true`** | **`alloydb_scann`** |
| **`alloydb_col_scann` (Vencedor GCP)** | **`0,5%` (Restrito)** | **`<= 5`** | **486,0** | **26,71** | **73,99** | **95,54** | **1,0000 (100%)** | **`true`** | **`alloydb_scann`** |

> **Não Existem Perguntas Bobas**
>
> **P: Espera aí! Se uma consulta isolada no AlloyDB levou `~5,1 ms`, por que o `p99` na tabela de nuvem foi `95,54 ms`?**
> **R:** Pense em um caixa de supermercado que passa suas compras em **5 segundos**. Se chegar 1 cliente de cada vez, você sai em 5 segundos! Mas se **32 pessoas** correrem para o mesmo caixa ao mesmo tempo (nosso teste de estresse de `500 TPS` em apenas `4 vCPU`), o último da fila vai esperar o pessoal da frente passar. O incrível é que, nessa mesma fila de 4 vCPUs, o AlloyDB aguentou **486 TPS (`p99 = 95,54 ms`)**, enquanto o AWS Aurora engasgou já em **92,2 TPS (`p99 = 567,21 ms`)**! Com `8 vCPU` em produção (ou `200 TPS` em `4 vCPU`), a fila desaparece e o `p99` volta a ficar abaixo de `20 ms`.
>
> **P: Como assim o `alloydb_scann` ficou *mais rápido* quando o filtro ficou mais rígido (`212,31 ms` em `50%` → `95,54 ms` em `0,5%`)?**
> **R:** Porque o pré-filtro por *bitmap* corta a pilha de trabalho *antes* de medir os ângulos! É como procurar uma figurinha rara: se alguém primeiro separa só as 2.500 figurinhas brilhantes (`0,5%`) em vez de 250.000 (`50%`), você acha a certa muito mais depressa — e sem perder nenhuma (`100%` de `Recall@10`).

### 5.4 Quatro Pistas "Aha!" de Engenharia Descobertas no AlloyDB Gerenciado

> **Nota para Iniciantes:** Esta subseção é um **bônus avançado para engenheiros de banco de dados (DBAs)**. Se você está começando agora, pode pular direto para a **Seção 5.5 (Custos)** sem perder nada da história!

Rodar o benchmark real de 2,5M de linhas no Google Cloud AlloyDB 16.14 revelou quatro ajustes práticos que geraram um ganho real de **12,7x** por consulta:

1. **Use `now()`, nunca `clock_timestamp()`, no Motor Colunar:**
   - *Armadilha:* `clock_timestamp()` é `VOLATILE` (muda a cada linha), impedindo o pushdown para stripes SIMD.
   - *Solução & Ganho:* Trocar para `now() - INTERVAL '24 hours'` (`STABLE`) desbloqueou `"Columnar cache search mode": "native"`.
2. **Separe `COUNT(DISTINCT)` da agregação colunar (ganho de `12,7x`):**
   - *Armadilha:* Contar aparelhos distintos dentro da varredura de 40.050 linhas forçava um `quicksort` de `3,4 MB` na memória (`64,8 ms`).
   - *Solução & Ganho:* Dividir [`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql) em `corridor_stats` (`AVG` SIMD puro em **`4,24 ms`**, `0` acessos ao `shared_buffers`) + `sender_velocity` (`Index Only Scan` em **`0,11 ms`**) derrubou a query isolada para **`~5,1 ms`**.
3. **Ajuste `scann.vector_node_min_dimensionality = 32` para vetores 64-D:**
   - *Armadilha:* O pré-filtro por bitmap em estágio único só liga por padrão em vetores `>= 100` dimensões.
   - *Solução & Ganho:* Ajustar `min_dimensionality = 32` + `custom_scan_replace_prefilter = on` ativou o **`Bitmap assisted pre-filtering`** em **`0,29 ms`** com **`100%` de `Recall@10`**.
4. **Rode `VACUUM ANALYZE` antes de popular o Motor Colunar:**
   - *Armadilha:* Linhas recém-inseridas via `COPY` precisam ser marcadas como *all-visible* para entrar 100% nos stripes colunares.
   - *Solução & Ganho:* `VACUUM ANALYZE` colocou `96.777 / 96.777` blocos no cache colunar; no AlloyDB gerenciado, use `ALTER DATABASE ... SET` (no lugar de `ALTER SYSTEM SET`) e `google_ml.create_model(..., model_auth_type => 'alloydb_service_agent_iam')`.

### 5.5 Análise de Custos (FinOps): Quanto Custa Cada Cenário (Sem Complicação!)

Imagine alugar dois caminhões para entregar pacotes: o **Caminhão A** custa quase o mesmo por dia que o **Caminhão B**, mas **carrega 5,3 vezes mais pacotes por viagem**! Na nuvem (**FinOps**, o estudo de quanto a arquitetura custa de verdade), olhar só o preço da "máquina de 4 vCPUs" engana: o que importa é **quanto custa entregar os mesmos `500 PIX por segundo`**.

Antes de olhar os números, entenda **3 palavrinhas de conta de nuvem** em 15 segundos:
- **1 Nó (Zonal) vs. HA (2 Nós):** com **1 nó**, se o servidor falhar, o banco sai do ar; com **HA (*High Availability*)**, existem 2 nós trabalhando em dupla — se um cair, o outro assume na hora.
- **On-Demand:** você paga por hora usada, sem contrato de fidelidade (igual à diária avulsa da academia).
- **Commit de 3 Anos (e o que é "Amortizado"):** você fecha contrato de 3 anos para ganhar ~45% a ~52% de desconto. No **Google Cloud (CUD)** a entrada é **\$0** (só paga a parcela mensal). Na **AWS (Reserved Instance *Partial Upfront*)**, você paga uma **entrada** no Dia 1 + parcelas mensais menores. Para comparar de forma justa, somamos tudo e dividimos por 36 meses: $\text{Custo Mensal Amortizado} = (\text{Entrada} + 36 \times \text{Mensal}) \div 36$.

![Análise de Custos FinOps: AlloyDB vs AWS Aurora em Produção](./docs/assets/illustration-finops-costs-ptbr.png)

Todos os preços abaixo foram extraídos diretamente das calculadoras oficiais em **20 de novembro de 2026** (`us-central1` no GCP e `us-east-2` na AWS, USD para `730 h/mês`), somando **100% dos recursos faturáveis** do nosso Terraform ([`terraform/gcp_alloydb/main.tf`](./terraform/gcp_alloydb/main.tf) e [`terraform/aws_aurora/main.tf`](./terraform/aws_aurora/main.tf)):
- **GCP (`us-central1`):** Banco AlloyDB (`N2`, storage + backup) + VM `c3-standard-4` (`50 GiB` SSD) + `Cloud NAT` público. *(VPC, Firewall, Peering e IAM = `$0`.)*
- **AWS (`us-east-2`):** Banco Aurora (`aurora-iopt1`, I/O `$0`) + EC2 `c7g.xlarge` (`8 GB gp3`) + `1` IPv4 Público. *(VPC, IGW, Security Group, IAM e AWS SSM = `$0`.)*

#### Passo 1 — Na Mesma Máquina de `4 vCPU / 32 GB`, Qual Custa Menos? (Cenários A e B)

Mesmo olhando **máquina idêntica contra máquina idêntica** (`10 GB` de storage), o AlloyDB já sai mais barato — e entrega **5,3x mais pagamentos por segundo** (`486,0 TPS` contra `92,2 TPS`):

| Cenário (`4 vCPU / 32 GB`) | Modalidade | GCP AlloyDB (`us-central1`) | AWS Aurora (`us-east-2`) | Diferença (AlloyDB) |
| :--- | :--- | :---: | :---: | :---: |
| **A. 1 Nó (Sem HA)** | On-Demand (Mensal / Anual) | **\$614,66 / mês** (\$7.376/ano) | \$636,90 / mês (\$7.643/ano) | **-3,5%** *(e **5,5x** menor/TPS)* |
| **A. 1 Nó (Sem HA)** | Commit 3 Anos (Amort. / Total 3A) | **\$297,33 / mês** (\$10.704 em 3A) | \$341,48 / mês (\$12.293 em 3A) | **-12,9%** *(\$0 vs. \$5.194 entrada)* |
| **B. 2 Nós (HA)** | On-Demand (Mensal / Anual) | **\$1.069,24 / mês** (\$12.831/ano) | \$1.161,77 / mês (\$13.941/ano) | **-8,0%** *(e **5,7x** menor/TPS)* |
| **B. 2 Nós (HA)** | Commit 3 Anos (Amort. / Total 3A) | **\$515,53 / mês** (\$18.559 em 3A) | \$630,00 / mês (\$22.680 em 3A) | **-18,2%** *(\$0 vs. \$10.387 entrada)* |

#### Passo 2 — E Para Aguentar `~500 TPS` Reais em Produção com HA? (Cenário C)

Aqui é onde a diferença explode! No nosso benchmark real:
- O **AlloyDB** precisa apenas dobrar para **`8 vCPU / 64 GB` HA** para manter `p99 < 20 ms` a `500 TPS` (com `100%` de Recall@10).
- O **AWS Aurora** saturou em `92,2 TPS` com `4 vCPU`. Para entregar `~500 TPS` (~5,3x mais), ele precisa saltar para uma máquina gigante de **`32 vCPU / 256 GiB`** (`2x db.r7g.8xlarge` HA) — e ainda continua preso a `67,3%` de Recall@10!

| Cenário C (`~500 TPS` com HA, `50 GB`) | GCP AlloyDB `8 vCPU` HA (`us-central1`) | AWS Aurora `2x r7g.8xlarge` HA (`us-east-2`) | Quanto o AlloyDB Economiza? |
| :--- | :---: | :---: | :---: |
| **On-Demand — Por Mês** | **\$1.994,41 / mês** | \$8.514,57 / mês | **\$6.520 / mês (-76,6%)** |
| **On-Demand — Por Ano** | **\$23.932,92 / ano** | \$102.174,84 / ano | **\$78.242 / ano (4,3x menor)** |
| **Commit 3 Anos — Entrada (Dia 1)** | **\$0,00** | **\$83.090,80** | **\$83.091 a menos no Dia 1** |
| **Commit 3 Anos — Média Mensal (Amort.)** | **\$967,93 / mês** | \$4.678,21 / mês *(\$2.370 + entrada/36)* | **\$3.710 / mês (-79,3%)** |
| **Commit 3 Anos — Por Ano** | **\$11.615,14 / ano** | \$56.138,49 / ano | **\$44.523 / ano (4,8x menor)** |
| **Commit 3 Anos — Total em 3 Anos** | **\$34.845,42** | \$168.415,48 | **\$133.570 economizados!** |

![Gráfico Comparativo de Custo Mensal e Custo Efetivo por TPS — AlloyDB vs AWS Aurora](./docs/assets/chart-finops-monthly-vs-tps-ptbr.png)

#### Passo 3 — Confira Cada Centavo nos 12 Links Oficiais das Calculadoras (Visão de 20 de Novembro de 2026)

*Todos os 12 links abaixo (6 GCP + 6 AWS) podem ser abertos, auditados e editados diretamente nas calculadoras oficiais (preços vigentes em **20 de novembro de 2026**, sujeitos a reajustes futuros):*

- **Google Cloud Pricing Calculator (`us-central1` — On-Demand & Commit 3 Anos CUD com \$0 de entrada):**
  - Cenário A (1 Nó Zonal `4 vCPU`): [On-Demand (\$614,66/mês)](https://cloud.google.com/products/calculator?hl=pt_br&dl=CjhDaVJrT0dSak1tRmpOaTFqTXpNNExUUmpaVFl0T0RFNE55MWxNVEUzWWpZM016Y3lNVGtRQVE9PRAIGiQyM2JmNzcxZi0xMzczLTQzMTAtYTY0My00ODAxZGExN2IyMWY%3D) | [3-Year CUD (\$297,33/mês)](https://cloud.google.com/products/calculator?hl=pt_br&dl=CjhDaVF3TW1GaU1qa3daaTB5TldJNUxUUmpNREV0WWpRMVlpMWpZekZsTWpZMU1qWmlOVEFRQVE9PRAIGiRmOGU2Njc4Yi1kZWRmLTRiYTAtOTk5OS1mYjQ5Yzc5ZDFhODU%3D)
  - Cenário B (2 Nós HA `4 vCPU`, Terraform): [On-Demand (\$1.069,24/mês)](https://cloud.google.com/products/calculator?hl=pt_br&dl=CjhDaVJsWlRBeU9UaGlOQzAwTnpRM0xUUXpaRFV0WVRFell5MDNNbU15WW1KbE16WTFabVlRQVE9PRAIGiRjYzNhYjU4ZS1lZmUyLTQxNDQtOTVlMS03MGZjOGZhZTZiOGU%3D) | [3-Year CUD (\$515,53/mês)](https://cloud.google.com/products/calculator?hl=pt_br&dl=CjhDaVE0WVRCaU1HWmpNQzAwT1RZNExUUTFZVGd0WWpJNU5TMHpPVEZpTlRoaFltVTROV0VRQVE9PRAIGiQ0ZDc5ZTljMy1iMjU3LTQxNTEtODkwMS0wZWQwNmYyMjhmZDA%3D)
  - Cenário C (Produção `8 vCPU` HA `p99 < 20 ms`): [On-Demand (\$1.994,41/mês)](https://cloud.google.com/products/calculator?hl=pt_br&dl=CjhDaVF6T1RFeE1XSXpaUzAwTXpjeUxUUmhNRFV0T0RGbVl5MHdPV0V6WWpFNU1EUTFNaklRQVE9PRAIGiQzZWViZWZjMi01N2E5LTQ2ZWUtODFmZC0yZThjNmM3MWVjNjM%3D) | [3-Year CUD (\$967,93/mês)](https://cloud.google.com/products/calculator?hl=pt_br&dl=CjhDaVJpWkRjNU1XUTFNUzA0TkRabExUUmxNbVF0WWpoaU55MHhZMkprWW1KaU0yWTVORGdRQVE9PRAIGiQ0N2JjMGUyZC0wYThmLTQ1MTEtYjgxZC0zYzYzNTQ0NGQxYTI%3D)
- **AWS Pricing Calculator (`us-east-2` — Ohio, Aurora I/O-Optimized `aurora-iopt1` — On-Demand & Commit 3 Anos RI Partial Upfront + 3Y EC2 Savings Plan):**
  - Cenário A (1 Nó Single-AZ `db.r7g.xlarge`, Terraform): [On-Demand (\$636,90/mês)](https://calculator.aws/#/estimate?id=38fb890f514ca93ae34dcabd8bccc1c267458bdf) | [3-Year Commit (\$341,48/mês amort. — \$5.193,50 entrada + \$197,22/mês)](https://calculator.aws/#/estimate?id=c8ef48373dcdcdccb0d2332f6c92e988767f41be)
  - Cenário B (2 Nós HA `2x db.r7g.xlarge`): [On-Demand (\$1.161,77/mês)](https://calculator.aws/#/estimate?id=6f7e0efac3a774acabcdd028d9591ccf249418ba) | [3-Year Commit (\$630,00/mês amort. — \$10.387,00 entrada + \$341,47/mês)](https://calculator.aws/#/estimate?id=ae7e7df82f26800a4b8b4fc506336604ac8ac2f3)
  - Cenário C (Produção `~500 TPS` HA `2x db.r7g.8xlarge`): [On-Demand (\$8.514,57/mês)](https://calculator.aws/#/estimate?id=3cb24d50f202b6e3964190118b90445aab492c15) | [3-Year Commit (\$4.678,21/mês amort. — \$83.090,80 entrada + \$2.370,13/mês)](https://calculator.aws/#/estimate?id=8cee4ea78ea3e4123935bd874d26d3cf9fba1753)

> **Não Existem Perguntas Bobas**
>
> **P: Eu preciso gastar \$1.000 para reproduzir este benchmark na minha conta?**
> **R:** De jeito nenhum! Como o pagamento na nuvem é por hora e destruímos tudo logo depois com `make destroy-cloud`, rodar o laboratório completo por **2 horas** custa cerca de **\$2,93 no GCP** e **\$1,74 na AWS** — **menos de \$5,00 no total**!
>
> **P: Por que o AlloyDB economizou \$133.570 em 3 anos no Cenário C?**
> **R:** Por dois motivos somados: (1) o Motor Colunar + `alloydb_scann` fazem o AlloyDB render **5,3x mais por vCPU**, então ele só precisa de **8 vCPUs** onde o Aurora precisa de **32 vCPUs**; e (2) no Google Cloud o **CUD de 3 anos** dá ~51,5% de desconto com **\$0 de entrada**.

> **Resumo no Bolso (O Placar Final da Seção 5)**
> - **Performance (`4 vCPU / 32 GB`, filtro `0,5%`):** AlloyDB entregou **`5,3x` mais TPS** (`486,0` vs. `92,2`), **`p99` `5,9x` menor** (`95,54 ms` vs. `567,21 ms`) e **`100%` vs. `67,3%`** na captura de fraudes.
> - **Custos em Produção (`~500 TPS` com HA, Commit 3 Anos):** AlloyDB **`8 vCPU` HA** custa **\$34.845 em 3 anos** (**\$967,93/mês**, \$0 de entrada) contra **\$168.415 em 3 anos** (**\$4.678,21/mês** amortizados) no AWS Aurora — **\$133.570 economizados (`-79,3%`, `4,8x` menor)**!

---

## 6. O Quadro Geral: Acompanhando Um Pagamento de Ponta a Ponta

### 6.1 Por Dentro do Cluster AlloyDB (Tudo Roda Dentro do Banco no Caminho Síncrono)

Observe no diagrama abaixo que o AlloyDB não chama nenhum banco analítico externo (como BigQuery) nem serviço vetorial externo durante o pagamento. O **armazenamento em linha (OLTP)**, o **Motor Colunar**, o **índice `alloydb_scann`** e a **fila `agent_triage_outbox`** rodam todos dentro do mesmo cluster **AlloyDB for PostgreSQL**. Apenas o worker assíncrono faz chamadas ao **Vertex AI (Gemini 4 Hydrogen)**.

![Arquitetura AlloyDB de Duas Velocidades](./docs/assets/arquitetura-two-speed-htap-alloydb-ptbr.png)

### 6.2 O Ciclo de Autoimunização (`~5,1 ms` Reflexo Medular vs. `~3,5 s` Agente Cortical)

Acompanhe o desenho abaixo com o dedo em três faixas: na **faixa de cima**, um golpe mutante cai na zona cinzenta em milissegundos; na **faixa do meio**, o robô Python chama o **Gemini 4 Hydrogen** (`~3,5 s`) sem travar o banco e grava a "vacina" 64-D; na **faixa de baixo**, segundos depois, o próximo golpe já bate de frente no escudo verde e é bloqueado sozinho!

![Ciclo de Autoimunização: Reflexo Medular vs Agente Cortical](./docs/assets/ciclo-autoimunizacao-reflexo-vs-cortical-ptbr.png)

### 6.3 Diagrama de Sequência Completo (Arquitetura + Cálculos Passo a Passo)

Para ver **quem faz cada conta e em qual milissegundo**, o diagrama de sequência abaixo une os 21 passos reais do código: desde as 6 pistas e a expansão 64-D no cliente (`< 0,2 ms`), passando pelos cálculos SIMD, `alloydb_scann` e equação de risco + disjuntor `0,92` dentro do AlloyDB (`~5,1 ms`), até a triagem sem travas no **Gemini 4 Hydrogen** (`~3,5 s`) e a autoimunização (`>= 0,98`):

![Diagrama de Sequência Completo: Arquitetura e Cálculos Passo a Passo](./docs/assets/diagrama-sequencia-arquitetura-calculos-ptbr.png)

---

## 7. Abrindo o Capô: Tour Guiado Pelo Código

Pense neste repositório como um **laboratório com 4 salas**: o **Cofre SQL** (`sql/`), o **Simulador de Pagamentos** (`src/benchmark/`), o **Detetive de IA** (`src/agent/`) e a **Planta da Nuvem** (`terraform/`). Tudo foi escrito com **Programação Orientada a Objetos (POO)** em Python e SQL modular:

```text
sprintalloydb/
├── docker-compose.yml                  # Container local AlloyDB Omni 16 (4 GB shm + 4096 MB Colunar + SCaNN)
├── Makefile                            # Comandos rápidos (make up-local, make test, etc.)
├── pyproject.toml                      # Dependências Python 3.11+ e configuração do pytest e ruff
├── sql/
│   ├── 01_schema.sql                   # Cria as tabelas payment_ledger, fraud_signatures e agent_triage_outbox
│   ├── 02_setup_alloydb.sql            # Ativa o Motor Colunar e constrói o índice alloydb_scann
│   ├── 03_setup_aurora_baseline.sql    # Constrói o índice pgvector HNSW para paridade no AWS Aurora
│   └── queries/
│       └── hot_path_authorize.sql      # A CTE SQL de 5 estágios (~5,1 ms por consulta isolada)
├── src/
│   ├── benchmark/
│   │   ├── feature_generator.py        # UUIDv7, projeção vetorial 64-D, matemática de risco e gerador de carga
│   │   ├── seeder.py                   # Carga rápida via COPY e Strategy Pattern para inicializar cada motor
│   │   ├── runner.py                   # Motor assíncrono de 500 TPS, leitor de EXPLAIN e avaliador de Recall@10
│   │   └── reporter.py                 # Gerador automático dos relatórios Markdown e CSV
│   └── agent/
│       └── triage_worker.py            # Worker em 3 fases sem bloqueio que aciona o Gemini 4 Hydrogen
├── terraform/
│   ├── gcp_alloydb/                    # Provisiona AlloyDB 4 vCPU / 32 GB + VM c3-standard-4 no GCP
│   └── aws_aurora/                     # Provisiona Aurora 4 vCPU / 32 GiB I/O-Optimized + EC2 c7g.xlarge na AWS
└── tests/                              # Suítes de testes automatizados unitários e de integração
```

### 7.1 Detalhe da Camada SQL e Diagrama ER das Tabelas do Banco (`sql/`)

O Diagrama de Entidade-Relacionamento (ER) abaixo mostra as três tabelas do banco de dados (`PAYMENT_LEDGER`, `AGENT_TRIAGE_OUTBOX` e `FRAUD_SIGNATURES`), todos os campos e tipos de dados, quais colunas são aceleradas pelo **Motor Colunar do AlloyDB** e pelo índice **`alloydb_scann`**, e como uma tabela alimenta a outra durante o ciclo de autoimunização:

![Diagrama de Entidade-Relacionamento (ER) das Tabelas do Banco](./docs/assets/diagrama-er-banco-dados-ptbr.png)

1. **[`sql/01_schema.sql`](./sql/01_schema.sql): As Três Tabelas Principais**
   - **`payment_ledger`:** Armazena cada transferência (`tx_id UUID PRIMARY KEY`, `sender_account_id`, `receiver_account_id`, `device_fingerprint`, `merchant_category`, `selectivity_bucket`, `amount_cents`, `tx_timestamp`, `behavioral_vec vector(64)`, `composite_risk_score` e `decision`).
   - **`fraud_signatures`:** Guarda os padrões vetoriais de 64 dimensões de fraudes confirmadas (`signature_id UUID PRIMARY KEY`, `merchant_category`, `selectivity_bucket`, `created_at`, `source` em `'SEED_CORPUS' | 'CHURN_STREAM' | 'GEMINI_AGENT_IMMUNIZED'`, `behavioral_vec vector(64)` e `pattern_description`).
   - **`agent_triage_outbox`:** Guarda as transações suspeitas da zona cinzenta (`outbox_id BIGSERIAL PRIMARY KEY`, `tx_id` com `ON DELETE CASCADE`, `status` em `'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'`, `payload JSONB`, `agent_verdict`, `agent_rationale`, `created_at` e `processed_at`), contando com um índice parcial `idx_outbox_pending_poll` (`WHERE status IN ('PENDING', 'PROCESSING')`) para encontrar casos pendentes e recuperar reservas expiradas em menos de 1 milissegundo.

2. **[`sql/02_setup_alloydb.sql`](./sql/02_setup_alloydb.sql): Configuração do Motor Colunar e do `alloydb_scann`**
   - Carrega as extensões `alloydb_scann`, `google_columnar_engine` e `google_ml_integration`.
   - Cria os índices B-Tree compartilhados (`idx_ledger_velocity_btree`, `idx_ledger_sender_24h` e `idx_fraud_sig_filters`) e constrói `idx_fraud_sig_scann`: `CREATE INDEX idx_fraud_sig_scann ON fraud_signatures USING scann (behavioral_vec cosine) WITH (num_leaves = 100, quantizer = 'sq8');`.
   - Configura 8 parâmetros SCaNN no banco via `ALTER DATABASE postgres SET` (incluindo `scann.vector_node_min_dimensionality = 32`, `scann.custom_scan_replace_prefilter = on`, `scann.num_leaves_to_search = 15` e `scann.pre_reordering_num_neighbors = 50`) para ativar o pré-filtro por bitmap em estágio único (`Custom Scan (vector scan)`), e executa `SELECT google_columnar_engine_add('public.payment_ledger', ...)` para fixar as colunas analíticas no cache colunar SIMD.

3. **[`sql/03_setup_aurora_baseline.sql`](./sql/03_setup_aurora_baseline.sql): Baseline Justo para o AWS Aurora**
   - Cria os mesmos índices B-Tree relacionais (`idx_ledger_velocity_btree` e `idx_ledger_sender_24h`) em `payment_ledger`, remove `idx_fraud_sig_filters` (`DROP INDEX IF EXISTS`) para que o Aurora avalie o pós-filtro real do HNSW, e constrói o índice vetorial HNSW do `pgvector` (`USING hnsw (behavioral_vec vector_cosine_ops) WITH (m = 16, ef_construction = 64)`) em `fraud_signatures`.

4. **[`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql): Por Dentro dos 5 Estágios da CTE Síncrona**
   - **Estágio 1 (`corridor_stats` + `sender_velocity` -> `velocity_window`):** Separa a média de 24 horas do corredor (`corridor_stats` usando `now() - INTERVAL '24 hours'` para pushdown SIMD puro no Motor Colunar) da velocidade individual do pagador (`sender_velocity` via `Index Only Scan` em `idx_ledger_sender_24h` para `sum_24h_cents`, `tx_count_24h` e `distinct_devices_24h`).
   - **Estágio 2 (`vector_anomaly`):** Consulta a `fraud_signatures` com o filtro `WHERE merchant_category = $3 AND selectivity_bucket <= $4 ORDER BY behavioral_vec <=> $2::vector(64) LIMIT 10`, convertendo a distância de cosseno em similaridade `1.0 - distância`.
   - **Estágio 3 (`risk_eval`):** Calcula a nota `composite_score` combinando `35%` da velocidade em 24h + `15%` da troca de aparelhos + `50%` da similaridade vetorial, contando ainda com o **disjuntor de segurança**: se `max_vec_sim >= 0.92`, a função `GREATEST(...)` eleva imediatamente a nota final para `max_vec_sim` (`>= 0.92`), garantindo que qualquer pagamento correspondente a uma fraude conhecida seja bloqueado na hora, mesmo que a conta não tenha gasto nada nas últimas 24 horas.
   - **Estágio 4 (`inserted_tx`):** Insere a transferência na `payment_ledger` com a decisão `'BLOCKED'` (`>= 0.85`), `'FLAGGED_GREY_ZONE'` (`0.60..0.8499`) ou `'APPROVED'` (`< 0.60`).
   - **Estágio 5 (`outbox_enqueue`):** Insere condicionalmente um pacote `JSONB` de 12 campos na `agent_triage_outbox` quando `decision = 'FLAGGED_GREY_ZONE'`, devolvendo `(tx_id, composite_risk_score, decision, outbox_id)` para a aplicação em uma única transação atômica.

### 7.2 Detalhe das Classes Python (`src/`)

1. **[`src/benchmark/feature_generator.py`](./src/benchmark/feature_generator.py): Geração de Tráfego, UUIDv7 e Matemática Vetorial 64-D**
   - **`UUIDv7Generator`:** Gera identificadores únicos de 128 bits ordenados por tempo (padrão RFC 9562 UUIDv7), onde os primeiros 48 bits guardam o timestamp em milissegundos. Ao contrário do UUIDv4 aleatório, que espalha escritas em páginas distantes do disco e fragmenta índices, o UUIDv7 insere novos pagamentos sempre em ordem sequencial na borda direita da árvore B-Tree.
   - **`BehavioralVectorProjector`:** Transforma deterministicamente um `TransactionContext` em um vetor `numpy.float64` (`list[float]`) de 64 dimensões normalizado em comprimento unitário (`||v||_2 = 1.0`). Também oferece o método `perturb(base_vec, target_cosine_similarity)` (exposto na fachada como `create_perturbed_vector`) para simular quadrilhas alterando seus scripts até atingir uma similaridade de cosseno exata ao redor de ataques conhecidos.
   - **`RiskScoringPolicy`:** Implementa a fórmula de risco composto e os limites de decisão (`APPROVED`, `FLAGGED_GREY_ZONE`, `BLOCKED`), espelhando a lógica da CTE SQL e validada pelos testes em [`tests/unit/test_risk_scoring_math.py`](./tests/unit/test_risk_scoring_math.py).
   - **`PaymentWorkloadGenerator`:** Orquestra requisições sintéticas de pagamento PIX/FedNow (`generate_payment_request`), contextos comportamentais normais e anômalos (`generate_random_context`) e a ligação de parâmetros SQL (`bind_hot_path_sql` e `PaymentRequest.to_sql_params`).

2. **[`src/benchmark/seeder.py`](./src/benchmark/seeder.py): Carga em Massa via `COPY` e Padrão Strategy**
   - **`EngineInitializerStrategy` (Classe Base Abstrata):** Define como cada motor de banco configura suas extensões e índices *após* o carregamento dos dados:
     - **`AlloyDBEngineInitializer`:** Selecionado via `--engine-mode alloydb`; executa [`sql/02_setup_alloydb.sql`](./sql/02_setup_alloydb.sql) (ativando o Motor Colunar e criando o índice `alloydb_scann`), com fallback automático para [`sql/03_setup_aurora_baseline.sql`](./sql/03_setup_aurora_baseline.sql) quando executado contra o PostgreSQL padrão.
     - **`AuroraBaselineEngineInitializer`:** Selecionado via `--engine-mode aurora`; executa [`sql/03_setup_aurora_baseline.sql`](./sql/03_setup_aurora_baseline.sql).
   - **`DatabaseSeeder`:** Transmite milhões de linhas diretamente para o PostgreSQL usando `cursor.copy("COPY ... FROM STDIN")` em lotes de 25.000 registros, executa `ANALYZE` para atualizar as estatísticas do planejador de consultas e o quantizador *k-means* do SCaNN, e aciona a estratégia de inicialização escolhida.

3. **[`src/benchmark/runner.py`](./src/benchmark/runner.py): Executor Assíncrono de 500 TPS e Avaliadores de Plano e Recall**
   - **`DatabaseStatsCollector` e `DatabaseBlockCounters`:** Consultam a `pg_stat_database` antes e depois da bateria para calcular o delta exato de `shared_buffer_hit_ratio`.
   - **`ExplainPlanAnalyzer`:** Executa `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` *fora* do loop cronometrado e inspeciona a árvore JSON do plano para confirmar o uso do `Custom Scan (Columnar Scan)` e do índice `idx_fraud_sig_scann` vs. `idx_fraud_sig_hnsw`.
   - **`RecallEvaluator`:** Mede o `Recall@10` em vetores de prova por faixa de seletividade (`500`, `50`, `5`) comparando os resultados do índice contra o gabarito exato de força bruta (`SET LOCAL enable_indexscan = off; SET LOCAL enable_bitmapscan = off;`).
   - **`HTAPBenchmarkRunner`:** Antes de cada bateria colunar, executa `VACUUM payment_ledger` e `google_columnar_engine_refresh('public.payment_ledger')`; usa `psycopg_pool.AsyncConnectionPool` para sustentar `500 TPS` (90% de execuções da `hot_path_authorize.sql` + 10% de inserções na `fraud_signatures` com `source = 'CHURN_STREAM'`), mede o `Recall@10` com `num_probes = 15` e grava os percentis `p50`, `p95` e `p99` em um modelo Pydantic validado (`BenchmarkResult`).

4. **[`src/agent/triage_worker.py`](./src/agent/triage_worker.py): Agente Autônomo Lock-Free em Três Fases**
   - **`OutboxRepository`:** Centraliza todas as operações SQL sobre `agent_triage_outbox` e `fraud_signatures` (`reclaim_stale_leases`, `claim_pending_batch` e `complete_triage_and_immunize`).
   - **`FraudInferenceStrategy` (Padrão *Strategy*, onde cada classe implementa uma forma trocável de chamar a IA):**
     - **`InDatabaseVertexAIStrategy`:** Invoca o **Gemini 4 Hydrogen** diretamente de dentro do SQL do AlloyDB via `SELECT google_ml.predict_row(model_id => 'gemini-4-hydrogen', ...)`.
     - **`GenAISDKStrategy`:** Invoca o **Gemini 4 Hydrogen** (`gemini-4-hydrogen`) pelo SDK Python `google-genai` com `response_mime_type="application/json"` e valida o retorno pelo modelo `AgentAssessment`.
     - **`DeterministicLocalStrategy`:** Avalia os casos localmente sem precisar de credenciais de nuvem para testes offline e integração contínua (e atua automaticamente como fallback seguro caso a chamada remota falhe).
   - **`AgentTriageWorker.process_once`:** Executa o ciclo em três fases:
     1. **Fase 1 (Reserva Rápida):** Recupera reservas antigas acima de 30 segundos, reserva um lote de linhas `PENDING` com `FOR UPDATE SKIP LOCKED`, muda o status para `'PROCESSING'` e faz commit imediatamente (`< 2 ms`) para não segurar nenhuma trava no banco durante a chamada à IA.
     2. **Fase 2 (Inferência na IA):** Executa `FraudInferenceStrategy.evaluate` totalmente fora de transações do banco (`~3,5 s` medidos ao vivo no Vertex AI `gemini-4-hydrogen`).
     3. **Fase 3 (Autoimunização):** Chama `complete_triage_and_immunize` para marcar o item da fila como `'COMPLETED'` e, quando `verdict == 'CONFIRMED_FRAUD'` com `confidence_score >= 0.85`, insere o vetor de 64 dimensões na tabela `fraud_signatures` (`source = 'GEMINI_AGENT_IMMUNIZED'`) com a checagem de deduplicação por cosseno `>= 0.98`.

5. **[`src/benchmark/reporter.py`](./src/benchmark/reporter.py): Agregador de Telemetria e Exportador Markdown/CSV**
   - **`CsvTelemetryExporter` e `MarkdownReportFormatter`:** Leem os arquivos JSON de telemetria (`--inputs`) e geram [`results/benchmark_summary.md`](./results/benchmark_summary.md) e [`results/raw_telemetry.csv`](./results/raw_telemetry.csv).

> **Não Existem Perguntas Bobas**
>
> **P: Por que o código usa `UUIDv7` em vez do famoso `UUIDv4` para dar um número de RG a cada PIX?**
> **R:** O `UUIDv4` é 100% aleatório: é como guardar folhas novas em páginas sorteadas de um fichário, rasgando e bagunçando o índice B-Tree o tempo inteiro! Já o **`UUIDv7`** começa com a data e a hora exatas em milissegundos, então todo PIX novo entra sempre em ordem no final do fichário — muito mais rápido para gravar e pesquisar.

---

## 8. Guia Passo a Passo: Escolha Sua Aventura!

Você não precisa de conta na nuvem para brincar com este projeto! Escolha o caminho que combina com o seu tempo:
- **10 segundos (sem Docker, sem nuvem):** rode os testes e gere o relatório a partir dos dados reais arquivados (Passo 8.2).
- **5 minutos no seu computador:** suba o **AlloyDB Omni** grátis no Docker (Passo 8.3).
- **Batalha completa na nuvem:** provisione **Google Cloud AlloyDB** e **AWS Aurora** com Terraform (Passos 8.4 e 8.5).

### 8.1 Pré-requisitos

1. **Python 3.11+**
2. **Docker e Docker Compose** (reserve pelo menos 10 GB de RAM nas configurações do Docker Desktop para que o container possa alocar `4gb` de memória compartilhada, `shm_size`, e `4096 MB` para o Motor Colunar local)
3. **Terraform >= 1.5** (necessário apenas ao provisionar os clusters no Google Cloud e na AWS)
4. Copie o arquivo de variáveis de exemplo (que define as URLs de conexão **DSN**, sigla para *Data Source Name*, o endereço padrão contendo usuário, senha, host e porta do banco de dados):
   ```bash
   cp .env.example .env
   ```

### 8.2 Passo 1: Executar os Testes Automatizados e Gerar o Relatório Offline (Leva 10 Segundos)

Você pode validar todo o código, a matemática de risco e os geradores de relatório na sua máquina antes mesmo de iniciar o Docker ou a nuvem:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Executa os testes unitários e de integração e o verificador de código
pytest -v
ruff check src/ tests/

# Consolida os 12 JSONs reais da nuvem em results/benchmark_summary.md e results/raw_telemetry.csv
python -m src.benchmark.reporter \
  --inputs "./results/gcp_live/run_*.json" "./results/aws_live/run_*.json" \
  --output-dir ./results
```

### 8.3 Passo 2: Executar Localmente com AlloyDB Omni (Docker Compose)

O **AlloyDB Omni** é a edição em container Docker do Google Cloud AlloyDB que roda localmente no seu computador ou servidor e inclui o **Motor Colunar** e o índice **`alloydb_scann`**.

1. **Inicie o container local do AlloyDB Omni 16:**
   ```bash
   make up-local
   ```
2. **Popule o banco com 200.000 pagamentos e 25.000 assinaturas vetoriais de fraude:**
   ```bash
   make seed-local
   ```
3. **Execute a suíte de benchmark de 500 TPS nas seletividades de 50%, 5% e 0,5%:**
   ```bash
   make benchmark-local
   ```
4. **Execute o worker autônomo de triagem:**
   - Modo local determinístico (sem chave de API, processa um lote e encerra):
     ```bash
     make worker-local
     ```
   - Usando o **Gemini 4 Hydrogen** via SDK Google GenAI:
     ```bash
     export GEMINI_API_KEY="sua-api-key"
     export GEMINI_MODEL_ID="gemini-4-hydrogen"
     python -m src.agent.triage_worker \
       --dsn "postgresql://postgres:postgres@localhost:5432/postgres" \
       --agent-mode genai_sdk \
       --model-id gemini-4-hydrogen \
       --once
     ```
5. **Desligue o container local ao terminar:**
   ```bash
   make down-local
   ```

### 8.4 Passo 3: Executar no Google Cloud (AlloyDB `4 vCPU / 32 GB` + Vertex AI Gemini 4 Hydrogen)

1. **Provisione o cluster AlloyDB e a VM geradora de carga `c3-standard-4`:**
   ```bash
   gcloud auth application-default login
   cd terraform/gcp_alloydb
   terraform init
   terraform apply \
     -var="project_id=SEU_PROJECT_ID_GCP" \
     -var="region=us-central1" \
     -var="db_password=SUA_SENHA_SEGURA"
   ```
2. **Conecte-se à VM `c3-standard-4` (`gcloud compute ssh`), clone este repositório, instale as dependências (`pip install -e .`), leia o IP privado em `terraform output` e execute a carga + ablação:**
   ```bash
   export PG_DSN="postgresql://postgres:SUA_SENHA_SEGURA@<IP_PRIVADO_ALLOYDB>:5432/postgres"

   python -m src.benchmark.seeder \
     --dsn "$PG_DSN" \
     --engine-mode alloydb \
     --ledger-rows 2000000 \
     --signature-rows 500000

   for MODE in alloydb_row_hnsw alloydb_col_hnsw alloydb_col_scann; do
     python -m src.benchmark.runner --dsn "$PG_DSN" --mode "$MODE" --tps 500 --duration 60
   done

   python -m src.agent.triage_worker --dsn "$PG_DSN" --agent-mode in_db_ml --model-id gemini-4-hydrogen
   ```

### 8.5 Passo 4: Executar o Teste de Paridade no AWS Aurora PostgreSQL 16 (`db.r7g.xlarge` I/O-Optimized)

1. **Provisione o cluster AWS Aurora I/O-Optimized (`PostgreSQL 16.14`) e a instância EC2 `c7g.xlarge`** (servidor virtual da AWS com acesso via AWS SSM, o *Systems Manager*, terminal seguro sem precisar abrir a porta SSH 22):
   ```bash
   cd terraform/aws_aurora
   terraform init
   terraform apply \
     -var="aws_region=us-east-2" \
     -var="engine_version=16.14" \
     -var="db_password=SUA_SENHA_SEGURA"
   ```
2. **Conecte-se à instância `c7g.xlarge` via AWS SSM, clone o repositório, instale (`pip install -e .`), pegue o endpoint em `terraform output` e rode o modo `aurora_io_hnsw`:**
   ```bash
   export AURORA_DSN="postgresql://postgres:SUA_SENHA_SEGURA@<ENDPOINT_WRITER_AURORA>:5432/postgres"

   python -m src.benchmark.seeder \
     --dsn "$AURORA_DSN" \
     --engine-mode aurora \
     --ledger-rows 2000000 \
     --signature-rows 500000

   python -m src.benchmark.runner \
     --dsn "$AURORA_DSN" \
     --mode aurora_io_hnsw \
     --tps 500 \
     --duration 60 \
     --output-dir ./results

   python -m src.benchmark.reporter --inputs "./results/run_*.json" --output-dir ./results
   ```
3. **Destrua os recursos das duas nuvens logo após coletar os resultados:**
   ```bash
   make destroy-cloud
   ```

> **Resumo Final no Bolso (Para Levar Para a Vida)**
> - **Reflexo + Cérebro:** nunca trave um pagamento de `50 ms` esperando uma IA pensar por `3,5 s` — deixe o banco agir em milissegundos e o **Gemini 4 Hydrogen** vacinar o banco nos bastidores.
> - **Motor Colunar + `alloydb_scann`:** em hardware idêntico (`4 vCPU / 32 GB`, 2,5M linhas), o AlloyDB entregou **`5,3x` mais TPS**, **`p99` `5,9x` menor** e **`100%` de precisão antifraude** contra **`67,3%`** no AWS Aurora.

---

## 9. Referências e Aprofundamento

Todos os links abaixo foram verificados diretamente e aprofundam cada conceito técnico, estatístico e arquitetural apresentado neste estudo.

### 9.1 Bancos de Dados, HTAP, Google Cloud AlloyDB e AWS Aurora

- **HTAP (*Hybrid Transactional/Analytical Processing*):** [Hybrid transactional/analytical processing — Wikipedia](https://en.wikipedia.org/wiki/Hybrid_transactional/analytical_processing) — Conceito de executar transações OLTP e análises OLAP no mesmo banco de dados.
- **Google Cloud AlloyDB Columnar Engine:** [About the AlloyDB columnar engine — Google Cloud Documentation](https://docs.cloud.google.com/alloydb/docs/columnar-engine/about) — Arquitetura do motor colunar híbrido em memória e aceleração vetorizada SIMD.
- **AlloyDB `alloydb_scann` (Criação e Sintaxe do Índice ScaNN):** [Create a ScaNN index — Google Cloud Documentation](https://docs.cloud.google.com/alloydb/docs/ai/create-scann-index) — Guia oficial de criação, `num_leaves`, `quantizer = 'sq8'` e busca vetorial filtrada no AlloyDB.
- **AlloyDB Embeddings Vetoriais:** [Store vector embeddings — Google Cloud Documentation](https://docs.cloud.google.com/alloydb/docs/ai/store-embeddings) — Armazenamento e consulta de vetores com `vector(n)` no AlloyDB for PostgreSQL.
- **AlloyDB `google_ml_integration` (`google_ml.create_model` / `predict_row`):** [Register and call remote AI models in AlloyDB overview — Google Cloud Documentation](https://docs.cloud.google.com/alloydb/docs/ai/model-endpoint-overview) — Registro e invocação de modelos de IA diretamente via SQL.
- **AWS Aurora I/O-Optimized (`aurora-iopt1`):** [Amazon Aurora storage — AWS Documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Overview.StorageReliability.html) — Arquitetura de armazenamento distribuído do Amazon Aurora e camada I/O-Optimized.
- **PostgreSQL 16 — WAL e Durabilidade ACID:** [Write-Ahead Logging (WAL) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/wal-intro.html) — Como o PostgreSQL garante durabilidade e recuperação após falhas de energia.
- **PostgreSQL 16 — MVCC:** [Concurrency Control (MVCC) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/mvcc-intro.html) — Controle de concorrência multiversão que permite leituras e escritas simultâneas sem bloqueio mútuo.
- **PostgreSQL 16 — CTEs (`WITH ... AS`):** [WITH Queries (Common Table Expressions) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/queries-with.html) — Encadeamento de múltiplos estágios SQL em uma única viagem ao banco.
- **PostgreSQL 16 — Fila Sem Travas (`FOR UPDATE SKIP LOCKED`):** [SELECT Locking Clause (`SKIP LOCKED`) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE) — Padrão de fila concorrente usado pelo worker de triagem.
- **PostgreSQL 16 — `JSONB`:** [JSON Types (`jsonb`) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/datatype-json.html) — Armazenamento binário indexável de documentos JSON usado no payload forense.
- **PostgreSQL 16 — Índices B-Tree:** [B-Tree Indexes — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/btree.html) — Estrutura ordenada padrão para filtros relacionais rápidos e pré-filtro por bitmap.
- **PostgreSQL 16 — `pg_stat_database` (`Shared Buffer Hit Ratio`):** [The Cumulative Statistics System — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/monitoring-stats.html) — Contadores `blks_hit` e `blks_read` para medir eficiência de memória RAM.
- **Padrão Transactional Outbox:** [Pattern: Transactional outbox — Microservices.io](https://microservices.io/patterns/data/transactional-outbox.html) — Base arquitetural da tabela `agent_triage_outbox` para desacoplar escrita síncrona de agentes assíncronos.

### 9.2 Busca Vetorial, Índices (`SCaNN` vs. `HNSW`) e Métricas (`p99` e `Recall@10`)

- **SCaNN e Quantização Vetorial Anisotrópica (Paper Original):** [Guo et al. (2020) — *Accelerating Large-Scale Inference with Anisotropic Vector Quantization* (arXiv:1908.10396)](https://arxiv.org/abs/1908.10396) — Artigo do Google Research que fundamenta o algoritmo SCaNN.
- **Código-Fonte Open Source do SCaNN:** [google-research/scann — GitHub](https://github.com/google-research/google-research/tree/master/scann) — Implementação oficial de referência do SCaNN pelo Google Research.
- **HNSW (Paper Original):** [Malkov & Yashunin (2018) — *Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs* (arXiv:1603.09320)](https://arxiv.org/abs/1603.09320) — Artigo original dos grafos hierárquicos navegáveis de pequeno mundo.
- **Extensão `pgvector` para PostgreSQL:** [pgvector/pgvector — GitHub](https://github.com/pgvector/pgvector) — Implementação open-source do tipo `vector(n)`, operador `<=>` e índice HNSW no PostgreSQL/Aurora.
- **Benchmark Padrão de Busca Vetorial (`Recall@10`):** [ANN-Benchmarks](https://ann-benchmarks.com/index.html) — Metodologia padrão da indústria para comparar QPS vs. `Recall@10` em busca aproximada de vizinhos mais próximos.
- **Precisão e Revocação (`Recall`):** [Precision and recall — Wikipedia](https://en.wikipedia.org/wiki/Precision_and_recall) — Definição matemática da métrica de revocação (quantos itens relevantes reais foram recuperados).
- **Latência de Cauda (`p95` e `p99`):** [Jeffrey Dean & Luiz André Barroso (2013) — *The Tail at Scale* (Google Research / Communications of the ACM)](https://research.google/pubs/the-tail-at-scale/) — Artigo clássico sobre por que sistemas em escala precisam controlar o `p99` em vez da média simples.
- **Instruções Vetorizadas de CPU (`SIMD`):** [Single instruction, multiple data (SIMD) — Wikipedia](https://en.wikipedia.org/wiki/Single_instruction,_multiple_data) — Processamento paralelo em registradores de CPU (AVX-512 / ARM NEON) usado pelo Motor Colunar e pelo SCaNN.

### 9.3 Fundamentos Matemáticos e Estatísticos do Modelo Antifraude

- **Random Fourier Features (Expansão Não-Linear para 64-D):** [Ali Rahimi & Benjamin Recht (2007) — *Random Features for Large-Scale Kernel Machines* (NeurIPS)](https://proceedings.neurips.cc/paper/2007/hash/013a006f03dbc5392effeb8f18fda755-Abstract.html) — Artigo premiado (NeurIPS Test of Time) que fundamenta aproximações de kernels não-lineares com senos e cossenos.
- **Teorema de Bochner:** [Bochner's theorem — Wikipedia](https://en.wikipedia.org/wiki/Bochner%27s_theorem) — Base teórica que conecta kernels invariantes a translação (como o RBF) à transformada de Fourier.
- **Similaridade de Cosseno (`<=>`):** [Cosine similarity — Wikipedia](https://en.wikipedia.org/wiki/Cosine_similarity) — Medida do ângulo entre dois vetores normalizados em comprimento unitário ($L_2$).
- **Ortogonalização de Gram-Schmidt:** [Gram–Schmidt process — Wikipedia](https://en.wikipedia.org/wiki/Gram%E2%80%93Schmidt_process) — Método geométrico usado para gerar mutações vetoriais com similaridade de cosseno exata.
- **Escore-Z (*Z-Score*):** [Standard score — Wikipedia](https://en.wikipedia.org/wiki/Standard_score) — Medida estatística de quantos desvios-padrão um valor de pagamento se afasta da média do corredor comercial.
- **Agrupamento *k-means* (Centroides do SCaNN):** [k-means clustering — Wikipedia](https://en.wikipedia.org/wiki/K-means_clustering) — Algoritmo de particionamento que define os centros geométricos das folhas (*leaves*) do índice SCaNN.
- **Tangente Hiperbólica (`tanh`):** [Hyperbolic functions — Wikipedia](https://en.wikipedia.org/wiki/Hyperbolic_functions) — Função de ativação não-linear usada nas dimensões `60..63` para limitar valores extremos em `[-1, +1]`.

### 9.4 Padrões de Identificadores, Modelos de IA e Pagamentos Instantâneos

- **UUIDv7 (Identificadores Ordenados por Tempo):** [IETF RFC 9562 — Universally Unique IDentifiers (UUIDs)](https://www.rfc-editor.org/info/rfc9562/) — Especificação oficial do UUIDv7 usado na chave primária `tx_id` para evitar fragmentação de B-Tree.
- **Modelos Gemini no Google Cloud (Vertex AI):** [Google models — Google Cloud Documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/google-models) — Documentação oficial dos modelos Google Gemini hospedados na nuvem.
- **PIX (Brasil):** [Pix — Banco Central do Brasil](https://www.bcb.gov.br/estabilidadefinanceira/pix) — Portal oficial do ecossistema de pagamentos instantâneos do Banco Central do Brasil.
- **FedNow (EUA):** [FedNow Service — Federal Reserve Financial Services](https://www.frbservices.org/financial-services/fednow-service/) — Portal oficial do sistema de pagamentos instantâneos do Federal Reserve dos Estados Unidos.
