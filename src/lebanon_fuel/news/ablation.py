"""Optional paired, chronological news feature experiment. Unknown coverage is excluded."""
from datetime import timedelta
from pathlib import Path
import json
import numpy as np
import pandas as pd
from lebanon_fuel.storage.database import Store
from lebanon_fuel.forecasting.data import midnight,mature_training
from lebanon_fuel.forecasting.models import fit_model,InadequateData
from .pipeline import initialize,snapshot


def run(root):
    root=Path(root);store=Store(root);initialize(store)
    config=json.loads((root/'config/forecasting_research.json').read_text())
    data=pd.read_csv(root/'data/exports/forecasting/development_design.csv')
    first=store.db.execute('SELECT MIN(first_known_at) FROM news_items').fetchone()[0]
    result=dict(status='not_evaluable_no_point_in_time_news_coverage',paired_predictions=0,incremental_skill=None,
                first_captured_news_version=first,claim='No evidence of historical improvement; unknown coverage is never zero-filled')
    rows=[];cache={}
    if first and pd.Timestamp(first)<=pd.to_datetime(data.origin,utc=True).max():
        for origin in sorted(data.origin.unique()):
            snap=snapshot(store,origin)
            if snap['coverage_status']=='collected_feed_window':cache[origin]={'x_news_'+k:v for k,v in snap['features'].items()}
        eligible=data[data.origin.isin(cache)].copy()
        for col in next(iter(cache.values()),{}):eligible[col]=eligible.origin.map(lambda o:cache[o][col])
        for regime in config['regimes']:
            for horizon in data.horizon.unique():
                group=eligible[(eligible.regime==regime['id'])&(eligible.horizon==horizon)]
                for i,day in enumerate(regime['fold_starts']):
                    cutoff=midnight(day);end=midnight(regime['fold_starts'][i+1]) if i+1<len(regime['fold_starts']) else midnight(regime['development_end'])+timedelta(days=1)
                    train=mature_training(group,cutoff);valid=group[(pd.to_datetime(group.origin,utc=True)>=pd.Timestamp(cutoff))&(pd.to_datetime(group.origin,utc=True)<pd.Timestamp(end))]
                    if valid.empty:continue
                    try:
                        with_news=fit_model('C_ridge',train,config)
                        without=fit_model('C_ridge',train.drop(columns=[c for c in train if c.startswith('x_news_')]),config)
                    except InadequateData:continue
                    a=with_news.predict(valid);b=without.predict(valid)
                    for (_,row),pa,pb in zip(valid.iterrows(),a,b):
                        rows.append(dict(origin=row.origin,regime=regime['id'],horizon=horizon,fold=i,
                            target=row.target_change_lbp_20l,with_news=pa,without_news=pb))
    store.close()
    if rows:
        frame=pd.DataFrame(rows);frame.to_csv(root/'reports/forecasting/news_ablation_predictions.csv',index=False)
        # Never pool nominal LBP errors across currency regimes/horizons.
        scores=[]
        for (regime,horizon),g in frame.groupby(['regime','horizon']):
            scores.append(dict(regime=regime,horizon=horizon,n=len(g),with_news_mae=float(abs(g.with_news-g.target).mean()),without_news_mae=float(abs(g.without_news-g.target).mean())))
        result.update(status='paired_development_only',paired_predictions=len(rows),incremental_skill=scores)
    (root/'reports/forecasting/news_ablation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
