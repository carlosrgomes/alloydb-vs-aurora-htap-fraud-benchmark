# Beyond Aurora for Real-Time AI Agents: Sub-20ms HTAP Payment Fraud & Anomaly Benchmark with AlloyDB Columnar Engine, SCaNN, and Autonomous Gemini 4 Hydrogen Triage

> **Language / Idioma:** **English (`README.md`)** | **[Leia em Português do Brasil (`README-ptbr.md`)](./README-ptbr.md)**

---

## 1. Starting from Zero: The 50-Millisecond Coffee Mystery

Imagine you are standing at a bakery counter and you pay for your coffee using an instant transfer on your phone, like **PIX** in Brazil or **FedNow** in the United States.

Between the moment your finger taps "Send" and the moment the card machine beeps **"Payment Approved"**, less than one-twentieth of a second passes (about **50 milliseconds**). To picture how fast that is, **a single human eye blink takes 300 milliseconds**. In other words, the entire payment has to finish six times faster than a blink!

Inside that tiny fraction of a blink, the bank's database has only **15 to 20 milliseconds** to finish **three completely different jobs at the exact same time**:

1. **Lock the transfer in the vault safely:** Write down who sent the money, who received it, and the exact amount, making sure not a single cent disappears or gets duplicated even if someone pulls the power plug mid-transfer.
2. **Check the last 24 hours of spending in that business category (the "payment corridor"):** Glance at roughly `40,000` recent transfers in that specific type of store (`merchant_category`, like bakeries versus car dealerships), add them up, and calculate the average to check whether the amount makes sense or an intruder is draining the account.
3. **Hunt for known scams in real time:** Fraud rings run automated bots that leave subtle "fingerprints" (phone model, late-night hours, device switching, internet network). The database must compare the current payment against a catalog of **500,000 confirmed scams**, while **50 brand-new scams per second** are being added to that catalog at the exact same time.

![What Happens in Less Than an Eye Blink When You Pay for Coffee](./docs/assets/illustration-bakery-pix-3-jobs-en.png)

