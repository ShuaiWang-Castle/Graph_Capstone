# Prospective public four-arm pipeline extension

This namespace implements the separately prospective comparison in
`research/safe_contraction/baseline-pipeline-extension-plan.md` and its interface
design. It follows the completed, immutable v1 recovery closeout: 139 logical
observations, 140 formal orchestration attempts, two selected and four formal
source native failures. Neither the original failed attempt nor any earlier raw
measurement is replaced. V2 contains no native solver, MILP, new dataset, changed
criterion, public pilot, or imported v1 time.

The fixed grid has six full SNAP graphs, discovery seeds 0/1/2, exact resolutions
1/2, 1, 2, four arms U/D/R/RD, and nine downstream seeds 10 through 18. Its ledger
contains 18 setup records, 54 case records, 216 arm states, 1,944 full unchanged
`solve_louvain` calls, and 648 correlated prefix summaries. Prefixes 1/3/9 reuse
the same nine calls. A positive-loop one-node quotient receives all nine calls.

## Interfaces and computation

`contracts.py` owns portable identities, immutable context/cache contracts,
partition canonicalization, primary outer intervals, and exclusive JSON writes.
`integer_objective.py` uses Python integers to evaluate the represented sparse
adjacency, including every diagonal entry, and creates one reduced `Fraction`
from exact within-weight and community-volume squares. Original objective
preparation is common; checker-specific Fraction caches belong to D/RD only.

`stages.py` calls unchanged production D and recursive named R implementations.
R and RD execute independent fresh complete R prefixes. Each final R CSR is
reconstructed through the unchanged core with `require_exact=True`; its actual
membership controls mapping and lifting. Canonically equivalent recursive
internal IDs are kept separately. RD maps the entire original forest, deduplicates
its current images, then applies cap 64. It performs exactly one D stage on that
fixed CSR and composes the two actual membership maps. Direct Python-integer
aggregation of the original graph checks every final entry, diagonal, degree,
and total volume. It also rejects an aggregate that cannot round-trip through
float64, even when its original entries were representable.

`run_case.py` retains every raw quotient label vector, lifted original label
vector, exact raw score and selected original output. Every arm has the same
external discovery-incumbent control, including quotients crossing discovery
communities. Discovery wins exact ties; strictly better tied seeds use the
earliest seed. No Louvain initial partition is supplied. Discovery
representability is recorded and does not determine fallback eligibility.

## Timer attribution

Every required preparation, criterion, quotient, mapping, exact scoring,
validation, selection and returned-label materialization is inside a charged
outer compute interval. Source timers inside those intervals are diagnostic.
They are never added to their containing primary interval.

The unchanged combined candidate call is measured as outer B. Preserve its
source F refinement time, its source proposal time, and exact diagnostic B-F.
These two duration components partition that physical outer call; they are not
reported as fabricated continuous intervals. Additional required original
discovery-label validation has its own `common_discovery` outer interval.
Additional forest-only bank validation has its own `fixed_bank_refinement`
outer interval. Thus final charged `common_discovery_seconds` is source B-F plus
label-validation time, and final charged `fixed_bank_refinement_seconds` is
source F plus bank-validation time. U pays neither the source refinement nor
forest-only validation. This explicit adapter attribution was authorized by
root before measurement; source B/F diagnostics stay unchanged.

For arm a and prefix k, the constructed standalone cost is the three common
phases C, plus F for D/R/RD, plus that arm's complete preparation H, plus its
first k three-phase seed intervals, plus only that prefix's own finalization.
Writer and collector use the same `math.fsum` of those five component totals.
This avoids a one-ulp inconsistency between chained additions and Python 3.12
float `sum`; the detected engineering attempt remains archived. Physical setup
is reused across resolutions and attributed once to each single-resolution
workload. RD pays its own R prefix and final CSR reconstruction, all bridge and
degree work, and the independent R-prefix equality check.

Raw loading/archive decoding, pre-run infrastructure identity checks, progress
sidecar writing, output serialization/compression/I/O, and purely derived table
formatting are outside constructed compute totals and separately recorded.
Whole-process physical elapsed is recorded separately. Normal enabled GC stays
enabled throughout; no manual collection is called. All four states and raw
portable label vectors remain alive through case finalization. `ru_maxrss` is
the monotone process peak with that retention; per-arm memory is `not_measured`.

## Source/configuration review and execution

Engineering fixtures are distinct from public evidence. `test_independent.py`
is independently owned and covers the four numerical/interface fixture groups.
`test_engineering.py` checks source/configuration gates and the controller's
immutable failed-setup path with synthetic inputs. Synthetic solver/clock/review
objects in tests are never an empirical result or actual independent approval.
Their execution records identify source/test/configuration hashes and retain
the failed engineering attempts.

`freeze.py` recursively includes every new runtime module and all local transitive
dependencies, separately pins all original v1 identities, data, closed-out bank
bytes, recovery/selection identities, design files, complete expected ledger,
versions and reviewed engineering record. It verifies imported origins before
measurement. It requires a real independent JSON review with:

- `status=approved_for_public_pipelines_v2_configuration_freeze`;
- `configuration_freeze_blockers=[]`;
- exact `config_sha256` and `runtime_source_sha256`;
- exact `engineering_validation_sha256`.

The engineering record must have `status=passed`, `engineering_only=true`, exact
source/configuration identities, all four `fixture_groups` marked `passed`, and
hash-bound `evidence_sha256` records. No official freeze or public measurement is
produced by author readiness. Root creates the new official freeze only after
the actual-source/configuration review. Then, from the repository root:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 PYTHONPATH=src:. \
  .venv/bin/python -m experiments.extensions.public_pipelines_v2.run_all \
  --freeze experiments/extensions/public_pipelines_v2/freeze.json
```

The controller uses one process and a cross-run file lock. It exclusively creates
a new run directory and will not resume or overwrite any earlier attempt. Every
case has a start record, ordered progress sidecars, one complete raw case and
completion marker, or a retained failed partial record. Unexpected arithmetic,
identity or helper errors halt this source version. A repair needs a separately
reviewed source version and run namespace.

`collect.py` starts from the frozen expected ledger. It validates raw hashes,
completion markers, all exact scores/tie choices, actual lifts, disjoint costs,
the executed orders and all failure/absence denominators. It rejects unlisted
records or favorable repeats and never selects a success from a partial case.
The collection contains 1,944 seed rows, 648 arm/prefix rows and 810 paired rows
for D/U, R/U, RD/U, D/R and RD/R. `total_cost_A_over_B` is T_A/T_B;
`speedup_B_over_A` is its inverse. A quality-matched ratio requires exact equal
returned rational Q. Raw evidence remains immutable and no v1/native timings
are pooled into these tables.
