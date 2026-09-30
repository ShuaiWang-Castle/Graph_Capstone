# 来源、实现身份与接入检查

本轮2026-09-30核验了下列一手页面/源码；不把作者的成绩当作本包复现结果。仓库默认HEAD会变化，执行机必须先锁到实际SHA。新出现的方法不能仅因年份新就被称为统一SOTA。

| 对象 | 一手入口 | 接入约束 |
|---|---|---|
| overlapping LFR | https://www.santofortunato.net/resources → 作者链接 https://github.com/andrealancichinetti/LFRbenchmarks | unweighted_undirected/ReadMe.txt：-on/-om，network.dat边重复两次，community.dat多成员，time_seed.dat。未在本容器下载运行 |
| LFR论文 | https://arxiv.org/abs/0904.3940 | 与nonoverlap版本区分；无需把作者PDF放进本包 |
| BigCLAM | https://cs.stanford.edu/people/jure/pubs/bigclam-wsdm13.pdf ; https://github.com/snap-stanford/snap/tree/master/examples/bigclam | 已核ReadMe与bigclam.cpp；actual code -c默认100/-nt默认4/-sa默认.05，而ReadMe不同；adapter显式设定。原生TAGMFast(G,10,10)没有seed参数 |
| NOCD | https://github.com/shchur/overlapping-community-detection ; https://arxiv.org/abs/1909.12201 | 作者PyTorch code；论文为Deep Learning on Graphs Workshop at KDD2019，不称KDD主会。README说论文实验是另一TensorFlow版。图输入用normalize(A)，不能用X属性 |
| NOCD接入 | interactive.ipynb, nocd/nn/gcn.py, nocd/nn/decoder.py | 官方notebook会读取Z_gt演示NMI，adapter删除这条评估路径，K仅显式输入。gcn sparse dropout硬编码CUDA，接入层记录device-neutral补丁；原生接口仍须宿主测试 |
| Ego-splitting | https://research.google/pubs/ego-splitting-framework-from-non-overlapping-to-overlapping-clusters/ | 论文框架允许局部与全局不同partitioner，必须声明实际用哪个 |
| Ego公开实现 | https://github.com/benedekrozemberczki/EgoSplitting ; https://github.com/benedekrozemberczki/karateclub | 这是第三方NetworkX/库实现，不冒充Google的原始大规模后端。adapter用Karate Club API；兼容困难可按其源代码窄依赖接入并明确身份 |
| Ego较快候选实现 | https://pypi.org/project/egosplit-sknetwork/ ; https://github.com/ryandewolfe33/egosplit-sknetwork | 可用于消除低效实现比较；本轮只核其维护者包说明，不承诺与作者结果等价 |
| Highway | https://arxiv.org/abs/2607.14531 | 2026预印本；不将其v1实验与后续主页数字混用 |
| Highway代码 | https://github.com/GiulioRossetti/cdlib/blob/f054f7ca237e4caed008c8e831f248b7f4bd41e8/cdlib/algorithms/internal/Highway.py | 已知固定SHA；纯Python读取图转无权无向。greedy anchor cover只选一个shared hub的toy限制已核验，但不是原生全流程质量/速度结论 |
| SLPA | https://cdlib.readthedocs.io/en/stable/reference/generated/cdlib.algorithms.slpa.html | API t=21,r=.1。文档正文写max20，而签名21；config显式传21。Reference link为 https://github.com/kbalasu/SLPA |
| Amazon | https://snap.stanford.edu/data/com-Amazon.html | 代理社区/预筛top5000不代表完整负标签；原图要完整保留 |
| DBLP | https://snap.stanford.edu/data/com-DBLP.html | 同上；venue归属不等于全部图结构 |
| CCFA | https://github.com/mikubaka88/CCFA-Skills/tree/5969e6b20a3bbcef9118fa00796d1417d48fcbf3 | 按需用于结果归因/方法审查，不以评分代替运行；不分发skill文本 |
| 原固定研究 | https://github.com/ShuaiWang-Castle/Graph_Capstone/tree/aff99d8ab46770f7b334e1be604e7e30434356ae | 不改43×5实验，不冒充已经取得其缺失raw tree |

## 未关闭的环境事项

- 当前包没有vendor任何上述方法，故作者源码许可证由宿主保留并检查。
- Python环境可为各baseline隔离；命令行adapter也可以通过其venv的python运行。严格计时应标明版本/编译器/线程，不能只给算法名字。
- `fetch_sources.py`只clone并锁源码，不会执行网络脚本、pip安装或make。
- pip老版本约束若不兼容，不要把修改PyTorch architecture或删dropout当普通兼容补丁。确有device/API等价改动必须保存diff，验证前向/损失和输入语义。
- 若找到Highway作者C++后端，另登记native arm。不要静默把纯Pythonarm换成C++后继续复用旧时间。
- 对0边/完整图，NOCD的BP decoder除数退化，应明确unsupported或采用有原始定义支持的处理；不能返回伪造的好答案。
