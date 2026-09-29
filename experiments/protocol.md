# Experiment protocol

Status: COMPLETE DESIGN UNDER FINAL CONFIGURATION REVIEW — 2026-09-29. This snapshot precedes public certification-performance measurements. `experiments/config.json` is the complete case/parameter specification. The eventual immutable freeze timestamp, source/config identities and independent review reference are recorded in `experiments/freeze.json`. Exploratory records under `research/safe_contraction/` remain separate.

## Claim and evidence scope

The candidate claim is a sparse, degree-weighted collective certificate for modularity-preserving fusion. It preserves the discrete optimum when accepted, with a resolution bound and a quantitative contraction-loss bound. It does not certify recovery of a latent community truth or promise that an arbitrary heuristic improves after contraction.

| Claim | Evidence | Decisive comparison or limitation |
| --- | --- | --- |
| Degree-weighted anchor reassignment cancels the exterior null term | Formal proof, independent exact expected-gain checks | Uniform anchor and generic signed-affinity contrast; neither variant universally dominates the other |
| Accepted blocks preserve an optimal modularity partition | Validated matrix acceptance, exact partition enumeration, numerical MILP diagnostics, quotient objective equality | Boundary equality, positive-degree overlap, zero-degree exclusion, quotient self-loops |
| Sparse verification avoids dense exterior affinity storage | Independently dense/sparse deviation equality and measured time/memory scaling | Full pair-distance checker and exact C-subinstance oracle on matching/hub families |
| Collective certificates add useful contraction coverage | Same graph/resolution/candidate budget, new method and published cheap criteria | Proportional twins, singleton dominance, refined positive-closure, strict almost-clique, recursive named-criterion composition, selected KaPoCE rules, and matched full solver on its predeclared supported inputs |
| Preprocessing has operational value | Total discovery+verification+quotient+downstream cost, repeated solver workloads | Unreduced input, independently timed solver, zero-benefit outcomes retained |

## Model and implementation

- Undirected, symmetric, nonnegative adjacency; all public evaluated edge weights are integers. Original inputs are loopless after documented processing. Quotients retain doubled internal mass on the diagonal and preserve full degrees.
- Zero-degree vertices remain individual vertices and are excluded from certified blocks.
- The proposed full certificate uses a sparse coordinate median of normalized exterior adjacency rows, including implicit zero entries, and exact rational acceptance after a floating screening calculation. All decisions labeled certified must use the validated path. A floating-only implementation is an ablation, not the reported full method.
- Exact block-size cap64, dense diagnostic cap64 and screen tolerance1e-10. Oversized bank entries are recorded as cap exclusions before assembly. The complete forest includes their smaller descendants regardless of any criterion decision; singleton leaves are unchanged. Integer-weight validation pilots support this implemented cap. Arbitrary binary-float weights incur larger exact bit costs and are outside the public timing claim.
- Candidate generator: NetworkX Louvain at proposal resolution1, then a full certificate-independent internal normalized-Laplacian bisection forest, minimum size2; size<4 stops. Split disconnected interiors into components first. A deterministic balanced vertex-order fallback is logged if the sparse eigensolver fails. The same bank is fixed before evaluating any criterion; no certificate outcome changes discovery. Candidate generation is a heuristic and does not contribute to correctness.
- Bisection uses D_full^-1/2 L(A_K) D_full^-1/2, with full input degrees. Dense eigh applies at size<=64; otherwise ARPACK uses k2/SM, tolerance1e-7, maxiter10000 and a fixed linspace(1,2) initial vector. Canonicalize the first nonzero vector sign, sort vector/sqrt(d) with vertex-id ties and split at half the vertex count. Candidate order and bank identity are retained before checking. No bank-count cap applies.
- Seed sets and candidate budgets are identical when comparing criteria on supplied candidate blocks. Whole-graph preprocessors are also reported separately because they use different discovery mechanisms.

## Data and preprocessing

Development-only graphs already inspected: weighted Karate Club, Les Misérables, Florentine families, Davis affiliation, one dense planted graph. Their observed performance must not select a favorable confirmatory subset.