> **There Are No Dumb Questions**
>
> **Q: Wait a minute... if Gemini is so smart, why doesn't the bank just ask the AI on every single payment?**
> **A:** Because deep thinking takes time! In our live test on **Google Cloud Vertex AI** (Google Cloud's managed AI platform, `locations/global` endpoint), asking **Gemini 4 Hydrogen** to investigate a suspicious transaction took **`3,543.6 ms` (~3.5 seconds)**. If the bank waited 3.5 seconds on every cup of coffee, the bakery line would wrap around the block and the payment would time out.
>
> **Q: Then what is the problem with traditional cloud databases like AWS Aurora?**
> **A:** CPU and memory traffic jams! Traditional databases store all data line by line inside one shared RAM area. When the database tries to scan 40,000 payments from the last 24 hours while running filtered vector searches, the processor clogs up and payments per second collapse.

### 1.1 The Big Idea: Two-Speed Architecture (Just Like Your Body!)

Have you ever accidentally touched a hot pan? Your hand pulls back **before your brain even finishes thinking "ouch, that's hot!"**. That happens because your body runs at **two speeds**: an ultra-fast reflex in your spine and deep detective thinking in your brain.

We built that exact same design inside **Google Cloud AlloyDB for PostgreSQL** and tested it head-to-head against **AWS Aurora PostgreSQL 16.14** on identical **`4 vCPU / 32 GB`** machines (4 virtual CPU cores and 32 gigabytes of RAM) with 2,500,000 rows:

1. **Speed 1 (`~5.1 ms` per query — The Spinal Reflex):** The database itself runs the 24-hour corridor math, compares the payment against 500,000 known scams, and safely locks the transfer in **`~5.1 ms`** (measured via `EXPLAIN ANALYZE`, PostgreSQL's built-in "X-ray & stopwatch" — comfortably inside the 15–20 ms budget). Honest payments breeze through; known scams are blocked on the spot.
2. **Speed 2 (`~3.5 s` in the background — The Detective Brain):** When a payment lands in the "grey zone" (not obviously honest, yet not matching any old scam), the database drops a copy into an internal waiting tray. A background worker picks it up without slowing down a single customer, asks **Gemini 4 Hydrogen** on Vertex AI (`locations/global`) to investigate, and when Gemini confirms a brand-new scam, writes its mathematical "fingerprint" right back into the database. Seconds later, Speed 1 blocks that new attack all by itself — the database literally **self-immunizes**!

---

## 2. Understanding Every Concept Before We Look at the Numbers

Before we open the benchmark tables, let's unpack every technical piece using everyday analogies — with zero unexplained jargon.

### 2.1 Milliseconds (`ms`), Throughput (`TPS`), and ACID Ledger Writes

A **millisecond (`ms`)** is one-thousandth of a second (`1,000 ms = 1 second`). Our strict budget for the database is **under 20 ms**. **Transactions Per Second (`TPS`)** measures how many payments hit the database every second. Throughout our benchmark, we fire **500 operations every second (`500 TPS`)** nonstop: 450 payment authorizations per second plus 50 new fraud signatures inserted per second.

Every payment is saved in a table called `payment_ledger` (the bank's official notebook) using **ACID transactions**. **ACID** stands for *Atomicity, Consistency, Isolation, and Durability*, which is the database's all-or-nothing safety guarantee: either the entire payment is recorded cleanly on disk, or nothing is changed at all. Under the hood, PostgreSQL enforces this using two mechanisms: a **Write-Ahead Log (`WAL`)**, which is a sequential crash-recovery diary written to disk before any table page changes, and **Multi-Version Concurrency Control (`MVCC`)**, which keeps row snapshots so readers and writers never block one another.

### 2.2 OLTP, OLAP, HTAP, and Single-Trip SQL (`CTE`)

In database engineering, workloads usually fall into two camps:
- **OLTP (Online Transaction Processing)** is like a supermarket cashier scanning one carton of milk: fast, tiny individual writes (`INSERT` one PIX transfer).
- **OLAP (Online Analytical Processing)** is like the store manager asking for the average price across 40,000 receipts from the last 24 hours (`SUM` and `AVG` over 40,000 rows).
- **HTAP (Hybrid Transactional and Analytical Processing)** means doing both the cashier's job and the manager's job inside the same database at the exact same instant, without copying data to a separate analytics server first.

Normally, an application talks to a database in several back-and-forth network trips: first asking for the 24-hour total, waiting for the answer, then asking for matching fraud patterns, waiting again, and finally saving the payment. Each trip across the network wastes milliseconds. In our project, we use a **SQL Common Table Expression (`CTE`, written with `WITH ... AS`)** inside [`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql) to bundle all five steps into a single instruction. The application makes one trip to the database and gets the final decision back in milliseconds.

![OLTP, OLAP, HTAP, and Single-Trip SQL CTE Explained at the Supermarket](./docs/assets/illustration-kid-htap-cte-en.png)

### 2.3 RAM, Shared Buffer Hit Ratio, and the AlloyDB Columnar Engine (`SIMD`)

Think of **RAM (Memory)** as your kitchen countertop, and **Disk (Storage)** as a basement pantry two flights of stairs down. Grabbing an ingredient already sitting on the countertop is instant; walking down to the basement takes ages. PostgreSQL keeps its most active data in 8-kilobyte blocks on that countertop, an area called the **Shared Buffer Pool (`shared_buffers`)**.

The **Shared Buffer Hit Ratio (`%`)** shows how often, out of every 100 reads, the data was already sitting on the countertop (RAM) without walking down to the basement (Disk). In our live cloud test with `32 GB` of RAM, all 2.5 million rows fit in memory on both engines (**`99.99%–100.0%`** hit ratio). Yet AWS Aurora still stalled at `92.2 TPS` (`p99 = 567.21 ms`) while AlloyDB flew at `486.0 TPS` (`p99 = 95.54 ms`)!

Why? Because of the structural difference between a **Row Store** and the **AlloyDB Columnar Engine**:

Imagine a paper ledger with `40,050` lines, where each line holds 10 pieces of information (*Transaction ID, Sender, Receiver, Device Code, Category, Timestamp, Amount, 64-Number Vector...*):
- **Row Store (AWS Aurora):** Standard PostgreSQL reads **every full line** just to sum the *Amount* column. Even when everything sits in RAM, the CPU burns almost all its cycles skipping over IDs, device codes, and vectors across `40,050` rows per payment — and on larger-than-RAM datasets, those scans also evict hot payment pages from memory.
- **AlloyDB Columnar Engine (`google_columnar_engine`):** AlloyDB carves out an isolated **columnar cache in RAM** (`8 GB` on the cloud cluster; `4 GB` in local Docker) storing *only* the math columns (`amount_cents`, `merchant_category`, `tx_timestamp`) stacked vertically side by side.
- **`SIMD` Superpower:** With numbers packed side by side, the CPU uses **SIMD (Single Instruction, Multiple Data)** circuits (such as **AVX-512** on Intel/AMD and **ARM NEON** on Apple Silicon/Graviton) to sum 8 to 16 values in one clock tick. In live `EXPLAIN ANALYZE` on 2.5M rows, AlloyDB summed `40,050` rows in **`4.24 ms`** with **`0` shared buffer hits**!

![Row-Only Buffer Pool vs AlloyDB Columnar Engine](./docs/assets/illustration-htap-memory-en.png)

### 2.4 64-Dimensional Vectors (`vector(64)`) and Cosine Similarity (`<=>`)

How does a database know whether a new payment behaves like a scam? We take behavioral clues from the transaction (such as transfer amount relative to the user's norm, time of night, device change frequency, implied travel speed, and merchant category) and convert them into a list of **64 numbers**. That list of 64 numbers is called a **64-Dimensional Vector Embedding (`vector(64)`)**.

Geometrically, you can picture that 64-number list as an arrow pointing in a specific direction in space. When we compare the current payment's arrow against a confirmed scam's arrow using PostgreSQL's **Cosine Distance operator (`<=>`)**, the database measures the angle between the two arrows. We convert that distance into **Cosine Similarity (`1.0 - distance`)**: a score of `1.0` means the two payments point in the exact same behavioral direction (a 100% match), while `0.0` means they are orthogonal (unrelated).

### 2.5 What Is `alloydb_scann` and Why Does `pgvector` HNSW Struggle When We Filter Data?

In a real bank, you never search across all fraud vectors blindly; you combine the vector search with a **SQL Filter** (for example: *"Only compare this payment against fraud vectors in merchant category #3 and within risk bucket `<= 5`"*).

The percentage of rows that survive that SQL filter is called **Selectivity**:
- At **50% Selectivity (`selectivity_bucket <= 500`)**, half the table passes the filter.
- At **5% Selectivity (`selectivity_bucket <= 50`)**, only 1 out of 20 rows passes.
- At **0.5% Selectivity (`selectivity_bucket <= 5`)**, only **1 out of 200 rows** passes the filter.

Checking hundreds of thousands of vectors one by one is too slow, so databases use a **Vector Index**. This is where **AWS Aurora (`pgvector` HNSW)** and **Google Cloud AlloyDB (`alloydb_scann`)** take completely different paths:

![Filtered Vector Search: pgvector HNSW vs AlloyDB SCaNN](./docs/assets/illustration-scann-vs-hnsw-en.png)

#### What Is `pgvector` HNSW, How Does It Work, and Where Does It Break?

Before we compare the two vector indexes, let's understand what **`pgvector`** and **`HNSW`** mean:
- **`pgvector`** is the open-source extension that adds vector storage (`vector(64)`) and similarity search to standard PostgreSQL and AWS Aurora.
- **`HNSW` (*Hierarchical Navigable Small World*):** Think of HNSW as a multi-story subway network built over your vectors:
  - **Multiple Floors:** The top floor has a few "express stations" (`m = 16` links per node); the ground floor connects every fraud vector to its closest local neighbors like city streets.
  - **Fast Navigation:** The database hops along express stations to reach your payment's neighborhood, then drops to the ground floor to grab the 10 closest neighbors.
- **Why HNSW Breaks Under Strict SQL Filters (`0.5%`) and Heavy Writes (`50 TPS`):**
  1. **Filter Blindness (Post-Filtering):** HNSW's web only knows angles — it has **no idea** which `merchant_category` or `selectivity_bucket` each node belongs to. Under a `0.5%` filter, **99.5% of visited nodes go straight into the trash**. Its candidate queue (`ef_search = 40`) runs dry before collecting 10 valid frauds: in our live AWS Aurora run, `Recall@10` dropped to **`67.3%` (`0.6733`)** at `p99 = 567.21 ms` (and turning on `hnsw.iterative_scan` to keep walking deeper degrades latency even further).
  2. **Lock Contention at `50 TPS`:** Every new fraud vector forces HNSW to search across layers (build parameter `ef_construction = 64`), lock neighboring nodes, and rewire up to `m = 16` edges.

#### What `alloydb_scann` Is and How It Solves Both Problems

**`alloydb_scann`** is AlloyDB's native vector index powered by **SCaNN (*Scalable Nearest Neighbors*)**, the Google Research algorithm behind Google Search, YouTube, and Google Play. It stands on three pillars:

1. **Tree-Quantized Partitioning (`num_leaves`):** Instead of tangling vectors in a hard-to-update spiderweb, `alloydb_scann` sorts them into organized folders ("leaves", such as `num_leaves = 100` for 500k vectors) around center points (*centroids*) learned via **k-means clustering**. A new fraud drops straight into its folder with zero web rewiring.

   ![Tree-Quantized Partitioning in AlloyDB SCaNN: Organized Folders vs Tangled Web](./docs/assets/illustration-scann-tree-partitioning-en.png)

2. **Anisotropic Vector Quantization and `sq8` Compression:** *Anisotropic quantization* preserves the arrow's **angle** (what matters for Cosine Similarity `<=>`), instead of naive uniform rounding. Meanwhile, `sq8` shrinks each 32-bit float into an 8-bit integer — **4x smaller**, fitting straight inside the CPU's SIMD cache.

   ![Anisotropic Vector Quantization and sq8 4x Compression in CPU Cache](./docs/assets/illustration-scann-sq8-quantization-en.png)

3. **Single-Stage Bitmap Pre-Filtering:** Relational columns (`merchant_category`, `selectivity_bucket`) use a **B-Tree** (PostgreSQL's balanced sorted tree index). `alloydb_scann` grabs the B-Tree's **bitmap** (a compact binary `1 = keep, 0 = skip` checklist) and intersects it with SCaNN's leaves *before* measuring any angles — skipping 99.5% of irrelevant rows and delivering **`100%` `Recall@10`** in **`0.29 ms`** on our live 2.5M-row run.

   ![Single-Stage Bitmap Pre-Filtering in AlloyDB SCaNN](./docs/assets/illustration-scann-bitmap-prefilter-en.png)

### 2.6 Lock-Free Queue (`FOR UPDATE SKIP LOCKED`) and `google_ml_integration`

When a borderline payment lands in `agent_triage_outbox`, multiple background AI workers poll it at the same time. Each row stores its forensic snapshot in **`JSONB`** (PostgreSQL's binary-indexed JSON format). With **`FOR UPDATE SKIP LOCKED`**, workers never block each other: if Worker #1 grabs Row #1, Worker #2 jumps straight to Row #2 in zero microseconds. The worker then invokes **Gemini 4 Hydrogen** on **Vertex AI** via **`google_ml_integration`** (`google_ml.predict_row`) or the Google GenAI Python **SDK** (*Software Development Kit*).

> **Bullet Points (What You Just Mastered in Section 2)**
> - **HTAP + CTE:** doing both the *cashier's* job (save 1 payment) and the *manager's* job (sum 40,000 receipts) at once, in **one single trip** to the database.
> - **SIMD Columnar Engine:** stores only the math columns vertically in RAM and adds 8 to 16 numbers per CPU tick without crowding out payment memory.
> - **`alloydb_scann` vs. HNSW:** HNSW walks blindly and throws away 99% of nodes on SQL filters; `alloydb_scann` applies a *bitmap* pre-filter before measuring angles.
> - **`FOR UPDATE SKIP LOCKED`:** a traffic-jam-free queue so multiple AI workers can grab cases in parallel.

---

## 3. Deep Dive: The Exact Mathematical and Vector Models Used to Detect Fraud

A critical question for both data scientists and engineers is: **What exact mathematical model generates the 64-dimensional vectors, how are attack mutations simulated, and what exact equations decide if a payment is fraudulent?**

We do not use random dummy numbers. In [`src/benchmark/feature_generator.py`](./src/benchmark/feature_generator.py) and [`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql), fraud detection is governed by **five explicit mathematical steps** that run in `< 0.2 ms` on the client and `~5.1 ms` per isolated query (`< 15 ms` in production on `8 vCPU`) inside the database.

![How an Instant Payment Becomes a 64-Number Behavioral Arrow](./docs/assets/illustration-math-6-to-64d-en.png)

### 3.1 Mathematical Step 1: The 6 Raw Behavioral Signals (`TransactionContext`)

Before a payment touches the database, we extract **6 core mathematical signals** (written in mathematical notation as $\mathbf{x} \in \mathbb{R}^6$, meaning a list $\mathbf{x}$ of 6 real decimal numbers) that summarize the physics and behavior of the transfer:

1. **$x_1$ = `velocity_ratio` (24h Spending Acceleration):** How fast the account is spending today divided by its normal daily average (Normal customer: `0.1 to 1.2`; Fraudulent attack: `2.5 to 6.0`).
2. **$x_2 = \sin\left(2\pi \cdot \frac{\text{hour}}{24}\right)$ and $x_3 = \cos\left(2\pi \cdot \frac{\text{hour}}{24}\right)$ (Cyclical Time-of-Day Encoding):**
   - *Why use Sine and Cosine for hours?* In plain numbers, `23:59` (hour 23) and `00:01` (hour 0) look 23 hours apart, even though they are only 2 minutes apart in the middle of the night. Mapping the 24-hour clock onto a unit circle using $(\sin \theta, \cos \theta)$ guarantees that late-night scam hours sit right next to each other geometrically.
3. **$x_4$ = `amount_zscore` (Statistical Z-Score of the Transfer Amount vs. the Business Category / "Corridor"):**
   - *What is a "Payment Corridor"?* In banking, a **corridor** (`merchant_category`, numbered `1..50` in our database) simply means the specific **type of business or payment channel**: for example, a bakery or coffee shop (where the 24-hour average transfer $\mu_{\text{corridor}}$ is \$15) versus a car dealership (where the 24-hour average is \$25,000). Sending \$8,000 at a car dealership is normal, but sending \$8,000 at a bakery is a major anomaly.
   - The **Z-Score** measures how many standard deviations ($\sigma$, the typical spread of values around the average) the current payment amount is above the normal 24-hour average ($\mu_{\text{corridor}}$) of that specific business category:

   ```math
   Z = \frac{\text{Amount} - \mu_{\text{corridor}}}{\sigma_{\text{corridor}}}
   ```

   (Normal customer: `-0.8 to +1.1`; Fraudulent attack: `+2.0 to +5.5` standard deviations above that category's norm).

   ![Clock on a Circle with Sine & Cosine and Z-Score at Bakery vs Car Dealership](./docs/assets/illustration-math-clock-zscore-en.png)

4. **$x_5$ = `geo_velocity_delta` (Physical Travel Speed / "Impossible Travel" in km/h):** The implied physical speed (distance divided by time) between the IP/GPS location of the user's previous transfer and the current one (Normal customer: `0 to 40 km/h`; Fraudulent attack via VPN or emulator jump across states/countries: `300 to 950 km/h`).
5. **$x_6$ = `graph_degree` (24h Fan-Out / Device and Receiver Multiplicity):** How many distinct hardware devices and receiver accounts have interacted with this sender in the last 24 hours (Normal customer: `1.0 to 2.5`; Mule or account-takeover ring: `4.0 to 12.0`).

### 3.2 Mathematical Step 2: Non-Linear 64-D Feature Expansion (`BehavioralVectorProjector.project`)

Think of this step like a **music equalizer**: we take 6 simple notes (the 6 clues above) and blend them into **64 rich chords**. Why? Because fraud rings hide in the *combination* of signals (like a huge amount *at 3:00 AM* *plus* impossible travel). Expanding into 64 numbers ($\mathbf{v} \in \mathbb{R}^{64}$), inspired by **Random Fourier Features (RFF)** and **Second-Order Polynomial Kernel Expansion**, lets a single **Cosine Distance (`<=>`)** inside PostgreSQL "hear" those curved combinations without calling a heavy neural network:

1. **Dimensions `0..47` (48 Multi-Frequency Fourier Harmonics):**
   For each of the 4 harmonic wave frequencies $f \in \{1, 2, 3, 4\}$, we compute both the sine and cosine of all 6 core signals scaled by $0.5 \cdot f$:

   ```math
   \mathbf{h}_f = \Big[\sin(0.5 \cdot f \cdot \mathbf{x}),\; \cos(0.5 \cdot f \cdot \mathbf{x})\Big] \in \mathbb{R}^{12} \quad \Longrightarrow \quad 4 \times 12 = 48\text{ dimensions}
   ```

   *Why this works mathematically:* By Bochner's theorem, expanding raw numbers into sine and cosine waves lets a simple dot product (Cosine Similarity) approximate a *Gaussian RBF kernel* (a smooth curved decision boundary from machine learning), turning curved boundaries into flat geometric angles.

   ![Fourier Equalizer: 6 Payment Clues Become 48 Waves](./docs/assets/illustration-math-fourier-waves-en.png)

2. **Dimensions `48..63` (16 Second-Order Cross-Terms and Hyperbolic Tangent Activations):**
   - **6 Pairwise Behavioral Interactions (`Dims 48..53`):** Multiply risk factors in pairs to capture joint spikes:

     ```math
     \text{velocity} \times \text{zscore},\quad \text{velocity} \times \text{geo},\quad \text{velocity} \times \text{degree},\quad \text{zscore} \times \text{geo},\quad \text{zscore} \times \text{degree},\quad \text{geo} \times \text{degree}
     ```

   - **6 Time-of-Night Cross-Modulations (`Dims 54..59`):** Cross the sine and cosine of the transaction hour with spending velocity, amount Z-score, and geographic travel speed:

     ```math
     \sin(\text{hour})\cdot\text{velocity},\; \cos(\text{hour})\cdot\text{velocity},\; \sin(\text{hour})\cdot\text{zscore},\; \cos(\text{hour})\cdot\text{zscore},\; \sin(\text{hour})\cdot\text{geo},\; \cos(\text{hour})\cdot\text{geo}
     ```

   - **4 Non-Linear Saturating Activations (`Dims 60..63`):** Apply the Hyperbolic Tangent ($\tanh$, a smooth S-shaped curve that squashes any extreme number into `[-1.0, +1.0]`) so a single outlier cannot dominate all 64 dimensions:

     ```math
     \tanh(\text{velocity} + \text{zscore}),\quad \tanh(\text{geo} + \text{degree}),\quad \sin(\text{velocity}\cdot\text{degree}),\quad \cos(\text{zscore}\cdot\text{geo})
     ```

   ![Cross-Terms and the Magic tanh Funnel in Dimensions 48..63](./docs/assets/illustration-math-cross-tanh-en.png)

3. **L2 Unit-Hypersphere Normalization (Every Arrow Has Length `1.0`):**
   Picture shrinking or stretching every arrow so they all have **the exact same length (`1.0`)**, making only their *direction* matter when comparing. We divide $\mathbf{r}$ by its Euclidean length $\lVert \mathbf{r} \rVert_2$:

   ```math
   \hat{\mathbf{v}} = \frac{\mathbf{r}}{\lVert \mathbf{r} \rVert_2} = \frac{\mathbf{r}}{\sqrt{\sum_{i=1}^{64} r_i^2}}, \quad \lVert \hat{\mathbf{v}} \rVert_2 = 1.0
   ```

   With length `1.0`, the **Cosine Similarity** between an incoming payment $\hat{\mathbf{v}}$ and a stored fraud signature $\hat{\mathbf{s}}$ inside `alloydb_scann` is the cosine of the angle $\theta$ between them:

   ```math
   \text{Cosine Similarity}(\hat{\mathbf{v}}, \hat{\mathbf{s}}) = 1.0 - d_{\cos}(\hat{\mathbf{v}}, \hat{\mathbf{s}}) = \hat{\mathbf{v}} \cdot \hat{\mathbf{s}} = \cos(\theta) \in [-1.0, 1.0]
   ```

   ![L2 Normalization: Every Arrow on the Unit Circle of Radius 1.0](./docs/assets/illustration-math-l2-normalize-en.png)

### 3.3 Mathematical Step 3: Gram-Schmidt Orthogonal Perturbation (`BehavioralVectorProjector.perturb`)

How do we test whether the database catches a fraudster who tweaks their bot to be exactly `96%` (`0.96`) or `78%` (`0.78`) similar to a known scam $\hat{\mathbf{u}}$? Think of the drawing below as using a **90° L-ruler and a protractor**: first we find a perpendicular arrow ($\hat{\mathbf{u}}_{\perp}$), then we blend both arrows in the exact ratio to tilt to the target angle!

![Gram-Schmidt Orthogonalization: Tilting an Arrow by an Exact Angle](./docs/assets/illustration-kid-gram-schmidt-en.png)

Instead of adding unpredictable random noise, `BehavioralVectorProjector.perturb(base_vec, target_cosine_similarity)` applies **Gram-Schmidt Orthogonalization** in 3 steps:
1. Draw a random 64-number vector $\mathbf{z} \sim \mathcal{N}(\mathbf{0}, \mathbf{I}_{64})$ (64 numbers sampled from a standard normal bell curve with mean `0` and standard deviation `1`).
2. Subtract its projection onto $\hat{\mathbf{u}}$ and normalize to get a unit arrow $\hat{\mathbf{u}}_{\perp}$ at an exact **90-degree angle** ($\hat{\mathbf{u}} \cdot \hat{\mathbf{u}}_{\perp} = 0$):

   ```math
   \mathbf{p} = \mathbf{z} - (\mathbf{z} \cdot \hat{\mathbf{u}})\hat{\mathbf{u}}, \quad \hat{\mathbf{u}}_{\perp} = \frac{\mathbf{p}}{\lVert \mathbf{p} \rVert_2}
   ```

3. Blend both arrows using the exact target cosine $\alpha = \cos(\theta)$:

   ```math
   \hat{\mathbf{v}}_{\text{mutated}} = \alpha \cdot \hat{\mathbf{u}} + \sqrt{1 - \alpha^2} \cdot \hat{\mathbf{u}}_{\perp}
   ```

   Because $\cos^2\theta + \sin^2\theta = 1$, $\hat{\mathbf{v}}_{\text{mutated}}$ stays length `1.0` with an **exact Cosine Similarity of $\alpha$** (to 6 decimal places) against $\hat{\mathbf{u}}$.

### 3.4 Mathematical Step 4: The Piecewise Hybrid Risk Scoring Equation (`hot_path_authorize.sql` and `RiskScoringPolicy`)

![How the Database Scores Risk and Fires the 0.92 Emergency Circuit Breaker](./docs/assets/illustration-math-risk-breaker-en.png)

Inside Stage 3 (`risk_eval`) of [`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql), the database combines the 24-hour Columnar Engine aggregates and the `alloydb_scann` top-10 vector similarity into the final risk score $R \in [0.0, 1.0]$ using a **Piecewise Linear + Non-Linear Circuit-Breaker Equation**:

```math
R = \min\left(1.0,\; \max\Big(\mathbb{I}(S_{\text{vec}} \ge 0.92) \cdot S_{\text{vec}},\;\; 0.35 \cdot V_{24h} + 0.15 \cdot D_{24h} + 0.50 \cdot S_{\text{vec}}\Big)\right)
```

Where each term is defined as:
- **$V_{24h} = \min\left(1.0,\; \frac{\text{24h spend}}{5,000,000}\right)$ (`sum_24h_cents`, Weight `0.35`):** Reaches its maximum of `1.0` when the sender's 24-hour cumulative spend in that merchant corridor reaches \$50,000 (`5,000,000` cents).
- **$D_{24h} = \min\left(1.0,\; \frac{\text{devices}_{24h}}{5.0}\right)$ (`distinct_devices_24h`, Weight `0.15`):** Reaches its maximum of `1.0` when 5 or more distinct hardware device fingerprints touch the account within 24 hours.
- **$S_{\text{vec}} = \max_{k \in 1..10} \Big(1.0 - d_{\cos}(\mathbf{v}_{\text{tx}},\; \mathbf{v}_{\text{sig},k})\Big)$ (`1.0 - (behavioral_vec <=> sig_k)`, Weight `0.50`):** The highest cosine similarity among the top-10 pre-filtered fraud signatures returned by `alloydb_scann`.
- **$\mathbb{I}(S_{\text{vec}} \ge 0.92) \cdot S_{\text{vec}}$ (The Self-Immunizing Circuit Breaker):**
  Here $\mathbb{I}(\text{condition})$ is an **indicator function** (a simple on/off switch that equals `1` if the condition inside the parentheses is true, and `0` if it is false). Notice why this switch is essential: suppose a brand-new mule account has \$0 spent in the last 24 hours ($V_{24h} = 0$) and only 1 device ($D_{24h} = 0.2$). Without the circuit breaker, even if its vector matched a confirmed fraud signature at $S_{\text{vec}} = 0.95$, the weighted sum alone would be $0.35(0) + 0.15(0.2) + 0.50(0.95) = 0.505$, which would mistakenly approve the fraud. Because of the $\max(\mathbb{I}(S_{\text{vec}} \ge 0.92) \cdot S_{\text{vec}}, \dots)$ override, any vector match $\ge 0.92$ bypasses the low velocity weights and jumps straight to $R = 0.95 \ge 0.85$ (`BLOCKED`).

**Decision Thresholds (`inserted_tx` CTE):**
- **$R < 0.60 \implies$ `'APPROVED'`** (Clean traffic passes in `~5.1 ms` per isolated query).
- **$0.60 \le R < 0.85 \implies$ `'FLAGGED_GREY_ZONE'`** (Enqueued into `agent_triage_outbox` for **Gemini 4 Hydrogen**).
- **$R \ge 0.85 \implies$ `'BLOCKED'`** (Known or immunized fraud blocked in `~5.1 ms` per isolated query).

> **Sharpen Your Pencil (15-Second Lightning Challenge!)**
>
> Imagine a scammer opens a **brand-new mule account** today. They have spent **\$0** in the last 24 hours ($V_{24h} = 0$) and are using just **1 phone** ($D_{24h} = 1/5 = 0.2$), but their behavioral arrow matches a scam Gemini discovered yesterday by **95%** ($S_{\text{vec}} = 0.95$).
> 1. What would the risk score be **without** the `0.92` circuit breaker?
> 2. What is the risk score **with** the `0.92` circuit breaker?
>
> <details>
> <summary><strong>Click here to check your answer</strong></summary>
>
> 1. **Without the circuit breaker:** $0.35(0) + 0.15(0.2) + 0.50(0.95) = 0 + 0.03 + 0.475 = \mathbf{0.505}$. Since `0.505 < 0.60`, the bank would **accidentally approve the scam**!
> 2. **With the circuit breaker ($\ge 0.92$):** since $0.95 \ge 0.92$, the circuit breaker snaps shut and jumps the score straight to **$\mathbf{0.95}$ (`BLOCKED`)**, stopping the mule account on its very first try!
>
> </details>

### 3.5 Mathematical Step 5: How Gemini 4 Hydrogen Evaluates Grey-Zone Cases and Immunizes the Database

![How Gemini Investigates Suspicious Payments and Vaccinates the Database](./docs/assets/illustration-math-gemini-vaccine-en.png)

When a payment lands in the grey zone ($0.60 \le R < 0.85$), how does **Gemini 4 Hydrogen (`gemini-4-hydrogen`)** evaluate it without slowing down the database?

In [`src/agent/triage_worker.py`](./src/agent/triage_worker.py), the evaluation runs in **Three Lock-Free Phases**:

#### Phase 1 (`< 2 ms` DB Transaction): Lock-Free Claiming (`FOR UPDATE SKIP LOCKED`)

`OutboxRepository.claim_pending_batch` grabs up to 5 `PENDING` rows from `agent_triage_outbox`, flips their status to `'PROCESSING'`, and **commits the transaction immediately**. Because the database transaction is closed before calling the AI model, **zero database locks are held** during the **`~3.5-second` (`3,543.6 ms`)** Gemini inference call (and if a worker crashes, `reclaim_stale_leases` resets rows older than 30 seconds back to `'PENDING'`).

#### Phase 2 (Stateless Vertex AI Inference — Live Measured `~3.5 s`): The Forensic Prompt and Structured JSON Reasoning

`FraudInferenceStrategy.build_prompt` constructs a forensic dossier from the 12-key `JSONB` payload captured at payment time:

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

The worker invokes **Gemini 4 Hydrogen** on Vertex AI's **`locations/global`** endpoint (`https://aiplatform.googleapis.com/v1/projects/<PROJECT_ID>/locations/global/publishers/google/models/gemini-4-hydrogen:generateContent`) with **`temperature = 0.0`** (deterministic analytical reasoning) and **`response_mime_type = "application/json"`** using either:
- **In-Database SQL (`InDatabaseVertexAIStrategy`):**
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
- **Google GenAI Python SDK (`GenAISDKStrategy`):** `client.models.generate_content(model="gemini-4-hydrogen", ...)`

**What Gemini 4 Hydrogen Evaluates and Returns (`AgentAssessment`):**
Gemini correlates three cross-signals that individually stayed below `0.85`:
1. **Corridor Outlier Ratio (`amount_cents / corridor_avg_cents`):** $\frac{850,000}{12,500} = 68\times$ above normal store spending in the last 24 hours;
2. **Account Drain Velocity and Device Sprawl:** `9` transfers operating the same account across `4` distinct hardware devices (`distinct_devices_24h = 4`);
3. **Sub-Threshold Vector Script Mutation:** A cosine similarity of `0.8120` shows the transaction behavior is 81.2% similar to a known fraud ring, indicating an attacker slightly altered their script parameters to slip beneath the `0.92` automatic circuit breaker.

In our live Vertex AI call (`3,543.6 ms`), **Gemini 4 Hydrogen** returned this exact JSON object, validated by the `AgentAssessment` model from **Pydantic** (a Python data-validation library):

```json
{
  "verdict": "CONFIRMED_FRAUD",
  "confidence_score": 0.88,
  "rationale": "Transaction amount (850000 cents) is 68x the 24h corridor average, occurring amid extreme 24h velocity (2450000 cents across 9 transactions) spanning 4 distinct devices indicative of account takeover or mule activity, reinforced by high cosine similarity (0.812) to known fraud signatures and an elevated composite risk score (0.741)."
}
```

#### Phase 3 (`< 5 ms` DB Transaction): Vector Deduplication and Self-Immunization

When `verdict == 'CONFIRMED_FRAUD'` and `confidence_score >= 0.85`, `OutboxRepository.complete_triage_and_immunize` marks the outbox row `'COMPLETED'` and inserts the payment's 64-D `behavioral_vec` into `fraud_signatures` (`source = 'GEMINI_AGENT_IMMUNIZED'`) with an **automatic `>= 0.98` cosine deduplication guard**:

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

This `WHERE NOT EXISTS` check guarantees that the `alloydb_scann` index is never polluted with duplicate vectors. On the next attempt by that fraud ring half a second later, $S_{\text{vec}} \to 1.00 \ge 0.92$, triggering the Step 4 circuit breaker in `~5.1 ms` per isolated query without calling Gemini again.

> **There Are No Dumb Questions**
>
> **Q: Why expand 6 clues into 64 numbers when 6 numbers already sound like enough?**
> **A:** Because scams hide in the *combination* of clues (for example, spending big *at 3:00 AM* *plus* impossible 900 km/h travel). Expanding into 64 dimensions with sine/cosine waves and cross-products lets a simple angle comparison inside the database spot those curved combinations without calling a heavy neural network!
>
> **Q: Does the database freeze while waiting ~3.5 seconds for Gemini?**
> **A:** Never! In Phase 1 (`< 2 ms`), the worker marks the row `'PROCESSING'` and closes the database transaction *before* calling Gemini. While Gemini thinks in the cloud, zero rows are locked and live payments keep flying through.

> **Bullet Points (Section 3 Math in 3 Lines)**
> - **6 clues → 64 numbers (length `1.0`):** turns behavior into a directional arrow ready for angle checks inside the database.
> - **`0.92` circuit breaker:** stops a brand-new mule account from slipping past with zero 24-hour spending history.
> - **Gemini vaccine (`~3.5 s` offline):** investigates grey-zone cases with zero DB locks and writes the new signature with `>= 0.98` deduplication.

---

## 4. What Is Analyzed in the Benchmark? (`p50`, `p95`, `p99`, `Recall@10`, and `Buffer Hit Ratio`)

When we compare **Google Cloud AlloyDB** and **AWS Aurora PostgreSQL 16**, we never rely on a simple "average" response time. Averages hide tail spikes: if 99 payments finish in 5 milliseconds and 1 payment freezes for 5 full seconds, the average looks fine, even though customers are experiencing timeouts.

Instead, our benchmark runner ([`src/benchmark/runner.py`](./src/benchmark/runner.py)) analyzes five concrete metrics on every run:

![What Are p50, p95, p99, and Recall@10 Explained Simply](./docs/assets/illustration-kid-p50-p99-recall-en.png)

1. **`p50` Latency (The Median Customer):** Imagine lining up 100 payments from fastest (#1) to slowest (#100). **`p50` is the time of payment #50 right in the middle.** When `p50 = 5.60 ms` (local AlloyDB Omni) or `26.71 ms` (4-vCPU cloud stress test at 486 TPS), half of all payments finished in that time or less.
2. **`p95` Latency (Peak Traffic Stability):** **`p95` is payment #95 in that line of 100.** When `p95 = 9.09 ms` (local AlloyDB Omni) or `73.99 ms` (4-vCPU cloud stress test), 95 out of every 100 payments finished in that time or less.
3. **`p99` Latency (The Worst-Case 1% Tail That Central Banks Enforce):** **`p99` is payment #99 out of 100**, representing the slowest 1% of requests when the database is under full `500 TPS` stress. Instant payment networks like PIX enforce strict service-level agreements on `p99`.
4. **`Recall@10` (Scam Detection Accuracy):** After the load test, the runner executes filtered vector queries twice: once using the vector index (`alloydb_scann` or `pgvector` HNSW), and once with indexes turned off (`SET LOCAL enable_indexscan = off`) so PostgreSQL checks every row to find the **true 10 closest fraud vectors**. `Recall@10` is the overlap between the two lists: **`1.00` means the index caught 10 out of the 10 real frauds**, whereas **`0.67` means the index missed roughly 1 in 3 real frauds**.
5. **`Shared Buffer Hit Ratio` (RAM Efficiency):** Measured directly from PostgreSQL's `pg_stat_database` catalog (`blks_hit` vs. `blks_read`), showing what percentage of page reads came straight from RAM without touching disk storage.

> **Bullet Points (How to Read Any Benchmark Like a Pro)**
> - **Ignore simple averages:** always look at **`p99`** — it tells you whether the unluckiest 1% of customers are stuck waiting at the checkout counter.
> - **Speed without accuracy is useless:** answering in 5 ms doesn't help if **`Recall@10`** is `0.67` and 1 out of every 3 real scams slips through the net!

---

## 5. Which Database Performed Better, and Why?

To guarantee a 100% fair race, both managed cloud clusters ran the **exact same version (`PostgreSQL 16.14`)** and **identical hardware capacity (`4 vCPU / 32 GB` RAM — `32 GiB` in AWS binary notation)**.

Both were loaded with the exact same **2,500,000 rows** (`2,000,000` payments in `payment_ledger` + `500,000` 64-D vectors in `fraud_signatures`), driven by a co-located `4 vCPU` VM in the same private VPC (`c3-standard-4` on GCP, `c7g.xlarge` on AWS) targeting **`500 TPS`** (`--duration 20` on archived cloud runs and `--duration 10` on local Docker; 90% HTAP authorizations + 10% live fraud inserts).

![Parity Benchmark Comparison: AlloyDB vs AWS Aurora](./docs/assets/architecture-comparison-alloydb-vs-aurora-en.png)

To prove *which specific technology* produces each gain, we executed a live **Ablation Study** (turning features on one at a time) across **4 progressive configurations** and all three filter widths (`50%`, `5%`, and `0.5%`). All 12 raw cloud JSON files are archived in [`results/gcp_live/`](./results/gcp_live) and [`results/aws_live/`](./results/aws_live), consolidated in [`results/benchmark_summary.md`](./results/benchmark_summary.md) and [`results/raw_telemetry.csv`](./results/raw_telemetry.csv).

### 5.1 Live Cloud Results Under the Strictest Filter (`0.5%` Selectivity, 2.5M Rows, Target 500 TPS)

| Live Cloud Configuration (`PostgreSQL 16.14`) | Hardware Specs | Vector Index Build (500k vecs) | TPS Achieved (Target: 500) | `p50` (Median) | `p95` (95% of traffic) | `p99` (Tail) | `Recall@10` (Fraud Accuracy) | Buffer Hit Ratio | What Happened in the Live Cloud Run? |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1. AWS Aurora PG 16.14** (`aurora-iopt1` + `pgvector` HNSW) | `db.r7g.xlarge` (4 vCPU / 32 GiB) | 97 s | 92.2 TPS | 377.93 ms | 510.10 ms | **567.21 ms** | **0.6733** (67.3%) | 100.0% | **CPU saturated at 18% of target TPS:** row-store scans + HNSW post-filtering miss 32.7% of real frauds. |
| **2. GCP AlloyDB (Row-Only)** (Columnar OFF + `pgvector` HNSW) | `4 vCPU / 32 GB` | ~9 min | 53.9 TPS | 667.27 ms | 918.37 ms | **1,058.39 ms** | **0.6733** (67.3%) | 100.0% | Without the Columnar Engine and SCaNN, AlloyDB hits the same row-store & HNSW ceiling. |
| **3. GCP AlloyDB + Columnar Engine** (Columnar ON + `pgvector` HNSW) | `4 vCPU / 32 GB` | ~9 min | 466.5 TPS | 32.70 ms | 95.26 ms | **133.39 ms** | **0.6733** (67.3%) | 100.0% | **Columnar Engine jumps throughput 8.6x and cuts `p99` 7.9x**, but HNSW still misses 32.7% of real frauds. |
| **4. GCP AlloyDB + Columnar + `alloydb_scann` (Winner)** | `4 vCPU / 32 GB` | **7 s** | **486.0 TPS** | **26.71 ms** | **73.99 ms** | **95.54 ms** | **1.0000** (100%) | 100.0% | **5.3x higher TPS, 14.1x faster `p50`, 5.9x faster `p99` than Aurora** with **100% fraud accuracy**. |

**Quick decode of these numbers:**
- **Isolated query (`EXPLAIN ANALYZE` on 2.5M rows):** **`~5.1 ms`** end-to-end (`4.24 ms` native SIMD Columnar Scan with `0` shared buffer hits + `0.11 ms` sender velocity + `0.29 ms` `alloydb_scann` pre-filter + `0.4 ms` ACID insert).
- **Production sizing for `p99 < 20 ms`:** Under sustained `500 TPS` on `4 vCPU`, CPU queuing lifts `p99` to `95.54 ms` on AlloyDB (vs. `567.21 ms` on Aurora). Scaling to `8 vCPU` (or running `200 TPS` on `4 vCPU`) keeps `p99 < 20 ms`.
- **Local Docker Compose (`225k` rows, [`results/docker_live/`](./results/docker_live)):** AlloyDB Omni delivered **`p99 = 9.49–13.63 ms`** (`100%` Recall@10) vs. PostgreSQL 16 + `pgvector` HNSW at **`p99 = 33.21–37.21 ms`** (`67.33–68.67%` Recall@10).

### 5.2 Why Configuration #4 (`AlloyDB + Columnar Engine + alloydb_scann`) Won Across Every Metric

1. **14.1x Faster Median (`26.71 ms` vs. `377.93 ms`) and 5.9x Faster `p99` (`95.54 ms` vs. `567.21 ms`):** Comparing Row #2 (`1,058.39 ms`) with Row #3 (`133.39 ms`) isolates the **Columnar Engine**: pushing the `40,050`-row 24-hour scan into SIMD stripes cut `p99` by **7.9x** and lifted throughput by **8.6x**.
2. **100.0% Fraud Accuracy vs. 67.33% on AWS Aurora (`Recall@10`):** Comparing Row #3 (`0.6733`) with Row #4 (`1.0000`) isolates **`alloydb_scann`**: single-stage bitmap pre-filtering ran in **`0.29 ms`** (`Num Filtered: 0`), dropped `p99` to **`95.54 ms`**, and rescued 100% of real frauds.
3. **5.3x Higher Throughput and 13.9x Faster Index Build:** Even on AWS Aurora's fastest storage tier (**`aurora-iopt1`**), Aurora plateaued at **92.2 TPS** scanning row *heap* pages (PostgreSQL's main row-storage area) and contending on HNSW locks. Building the 500k-vector `alloydb_scann` (`sq8`) index took **`7 s`** vs. **`97 s`** for HNSW on Aurora (`134.67 s` vs. `252.84 s` total seed).

### 5.3 Full Live Cloud Selectivity Sensitivity Matrix (`50%`, `5%`, and `0.5%` Filters on 2.5M Rows)

Look at how all three `pgvector` HNSW configurations (`aurora_io_hnsw`, `alloydb_row_hnsw`, `alloydb_col_hnsw`) stay trapped around **`67%–71%` Recall@10** across every filtered regime, whereas **`alloydb_col_scann` achieves `93.3%–100.0%` Recall@10 and gets *faster* as the SQL filter narrows** (`p99` drops from `212.31 ms` at `50%` down to `95.54 ms` at `0.5%` because the pre-filter bitmap shrinks the candidate set):

| Mode (`PostgreSQL 16.14`, `4 vCPU / 32 GB`) | Filter Selectivity | SQL Predicate (`selectivity_bucket`) | TPS Achieved | `p50` (ms) | `p95` (ms) | `p99` (ms) | `Recall@10` (Accuracy) | Columnar Scan | Vector Index |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `aurora_io_hnsw` (AWS Aurora I/O-Opt) | `50.0%` (Broad) | `<= 500` | 92.5 | 378.72 | 508.00 | 554.21 | 0.7000 (70.0%) | `false` | `pgvector_hnsw` |
| `aurora_io_hnsw` (AWS Aurora I/O-Opt) | `5.0%` (Medium) | `<= 50` | 92.7 | 375.61 | 508.32 | 561.66 | 0.6867 (68.7%) | `false` | `pgvector_hnsw` |
| `aurora_io_hnsw` (AWS Aurora I/O-Opt) | `0.5%` (Strict) | `<= 5` | 92.2 | 377.93 | 510.10 | 567.21 | 0.6733 (67.3%) | `false` | `pgvector_hnsw` |
| `alloydb_row_hnsw` (GCP Row-Only) | `50.0%` (Broad) | `<= 500` | 56.7 | 614.14 | 828.15 | 927.20 | 0.7067 (70.7%) | `false` | `pgvector_hnsw` |
| `alloydb_row_hnsw` (GCP Row-Only) | `5.0%` (Medium) | `<= 50` | 51.6 | 692.19 | 1,003.10 | 1,114.98 | 0.7000 (70.0%) | `false` | `pgvector_hnsw` |
| `alloydb_row_hnsw` (GCP Row-Only) | `0.5%` (Strict) | `<= 5` | 53.9 | 667.27 | 918.37 | 1,058.39 | 0.6733 (67.3%) | `false` | `pgvector_hnsw` |
| `alloydb_col_hnsw` (GCP Columnar + HNSW) | `50.0%` (Broad) | `<= 500` | 253.9 | 38.89 | 692.51 | 946.02 | 0.7133 (71.3%) | `true` | `pgvector_hnsw` |
| `alloydb_col_hnsw` (GCP Columnar + HNSW) | `5.0%` (Medium) | `<= 50` | 485.0 | 27.79 | 75.39 | 96.80 | 0.6800 (68.0%) | `true` | `pgvector_hnsw` |
| `alloydb_col_hnsw` (GCP Columnar + HNSW) | `0.5%` (Strict) | `<= 5` | 466.5 | 32.70 | 95.26 | 133.39 | 0.6733 (67.3%) | `true` | `pgvector_hnsw` |
| **`alloydb_col_scann` (GCP Winner)** | **`50.0%` (Broad)** | **`<= 500`** | **317.2** | **91.19** | **177.74** | **212.31** | **0.9333 (93.3%)** | **`true`** | **`alloydb_scann`** |
| **`alloydb_col_scann` (GCP Winner)** | **`5.0%` (Medium)** | **`<= 50`** | **470.2** | **37.94** | **88.29** | **120.03** | **1.0000 (100%)** | **`true`** | **`alloydb_scann`** |
| **`alloydb_col_scann` (GCP Winner)** | **`0.5%` (Strict)** | **`<= 5`** | **486.0** | **26.71** | **73.99** | **95.54** | **1.0000 (100%)** | **`true`** | **`alloydb_scann`** |

> **There Are No Dumb Questions**
>
> **Q: Wait a second! If a single AlloyDB query took `~5.1 ms`, why is `p99` in the cloud table `95.54 ms`?**
> **A:** Picture a supermarket cashier who scans your items in **5 seconds**. If 1 shopper arrives at a time, you're out in 5 seconds! But if **32 shoppers** sprint to the same cashier at the exact same instant (our `500 TPS` stress test on just `4 vCPU`), the last person in line waits for the people ahead. The wild part is that on the exact same 4 vCPUs, AlloyDB handled **486 TPS (`p99 = 95.54 ms`)** while AWS Aurora jammed at **92.2 TPS (`p99 = 567.21 ms`)**! With `8 vCPU` in production (or `200 TPS` on `4 vCPU`), the queue vanishes and `p99` stays right under `20 ms`.
>
> **Q: How did `alloydb_scann` get *faster* when the SQL filter got stricter (`212.31 ms` at `50%` → `95.54 ms` at `0.5%`)?**
> **A:** Because bitmap pre-filtering shrinks the pile *before* measuring any vector angles! It's like hunting for a rare trading card: if someone first hands you only the 2,500 holographic cards (`0.5%`) instead of 250,000 (`50%`), you find the right one way faster — and without missing a single match (`100%` `Recall@10`).

### 5.4 Four "Aha!" Engineering Clues Discovered on Managed AlloyDB

> **Beginner Note:** This subsection is an **optional deep dive for database engineers (DBAs)**. If you are new to databases, feel free to jump straight to **Section 5.5 (Costs)** without missing a beat!

Running the full 2.5M-row benchmark on managed Google Cloud AlloyDB 16.14 surfaced four practical tweaks that delivered a **12.7x** per-query speedup:

1. **Use `now()`, never `clock_timestamp()`, in Columnar Engine filters:**
   - *The Trap:* `clock_timestamp()` is `VOLATILE` (re-evaluated per row), blocking SIMD pushdown.
   - *The Fix & Payoff:* Switching to `now() - INTERVAL '24 hours'` (`STABLE`) unlocked `"Columnar cache search mode": "native"`.
2. **Split `COUNT(DISTINCT)` out of the columnar aggregation (`12.7x` speedup):**
   - *The Trap:* Counting distinct devices inside the 40,050-row scan forced a `3.4 MB` in-memory `quicksort` (`64.8 ms`).
   - *The Fix & Payoff:* Splitting [`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql) into `corridor_stats` (pure SIMD `AVG` in **`4.24 ms`**, `0` shared buffer hits) + `sender_velocity` (`Index Only Scan` in **`0.11 ms`**) cut isolated query time to **`~5.1 ms`**.
3. **Set `scann.vector_node_min_dimensionality = 32` for 64-D vectors:**
   - *The Trap:* Single-stage bitmap pre-filtering defaults to vectors with `>= 100` dimensions.
   - *The Fix & Payoff:* Setting `min_dimensionality = 32` + `custom_scan_replace_prefilter = on` unlocked **`Bitmap assisted pre-filtering`** in **`0.29 ms`** at **`100%` `Recall@10`**.
4. **Run `VACUUM ANALYZE` before populating the Columnar Engine:**
   - *The Trap:* Bulk `COPY` rows must be marked *all-visible* to load 100% into columnar stripes.
   - *The Fix & Payoff:* `VACUUM ANALYZE` loaded `96,777 / 96,777` blocks into columnar stripes; on managed AlloyDB, use `ALTER DATABASE ... SET` (instead of `ALTER SYSTEM SET`) and `google_ml.create_model(..., model_auth_type => 'alloydb_service_agent_iam')`.

### 5.5 Cost Analysis (FinOps): What Each Scenario Costs (Made Crystal Clear!)

Imagine renting two delivery trucks: **Truck A** costs almost the same per day as **Truck B**, yet **carries 5.3 times more packages per trip**! In cloud finance (**FinOps**), comparing databases strictly by "4-vCPU sticker price" hides what really matters: **what it costs to deliver the same `500 payments per second`**.

Before looking at the numbers, learn **3 cloud-billing words** in 15 seconds:
- **1 Node (Zonal) vs. HA (2 Nodes):** with **1 node**, if that server fails, the database goes down; with **HA (High Availability)**, two nodes work as a pair — if one fails, the standby takes over automatically.
- **On-Demand:** pay by the hour with zero commitment (like buying single gym day passes).
- **3-Year Commit (and what "Amortized" means):** commit for 3 years to unlock ~45% to ~52% savings. On **Google Cloud (CUD)** you pay **\$0 upfront** (monthly bill only). On **AWS (Reserved Instance *Partial Upfront*)**, you pay an **upfront fee** on Day 1 plus smaller monthly bills. To compare apples to apples, we spread the upfront across all 36 months: $\text{Amortized Monthly Cost} = (\text{Upfront} + 36 \times \text{Monthly}) \div 36$.

![FinOps Cost Analysis: AlloyDB vs AWS Aurora in Production](./docs/assets/illustration-finops-costs-en.png)

Every figure below comes directly from the official calculators on **November 20, 2026** (`us-central1` on GCP and `us-east-2` on AWS, USD for `730 hrs/month`), summing **100% of billable Terraform resources** ([`terraform/gcp_alloydb/main.tf`](./terraform/gcp_alloydb/main.tf) and [`terraform/aws_aurora/main.tf`](./terraform/aws_aurora/main.tf)):
- **GCP (`us-central1`):** AlloyDB (`N2`, storage + backup) + `c3-standard-4` VM (`50 GiB` SSD) + Public `Cloud NAT`. *(VPC, Firewall, Peering, IAM = `$0`.)*
- **AWS (`us-east-2`):** Aurora (`aurora-iopt1`, `$0` I/O) + `c7g.xlarge` EC2 (`8 GB gp3`) + `1` Public IPv4. *(VPC, IGW, Security Group, IAM, AWS SSM = `$0`.)*

#### Step 1 — On Identical `4 vCPU / 32 GB` Hardware, Which One Costs Less? (Scenarios A & B)

Even comparing **identical hardware against identical hardware** (`10 GB` storage), AlloyDB is already cheaper — while delivering **5.3x more payments per second** (`486.0 TPS` vs. `92.2 TPS`):

| Scenario (`4 vCPU / 32 GB`) | Pricing Model | GCP AlloyDB (`us-central1`) | AWS Aurora (`us-east-2`) | Difference (AlloyDB) |
| :--- | :--- | :---: | :---: | :---: |
| **A. 1 Node (No HA)** | On-Demand (Monthly / Annual) | **\$614.66 / mo** (\$7,376/yr) | \$636.90 / mo (\$7,643/yr) | **-3.5%** *(and **5.5x** lower/TPS)* |
| **A. 1 Node (No HA)** | 3-Year Commit (Amort. / 3Y Total) | **\$297.33 / mo** (\$10,704 over 3Y) | \$341.48 / mo (\$12,293 over 3Y) | **-12.9%** *(\$0 vs. \$5,194 upfront)* |
| **B. 2 Nodes (HA)** | On-Demand (Monthly / Annual) | **\$1,069.24 / mo** (\$12,831/yr) | \$1,161.77 / mo (\$13,941/yr) | **-8.0%** *(and **5.7x** lower/TPS)* |
| **B. 2 Nodes (HA)** | 3-Year Commit (Amort. / 3Y Total) | **\$515.53 / mo** (\$18,559 over 3Y) | \$630.00 / mo (\$22,680 over 3Y) | **-18.2%** *(\$0 vs. \$10,387 upfront)* |

#### Step 2 — What About Sustaining `~500 TPS` in Production with HA? (Scenario C)

Here is where the gap explodes! In our live benchmark:
- **AlloyDB** only needs to double to **`8 vCPU / 64 GB` HA** to keep `p99 < 20 ms` at `500 TPS` (with `100%` Recall@10).
- **AWS Aurora** saturated at `92.2 TPS` on `4 vCPU`. To deliver `~500 TPS` (~5.3x more), it must jump to a giant **`32 vCPU / 256 GiB`** cluster (`2x db.r7g.8xlarge` HA) — and still remains capped at `67.3%` Recall@10!

| Scenario C (`~500 TPS` with HA, `50 GB`) | GCP AlloyDB `8 vCPU` HA (`us-central1`) | AWS Aurora `2x r7g.8xlarge` HA (`us-east-2`) | How Much AlloyDB Saves |
| :--- | :---: | :---: | :---: |
| **On-Demand — Monthly** | **\$1,994.41 / mo** | \$8,514.57 / mo | **\$6,520 / mo (-76.6%)** |
| **On-Demand — Annual** | **\$23,932.92 / yr** | \$102,174.84 / yr | **\$78,242 / yr (4.3x lower)** |
| **3-Year Commit — Day 1 Upfront** | **\$0.00** | **\$83,090.80** | **\$83,091 less on Day 1** |
| **3-Year Commit — Avg Monthly (Amort.)** | **\$967.93 / mo** | \$4,678.21 / mo *(\$2,370 + upfront/36)* | **\$3,710 / mo (-79.3%)** |
| **3-Year Commit — Annual** | **\$11,615.14 / yr** | \$56,138.49 / yr | **\$44,523 / yr (4.8x lower)** |
| **3-Year Commit — 3-Year Total** | **\$34,845.42** | \$168,415.48 | **\$133,570 saved!** |

![Monthly Cost and Effective Cost per TPS Comparison Chart — AlloyDB vs AWS Aurora](./docs/assets/chart-finops-monthly-vs-tps-en.png)

#### Step 3 — Verify Every Cent in the 12 Official Calculator Links (Snapshot from November 20, 2026)

*All 12 links below (6 GCP + 6 AWS) can be opened, audited, and customized directly in the official calculators (prices reflect **November 20, 2026**, subject to future provider updates):*

- **Google Cloud Pricing Calculator (`us-central1` — On-Demand & 3-Year CUD with \$0 upfront):**
  - Scenario A (1-Node Zonal `4 vCPU`): [On-Demand (\$614.66/mo)](https://cloud.google.com/products/calculator?hl=en&dl=CjhDaVJrT0dSak1tRmpOaTFqTXpNNExUUmpaVFl0T0RFNE55MWxNVEUzWWpZM016Y3lNVGtRQVE9PRAIGiQyM2JmNzcxZi0xMzczLTQzMTAtYTY0My00ODAxZGExN2IyMWY%3D) | [3-Year CUD (\$297.33/mo)](https://cloud.google.com/products/calculator?hl=en&dl=CjhDaVF3TW1GaU1qa3daaTB5TldJNUxUUmpNREV0WWpRMVlpMWpZekZsTWpZMU1qWmlOVEFRQVE9PRAIGiRmOGU2Njc4Yi1kZWRmLTRiYTAtOTk5OS1mYjQ5Yzc5ZDFhODU%3D)
  - Scenario B (2-Node HA `4 vCPU`, Terraform): [On-Demand (\$1,069.24/mo)](https://cloud.google.com/products/calculator?hl=en&dl=CjhDaVJsWlRBeU9UaGlOQzAwTnpRM0xUUXpaRFV0WVRFell5MDNNbU15WW1KbE16WTFabVlRQVE9PRAIGiRjYzNhYjU4ZS1lZmUyLTQxNDQtOTVlMS03MGZjOGZhZTZiOGU%3D) | [3-Year CUD (\$515.53/mo)](https://cloud.google.com/products/calculator?hl=en&dl=CjhDaVE0WVRCaU1HWmpNQzAwT1RZNExUUTFZVGd0WWpJNU5TMHpPVEZpTlRoaFltVTROV0VRQVE9PRAIGiQ0ZDc5ZTljMy1iMjU3LTQxNTEtODkwMS0wZWQwNmYyMjhmZDA%3D)
  - Scenario C (Production `8 vCPU` HA `p99 < 20 ms`): [On-Demand (\$1,994.41/mo)](https://cloud.google.com/products/calculator?hl=en&dl=CjhDaVF6T1RFeE1XSXpaUzAwTXpjeUxUUmhNRFV0T0RGbVl5MHdPV0V6WWpFNU1EUTFNaklRQVE9PRAIGiQzZWViZWZjMi01N2E5LTQ2ZWUtODFmZC0yZThjNmM3MWVjNjM%3D) | [3-Year CUD (\$967.93/mo)](https://cloud.google.com/products/calculator?hl=en&dl=CjhDaVJpWkRjNU1XUTFNUzA0TkRabExUUmxNbVF0WWpoaU55MHhZMkprWW1KaU0yWTVORGdRQVE9PRAIGiQ0N2JjMGUyZC0wYThmLTQ1MTEtYjgxZC0zYzYzNTQ0NGQxYTI%3D)
- **AWS Pricing Calculator (`us-east-2` — Ohio, Aurora I/O-Optimized `aurora-iopt1` — On-Demand & 3-Year RI Partial Upfront + 3Y EC2 Savings Plan):**
  - Scenario A (1-Node Single-AZ `db.r7g.xlarge`, Terraform): [On-Demand (\$636.90/mo)](https://calculator.aws/#/estimate?id=38fb890f514ca93ae34dcabd8bccc1c267458bdf) | [3-Year Commit (\$341.48/mo amort. — \$5,193.50 upfront + \$197.22/mo)](https://calculator.aws/#/estimate?id=c8ef48373dcdcdccb0d2332f6c92e988767f41be)
  - Scenario B (2-Node HA `2x db.r7g.xlarge`): [On-Demand (\$1,161.77/mo)](https://calculator.aws/#/estimate?id=6f7e0efac3a774acabcdd028d9591ccf249418ba) | [3-Year Commit (\$630.00/mo amort. — \$10,387.00 upfront + \$341.47/mo)](https://calculator.aws/#/estimate?id=ae7e7df82f26800a4b8b4fc506336604ac8ac2f3)
  - Scenario C (Production `~500 TPS` HA `2x db.r7g.8xlarge`): [On-Demand (\$8,514.57/mo)](https://calculator.aws/#/estimate?id=3cb24d50f202b6e3964190118b90445aab492c15) | [3-Year Commit (\$4,678.21/mo amort. — \$83,090.80 upfront + \$2,370.13/mo)](https://calculator.aws/#/estimate?id=8cee4ea78ea3e4123935bd874d26d3cf9fba1753)

> **There Are No Dumb Questions**
>
> **Q: Do I have to spend \$1,000 to reproduce this benchmark in my own account?**
> **A:** Not at all! Because cloud billing is hourly and we tear everything down right after with `make destroy-cloud`, running the full lab for **2 hours** costs roughly **\$2.93 on GCP** and **\$1.74 on AWS** — **under \$5.00 total**!
>
> **Q: Why did AlloyDB save \$133,570 over 3 years in Scenario C?**
> **A:** Two reasons working together: (1) the Columnar Engine + `alloydb_scann` give AlloyDB **5.3x more TPS per vCPU**, so it only needs **8 vCPUs** where Aurora needs **32 vCPUs**; and (2) Google Cloud's **3-Year CUD** gives ~51.5% off with **\$0 upfront**.

> **Bullet Points (The Final Scoreboard from Section 5)**
> - **Performance (`4 vCPU / 32 GB`, `0.5%` filter):** AlloyDB delivered **`5.3x` higher TPS** (`486.0` vs. `92.2`), **`5.9x` lower `p99`** (`95.54 ms` vs. `567.21 ms`), and **`100%` vs. `67.3%`** fraud accuracy.
> - **Production Costs (`~500 TPS` with HA, 3-Year Commit):** AlloyDB **`8 vCPU` HA** costs **\$34,845 over 3 years** (**\$967.93/mo**, \$0 upfront) vs. **\$168,415 over 3 years** (**\$4,678.21/mo** amortized) on AWS Aurora — **\$133,570 saved (`-79.3%`, `4.8x` cheaper)**!

---

## 6. The Big Picture: Tracing One Payment End-to-End

### 6.1 Inside the AlloyDB Cluster (Everything Runs In-Database on the Hot Path)

Notice in the diagram below that AlloyDB never calls an external data warehouse (like BigQuery) or an external vector service during a payment. The **OLTP Row Store**, the **Columnar Engine**, the **`alloydb_scann` index**, and the **`agent_triage_outbox` table** all live inside the same **AlloyDB for PostgreSQL** cluster. Only the asynchronous worker reaches out to **Vertex AI (Gemini 4 Hydrogen)**.

![Two-Speed AlloyDB Architecture](./docs/assets/architecture-two-speed-htap-alloydb-en.png)

### 6.2 The Self-Immunizing Loop (`~5.1 ms` Spinal Reflex vs. `~3.5 s` Cortical Agent)

Trace the diagram below with your finger across three lanes: on the **top lane**, a mutated scam lands in the grey zone in milliseconds; on the **middle lane**, the Python worker calls **Gemini 4 Hydrogen** (`~3.5 s`) with zero DB locks and writes the 64-D "vaccine"; on the **bottom lane**, seconds later, the next attack slams into the green shield and gets blocked automatically!

![Spinal Reflex vs Cortical Agent Loop](./docs/assets/self-immunizing-spinal-reflex-vs-cortical-en.png)

### 6.3 Full Sequence Diagram (Architecture + Step-by-Step Math)

To see **who computes each formula and in which millisecond**, the sequence diagram below connects all 21 steps from the actual codebase: from the 6 clues and 64-D expansion on the client (`< 0.2 ms`), through the SIMD scan, `alloydb_scann`, and risk equation + `0.92` circuit breaker inside AlloyDB (`~5.1 ms`), all the way to lock-free **Gemini 4 Hydrogen** triage (`~3.5 s`) and self-immunization (`>= 0.98`):

![Full Architecture Sequence Diagram Including Step-by-Step Calculations](./docs/assets/architecture-sequence-diagram-with-math-en.png)

---

## 7. Popping the Hood: A Guided Tour of the Code

Think of this repository as a **4-room lab**: the **SQL Vault** (`sql/`), the **Payment Simulator** (`src/benchmark/`), the **AI Detective** (`src/agent/`), and the **Cloud Blueprint** (`terraform/`). Everything is built with **Object-Oriented Programming (OOP)** in Python and modular SQL:

```text
sprintalloydb/
├── docker-compose.yml                  # Local AlloyDB Omni 16 container (4 GB shm + 4096 MB Columnar + SCaNN)
├── Makefile                            # One-command shortcuts (make up-local, make test, etc.)
├── pyproject.toml                      # Python 3.11+ package dependencies, pytest & ruff settings
├── sql/
│   ├── 01_schema.sql                   # Creates payment_ledger, fraud_signatures & agent_triage_outbox
│   ├── 02_setup_alloydb.sql            # Enables Columnar Engine & builds the alloydb_scann index
│   ├── 03_setup_aurora_baseline.sql    # Builds the pgvector HNSW index for AWS Aurora parity
│   └── queries/
│       └── hot_path_authorize.sql      # The 5-stage SQL CTE (~5.1 ms per isolated query)
├── src/
│   ├── benchmark/
│   │   ├── feature_generator.py        # UUIDv7, 64-D vector projection, risk math & workload generator
│   │   ├── seeder.py                   # High-speed COPY loader & Strategy Pattern engine initializers
│   │   ├── runner.py                   # 500 TPS async load driver, EXPLAIN analyzer & Recall@10 evaluator
│   │   └── reporter.py                 # Markdown & CSV report generator
│   └── agent/
│       └── triage_worker.py            # 3-phase lock-free worker invoking Gemini 4 Hydrogen
├── terraform/
│   ├── gcp_alloydb/                    # Provisions 4 vCPU / 32 GB AlloyDB + c3-standard-4 VM on GCP
│   └── aws_aurora/                     # Provisions 4 vCPU / 32 GiB Aurora I/O-Optimized + c7g.xlarge on AWS
└── tests/                              # Automated unit and integration test suites
```

### 7.1 Detailed Breakdown of the SQL Layer and Database ER Diagram (`sql/`)

The Entity-Relationship (ER) diagram below shows the three tables inside the database (`PAYMENT_LEDGER`, `AGENT_TRIAGE_OUTBOX`, and `FRAUD_SIGNATURES`), every column and data type, which columns are accelerated by the **AlloyDB Columnar Engine** and **`alloydb_scann`**, and how they connect during the self-immunizing loop:

![Database Entity-Relationship (ER) Diagram](./docs/assets/database-er-diagram-en.png)

1. **[`sql/01_schema.sql`](./sql/01_schema.sql): The Three Core Tables**
   - **`payment_ledger`:** Stores every instant transfer (`tx_id UUID PRIMARY KEY`, `sender_account_id`, `receiver_account_id`, `device_fingerprint`, `merchant_category`, `selectivity_bucket`, `amount_cents`, `tx_timestamp`, `behavioral_vec vector(64)`, `composite_risk_score`, and `decision`).
   - **`fraud_signatures`:** Stores confirmed 64-D fraud patterns (`signature_id UUID PRIMARY KEY`, `merchant_category`, `selectivity_bucket`, `created_at`, `source` in `'SEED_CORPUS' | 'CHURN_STREAM' | 'GEMINI_AGENT_IMMUNIZED'`, `behavioral_vec vector(64)`, and `pattern_description`).
   - **`agent_triage_outbox`:** Stores suspicious grey-zone payments (`outbox_id BIGSERIAL PRIMARY KEY`, `tx_id` with `ON DELETE CASCADE`, `status` in `'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'`, `payload JSONB`, `agent_verdict`, `agent_rationale`, `created_at`, and `processed_at`) along with a partial index `idx_outbox_pending_poll` (`WHERE status IN ('PENDING', 'PROCESSING')`) so background workers find pending items and recover stalled leases in sub-millisecond time.

2. **[`sql/02_setup_alloydb.sql`](./sql/02_setup_alloydb.sql): AlloyDB Columnar Engine and `alloydb_scann` Setup**
   - Loads `alloydb_scann`, `google_columnar_engine`, and `google_ml_integration`.
   - Creates the shared B-Tree indexes (`idx_ledger_velocity_btree`, `idx_ledger_sender_24h`, and `idx_fraud_sig_filters`) and builds `idx_fraud_sig_scann`: `CREATE INDEX idx_fraud_sig_scann ON fraud_signatures USING scann (behavioral_vec cosine) WITH (num_leaves = 100, quantizer = 'sq8');`.
   - Configures 8 database-level SCaNN parameters via `ALTER DATABASE postgres SET` (including `scann.vector_node_min_dimensionality = 32`, `scann.custom_scan_replace_prefilter = on`, `scann.num_leaves_to_search = 15`, and `scann.pre_reordering_num_neighbors = 50`) to enable single-stage bitmap pre-filtering (`Custom Scan (vector scan)`), and calls `SELECT google_columnar_engine_add('public.payment_ledger', ...)` to pin the analytical columns in the SIMD columnar cache.

3. **[`sql/03_setup_aurora_baseline.sql`](./sql/03_setup_aurora_baseline.sql): Fair AWS Aurora Baseline**
   - Creates the identical relational B-Tree indexes (`idx_ledger_velocity_btree` and `idx_ledger_sender_24h`) on `payment_ledger`, drops `idx_fraud_sig_filters` (`DROP INDEX IF EXISTS`) so Aurora evaluates true HNSW post-filtering, and builds the `pgvector` HNSW index (`USING hnsw (behavioral_vec vector_cosine_ops) WITH (m = 16, ef_construction = 64)`) on `fraud_signatures`.

4. **[`sql/queries/hot_path_authorize.sql`](./sql/queries/hot_path_authorize.sql): Inside the 5-Stage Single-Trip CTE**
   - **Stage 1 (`corridor_stats` + `sender_velocity` -> `velocity_window`):** Separates the 24-hour corridor average (`corridor_stats` using `now() - INTERVAL '24 hours'` for pure SIMD Columnar Engine aggregate pushdown) from the sender's individual 24-hour velocity (`sender_velocity` using `Index Only Scan` on `idx_ledger_sender_24h` for `sum_24h_cents`, `tx_count_24h`, and `distinct_devices_24h`).
   - **Stage 2 (`vector_anomaly`):** Queries `fraud_signatures` with `WHERE merchant_category = $3 AND selectivity_bucket <= $4 ORDER BY behavioral_vec <=> $2::vector(64) LIMIT 10`, converting cosine distance into similarity `1.0 - distance`.
   - **Stage 3 (`risk_eval`):** Computes `composite_score` using the weighted formula (`35%` 24h velocity + `15%` device churn + `50%` vector similarity) plus the **circuit-breaker override**: if `max_vec_sim >= 0.92`, `GREATEST(...)` immediately elevates the score to `max_vec_sim` (`>= 0.92`), guaranteeing that any transaction matching a known fraud signature is blocked even if the account has zero prior spending today.
   - **Stage 4 (`inserted_tx`):** Inserts the transfer into `payment_ledger` with `decision = 'BLOCKED'` (`>= 0.85`), `'FLAGGED_GREY_ZONE'` (`0.60..0.8499`), or `'APPROVED'` (`< 0.60`).
   - **Stage 5 (`outbox_enqueue`):** Conditionally inserts a 12-field `JSONB` forensic payload into `agent_triage_outbox` when `decision = 'FLAGGED_GREY_ZONE'`, returning `(tx_id, composite_risk_score, decision, outbox_id)` to the caller in one atomic transaction.

### 7.2 Detailed Breakdown of the Python Classes (`src/`)

1. **[`src/benchmark/feature_generator.py`](./src/benchmark/feature_generator.py): Synthetic Traffic, UUIDv7, and 64-D Vector Math**
   - **`UUIDv7Generator`:** Generates time-ordered 128-bit UUIDs (RFC 9562 UUIDv7) where the first 48 bits store the Unix timestamp in milliseconds. Unlike random UUIDv4 keys that scatter writes across random disk pages and fragment B-Tree indexes, UUIDv7 keys append sequentially at the right edge of the B-Tree.
   - **`BehavioralVectorProjector`:** Deterministically maps a `TransactionContext` into a 64-dimensional `numpy.float64` vector (`list[float]`) normalized to unit length (`||v||_2 = 1.0`). It also provides `perturb(base_vec, target_cosine_similarity)` (exposed on the facade as `create_perturbed_vector`) to simulate fraud rings mutating their scripts to an exact cosine similarity around known attack centroids.
   - **`RiskScoringPolicy`:** Encapsulates the composite risk formula and decision thresholds (`APPROVED`, `FLAGGED_GREY_ZONE`, `BLOCKED`), mirrored against the SQL CTE and verified by unit tests in [`tests/unit/test_risk_scoring_math.py`](./tests/unit/test_risk_scoring_math.py).
   - **`PaymentWorkloadGenerator`:** Orchestrates synthetic PIX/FedNow payment requests (`generate_payment_request`), normal and anomalous behavioral contexts (`generate_random_context`), and SQL parameter binding (`bind_hot_path_sql` and `PaymentRequest.to_sql_params`).

2. **[`src/benchmark/seeder.py`](./src/benchmark/seeder.py): High-Speed Bulk Seeding and Engine Strategy Pattern**
   - **`EngineInitializerStrategy` (Abstract Base Class):** Defines how each database engine configures its extensions and indexes *after* bulk data is loaded:
     - **`AlloyDBEngineInitializer`:** Selected via `--engine-mode alloydb`; executes [`sql/02_setup_alloydb.sql`](./sql/02_setup_alloydb.sql) (enabling the Columnar Engine and building the `alloydb_scann` index), with automatic fallback to [`sql/03_setup_aurora_baseline.sql`](./sql/03_setup_aurora_baseline.sql) when run against standard PostgreSQL.
     - **`AuroraBaselineEngineInitializer`:** Selected via `--engine-mode aurora`; executes [`sql/03_setup_aurora_baseline.sql`](./sql/03_setup_aurora_baseline.sql).
   - **`DatabaseSeeder`:** Streams millions of ledger rows and fraud signatures directly into PostgreSQL memory using `cursor.copy("COPY ... FROM STDIN")` in 25,000-row batches, runs `ANALYZE` so the query planner and SCaNN k-means quantizer have fresh statistics, and invokes the chosen `EngineInitializerStrategy`.

3. **[`src/benchmark/runner.py`](./src/benchmark/runner.py): Asynchronous 500 TPS Runner and Plan/Recall Evaluators**
   - **`DatabaseStatsCollector` and `DatabaseBlockCounters`:** Query `pg_stat_database` before and after the timed run to compute the exact `shared_buffer_hit_ratio` delta.
   - **`ExplainPlanAnalyzer`:** Executes `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` *outside* the timed loop and inspects the JSON plan tree to confirm `Custom Scan (Columnar Scan)` and `idx_fraud_sig_scann` vs. `idx_fraud_sig_hnsw`.
   - **`RecallEvaluator`:** Measures `Recall@10` across probe vectors per selectivity bucket (`500`, `50`, `5`) by comparing index results against exact brute-force ground truth (`SET LOCAL enable_indexscan = off; SET LOCAL enable_bitmapscan = off;`).
   - **`HTAPBenchmarkRunner`:** Before every columnar run, executes `VACUUM payment_ledger` and `google_columnar_engine_refresh('public.payment_ledger')`; uses `psycopg_pool.AsyncConnectionPool` to sustain `500 TPS` (90% `hot_path_authorize.sql` executions + 10% `fraud_signatures` churn inserts with `source = 'CHURN_STREAM'`), measures `Recall@10` with `num_probes = 15`, and records `p50`, `p95`, and `p99` latencies into a validated `BenchmarkResult` Pydantic model.

4. **[`src/agent/triage_worker.py`](./src/agent/triage_worker.py): Three-Phase Lock-Free Autonomous Agent**
   - **`OutboxRepository`:** Handles all SQL operations on `agent_triage_outbox` and `fraud_signatures` (`reclaim_stale_leases`, `claim_pending_batch`, and `complete_triage_and_immunize`).
   - **`FraudInferenceStrategy` (*Strategy Pattern*, where each class provides a swappable way to call the AI):**
     - **`InDatabaseVertexAIStrategy`:** Calls **Gemini 4 Hydrogen** from inside AlloyDB using `SELECT google_ml.predict_row(model_id => 'gemini-4-hydrogen', ...)`.
     - **`GenAISDKStrategy`:** Calls **Gemini 4 Hydrogen** (`gemini-4-hydrogen`) via the `google-genai` Python SDK with `response_mime_type="application/json"` and validates the response via `AgentAssessment`.
     - **`DeterministicLocalStrategy`:** Evaluates payloads locally without cloud credentials for offline testing and continuous integration (and automatically serves as a safe fallback if a remote AI call fails).
   - **`AgentTriageWorker.process_once`:** Executes the three-phase cycle:
     1. **Phase 1 (Claim):** Reclaims stale leases older than 30 seconds, claims a batch of `PENDING` rows with `FOR UPDATE SKIP LOCKED`, sets `status = 'PROCESSING'`, and commits immediately (`< 2 ms`) so no row locks are held during AI inference.
     2. **Phase 2 (Infer):** Runs `FraudInferenceStrategy.evaluate` completely outside any database transaction (`~3.5 s` live measured on Vertex AI `gemini-4-hydrogen`).
     3. **Phase 3 (Immunize):** Calls `complete_triage_and_immunize` to mark the outbox row `'COMPLETED'` and, when `verdict == 'CONFIRMED_FRAUD'` and `confidence_score >= 0.85`, inserts the 64-D vector into `fraud_signatures` (`source = 'GEMINI_AGENT_IMMUNIZED'`) with the `>= 0.98` cosine deduplication check.

5. **[`src/benchmark/reporter.py`](./src/benchmark/reporter.py): Telemetry Aggregator and Markdown/CSV Exporter**
   - **`CsvTelemetryExporter` and `MarkdownReportFormatter`:** Aggregate the telemetry JSON files (`--inputs`) and generate [`results/benchmark_summary.md`](./results/benchmark_summary.md) and [`results/raw_telemetry.csv`](./results/raw_telemetry.csv).

> **There Are No Dumb Questions**
>
> **Q: Why does the code use `UUIDv7` instead of the famous `UUIDv4` to give every payment an ID?**
> **A:** `UUIDv4` is 100% random — it's like shoving new sheets into random pages of a binder, constantly splitting and scrambling the B-Tree index! **`UUIDv7`** starts with the exact millisecond timestamp, so every new payment appends neatly at the end of the binder — much faster to write and search.

---

## 8. Step-by-Step Guide: Choose Your Own Adventure!

You don't need a cloud account to play with this project! Pick the path that fits your time:
- **10 seconds (no Docker, no cloud):** run the tests and rebuild the report from our archived live cloud data (Step 8.2).
- **5 minutes on your laptop:** spin up **AlloyDB Omni** for free in Docker (Step 8.3).
- **Full cloud race:** provision **Google Cloud AlloyDB** and **AWS Aurora** with Terraform (Steps 8.4 & 8.5).

### 8.1 Prerequisites

1. **Python 3.11+**
2. **Docker and Docker Compose** (allocate at least 10 GB of RAM in Docker Desktop settings so the container can reserve `4gb` of shared memory, `shm_size`, and `4096 MB` for the local Columnar Engine)
3. **Terraform >= 1.5** (only required when deploying the cloud clusters on Google Cloud and AWS)
4. Copy the environment configuration template (which sets default **DSN** connection URLs, where *DSN* stands for *Data Source Name*, the standard URL containing the database username, password, host address, and port):
   ```bash
   cp .env.example .env
   ```

### 8.2 Step 1: Run the Automated Tests and Generate Reports Offline (Takes 10 Seconds)

You can verify all code, risk math, and report generators immediately on your machine without starting Docker or cloud clusters:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the automated unit & integration tests and linter
pytest -v
ruff check src/ tests/

# Consolidate the 12 live cloud JSON files into results/benchmark_summary.md and results/raw_telemetry.csv
python -m src.benchmark.reporter \
  --inputs "./results/gcp_live/run_*.json" "./results/aws_live/run_*.json" \
  --output-dir ./results
```

### 8.3 Step 2: Run Locally with AlloyDB Omni (Docker Compose)

**AlloyDB Omni** is the downloadable Docker container edition of Google Cloud AlloyDB that runs locally on your laptop and includes the **Columnar Engine** and **`alloydb_scann`**.

1. **Start the local AlloyDB Omni 16 container:**
   ```bash
   make up-local
   ```
2. **Seed 200,000 ledger rows and 25,000 fraud signatures:**
   ```bash
   make seed-local
   ```
3. **Run the 500 TPS benchmark suite across 50%, 5%, and 0.5% selectivities:**
   ```bash
   make benchmark-local
   ```
4. **Run the autonomous triage worker:**
   - Local deterministic mode (no API key needed, processes one batch and exits):
     ```bash
     make worker-local
     ```
   - Live **Gemini 4 Hydrogen** via Google GenAI SDK:
     ```bash
     export GEMINI_API_KEY="your-api-key"
     export GEMINI_MODEL_ID="gemini-4-hydrogen"
     python -m src.agent.triage_worker \
       --dsn "postgresql://postgres:postgres@localhost:5432/postgres" \
       --agent-mode genai_sdk \
       --model-id gemini-4-hydrogen \
       --once
     ```
5. **Shut down the local container when finished:**
   ```bash
   make down-local
   ```

### 8.4 Step 3: Run on Google Cloud (AlloyDB `4 vCPU / 32 GB` + Vertex AI Gemini 4 Hydrogen)

1. **Provision the AlloyDB cluster and co-located `c3-standard-4` VM:**
   ```bash
   gcloud auth application-default login
   cd terraform/gcp_alloydb
   terraform init
   terraform apply \
     -var="project_id=YOUR_GCP_PROJECT_ID" \
     -var="region=us-central1" \
     -var="db_password=YOUR_SECURE_DB_PASSWORD"
   ```
2. **Connect to the `c3-standard-4` VM (`gcloud compute ssh`), clone this repository, install dependencies (`pip install -e .`), read the private IP from `terraform output`, then seed and run the ablation suite:**
   ```bash
   export PG_DSN="postgresql://postgres:YOUR_SECURE_DB_PASSWORD@<ALLOYDB_PRIMARY_IP>:5432/postgres"

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

### 8.5 Step 4: Run the AWS Aurora PostgreSQL 16 Parity Test (`db.r7g.xlarge` I/O-Optimized)

1. **Provision the AWS Aurora I/O-Optimized (`PostgreSQL 16.14`) cluster and `c7g.xlarge` EC2 load generator** (an AWS virtual server accessed via AWS SSM, *Systems Manager*, a secure terminal without opening SSH port 22):
   ```bash
   cd terraform/aws_aurora
   terraform init
   terraform apply \
     -var="aws_region=us-east-2" \
     -var="engine_version=16.14" \
     -var="db_password=YOUR_SECURE_DB_PASSWORD"
   ```
2. **Connect to the `c7g.xlarge` instance via AWS SSM, clone the repo, install (`pip install -e .`), grab the endpoint from `terraform output`, and run `aurora_io_hnsw`:**
   ```bash
   export AURORA_DSN="postgresql://postgres:YOUR_SECURE_DB_PASSWORD@<AURORA_WRITER_ENDPOINT>:5432/postgres"

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
3. **Tear down both cloud environments right after collecting telemetry:**
   ```bash
   make destroy-cloud
   ```

> **Final Bullet Points (To Keep in Your Pocket)**
> - **Reflex + Brain:** never stall a `50 ms` payment waiting `3.5 s` for an AI model — let the database react in milliseconds while **Gemini 4 Hydrogen** vaccinates the database in the background.
> - **Columnar Engine + `alloydb_scann`:** on identical `4 vCPU / 32 GB` hardware (2.5M rows), AlloyDB delivered **`5.3x` higher TPS**, **`5.9x` lower `p99`**, and **`100%` fraud accuracy** vs. **`67.3%`** on AWS Aurora.

---

## 9. References & Further Reading

Every link below was directly verified and provides deeper technical, mathematical, or architectural coverage of the concepts used in this benchmark.

### 9.1 Databases, HTAP, Google Cloud AlloyDB, and AWS Aurora

- **HTAP (Hybrid Transactional/Analytical Processing):** [Hybrid transactional/analytical processing — Wikipedia](https://en.wikipedia.org/wiki/Hybrid_transactional/analytical_processing) — Overview of running OLTP writes and OLAP analytics simultaneously in one database.
- **Google Cloud AlloyDB Columnar Engine:** [About the AlloyDB columnar engine — Google Cloud Documentation](https://docs.cloud.google.com/alloydb/docs/columnar-engine/about) — Architecture of the in-memory hybrid columnar store and SIMD vectorized scans.
- **AlloyDB `alloydb_scann` (Creating & Tuning ScaNN Indexes):** [Create a ScaNN index — Google Cloud Documentation](https://docs.cloud.google.com/alloydb/docs/ai/create-scann-index) — Official guide to `num_leaves`, `quantizer = 'sq8'`, and filtered vector indexing in AlloyDB.
- **AlloyDB Vector Embeddings:** [Store vector embeddings — Google Cloud Documentation](https://docs.cloud.google.com/alloydb/docs/ai/store-embeddings) — Storing and querying `vector(n)` embeddings in AlloyDB for PostgreSQL.
- **AlloyDB `google_ml_integration` (`google_ml.create_model` / `predict_row`):** [Register and call remote AI models in AlloyDB overview — Google Cloud Documentation](https://docs.cloud.google.com/alloydb/docs/ai/model-endpoint-overview) — Registering and invoking remote AI models directly from SQL.
- **AWS Aurora I/O-Optimized (`aurora-iopt1`):** [Amazon Aurora storage — AWS Documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Overview.StorageReliability.html) — Amazon Aurora's distributed storage architecture and I/O-Optimized tier.
- **PostgreSQL 16 — WAL & ACID Durability:** [Write-Ahead Logging (WAL) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/wal-intro.html) — How PostgreSQL guarantees crash recovery and ACID durability.
- **PostgreSQL 16 — MVCC:** [Concurrency Control (MVCC) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/mvcc-intro.html) — Multi-Version Concurrency Control allowing concurrent readers and writers without blocking.
- **PostgreSQL 16 — CTEs (`WITH ... AS`):** [WITH Queries (Common Table Expressions) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/queries-with.html) — Composing multi-stage SQL pipelines in a single network round-trip.
- **PostgreSQL 16 — Lock-Free Queues (`FOR UPDATE SKIP LOCKED`):** [SELECT Locking Clause (`SKIP LOCKED`) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE) — Non-blocking queue polling pattern used by the triage worker.
- **PostgreSQL 16 — `JSONB`:** [JSON Types (`jsonb`) — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/datatype-json.html) — Decomposed binary JSON storage used for the forensic outbox payload.
- **PostgreSQL 16 — B-Tree Indexes:** [B-Tree Indexes — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/btree.html) — Standard balanced sorted tree index powering relational predicates and bitmap pre-filtering.
- **PostgreSQL 16 — `pg_stat_database` (Shared Buffer Hit Ratio):** [The Cumulative Statistics System — PostgreSQL 16 Documentation](https://www.postgresql.org/docs/16/monitoring-stats.html) — `blks_hit` and `blks_read` counters used to compute RAM hit ratio.
- **Transactional Outbox Pattern:** [Pattern: Transactional outbox — Microservices.io](https://microservices.io/patterns/data/transactional-outbox.html) — Architectural foundation for `agent_triage_outbox` decoupling hot-path writes from async AI agents.

### 9.2 Vector Search, Indexes (`SCaNN` vs. `HNSW`), and Metrics (`p99` & `Recall@10`)

- **SCaNN & Anisotropic Vector Quantization (Original Paper):** [Guo et al. (2020) — *Accelerating Large-Scale Inference with Anisotropic Vector Quantization* (arXiv:1908.10396)](https://arxiv.org/abs/1908.10396) — Google Research paper introducing the mathematical foundations of SCaNN.
- **SCaNN Open-Source Implementation:** [google-research/scann — GitHub](https://github.com/google-research/google-research/tree/master/scann) — Official open-source reference library by Google Research.
- **HNSW (Original Paper):** [Malkov & Yashunin (2018) — *Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs* (arXiv:1603.09320)](https://arxiv.org/abs/1603.09320) — Seminal paper defining HNSW graph indexes.
- **`pgvector` Extension for PostgreSQL:** [pgvector/pgvector — GitHub](https://github.com/pgvector/pgvector) — Open-source PostgreSQL extension providing `vector(n)`, `<=>` cosine distance, and HNSW indexing.
- **Vector Search Benchmarking Standard (`Recall@10`):** [ANN-Benchmarks](https://ann-benchmarks.com/index.html) — Industry-standard methodology evaluating QPS vs. `Recall@10` across approximate nearest neighbor indexes.
- **Precision and Recall:** [Precision and recall — Wikipedia](https://en.wikipedia.org/wiki/Precision_and_recall) — Mathematical definition of recall (fraction of true relevant items retrieved).
- **Tail Latency (`p95` and `p99`):** [Jeffrey Dean & Luiz André Barroso (2013) — *The Tail at Scale* (Google Research / Communications of the ACM)](https://research.google/pubs/the-tail-at-scale/) — Classic systems paper explaining why large-scale services must optimize `p99` tail latency rather than averages.
- **SIMD Vectorized CPU Execution:** [Single instruction, multiple data (SIMD) — Wikipedia](https://en.wikipedia.org/wiki/Single_instruction,_multiple_data) — Data-level parallel CPU instructions (AVX-512 / ARM NEON) powering both the Columnar Engine and SCaNN.

### 9.3 Mathematical & Statistical Foundations of the Fraud Model

- **Random Fourier Features (Non-Linear 64-D Expansion):** [Ali Rahimi & Benjamin Recht (2007) — *Random Features for Large-Scale Kernel Machines* (NeurIPS)](https://proceedings.neurips.cc/paper/2007/hash/013a006f03dbc5392effeb8f18fda755-Abstract.html) — NeurIPS Test-of-Time paper behind approximating non-linear kernels via sine and cosine harmonics.
- **Bochner's Theorem:** [Bochner's theorem — Wikipedia](https://en.wikipedia.org/wiki/Bochner%27s_theorem) — Theoretical foundation linking shift-invariant kernels (such as RBF) to Fourier transforms.
- **Cosine Similarity (`<=>`):** [Cosine similarity — Wikipedia](https://en.wikipedia.org/wiki/Cosine_similarity) — Angular similarity between $L_2$-normalized unit vectors.
- **Gram-Schmidt Orthogonalization:** [Gram–Schmidt process — Wikipedia](https://en.wikipedia.org/wiki/Gram%E2%80%93Schmidt_process) — Geometric orthogonalization used to synthesize mutated attack vectors at exact target cosine similarities.
- **Z-Score (Standard Score):** [Standard score — Wikipedia](https://en.wikipedia.org/wiki/Standard_score) — Statistical measure of how many standard deviations a payment amount lies from its corridor mean.
- **k-means Clustering (SCaNN Centroids):** [k-means clustering — Wikipedia](https://en.wikipedia.org/wiki/K-means_clustering) — Clustering algorithm used to partition vectors into SCaNN tree leaves around learned centroids.
- **Hyperbolic Tangent (`tanh`):** [Hyperbolic functions — Wikipedia](https://en.wikipedia.org/wiki/Hyperbolic_functions) — Smooth saturating non-linear activation used in dimensions `60..63` to bound extreme outliers within `[-1, +1]`.

### 9.4 Identifier Standards, AI Models, and Instant Payment Rails

- **UUIDv7 (Time-Ordered Identifiers):** [IETF RFC 9562 — Universally Unique IDentifiers (UUIDs)](https://www.rfc-editor.org/info/rfc9562/) — Official standard for time-ordered UUIDv7 primary keys preventing B-Tree page fragmentation.
- **Google Gemini Models on Google Cloud:** [Google models — Google Cloud Documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/google-models) — Official documentation for Google's managed Gemini model family.
- **PIX (Brazil):** [Pix — Banco Central do Brasil](https://www.bcb.gov.br/estabilidadefinanceira/pix) — Official Central Bank of Brazil portal for the PIX instant payment system.
- **FedNow (United States):** [FedNow Service — Federal Reserve Financial Services](https://www.frbservices.org/financial-services/fednow-service/) — Official Federal Reserve portal for the FedNow instant payment rail.
