"""Evidence-bound M2 figures; all points come from immutable raw queries."""
from pathlib import Path
import json,sys
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter
import numpy as np
from experiments.plot_helpers.ccfa_plot_recipes import slopegraph,Theme
from experiments.common import sha

raw=ROOT/'results/m2/run_v12_001';out=ROOT/'figures/m2';out.mkdir(parents=True,exist_ok=True)
plt.rcParams.update({'font.family':'serif','font.serif':['Times New Roman','DejaVu Serif'],
                    'font.size':10,'axes.spines.top':False,'axes.spines.right':False,
                    'svg.fonttype':'none','pdf.fonttype':42})
def get(name):return json.loads((raw/(name+'.json')).read_text())
def save(fig,name):
    for suffix in ['svg','pdf','png']:fig.savefig(out/(name+'.'+suffix),dpi=170,bbox_inches='tight')
    plt.close(fig)

fig,ax=plt.subplots(figsize=(7.4,3.2))
for variant,label,colour,marker in [('main','R-supp, P=3','#0072B2','o'),('cap05','R-cap(1/2), P=3','#D55E00','s'),('P2','R-supp, P=2','#009E73','^')]:
    vals=[get(f'same12_{i:02d}_{variant}')['evaluation']['F1'] for i in range(12)]
    ax.plot(range(12),vals,label=label,color=colour,marker=marker,ms=5,lw=1.1)
ax.set(xlabel='Fixed SBM instance',ylabel='F1',ylim=(0,1.05),xticks=range(12))
ax.grid(axis='y',alpha=.18);ax.legend(frameon=False,ncol=3,loc='lower left')
save(fig,'same12_f1')

fig,axes=plt.subplots(1,2,figsize=(7.4,3.35),sharex=True,sharey=True)
for ax,variant,label,colour,marker in zip(axes,['main','cap05'],['R-supp','R-cap(1/2)'],['#0072B2','#D55E00'],['o','s']):
    before=[get(f'lfr_n1000_o00_m50_s11_base_q{i:02d}_{variant}')['evaluation']['F1'] for i in range(12)]
    after=[get(f'lfr_n1000_o00_m50_s11_low_q{i:02d}_{variant}')['evaluation']['F1'] for i in range(12)]
    ax.plot([0,1],[0,1],color='.65',lw=1,zorder=0);ax.scatter(before,after,c=colour,marker=marker,s=36)
    ax.set(title=label,xlabel='F1 without K30',xlim=(-.02,1.03),ylim=(-.02,1.03));ax.grid(alpha=.12)
    ax.text(.04,.95,'0/12 included K30',transform=ax.transAxes,ha='left',va='top',fontsize=9)
    if variant=='main':
        ax.annotate('seed 91',xy=(before[3],after[3]),xytext=(.44,.2),arrowprops={'arrowstyle':'->','color':colour},fontsize=9)
axes[0].set_ylabel('F1 with remote K30')
save(fig,'remote_clique_paired')

fig,ax=plt.subplots(figsize=(5.4,3.1))
for placement,label,colour,marker in [('base','Original M','#0072B2','o'),('low','M including K30','#D55E00','s')]:
    r=get(f'lfr_n1000_o00_m50_s11_{placement}_q03_main')['result']
    stages=[t for t in r['diffusion_trace'] if t.get('sweep_value_exact') is not None and t['j']>=6]
    ax.plot([t['mass'] for t in stages],[float(Fraction(t['sweep_value_exact'])) for t in stages],color=colour,marker=marker,label=label)
    best=next(t for t in stages if t['j']==r['j_star'])
    ax.scatter([best['mass']],[float(Fraction(best['sweep_value_exact']))],facecolors='none',edgecolors=colour,s=130,lw=1.5)
ax.set(xlabel='Injection mass',ylabel='Best Z-sweep value',xscale='log',xticks=[1920,3840,7680]);ax.set_xticklabels(['1920','3840','7680'])
ax.xaxis.set_minor_formatter(NullFormatter());ax.grid(alpha=.15);ax.legend(frameon=False);save(fig,'seed91_mass_choice')

selected=[]
for qi in [3,9]:
    before=get(f'lfr_n1000_o00_m50_s11_base_q{qi:02d}_main')
    after=get(f'lfr_n1000_o00_m50_s11_low_q{qi:02d}_main')
    selected.append({'seed':f"seed {before['seed']}",'before':before['evaluation']['F1'],'after':after['evaluation']['F1']})
svg=slopegraph(selected,'before','after','seed','Remote-clique failure cases','Original','With K30',
              subtitle='ZR-HFD R-supp; exact matched queries',note='No clique vertices were returned. Full 12-query results appear in the paired scatter.',
              palette=['#0072B2','#D55E00'],theme=Theme(width=820,height=420))
(out/'remote_failure_cases.svg').write_text(svg,encoding='utf-8')
(out/'CAPTIONS_ZH.md').write_text('''# M2 图注

`same12_f1`：固定同批12个SBM实例的实际F1。P3 R-supp exact10/12、P3 R-cap exact6/12；P2一个稀疏例提前停止、F1约.099。无置信区间或理论证明声明。

`remote_clique_paired`：12个相同seed的无团/有团F1，低编号放置；高编号逐查询结果完全相同。四组均0/12输出包含团节点，但R-supp两例F1下降>.01，G-E1失败。重叠点未人为抖动以免虚构变化。

`seed91_mass_choice`：seed91在质量1920/3840/7680的Z-sweep值，圆圈标最佳档；添加远处团只改变全图M，使j*=8切为7、区域缩小。窄纵轴用于显示真实档间差值，并非F1收益图。

`remote_failure_cases.svg`：仅两个下降>.01的具体案例；这不是全样本分布，不替代上面的12-query scatter。

全部图来自immutable `results/m2/run_v12_001`，工程回归而非正式性能测试。可重跑 `.venv/bin/python experiments/plot_m2.py`。SVG为live text，PDF为vector，PNG仅供preview。
''',encoding='utf-8')
(out/'provenance.json').write_text(json.dumps({'source_summary':'results/m2/summary_v12_001.json','source_sha256':sha(ROOT/'results/m2/summary_v12_001.json'),
  'script_sha256':sha(Path(__file__)),'raw_queries_sha256':{str(p.relative_to(ROOT)):sha(p) for p in raw.glob('*.json')},
  'scope':'M2 actual engineering results; no fabricated intervals or omitted failed cases'},indent=2)+'\n')
print(str(out.relative_to(ROOT)))