Confirmatory public set: SNAP ca-GrQc, ca-HepTh, email-Eu-core, facebook_combined, ca-CondMat and p2p-Gnutella08. All six inputs are archived with download provenance in `data/registry.json`. Convert directed inputs to undirected simple unions, remove self-loops, collapse reciprocal/duplicate rows and retain all listed endpoints. Relabel by ascending original id. Processed counts are stored in `data/processed-metadata.json`. Report full graph and coverage restricted to its deterministic largest connected component under the same original S and certificates; break LCC size ties by its smallest vertex id. This supplement does not recompute an LCC-only objective.

No department labels or planted labels are used to claim community-recovery accuracy. The objective is modularity optimization.

The explicit controlled grid contains45 cases: matching cliques k3/4/5/8/16/32/64; common-hub k6; one loopless uniform-advantage control at gamma1/8; three heterogeneous weighted planted graphs;24 independently noisy planted graphs; six common-profile scaling graphs; and three exploratory proved-failure private-leaf cases. Exact parameters and independent generation/noise/relabel seeds are listed in config. Generation never resamples based on a certificate. The six profile graphs are supplied-block computation studies with no candidate-bank or native benchmark. Other controlled cases use the independent bank and a separately labeled supplied-reference-block panel. The latent blocks in that panel never enter discovery or recovery-accuracy claims.

## Baselines and configuration contract

| Baseline | Source and implementation | Status |
| --- | --- | --- |
| No contraction | Same downstream solver and complete graph objective | Implemented9 paired seeds and discovery-incumbent control |
| Singleton dominant attractive edge | Lange 2018/2019; exact sparse rank-one row sum | Implemented and exact-validated; public strict union |
| Refined positive-closure attractive edge | Lange 2019 Theorem4 Eq21; sparse positive-neighbor intersections | Implemented and exact-validated; public strict union |
| Degree-proportional twins | SEA2022 Twin Simple, fixed degree-ratio modularity subcase | Implemented across all public graphs; weak components have audited anchor compatibility |
| Uniform collective contrast | Project-derived mechanism reference, exact rational PSD | Supplied controlled/development panels; n/exterior cap150, block cap64 |
| Full pair-distance collective test | Project-derived sparse exact penalties with null cancellation | Exact rational supplied-block reference, cap64; full k×k pair assembly cost retained |
| Almost-clique block | Böcker2011 Rule4, same supplied K | Exact positive-internal Stoer-Wagner mincut; public same-bank strict coverage; weak individual controlled panel |
| Positive-closure spanning pairs | Lange2019 Theorem4 Eq19, same supplied K | All fixed star pairs must be strict for whole-K acceptance; block64, closure128, signed-cut enumeration16; weak pairs individual |
| KaPoCE weighted preprocessing rules | Pinned author code; recursive unchanged star/P3/twin/ICX/heavy routines | Implemented selected weighted preprocessing, not full solver; exact integer conversion with exclusions |
| Recursive cheap-criterion composition | Strict pair and almost-clique rules plus compatible profile twins, current quotient rechecks | Implemented until fixed point with exact integer quotient; same original bank mapped each round, cap64, no round limit or cannot-link fixes |
| Full KaPoCE solver | Complete unchanged solver/search API with overflow instrumentation | Implemented matched original/proposed-quotient calls, exact original-Q validation,30-second guard per arm; overflow becomes numeric-domain exclusion |
| C-subinstance isolation oracle | SEA2022 Theorem2; exact enumeration or numerical MILP | Exact active limit10; numerical active limit50/time5s/tolerance1e-8; score equality includes ties |

Selected KaPoCE routines are not the whole solver. No rounded modularity-cost conversion is allowed. Integer overflow or an unsupported input is recorded as unavailable, never as zero reduction. Exact-oracle timeouts are unresolved, never false-negative decisions. The strongest applicable cheap rules and supplied-block oracles must be retained even when they eliminate a proposed separation example.

C-subinstances retain the original global B on incident pairs and zero exterior–exterior terms. An exterior vertex with no positive B to any K member can be freely isolated and omitted without changing this subinstance optimum. The guarded oracle stratum includes every controlled reference block and every development bank block of size2..64. Numerical matches remain uncertified. Compare the isolated-K internal score with the optimum/bounds, including ties; solver-returned labels alone do not decide isolation.

