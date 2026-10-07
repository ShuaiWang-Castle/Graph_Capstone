# Who is a useful neighbour? Reconstructing hidden county outage reports

A candidate direction for the COMPSCI 521 capstone, started on 2026-10-06. This folder holds a public dataset of 26
storm windows, the code of a first experiment, and its results. It is a pilot, not a finished study.
`HANDOFF_ZH.md` describes the state of the work for whoever continues it.

## Question

During a storm, the outage report of some counties is missing. Which other counties are useful stand-ins for them:
the nearest ones, the ones with the most similar weather, or the ones with the most similar static profile?

Each county is a vertex. Three k-nearest-neighbour graphs define "neighbour" in three ways, none of them using outage
data. A share of the counties is hidden, and their hourly outage share is rebuilt from the visible ones with the same
reconstructor on every graph (harmonic interpolation, Zhu, Ghahramani and Lafferty 2003), next to simple baselines.

## Layout

| Path | Content |
|---|---|
| `data/` | 26 storm windows: hourly outage share and weather per county, county statics, storm reports, county outlines. See `data/README.md` for sources and licences. |
| `code/data.py` | Loader. |
| `code/recon.py` | Graphs, reconstructors, masks, evaluation. |
| `code/run_pilot.py` | The reconstruction experiment. |
| `code/explore_timing.py` | Timing against severity in the reconstructions. |
| `code/explore_smooth.py` | Smoothness of onset, peak and restoration time over the map. |
| `code/sim_front.py` | A small model: a moving front and the Fiedler vector of the similarity graph. |
| `code/extra_derecho_2020.py` | Exploratory: similarity graphs of the August 2020 derecho. |
| `code/build_dataset.py` | How `data/` was assembled (provenance; needs sources that are not in this repository). |
| `results/` | Per-draw results (`*.csv`) and the printed tables (`*_summary.txt`). |

## Running

Python 3.11 with `pip install -r requirements.txt`. From `code/`:

    python run_pilot.py 8          # about 20 s
    python explore_timing.py
    python explore_smooth.py
    python sim_front.py
    python extra_derecho_2020.py

The scripts write into `results/`. The files there were produced by exactly these commands.

## Results so far

Setting: k = 8, 20% of the counties hidden, 10 draws per storm window. "Random" hides scattered counties; "block"
hides one contiguous region. Error is the mean absolute error of the hourly outage share; skill is the reduction of
that error relative to the mean of the visible counties.

All counties, 26 windows (no weather graph, see the caveat below):

| Method | Random: error | skill | Block: error | skill |
|---|---:|---:|---:|---:|
| inverse-distance weighting, 8 nearest visible counties | 0.0091 | 0.29 | 0.0133 | 0.13 |
| spatial graph, harmonic | 0.0096 | 0.27 | 0.0127 | 0.14 |
| spatial graph, mean of visible neighbours | 0.0095 | 0.27 | 0.0148 | 0.07 |
| nearest visible county | 0.0105 | 0.21 | 0.0136 | 0.09 |
| mean of the visible counties of the same state | 0.0136 | 0.16 | 0.0158 | 0.06 |
| static graph, harmonic | 0.0149 | 0.08 | 0.0166 | -0.02 |
| mean of all visible counties | 0.0168 | 0 | 0.0174 | 0 |

Counties with weather values only, 24 windows, three graphs:

| Method | Random: error | Block: error |
|---|---:|---:|
| inverse-distance weighting | 0.0086 | 0.0136 |
| weather graph, harmonic | 0.0089 | 0.0131 |
| spatial graph, harmonic | 0.0090 | 0.0130 |
| static graph, harmonic | 0.0126 | 0.0153 |
| mean of all visible counties | 0.0139 | 0.0159 |

For hidden counties whose outage share reached 10%, all counties, random hiding:

| Method | Reconstructed peak / true peak | Correlation of the hourly curves | Onset error |
|---|---:|---:|---:|
| inverse-distance weighting | 0.47 | 0.81 | 2.4 h |
| spatial graph, harmonic | 0.43 | 0.80 | 2.6 h |
| static graph, harmonic | 0.30 | 0.62 | 7.7 h |

What these numbers say, and no more:

- Nearby counties are useful stand-ins. Counties with a similar static profile are not: they do little better than
  the overall mean.
- Weather-similar counties do as well as nearby ones, but the two graphs are nearly the same graph: a median of 75%
  of the weather-graph edges are also spatial-graph edges. The pilot does not show that weather similarity adds
  anything to proximity.
- Propagation on the graph helps when a whole region is hidden. For scattered missing counties, plain
  inverse-distance weighting is as good or better.
- Every method flattens severe counties: the reconstructed peak is under half of the true one. The timing is
  recovered much better than the size.
- Hiding a region roughly halves the skill and triples the onset error (2.6 h to 8.6 h for the spatial graph).

## Caveats

- **Weather is missing for many counties.** In 18 of the 26 windows the weather block of 22% to 81% of the counties
  is zero-filled. `data.load_event` flags them (`has_weather`), and every comparison that involves the weather graph
  is restricted to counties with values. A first run that did not do this made the weather graph look worse than
  the spatial one; that result was an artefact and is not in this repository.
- Ten draws per window, one value of k, one hidden share. No confidence intervals yet.
- The weather graph uses the weather of the whole window. That is fine for reconstruction after the fact and is not
  a nowcast.
- Reconstruction from counties observed at the same hour is a different task from forecasting, and the numbers here
  say nothing about forecasting models.
- `results/pilot_smoothness_summary.txt` does not fit a simple "timing is shared, severity is local" reading: over
  the map, the time to restore is the smoothest of the three quantities, and the onset hour the least smooth.
- The derecho analysis and the simulation are exploratory. In the simulation the curves are shifted copies of one
  shape, which is the case the method is built for.

## Restricted data

The team also holds a competition dataset under a non-disclosure agreement. It is not in this repository. Do not add
it, or anything derived from it, here.
