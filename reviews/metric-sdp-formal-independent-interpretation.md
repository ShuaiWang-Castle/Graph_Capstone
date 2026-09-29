# Independent interpretation of the formal metric-SDP study

## Decision and scope

**C001 complete-cost utility is not established by this fixed study.** The new D stage gives conspicuous wins over S on a few controlled graphs, but it neither improves verified completion over S nor shows a robust complete-cost advantage over the stronger SW reference. The application result should be reported as mixed-to-negative, with the large regressions visible. It cannot support a top-tier practical-speedup claim. This is an interpretation of the audited, finite inventory, not a new exact-proof audit or a judgment that the safety theorem is false.

I used the frozen 43-case/5-arm contract and the prospective `T_SD/T_reference` complete-compute-cost estimand. I did not change its target, censoring policy, strata, or denominator; I ran no scientific jobs. I checked distinct case-arm and pair keys, independently rebuilt target-pair outcomes from audited job statuses, and recomputed every non-null primary ratio from the corresponding two `full_compute_seconds` values. All 86 primary pair rows matched. I rely on the separate exactness closeout for proof replay; I did not independently repeat its NPZ/proof computations.

Pinned inputs (SHA-256):

| Artifact | SHA-256 |
|---|---|
| `analysis/metric_sdp/formal/fixed-contract.json` | `65d4078b433c002086fbf404e470d8094497083eb549e08f712d1d3c1d0bde83` |
| `analysis/metric_sdp/formal/method-specification.json` | `fb8500f9015998065308edc2fdeedb1c85a19422addacfd3d3b860ff1e868991` |
| `analysis/metric_sdp/formal_audit/audit-20260929-v1/closeout.json` | `cbf69b8e96671434ec899e441efb8f8377839c1ea4a2a07c2049841d0a3d4d52` |
| `analysis/metric_sdp/formal/audited-20260929-v1/collection-manifest.json` | `81cc5768c77f1a9b2609c4b279c2cb9f2b493da3b2ae37f1a71d6bc2058bc7ce` |
| `analysis/metric_sdp/formal/audited-20260929-v1/job-rows.json` | `d5b19506474924834693010e6766548e8f8a6e4354d4b6e9d89b94813397deb4` |
| `analysis/metric_sdp/formal/audited-20260929-v1/primary-pair-rows.json` | `9866ade9fb43126074fdbf33591cbd9b9727fabfaf827a7f1b8baaa805b35e36` |
| `analysis/metric_sdp/formal/audited-20260929-v1/summary.json` | `d6329644815d5b7079f14de0cf240d53fe7fcca7ef2906d40dc6b5d145e9b753` |

## Denominator and primary comparisons

All 43 cases and 215 scheduled jobs appear exactly once. The independent closeout credits 182 verified targets and retains 33 full-wall-limit outcomes; none is unexecuted. Per-arm verified targets out of 43 are U 37, S 37, D 36, SD 36, and SW 36. A wall-limited result is unresolved, not a completed 300-second solve or evidence that its contraction was unsafe. The conditional time ratios below therefore have `n=36` and must always be accompanied by the full 43-case outcome counts.

| Fixed comparison; ratio is `T_SD/T_B` | Both target | SD only | B only | Neither | SD faster / slower / undefined, out of 43 | Conditional median; min–max ratio, `n=36` |
|---|---:|---:|---:|---:|---:|---:|
| SD/S | 36 | 0 | 1 | 6 | 17 / 19 / 7 | 1.000379; 0.009134–1.743446 |
| SD/SW | 36 | 0 | 0 | 7 | 15 / 21 / 7 | 1.007499; 0.787373–98.857642 |

Smaller ratios favor SD. Thus the SD/S conditional median is essentially parity and its one completion discordance favors S (`controlled-016-noisy_planted_clusters`). The SD/SW conditional median slightly favors SW; SW matches SD's 36 verified completions. These are descriptive medians of paired ratios, not ratios of marginal median costs, and the 7 undefined comparisons remain in each 43-case denominator. No IID confidence interval or population-success statement is justified: the 39 controlled cases share designs, parameters and seeds, and the four public cases were previously used development examples.

## Mechanism, wins, and negative cases

D has an accepted removal prefix in 12 SD cases. Relative to S, SD ends with a smaller quotient in exactly those 12 cases and an equal-sized quotient in the other 31. Within those 12, SD/S is faster in 6, slower in 5, and undefined in 1. The largest relative-S gains are real descriptive outcomes: `controlled-014` has `T_SD/T_S=0.009134` (about 109.5-fold reciprocal speedup) and `controlled-032` has `0.011291` (about 88.6-fold). Across the full 36 jointly completed cases, five SD/S ratios are below 0.5 and none exceeds 2.

The strong reference changes that interpretation. SW ends with a quotient **no larger** than SD's in all 43 cases: equal size in 36 and strictly smaller in 7. In the 12 D-active SD cases, SD/SW is faster in 3, slower in 8, and undefined in 1. None of the 36 jointly completed SD/SW ratios is below 0.5, whereas seven exceed 2. For example, `controlled-012` and `controlled-013` give SD/S ratios 0.1602 and 0.0992, yet their SD/SW ratios are 8.80 and 10.55 because SW reduces their 240-node graphs further. `controlled-030` is 158 seconds for SD versus 1.598 seconds for SW (`98.86` ratio; final quotient sizes 182 versus 8). `controlled-031` is 129.3 versus 1.691 seconds (`76.50` ratio; 182 versus 8). These are major complete-cost regressions, not marginal setup noise.

SD does beat SW on some cases, including `controlled-014` (`0.8059`) and `controlled-032` (`0.8692`), but its best observed SD/SW ratio is 0.7874 on `controlled-043`, where D removes zero vertices. An equal quotient *size* does not by itself prove identical quotient partitions, so I do not claim SW logically subsumes every D operation from these rows alone. The measured point is narrower and sufficient: this protocol supplies no extra verified completion or smaller final quotient for SD over SW, and its complete-cost evidence is unfavorable overall with severe negative cases.

## Implication for the manuscript and venue claim

The correct scientific outcome is a rigorously audited, backend-specific negative utility test with a few bounded mechanism wins over S. The tested workload uses a fixed 300-compute-second/monitored-6-GiB policy, one rigorous metric-SDP/SCS workflow, 39 correlated controlled cases, and four development public graphs; it does not establish broad public-graph, arbitrary solver, discrete-optimum, or asymptotic speedup. Complete compute cost includes the declared discovery, contractions, checkpoints, modeling, solving, repair, and validation, while imports and final serialization are excluded by the prospective contract. The independent proof-audit wall time is likewise excluded from each runtime by that contract, rather than being silently added or used to rescue an unfavorable result.

The safety/correctness result may still be a mathematical contribution, and the exact negative experiment is valuable to report. Yet C001, as an application-level practical benefit over the strongest implemented reference, remains open or fails on this inventory. The earlier C002 novelty concerns and prior weak-reject full-paper reviews are separate gates; this result does not turn them into an approval. A top-tier-ready claim would require a new, prospectively justified substantive use or a sharper theoretical distinction and then independent full-paper review. The frozen study itself must remain intact, including every timeout and regression.
