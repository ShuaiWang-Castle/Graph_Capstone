# Independent formal exact closeout

The helper author is `/root/formal_data_auditor`, distinct from the composition and collector author `/root/experiment_supervisor`. This task authored neither the formal runtime nor the rational proof module. The helper is for post-measurement proof/data integrity of the fixed43-case, five-arm inventory. It supplies no C001 conclusion or venue judgment.

`closeout.py` is the canonical helper; `engineering.py` is the canonical new engineering fixture source. The current engineering sources are **unexecuted** because the once-only scientific study is running. Only authoring and static inspection have occurred in this namespace. Do not run either source against actual measurements before root's explicit measurements-finished signal. No formal arm is ever rerun by this helper.

The actual-run interface requires the separately sealed config/freeze hashes, a pinned diagnostic collection manifest and a separately authored helper source approval. The helper source reviewer must be distinct from both this author and the composition author. The approval JSON contract is:

```json
{
  "schema": "metric-sdp-formal-audit-helper-source-review-v1",
  "reviewer_task": "<independent reviewer identity>",
  "independent_of_helper_author": true,
  "approved_for_post_measurement_exact_audit": true,
  "blocking_defects": [],
  "source_sha256": {
    "analysis/metric_sdp/formal_audit/__init__.py": "<reviewed SHA>",
    "analysis/metric_sdp/formal_audit/closeout.py": "<reviewed SHA>"
  }
}
```

This is an approval of the helper source for its stated post-measurement scope. A filename, reviewer label or mock fixture is never itself approval. The integrating root must provide the approval's exact SHA after checking the independent review's evidence and source identities. It grants no scientific execution permission and changes no frozen runtime/configuration.

After measurements finish, the author fixtures can run into a new absent destination:

```text
env PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv-sdp/bin/python -m analysis.metric_sdp.formal_audit.engineering --measurements-finished --output analysis/metric_sdp/formal_audit/engineering-attempts/attempt-001
```

Every actual fixture graph has n<=4. The complete215-row test uses new mocks and constructs no scientific input. Fixtures exercise hand-derived collective matrices, the lower pair-median tie, sequential weak quotient maps and loop mass, exact stored CSR/bank/incumbent checks, raw/payload binding, a membership lift, unresolved marker/status semantics, singular/indefinite PSD cases and refusal of missing applicable checks across all215 mocks. Explicit Gram factors avoid eigensolver/factor proposals. The suite writes exact fixture values, source identities, full unittest output and an attempt record once. A failed attempt is retained; any necessary later attempt uses a new absent directory. Engineering wall times are never study performance data.

For the actual proof/data audit, first create the diagnostic collection according to `analysis/metric_sdp/formal/README.md`, then run:

```text
env PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv-sdp/bin/python -m analysis.metric_sdp.formal_audit.closeout --measurements-finished --config <formal-config> --config-sha256 <sealed-config-SHA> --freeze <formal-freeze> --freeze-sha256 <sealed-freeze-SHA> --run-dir <finished-raw-run> --collection <diagnostic-collection> --collection-sha256 <manifest-SHA> --source-approval <independent-helper-source-review> --source-approval-sha256 <review-SHA> --output <new-directory-under-analysis/metric_sdp/formal_audit>
```

Run from the project root. Imports cannot write bytecode; outputs are confined to the new assigned audit directory. The raw run, its three sibling operator sidecars, source/configuration, old reviews and measurements are read-only. `closeout.json` uses `metric-sdp-formal-independent-exactness-closeout-v1` and covers all215 ordered rows when source/operator prerequisites authenticate. Per-job defects preserve that row, block the whole approval and leave all paired scientific ratios unavailable. A failed global prerequisite produces an explicit refusal with the215 denominator; the pinned diagnostic collection continues to retain every raw outcome. Incomplete controller exception or operator evidence cannot authorize proof/data attachment.

The helper independently reconstructs each encountered whole original input once after measurement. It decodes and matches the stored canonical CSR, rebuilds full exact degrees/S/gamma and the full B/S trace, validates stored original bank content/structure/hash and cross-arm identity, and recomputes its discovery-label partition value. It does not rerun candidate discovery. The bank constructor's identity and execution lineage are dependencies of the separately reviewed frozen runtime.

Each durable operation is checked on its actual current rational quotient. Dense Fraction oracles independently reconstruct optimized pair loss and the lower weighted median, uniform exterior distances, actual unweighted normalized-row medians for D, and fixed-degree full-pair penalties for W. Exact Schur PSD tests determine acceptance/strictness; full aggregation independently checks canonical maps, loops, degrees, S, gamma, full trace and both graph fingerprints. Original-bank mapping/deduplication and phase/count records are checked sequentially. No negative candidate scan or whole fixed-point rerun occurs. A completed preprocessing record relies on the independently reviewed frozen stage orchestration for its fixed-point attribution. An interrupted durable prefix receives no final-quotient or completed-current-phase credit.

For complete component payloads, the reviewed rational verifier replays exact primal PSD/diag/box/ALL triangles, full-domain dual feasibility, factors/Grams/residuals and exact endpoints. Reused pilot checks bind raw H/y/lambda quantization and all box/active-triangle ordering. The raw NPZ contains no factor arrays: the helper **does not regenerate factors from H or PSD slack**. Stored factors are exact certificates, while their numerical proposal lineage is the frozen producer dependency. Earlier rounds have retained raw/scalar diagnostics but no complete earlier proof payload; only a complete terminal component payload is independent bound evidence. Interrupted or partial artifacts are retained and never converted into proofs.

The original primal lift uses membership congruence of the verified component direct sum. ALL distinct quotient triangles are checked; original triples with repeated mapped indices reduce exactly to diagonal/box constraints. The original full trace is recomputed directly. The quotient upper bound transfers through every replayed relaxed-safe operation and through nonpositive signed-component cross terms. The lower endpoint bounds the relaxation from below; the upper endpoint bounds the original relaxation and hence the discrete problem. Exact width, incumbent gap and target interpretation are checked in original normalization.

Complete compute time is authenticated by runtime/controller/timer markers and the reviewed disjoint ledger. Original, accepted-operation and intermediate checkpoints are included. Composition-internal, callback and round diagnostics remain subsets and are never added again. Final proof/result serialization is excluded from compute time but complete serialization is required for target credit. Actual operator command/environment/source identities, retained events/log/exit, status/per-arm/unexecuted summary counts, immediate fatal halt, physical-limit scalars and monitored RSS are bound to the complete raw inventory. Watchdog races may leave a late timer/finish marker; the retained physical interruption still prevents target credit.

The reused helper has SHA `54b070b18247eb238235c3d3147d3be3871b516f749814b3144f6cd86532420d`. Its functions used are `inspect_environment`, `positive_components`, `raw_round`, `proof_raw_binding` and `global_primal`; the old pilot audit and old suite are not rerun. The rational source review is externally pinned at SHA `71ca7c2024de4157fcbef6c8283667578883f59112b15bfff98b0d965f5f7c43`; the independently replayed six-U pilot closeout is pinned at SHA `4724d5223f65e54786b5cd8567f852637f3776726a9e6bc186c88b85af947324`. Approval content and actual dependency source hashes are checked explicitly. The stdlib-only collector remains diagnostic input; this helper supplies the separate exact replay and immutable inventory binding required before descriptive scientific credit.

The pinned CCFA humanization/common/integrity-auditor instructions were read and applied. Their licenses and the skill source commits remain preserved by the root-owned `research/skill-provenance.json`; this task changes neither. Original17 sources, formal23 sources, the frozen pilot, the formal freeze and all old measurements/reviews remain unchanged.