The common-hub matching family is known to be solved by the actual star/P3 implementation; retain it as a mechanism/cost diagnostic and negative separation outcome. Do not present it as KaPoCE coverage superiority. The native adapter's n<=2000 and exact integer arithmetic restrictions make it unavailable on most primary full graphs. Report it only on predefined compatible controlled/development strata; a sparse exact proportional-twin criterion remains required on all public graphs.

Published pair criteria default to strict inequalities for safe simultaneous union. Their weak equality cases require sequential quotient rechecks and are reported separately. New exact block certificates permit safe overlap union by the audited optimal-anchor lemma; do not confuse the composition policies when comparing coverage.

The exact degree-proportional twin components inherit compatibility from the two-vertex weighted-anchor condition: their normalized exterior profiles coincide and their internal modularity affinity is nonnegative. This exception does not authorize union of unrelated weak published pair/block decisions.

## Measurements

- Accepted-block and removed-vertex coverage; reduction in stored off-diagonal edges; additional contraction beyond each baseline and overlap of their certified decisions.
- Discovery time, floating screen time, exact validation time, quotient time, downstream solver time and their sum. Report peak memory and all size-cap/eigensolver/overflow failures.
- Modularity after lifting, numerical-oracle status and numerical optimality gap. Preserve incumbent and numerical upper bound when the MILP times out; neither zero gap nor a float bound is an exact proof.
- Diagnostic resolution threshold distribution and exact-verified contraction over gamma in {0.5,1,2}; for an interval, verify its maximum gamma with rational LDL using the same fixed graph/block quantities. Any reported rigorous endpoint/loss bound must have a validated acceptance calculation; raw eigenvalue-derived gamma_max and regret remain diagnostics.
- Seeds 0,1,2 for proposal discovery. For runtime repetition, reuse fixed graph/partition/candidates so stochastic discovery is not confused with solver variability. Execution order is alternated and recorded; do not report a significance test from deterministic replicate timings.

Downstream schedule: Louvain seeds10..18, prefix workloads1/3/9, each at gamma in {0.5,1,2}; the discovery partition is a feasible incumbent for both arms. Report Q_discovery, Q_unreduced_downstream and Q_reduced_lifted, and best-of(discovery, downstream) for each arm. Charge discovery once to preprocessing; also show discovery+unreduced downstream to isolate the contraction effect. The cold unreduced timing remains downstream-only. Numerical complete-transitivity MILP runs on predefined development inputs n<=150 with a 60-second limit at each gamma; reported time includes model construction.

Measured pipeline time includes CSR preparation and eager full-graph rational degree caching, proposal discovery, refinement, screens, exact validation, exact quotient, downstream conversion, incumbent objective evaluation, solver time, partition-to-label conversion, objective evaluation and lifting. The discovery control includes proposal discovery and original incumbent evaluation. Each reported single-resolution workload charges common graph/discovery preparation once; the case process actually reuses that setup across gamma values. Other public criteria supply coverage and checker-time evidence; matched downstream speedups currently concern the proposed pipeline versus unreduced/discovery controls. Raw data loading is shared; summary diagnostics, bank/decision serialization and file writing are reporting overhead excluded from compute speedups and explicitly recorded as such. Public peak RSS covers the entire case process and retained shared objects, rather than a falsely isolated checker peak.

One benchmark child runs at a time with frozen BLAS/OpenMP thread variables set to1. Public paired solver execution alternates the order by dataset index, proposal seed, gamma index and downstream index. Isolated scaling runs use three timing replicates with cyclic method order and one separate tracemalloc memory replicate; memory-profiled timings are excluded. Report complete-process RSS and traced allocations with their different semantics. Dense exterior scaling is a noncertifying assembly diagnostic, not a full exact algorithm comparator. Profile cases use gamma1, where the fixed common-profile family has a positive production margin; the exact full-pair reference remains a separately labeled arithmetic policy.

