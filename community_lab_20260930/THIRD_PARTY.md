# Third-party software and data scope

The repository-level MIT license covers original project contributions only. It does not relicense the third-party files in the compact replay archive, the copied vendor patch, or the research-review guidance. Exact commits, source URLs and audited license hashes are in `provenance/SOURCE_LOCK.json`; unmodified license texts are in `provenance/licenses/` and also inside the replay ZIP.

| Source | License | Scope |
|---|---|---|
| SNAP / BigCLAM | BSD-3-Clause | Indexed macOS ARM64 binary; upstream commit and license retained |
| LFR benchmarks | MIT | Generator provenance; generated development graphs in replay data |
| NOCD | MIT | Indexed Python package and author copyright retained |
| CDlib Highway / native Highway reference | BSD-2-Clause | Indexed Python/native dependencies; license texts retained |
| Karate Club | GPL-3.0 | Indexed `external/karateclub/karateclub` Python package remains GPL-3.0 |
| Ego reference | GPL-3.0 | Source provenance and license, not relicensed by this project |
| egosplit-sknetwork | MIT | Source provenance, license, known-bug patch and `adapters/vendor_patches/ego_sknetwork_fixed.py` |
| Supervisor-Skills guidance | CC BY-NC-SA 4.0 | Unmodified research-review guidance by Yuyu Luo and contributors; source URL/commit in `provenance/supervisor_skill_provenance.json`, license and attribution in `provenance/skill_guidance/Supervisor-Skills/`; not covered by repository MIT |

The replay package is an aggregate of separately licensed components. The binary payloads are the measured ARM64 executables, not portable executables for other operating systems. Offline score replay does not execute them. Third-party research-paper PDFs, upstream dataset collections, Git metadata, virtual environments, and credentials are not part of this publication.

The 24 LFR graphs and ground-truth covers are actual generated research inputs. Ground truth is provided for offline evaluation; it was not an algorithm decision input, except for the separately identified oracle-K scalar panel.
