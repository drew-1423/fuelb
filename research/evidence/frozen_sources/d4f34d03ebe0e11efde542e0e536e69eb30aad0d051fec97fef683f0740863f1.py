"""Past-only ensemble weights, empirical intervals and separate sign probabilities."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import linprog, minimize_scalar
from sklearn.linear_model import LogisticRegression
from .models import weights,preprocess,inner_split

DEADBAND_LBP=3000.0  # User-specified class tolerance; Ministry rounding is unverified.
SMOOTHING_ALPHA=.03
ENSEMBLE_MEMBERS=('B_structural_proxy','C_ridge','E_lightgbm','F_catboost','G_hybrid','Z_last_change')
OVX_REGIMES=('Low','Normal','Elevated','Stress')


def past_predictions(predictions,cutoff):
    if predictions.empty:return predictions
    return predictions[(pd.to_datetime(predictions.origin,utc=True)<pd.Timestamp(cutoff)) &
        (pd.to_datetime(predictions.label_end,utc=True)<pd.Timestamp(cutoff))].copy()


def fit_ensemble(previous,available,config):
    fallback={'weights':{'A_no_change':1.0},'status':'insufficient_prior_oof_baseline_fallback','n':0}
    if previous.empty:return fallback
    minimum=config['ensemble_minimum_oof']
    candidates=[m for m in ENSEMBLE_MEMBERS if m in available and
        previous[previous.family==m].base_revision_id.nunique()>=minimum]
    if not candidates:return fallback
    pivot=previous[previous.family.isin(candidates)].pivot(index='origin',columns='family',values='prediction').dropna()
    meta=previous.drop_duplicates('origin').set_index('origin').loc[pivot.index]
    if meta.base_revision_id.nunique()<minimum:return fallback
    x=pivot[candidates].to_numpy();y=meta.target_change_lbp_20l.to_numpy();w=np.full(len(meta),1/len(meta))
    scale=max(float(np.mean(abs(y))),1.0);x=x/scale;y=y/scale
    n,k=x.shape
    # Convex absolute-error weights on strictly prior OOF predictions only.
    objective=np.r_[np.zeros(k),w]
    bounds=[(0,1)]*k+[(0,None)]*n
    result=linprog(objective,A_ub=np.r_[np.c_[x,-np.eye(n)],np.c_[-x,-np.eye(n)]],
        b_ub=np.r_[y,-y],A_eq=np.r_[np.ones(k),np.zeros(n)][None,:],b_eq=[1],bounds=bounds,method='highs')
    singles=np.average(abs(x-y[:,None]),axis=0,weights=w)
    if not result.success:
        chosen=candidates[int(np.argmin(singles))]
        return dict(weights={chosen:1.0},status='optimizer_failed_best_prior_single',n=n)
    best=float(result.fun)
    chosen_weights={m:float(v) for m,v in zip(candidates,result.x[:k]) if v>1e-10}
    total=sum(chosen_weights.values());chosen_weights={m:v/total for m,v in chosen_weights.items()};status='prior_oof_convex_mae_weights'
    return dict(weights=chosen_weights,status=status,n=n,base_decisions=meta.base_revision_id.nunique(),
        first_origin=meta.index.min(),last_origin=meta.index.max(),maximum_label_end=meta.label_end.max(),
        candidates=candidates,prior_blend_mae_lbp_20l=best*scale)


def nonoverlapping(previous,maximum=80):
    """Keep recent non-overlapping label windows, at most one per base decision."""
    chosen=[];next_origin=None;seen=set()
    for _,row in previous.sort_values('origin',ascending=False).iterrows():
        if row.base_revision_id in seen:continue
        if next_origin is None or pd.Timestamp(row.label_end)<next_origin:
            chosen.append(row);seen.add(row.base_revision_id);next_origin=pd.Timestamp(row.origin)
            if len(chosen)>=maximum:break
    return pd.DataFrame(chosen) if chosen else previous.iloc[:0]


def calibration_sample(previous,maximum=60):
    """One observation per k-day stride bucket; never deduplicate by base price.

    A fixed 7-day stride aliases one weekday. Rotate the preferred weekday among
    buckets without consulting targets; missing weekdays cannot be invented.
    This reduces phase bias, but overlapping targets remain time-dependent.
    """
    if previous.empty:return previous,1
    if previous.horizon.nunique()!=1 or ('family' in previous and previous.family.nunique()!=1):
        raise ValueError('Calibration must be conditioned on one horizon and one model')
    p=previous.dropna(subset=['prediction','target_change_lbp_20l']).sort_values('origin').drop_duplicates('origin',keep='last').copy()
    if p.empty:return p,1
    kind,n=p.horizon.iloc[0].split('_')
    if kind=='day':days=int(n)
    else:
        interval=p.get('x_interval_median',pd.Series(dtype=float)).median()
        if not np.isfinite(interval):
            interval=pd.to_datetime(p.origin,utc=True).diff().dt.total_seconds().median()/86400
        days=int(n)*(float(interval) if np.isfinite(interval) and interval>0 else 1.)
    stride=max(1,int(np.floor(days/2)))
    dates=pd.to_datetime(p.origin,utc=True).dt.tz_convert('Asia/Beirut')
    p['_bucket']=[d.date().toordinal()//stride for d in dates]
    p['_weekday']=dates.dt.day_of_week.to_numpy()
    p['_priority']=(p['_weekday']-p['_bucket']%7)%7
    # Vectorized equivalent of per-bucket circular weekday priority/latest tie-break.
    selected=p.sort_values(['_bucket','_priority','origin'],ascending=[True,True,False]).drop_duplicates('_bucket')
    return selected.sort_values('origin').tail(maximum).drop(columns=['_bucket','_weekday','_priority']),stride


def calibrate(previous,config,cutoff=None):
    if cutoff is not None:previous=past_predictions(previous,cutoff)
    p,stride=calibration_sample(previous,60)
    residuals=(p.target_change_lbp_20l-p.prediction).to_numpy(float) if len(p) else np.array([])
    trailing=previous.sort_values('origin').tail(20) if len(previous) else previous
    mae=float(np.mean(abs(trailing.target_change_lbp_20l-trailing.prediction))) if len(trailing) else 0.
    floor=max(5000.,.25*mae)
    output=dict(n=len(p),status='insufficient_matured_oof_residuals',radius=None,cqr_correction=None,
                residual_quantile_10=None,residual_quantile_90=None,
                nominal_coverage=.9,maximum_label_end=p.label_end.max() if len(p) else None,
                residuals=residuals.tolist(),minimum_half_width_lbp=floor,trailing20_mae_lbp=mae,
                stride_days=stride,sampling='one_per_stride_bucket_rotating_weekday_no_base_deduplication',
                weekday_counts={str(k):int(v) for k,v in pd.to_datetime(p.origin,utc=True).dt.tz_convert('Asia/Beirut').dt.day_of_week.value_counts().items()} if len(p) else {},
                deadband_lbp=DEADBAND_LBP,smoothing_alpha=SMOOTHING_ALPHA,
                limitations='Latest-vintage research; temporal dependence and missing days prevent coverage/equal-weekday guarantees')
    if len(p)<config['minimum_calibration']:return output
    # Symmetric finite-sample conformal score, expanded by the requested positive floor.
    rank=int(np.ceil((len(p)+1)*.9))
    if rank>len(p):return output
    radius=max(floor,float(np.sort(abs(residuals))[rank-1]))
    output.update(status='horizon_conditioned_past_oof_conformal_research',radius=radius,
                  residual_quantile_05=float(np.quantile(residuals,.05,method='lower')),
                  residual_quantile_10=float(np.quantile(residuals,.10,method='lower')),
                  residual_quantile_90=float(np.quantile(residuals,.90,method='higher')),
                  residual_quantile_95=float(np.quantile(residuals,.95,method='higher')))
    return output


def calibrate_for_ovx_regime(previous,regime,config):
    """Use regime-conditional conformal residuals only when the sample is adequate."""
    pooled=calibrate(previous,config)
    if not isinstance(regime,str) or regime not in OVX_REGIMES:
        pooled.update(ovx_regime_conditioning='pooled_no_current_ovx_regime',requested_ovx_regime=None)
        return pooled
    subset=previous[previous.ovx_regime.eq(regime)] if 'ovx_regime' in previous else previous.iloc[:0]
    conditioned=calibrate(subset,config)
    if conditioned.get('radius') is not None and conditioned['n']>=config.get('minimum_calibration',20):
        conditioned.update(ovx_regime_conditioning='regime_conditioned_matured_oof',requested_ovx_regime=regime)
        return conditioned
    pooled.update(ovx_regime_conditioning='pooled_fallback_insufficient_regime_residuals',
                  requested_ovx_regime=regime,regime_calibration_n=conditioned.get('n',0))
    return pooled


def available_ovx_regime_calibrations(previous,config):
    """Persist only regime calibrations with finite, adequately sized OOF samples."""
    output={}
    if 'ovx_regime' not in previous:return output
    for regime in OVX_REGIMES:
        subset=previous[previous.ovx_regime.eq(regime)]
        result=calibrate(subset,config)
        if result.get('radius') is not None and result['n']>=config.get('minimum_calibration',20):
            result.update(ovx_regime_conditioning='regime_conditioned_matured_oof',requested_ovx_regime=regime)
            output[regime]=result
    return output


def direction_class(values,deadband=DEADBAND_LBP):
    values=np.asarray(values,float)
    return np.where(values>deadband,1,np.where(values < -deadband,-1,0))


def residual_probabilities(predictions,calibration,alpha=SMOOTHING_ALPHA):
    """Order: decrease, no_change (within ±3000), increase. Additive Dirichlet smoothing."""
    point=np.atleast_1d(np.asarray(predictions,float));errors=np.asarray(calibration.get('residuals',[]),float)
    if not np.isfinite(point).all() or not np.isfinite(errors).all() or not np.isfinite(alpha) or alpha<=0:
        raise ValueError('Finite forecasts/residuals and positive smoothing required')
    if not len(errors):return np.full((len(point),3),np.nan)
    classes=direction_class(point[:,None]+errors[None,:])
    counts=np.column_stack([(classes==event).sum(axis=1) for event in (-1,0,1)])
    return (counts+alpha)/(len(errors)+3*alpha)


@dataclass
class DirectionModel:
    prior:np.ndarray
    metadata:dict
    columns:object=None
    transform:object=None
    fitted:object=None
    temperature:float=1.0

    def predict(self,frame):
        if self.fitted is None:return np.tile(self.prior,(len(frame),1))
        partial=self.fitted.predict_proba(self.transform.transform(frame[self.columns]))
        probabilities=np.full((len(frame),3),1e-9)
        for j,c in enumerate(self.fitted.classes_):probabilities[:,int(c)+1]=partial[:,j]
        logs=np.log(np.clip(probabilities,1e-9,1))/self.temperature
        exp=np.exp(logs-logs.max(axis=1,keepdims=True));return exp/exp.sum(axis=1,keepdims=True)


def fit_direction(frame):
    """Exact sign classes. Independent of point-model family; no invented zero band."""
    sign=np.sign(frame.target_change_lbp_20l).astype(int).to_numpy();w=weights(frame)
    counts=np.array([w[sign==c].sum() for c in (-1,0,1)])
    model=DirectionModel((counts+.5)/(counts.sum()+1.5),
        dict(status='smoothed_historical_class_frequencies_not_calibrated',train_base_decisions=frame.base_revision_id.nunique(),
             class_order=['decrease','unchanged_price','increase'],calibration_base_decisions=0))
    before,after=inner_split(frame)
    if before.base_revision_id.nunique()<30 or after.base_revision_id.nunique()<20 or len(set(np.sign(before.target_change_lbp_20l)))<2:return model
    model.columns=['x_domestic_change_lag1','x_structural_cost_gap','x_brent_spot_return7','x_days_since_source_date','x_interval_median','x_weekday']
    model.transform=preprocess();x=model.transform.fit_transform(before[model.columns])
    model.fitted=LogisticRegression(C=.1,max_iter=1000).fit(x,np.sign(before.target_change_lbp_20l).astype(int),sample_weight=weights(before))
    base=model.predict(after);actual=np.sign(after.target_change_lbp_20l).astype(int).to_numpy()+1;aw=weights(after)
    def loss(temp):
        logs=np.log(base)/temp;p=np.exp(logs-logs.max(axis=1,keepdims=True));p/=p.sum(axis=1,keepdims=True)
        return float(np.average(-np.log(p[np.arange(len(p)),actual]),weights=aw))
    opt=minimize_scalar(loss,bounds=(.5,5),method='bounded');model.temperature=float(opt.x)
    model.metadata.update(status='purged_inner_holdout_temperature_scaled_logistic_research',
        fit_base_decisions=before.base_revision_id.nunique(),calibration_base_decisions=after.base_revision_id.nunique(),
        maximum_fit_label_end=before.label_end.max(),calibration_first_origin=after.origin.min(),
        maximum_calibration_label_end=after.label_end.max(),temperature=model.temperature,
        limitation='Small dependent samples; calibration must be assessed in later chronological predictions')
    return model
