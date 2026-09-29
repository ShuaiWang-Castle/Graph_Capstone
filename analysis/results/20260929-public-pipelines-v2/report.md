# Public pipeline v2 descriptive results

The frozen collection is complete: 54 cases, 216 arm states, 1,944 scheduled solver calls and 648 prefix summaries. All six full graphs and all three discovery seeds appear in the 810 paired rows.

The summary contains 270 graph/resolution/comparison/prefix groups and 72 graph/resolution/arm coverage groups. Each group preserves the three seed values and median/min/max. Absolute Q and Q differences remain reduced rational values. Quality-matched speedups use only seeds with exactly equal returned Q; empty subsets have n=0 and null statistics.

Coverage uses one case/arm observation rather than repeating it across prefixes. RD additional removals, complete mapped-bank denominators and every D/RD degree-decision status are retained. The largest-component supplement uses the original full-graph objective.

Speedup B/A means constructed T_B/T_A; time ratio A/B means T_A/T_B. Slower/equal/faster/undefined and quality worse/equal/better counts retain the three-seed denominator. No relative Q ratio is formed. The three prefixes share nine solver executions and are correlated. No v1/native time is pooled, no p-value is computed, and per-arm peak memory is not measured.

See summary.json and the four CSV tables; report-provenance.json binds this analysis source, all validated inputs and the output bytes.
