# Complete frozen-suite analysis

`report.py` imports only the Python standard library. It reads immutable run
artifacts and writes a separate deterministic report, JSON records, CSV tables,
and SHA-256 provenance. It does not execute any method, solver, graph generator,
or plotting code.

The complete-suite API is:

```python
from analysis.report import generate_report

generate_report(
    "analysis/collections/20260929-v1-recovery",
    "analysis/results/20260929-v1-recovery",
    project_root=".",
    expected_job_count=139,
)
```

The original v1 is halted and remains ineligible for a final report. After all
73 separately reviewed recovery processes complete, construct the fixed
139-logical-job derived collection (66 complete parent jobs, whole recovery
Davis, 72 recovery scaling jobs):

```sh
python -m analysis.collect_recovery --parent-run experiments/runs/20260929-frozen-v1 --recovery-run experiments/runs/20260929-v1-recovery --output-dir analysis/collections/20260929-v1-recovery --expected-jobs 139
python -m analysis.report --run-dir analysis/collections/20260929-v1-recovery --output-dir analysis/results/20260929-v1-recovery --expected-jobs 139
```

`audit_suite` refuses an incomplete suite before reading gamma measurements.
It checks manifest/config/freeze identities, frozen source/data/protocol/review
hashes, expected job identities and order, every launch/terminal ledger event,
zero exits, completion markers, and the complete required-file inventory.
Unrecorded failure measurements forbid a final report. The full
analysis additionally reconciles bank hashes, certification counts, structural
equivalence ranks, paired workload formulas, exact retained-incumbent values,
native statuses, and timing/memory repetition membership.

The separately reviewed recovery branch verifies original/recovery freezes,
the independent review, engineering packet, exact prospective selection and
separate collector/report source hashes. Source logs and ledgers retain 140
actual orchestration attempts; the collection's 139-entry ledger is explicitly
derived and is never described as the original run. Every selected artifact is
an exact byte copy. Whole recovery Davis is primary, even for its first two
gammas; parent partial timings remain nonprimary source evidence. The rerun must
retain the original graph, dataset, refined bank, discovery labels and seed.

The only allowed failed records are the precisely pinned Davis gamma2 two-arm
native assertion. Preserved core fields remain equal; five source-backed
post-preservation timing fields are checked separately. Failed solver statuses
remain failed, with no reported optimum, packing lower bound, gap or completed
solve-time ratio. Only the independently verified supplied incumbent remains
usable. All other failures, changed payloads, unknown recovery artifacts and
input/bank drift reject collection. Native process completion is never inferred
from successful orchestration completion.

The output preserves all structured cap, guard, domain and timeout outcomes.
Native completed-pair ratios never use timeout observation time as solved time.
Analytic one-node quotient pairs stay separate from native-only completed pairs.
Integer editing costs are deliberately absent from cross-arm comparisons.
Selected preprocessing counts use expanded residual and solved groups.
Every completed native claimed optimum must have exact lifted original Q at
least as large as source-backed exact full-original discovery and numerical
MILP feasible Q. Floating bounds and local C-subinstance objectives are not
part of this integrity gate; failed native arms make no optimum comparison.
AUTO production, forced EXACT, independent rational references, numerical
oracles, computation-only controls, and exploratory stress controls remain
distinct. Structural join-rank comparisons make no joint-safety or domination
claim. No old preprocessor has paired public Louvain arms in this configuration.

Production rows additionally preserve `accepted_pair_blocks`,
`accepted_collective_blocks`, and the full `accepted_block_size_counts`.
`pair_only_removed_vertices` and `collective_only_removed_vertices` are separate
equivalence ranks; they may overlap and must not be added.
`collective_additions_beyond_accepted_production_pairs` is the unchanged raw
all-certificate identification rank minus the pair-only rank. The public
aggregate table gives median/min/max over discovery seeds; controlled and
development production rows expose the same quantities. Computation-only cases
without a candidate bank remain unavailable. These are post-freeze descriptive
mechanism summaries, not new predeclared primary endpoints. Pair-only refers to
accepted size-two production certificates, not an executed exact Böcker Rule5
baseline. The independent novelty audit is separately hashed in analysis
provenance when present.

Public medians and ranges span the three fixed discovery seeds. Scaling checker
times use the three unprofiled repetitions; memory uses the single independent
profiled repetition. Complete process RSS includes input/preparation, and full
checker timing includes the CSR slicing column workspace. Dense exterior
assembly is an uncertified diagnostic.

Scaling tables also preserve the existing component timers, without taking new
measurements. The aggregate prefixes are
`unprofiled_production_exterior_assembly_seconds_*`,
`unprofiled_production_dense_eigensolve_seconds_*`,
`unprofiled_production_exact_verification_seconds_*`,
`unprofiled_reference_assembly_seconds_*`,
`unprofiled_reference_verification_seconds_*`, and
`unprofiled_dense_diagnostic_assembly_seconds_*` (plus its dense-exterior alias),
where `*` is `n`, `median`, `min` or `max`. Production exterior assembly is only
sparse dispersion. Reference assembly also constructs the rational contrast
matrix and projected basis. Dense assembly includes the exterior table and
float contrast matrix. Each row carries `component_timing_scope`; these timers
are not interchangeable kernels. Whole checker and preparation plus checker
remain the primary timings.

Tiny schema fixture validation is intentionally separate from formal evidence:

```sh
python -m unittest analysis.test_report
```

Do not run validation or full analysis while the sequential benchmark suite is
active unless root schedules a quiet engineering window. The fixture is
synthetic JSON used only to catch reporting mistakes;
it performs no research experiment and supports no numerical method claim.
