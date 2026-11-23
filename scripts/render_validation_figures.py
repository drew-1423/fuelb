"""Static research figures from stored validation results; no fitting."""
from pathlib import Path
import os
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'data/cache/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

folder=ROOT/'reports/model_validation';common=pd.read_csv(folder/'common_origin_metrics.csv');metrics=pd.read_csv(folder/'metrics.csv')
names={'A_no_change':'No change','Z_last_change':'Last change','Z_brent':'Brent proxy','B_structural_proxy':'Structural proxy','C_ridge':'Ridge','E_lightgbm':'LightGBM','F_catboost':'CatBoost','G_hybrid':'Hybrid','H_ensemble':'Ensemble'}
fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
for j,regime in enumerate(['pre_crisis','recent_pre_fiscal']):
    g=common[(common.regime==regime)&(common.horizon=='decision_1')&(common.scope=='excluding_sarimax')&common.family.isin(names)].sort_values('change_mae_lbp')
    ax=axes[0,j];ax.barh([names[x] for x in g.family],g.change_mae_lbp,color=['#287e63' if x=='Z_last_change' else '#537991' for x in g.family]);ax.invert_yaxis()
    ax.set_xlabel('Mean absolute change error (LBP / 20 L)');ax.grid(axis='x',alpha=.2)
    ax.set_title(('2018–2019' if j==0 else '2025')+f' challenge: {int(g.n.iloc[0])} identical next-decision cases')
    horizons=['decision_1','decision_2','decision_4','day_1','day_3','day_7','day_14','day_30'];labels=['Next','2nd','4th','1 day','3 days','7 days','14 days','30 days']
    q=metrics[(metrics.regime==regime)&(metrics.family=='H_ensemble')].set_index('horizon').reindex(horizons)
    ax=axes[1,j];ax.axhline(.9,color='#a54232',linestyle='--',label='Requested 90%')
    for i,row in enumerate(q.itertuples()):
        if row.interval_n:
            ax.scatter(i,row.interval_coverage,color='#537991',s=50)
            ax.annotate(f'n={int(row.interval_n)}',(i,row.interval_coverage),xytext=(0,8),textcoords='offset points',ha='center',fontsize=8)
        else:ax.text(i,.08,'No\ninterval',ha='center',fontsize=8,color='#777777')
    ax.set_xticks(range(8),labels,rotation=30);ax.set_xlim(-.5,7.5);ax.set_ylim(0,1.12);ax.yaxis.set_major_formatter(PercentFormatter(1));ax.grid(axis='y',alpha=.2)
    ax.set_title('Ensemble: empirical coverage of nominal 90% intervals')
fig.suptitle('Part 6: exposed retrospective challenges • no production approval',fontsize=14)
fig.savefig(folder/'validation_summary.png',dpi=160);plt.close(fig)
