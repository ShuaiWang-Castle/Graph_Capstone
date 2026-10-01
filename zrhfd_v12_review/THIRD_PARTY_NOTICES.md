# 第三方来源与许可证记录

本文件记录已经取得的来源，不新增项目整体再发布许可。精确 commits、文件 SHA-256、下载时间和 primary-paper receipts 在 `provenance/`，重现索引在 `experiments/reproduction/lock.json`。

| 来源 | 固定版本/提交 | 已保留许可与用途 |
|---|---|---|
| LFRbenchmarks | `ec9a860282d8fc9d52e9e08fea9ce93ddeb473af` | MIT，`external/generators/lfr_native/LICENSE`；保留源码和署名，本地生成图 |
| HFD 作者仓库 | `f4111f7fa2ceb44a99acdf8057a609b7322e1ebf` | 未找到 LICENSE；固定下载入口 [HFD](https://github.com/s-h-yang/HFD)，默认重现复制包不包含源码，不据此推断再发布许可 |
| pNormFlowDiffusion 作者仓库 | `ba0f59e6a1863d30a6198f5ab45b8ebc880ef93d` | 未找到 LICENSE；固定下载入口 [pNormFlowDiffusion](https://github.com/s-h-yang/pNormFlowDiffusion)，同样不默认复制或再发布 |
| LocalGraphClustering | `a6325350997932d548a876deb259c2387fc2c809` | MIT，`external/localgraphclustering/LICENSE.txt`；来源核对，不能将其其他 flow 算法冒称 p-norm 作者实现 |
| leidenalg | `d7cbb3ee6f29d1214b96c0f4dd120c609c6cca65`，Python package 0.12.0 | 仓库 LICENSE 为 GNU GPL v3 文本，`external/leidenalg/LICENSE`；运行包和依赖各自许可另见安装 distribution |
| Julia | 1.10.10 | Julia MIT 许可及发行包 `THIRDPARTY.md`/各 bundled library 许可；archive SHA `52d3f82c50d9402e42298b52edc3d36e0f73e59f81fc8609d22fa094fbad18be`，官方来源和文件清单见 `julia-runtime.json` |
| Combinatorics.jl | 1.0.2，tree `08c8b6831dc00bfea825826be0bc8336fc369860` | MIT，task-local depot 原 LICENSE.md 的 SHA 在 `julia-dependencies.json`；不全局安装 |
| CCFA-Skills | `5969e6b20a3bbcef9118fa00796d1417d48fcbf3` | 原许可逐字保存在 `provenance/skills/CCFA-Skills_LICENSE`，使用来源见 `skill-provenance.json` |
| Supervisor-Skills | `207bc6f7a1aa107e544099c2c7cc86816fba9628` | 原许可逐字保存在 `provenance/skills/Supervisor-Skills_LICENSE`，同目录记录 pin |

论文 PDF 仅作为 primary source 本地核对材料；重现入口按下载 receipt 的 SHA 与固定 arXiv 版本获取，不自动打包公开发表。TL-HFD 没有检得作者执行代码，本项目复现明确标为 TL*，其步长等工程输入与论文未披露项另行记录。CFSP 仅为已取得来源，未执行算法不冒称 baseline 已完成。

Benson 官方 labeled contact-high-school 与修正后的 Trivago archives 来源、SHA、时间和 README 都保留在 `provenance/baselines/benson-download.json` 及 `data/external/benson-downloads/`。网页可公开下载不等于此文件授予数据再发布许可。重现包默认通过原下载入口取得数据；Trivago 旧作者 raw 的重复末 token 与现行官方修正数据差异保留在 `hypergraph-data.json`，不混称相同论文数据。

Python 依赖的版本清单不是许可证清单；NumPy、SciPy、Numba、igraph、leidenalg、CVXPY 等及其 bundled libraries 的实际许可随各 distribution 保留。用户给出的 `inputs/` 附件作为本地研究来源保存，未赋予额外公开传播授权。