For NetworkX quotient execution use a self-loop of weight A'_aa/2 and off-diagonal weight A'_ab. Core/MILP adjacency remains A' unchanged. Verify this convention against exact original lifted modularity before public runs. It prevents double-counting quotient internal mass in NetworkX's degree convention.

## Mechanism ablations

1. Uniform versus degree-weighted anchor: tests null cancellation and degree heterogeneity, including the known reverse-dominance example.
2. Zero versus sparse median versus anchor reference: tests removal of common exterior adjacency and center cost.
3. Pair-distance versus center bound: measures certification conservatism on blocks small enough for the exact pair computation.
4. Whole proposed communities versus recursive candidate refinement: measures discovery cost and whether the checker merely relies on favorable hand-picked blocks.

The supplied-block panels retain production AUTO median decisions, a core forced-EXACT median boundary panel, and independent forced-EXACT median/zero/first-anchor/full-pair references. Compare center and pair penalties under the same forced-EXACT policy. Production coverage and quotient timing always come from the configured AUTO implementation. Include weak Böcker outcomes and Lange weak target-pair outcomes individually without composing them.

## Integrity, raw results and stopping criteria

Each run records source/config hashes, package versions, hardware, seeds, dataset hashes, status and raw measurements under an immutable run identifier. A report reads those results; it must not manually insert a gain or silently remove failures. Method or protocol changes after freeze require an entry in `reviews/revision-ledger.md` and a new labeled exploratory run before any revised confirmatory evaluation.

Mathematical safety violations halt affected execution and trigger repair. A known prior criterion with the same collective mechanism triggers a novelty revision. If coverage is negligible beyond cheaper rules or total cost consistently exceeds the relevant workload saving, revise the paper's central claim or pivot; do not replace a performance claim with a longer benchmark table.

The sequential launcher records every configured command and its process log/exit. Any unexpected nonzero child exit halts the run for repair and preserves the remaining unlaunched grid. Domain exclusions and bounded solver timeouts are structured normal records; they do not trigger substitutions or silent retries. Partial cases retain their completed gamma files, started/failure records and the failed phase.

## Independent freeze review

The initial Supervisor review identified E1–E9. Its canonical follow-up report records resolution of code/configuration findings and the final design verdict before freeze. The complete actual comparator configurations, command contracts and correctness validation must be stable before creating the freeze manifest. This is a design review; empirical usefulness and conference readiness are assessed after results and manuscript exist.

The complete KaPoCE comparator uses the public weighted `ExactSolver::solve` entry, compiling all exact/heuristic/graph/I/O translation units except the unused Boost CLI parser. Assertion/PARANOID and fail-on-signed-overflow instrumentation apply identically to both arms. Caps are n2..2000, initial scaled pair magnitude20000, and aggregate62,500,000. Default upstream RNG and unweighted200-restart stage are retained. Alternating arm order uses case index plus gamma index. The actual independent-bank discovery partition supplies the same exact feasible original Q to both arms. A one-node quotient is solved analytically and clearly marked outside the native minimum domain. Timeouts retain only the supplied incumbent and completed initial untouched-input bound; no interrupted search bound is invented. Solver cost integers have independent GCD scaling, so cross-arm comparisons use exact original Q and separately reported times. All full-native comparison times include input conversion and independent validation; full pipeline costs additionally charge shared graph preparation/discovery and reduced refinement/check/quotient. Unexpected selected/full native failures, invalid output or unavailable frozen build preserve the native record then halt the case and outer suite.

Full-solver completed-time comparisons require both arms to return optimal or optimal_trivial. Analytically solved one-node quotients form a separate labeled total-pipeline panel and do not enter native-solver-only timing. A timeout is a right-censored unresolved solve outcome, not a completed30-second solve, so no completed-time speedup ratio uses timeout limits. Keep all domain exclusions, failures and unavailable rows with original denominators; skipped-arm pipeline times never enter solve-time speedup aggregation. Selected routines also use assertions/PARANOID and fail-on-signed-integer-overflow instrumentation, retaining their existing current-residual Twin Simple guard. Full matched costs explicitly charge the original incumbent evaluation to both arms and the quotient label projection/exact-Q alignment to reduced preprocessing.
