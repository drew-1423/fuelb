"""Independent metric equations. Counts accompany every statistic."""
import numpy as np
import pandas as pd


def score(frame):
    y=frame.target_change_lbp_20l.to_numpy(float);p=frame.prediction.to_numpy(float);e=p-y
    n=len(frame);actual_price=frame.base_price_lbp_20l.to_numpy(float)+y;predicted_price=frame.base_price_lbp_20l.to_numpy(float)+p
    out=dict(n=n,distinct_base_decisions=frame.base_revision_id.nunique(),first_origin=frame.origin.min(),last_origin=frame.origin.max(),
        price_mae_lbp=float(np.mean(abs(predicted_price-actual_price))),price_rmse_lbp=float(np.sqrt(np.mean((predicted_price-actual_price)**2))),
        change_mae_lbp=float(np.mean(abs(e))),change_rmse_lbp=float(np.sqrt(np.mean(e**2))),bias_lbp=float(np.mean(e)),
        direction_accuracy=float(np.mean(np.sign(p)==np.sign(y))),point_no_change_accuracy=float(np.mean((p==0)==(y==0))),
        actual_no_change_n=int(np.sum(y==0)),point_predicted_no_change_n=int(np.sum(p==0)),
        no_change_recall=float(np.mean(p[y==0]==0)) if np.any(y==0) else np.nan,
        no_change_precision=float(np.mean(y[p==0]==0)) if np.any(p==0) else np.nan)
    probability=frame[['p_decrease','p_unchanged_price','p_increase']].to_numpy(float)
    good=np.isfinite(probability).all(axis=1);q=probability[good];classes=np.sign(y[good]).astype(int)+1
    out.update(probability_n=int(good.sum()),brier_multiclass=float(np.mean(np.sum((q-np.eye(3)[classes])**2,axis=1))) if len(q) else np.nan,
        brier_no_change=float(np.mean((q[:,1]-(y[good]==0))**2)) if len(q) else np.nan,
        probability_direction_accuracy=float(np.mean(q.argmax(axis=1)==classes)) if len(q) else np.nan,
        probability_no_change_accuracy=float(np.mean((q.argmax(axis=1)==1)==(classes==1))) if len(q) else np.nan,
        log_loss=float(np.mean(-np.log(np.clip(q[np.arange(len(q)),classes],1e-12,1)))) if len(q) else np.nan)
    interval=frame.interval_low.notna()&frame.interval_high.notna();r=frame[interval]
    out.update(interval_n=len(r),interval_nominal=.9,interval_coverage=float(np.mean((r.interval_low<=r.target_change_lbp_20l)&(r.target_change_lbp_20l<=r.interval_high))) if len(r) else np.nan,
        interval_width_lbp=float(np.mean(r.interval_high-r.interval_low)) if len(r) else np.nan,
        zero_width_interval_n=int(np.sum(r.interval_high==r.interval_low)),
        unavailable_interval_n=n-len(r))
    return out


def grouped(frame,keys=('regime','horizon','family')):
    return pd.DataFrame([dict(zip(keys,k if isinstance(k,tuple) else (k,)),**score(g)) for k,g in frame.groupby(list(keys))])


def reliability(frame):
    result=[]
    # Point families share a classifier; this is one probability experiment, not N independent ones.
    unique=frame.drop_duplicates(['regime','horizon','origin'])
    for (regime,horizon),g in unique.groupby(['regime','horizon']):
        for model,prefix in [('shared_direction','p_'),('training_class_frequency','prior_p_')]:
            for name,code in [('decrease',-1),('unchanged_price',0),('increase',1)]:
                p=g[prefix+name];valid=p.notna();bins=np.minimum((p.fillna(0)*5).astype(int),4)
                for b in range(5):
                    use=valid&(bins==b)
                    if not use.any():continue
                    result.append(dict(regime=regime,horizon=horizon,probability_model=model,event=name,bin_lower=b/5,bin_upper=(b+1)/5,
                        n=int(use.sum()),base_decisions=g.loc[use,'base_revision_id'].nunique(),mean_predicted=float(p[use].mean()),
                        observed_frequency=float((np.sign(g.loc[use,'target_change_lbp_20l'])==code).mean())))
    return pd.DataFrame(result)


def common_origins(frame):
    result=[]
    for (regime,horizon),g in frame.groupby(['regime','horizon']):
        for scope in ['all_available','excluding_sarimax']:
            f=g if scope=='all_available' else g[g.family!='D_sarimax']
            ids=set.intersection(*[set(x.origin) for _,x in f.groupby('family')])
            if not ids:continue
            m=grouped(f[f.origin.isin(ids)]);m['scope']=scope;result.append(m)
    return pd.concat(result,ignore_index=True) if result else pd.DataFrame()


def bootstrap_difference(differences,block,replications=1000,seed=20261112,level=.9):
    values=np.asarray(differences,float);n=len(values);rng=np.random.default_rng(seed)
    starts=rng.integers(0,n,size=(replications,int(np.ceil(n/block))))
    indices=(starts[:,:,None]+np.arange(block))%n
    means=values[indices.reshape(replications,-1)[:,:n]].mean(axis=1)
    return np.quantile(means,[(1-level)/2,1-(1-level)/2])


def paired_comparisons(frame,protocol):
    records=[];cfg=protocol['block_bootstrap']
    for (regime,horizon),g in frame.groupby(['regime','horizon']):
        for baseline in protocol['required_baselines']:
            b=g[g.family==baseline].set_index('origin')
            for family,f in g.groupby('family'):
                if family==baseline:continue
                f=f.set_index('origin');ids=f.index.intersection(b.index);a=f.loc[ids];bb=b.loc[ids]
                item=dict(regime=regime,horizon=horizon,family=family,baseline=baseline,n=len(ids),
                    baseline_available_n=len(b),candidate_available_n=len(f),status='unavailable_official_structural_inputs' if baseline=='B_official_structural' else 'insufficient_common_origins')
                if not len(ids):records.append(item);continue
                ae=abs(a.prediction-a.target_change_lbp_20l);be=abs(bb.prediction-bb.target_change_lbp_20l)
                per_base=(ae-be).groupby(a.base_revision_id).mean()
                # Preserve base-decision temporal order, not arbitrary numerical ID order.
                order=a.reset_index().sort_values('origin').drop_duplicates('base_revision_id').base_revision_id
                values=per_base.loc[order].to_numpy();n=len(values)
                kind,steps=horizon.split('_');effective=int(steps) if kind=='decision' else int(np.ceil(int(steps)/max(float(a.x_interval_median.median()),1)))
                block=max(int(np.ceil(n**(1/3))),2*effective)
                item.update(mae=float(ae.mean()),baseline_mae=float(be.mean()),mae_difference=float(ae.mean()-be.mean()),
                    base_balanced_difference=float(values.mean()),distinct_base_decisions=n,block_length=block,
                    improvement_percent=float((1-ae.mean()/be.mean())*100) if be.mean()>0 else np.nan)
                if n>=cfg['minimum_base_decisions'] and n>=4*block:
                    low,high=bootstrap_difference(values,block,cfg['replications'],cfg['seed'],cfg['level'])
                    item.update(status='exploratory_dependent_block_bootstrap',difference_ci_low=float(low),difference_ci_high=float(high),
                        ci_level=cfg['level'],replications=cfg['replications'],confirmatory=False)
                else:item['status']='too_few_effective_blocks_for_inference'
                records.append(item)
    return pd.DataFrame(records)
