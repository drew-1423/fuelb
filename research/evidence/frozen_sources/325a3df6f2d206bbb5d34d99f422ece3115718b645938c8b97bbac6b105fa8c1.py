"""Reproducible development folds. This is not the independent Part 6 assessment."""
from datetime import datetime,timezone,timedelta
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd

from .data import horizon_ids,midnight,mature_training,STATUS
from .models import fit_model,InadequateData,official_structural_forecast,weights
from .uncertainty import (past_predictions,fit_ensemble,calibrate,calibrate_for_ovx_regime,
    available_ovx_regime_calibrations,fit_direction,residual_probabilities,direction_class)


def json_default(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    raise TypeError(type(value).__name__)


def dump(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2,default=json_default,allow_nan=False)+'\n')


def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def fit_set(train,config):
    models={};gates={}
    for family in config['families']:
        if family=='H_ensemble':continue
        try:models[family]=fit_model(family,train,config)
        except InadequateData as exc:gates[family]=str(exc)
    return models,gates


def forecast(models,ensemble,direction,calibrations,origins,config):
    point={name:model.predict(origins) for name,model in models.items()}
    if ensemble['weights'] and all(m in point for m in ensemble['weights']):
        point['H_ensemble']=sum(point[m]*w for m,w in ensemble['weights'].items())
    results=[]
    for family,predictions in point.items():
        q=models[family].quantiles(origins) if family in models else None
        cal=calibrations.get(family,{})
        probabilities=np.full((len(predictions),3),np.nan)
        valid_point=np.isfinite(predictions)
        probabilities[valid_point]=residual_probabilities(np.asarray(predictions)[valid_point],cal)
        for i,(_,row) in enumerate(origins.iterrows()):
            prediction=float(predictions[i])
            if not np.isfinite(prediction) or row.base_price_lbp_20l+prediction<0:continue
            raw_low=float(q[0][i]) if q is not None else np.nan;raw_high=float(q[1][i]) if q is not None else np.nan
            low=high=np.nan;low80=high80=np.nan;kind='unavailable_insufficient_past_errors'
            if cal.get('radius') is not None:
                low=prediction-cal['radius'];high=prediction+cal['radius'];kind='past_oof_absolute_error_interval'
                residuals=np.asarray(cal.get('residuals',[]),float)
                if len(residuals) and np.isfinite(residuals).all():
                    floor=float(cal.get('minimum_half_width_lbp',5000.))
                    q10=float(cal.get('residual_quantile_10',np.quantile(residuals,.10,method='lower')))
                    q90=float(cal.get('residual_quantile_90',np.quantile(residuals,.90,method='higher')))
                    low80=prediction+min(q10,-floor)
                    high80=prediction+max(q90,floor)
            columns=['origin','origin_beirut','origin_date','regime','horizon','base_revision_id','base_source_date',
                     'base_price_lbp_20l','base_status','label_end','target_change_lbp_20l','target_source_date',
                     'target_revision_id','witness_revision_id','observed_updates','target_interpretation']
            columns+=['next_announcement_expected_wait_days','next_announcement_timing_status']
            columns+=['x_interval_median','partition']
            columns+=['ovx_regime','ovx_regime_basis','x_ovx_level','x_ovx_5d_change',
                      'x_ovx_20d_change','x_ovx_252d_percentile']
            output={k:row[k] for k in columns if k in row}
            target_kind,steps=row.horizon.split('_')
            endpoint=(pd.Timestamp(row.origin).tz_convert('Asia/Beirut').date()+timedelta(days=int(steps))).isoformat() if target_kind=='day' else None
            output.update(family=family,prediction=prediction,predicted_endpoint_price_lbp_20l=row.base_price_lbp_20l+prediction,
                forecast_target='change_to_kth_next_recorded_decision' if target_kind=='decision' else 'change_to_conditional_prevailing_recorded_price',
                calendar_endpoint_beirut=endpoint,official_effective_timing_certified=False,
                raw_low=raw_low,raw_high=raw_high,interval_low=low,interval_high=high,
                interval_80_low=low80,interval_80_high=high80,interval_80_nominal_coverage=.8,
                interval_kind=kind,
                interval_nominal_coverage=config['coverage'],calibration_n=cal.get('n',0),
                interval_usage_status='research_candidate_not_validated_for_use',
                calibration_maximum_label_end=cal.get('maximum_label_end'),
                calibration_ovx_regime=cal.get('requested_ovx_regime'),
                ovx_regime_conditioning=cal.get('ovx_regime_conditioning','pooled_calibration'),
                p_decrease=probabilities[i,0],p_unchanged_price=probabilities[i,1],p_increase=probabilities[i,2],
                p_no_change=probabilities[i,1],probability_n=cal.get('n',0),deadband_lbp=3000.,
                probability_status=cal.get('status','unavailable_no_matured_oof_residuals'),probability_model='model_specific_empirical_residuals_alpha_0.03',
                information_status=STATUS,production_approved=False)
            results.append(output)
    return pd.DataFrame(results)


def walk_calibration(predictions,previous,config):
    """Recalibrate at each origin; point fits/ensemble weights stay fixed per fold."""
    pool=pd.concat([previous,predictions],ignore_index=True) if not previous.empty else predictions.copy()
    result=predictions.copy()
    for origin,indexes in result.groupby('origin',sort=True).groups.items():
        available=past_predictions(pool,origin)
        for family,ids in result.loc[indexes].groupby('family').groups.items():
            current_regime=result.loc[ids,'ovx_regime'].iloc[0] if 'ovx_regime' in result else None
            cal=calibrate_for_ovx_regime(available[available.family.eq(family)],current_regime,config)
            point=result.loc[ids,'prediction'].to_numpy(float)
            result.loc[ids,'calibration_n']=cal['n']
            result.loc[ids,'calibration_maximum_label_end']=cal['maximum_label_end']
            result.loc[ids,'calibration_stride_days']=cal['stride_days']
            result.loc[ids,'minimum_half_width_lbp']=cal['minimum_half_width_lbp']
            result.loc[ids,'probability_n']=cal['n']
            result.loc[ids,'probability_status']=cal['status']
            result.loc[ids,'calibration_ovx_regime']=cal.get('requested_ovx_regime')
            result.loc[ids,'ovx_regime_conditioning']=cal.get('ovx_regime_conditioning')
            probs=residual_probabilities(point,cal)
            result.loc[ids,['p_decrease','p_unchanged_price','p_increase']]=probs
            result.loc[ids,'p_no_change']=probs[:,1]
            if cal['radius'] is not None:
                result.loc[ids,'interval_low']=point-cal['radius']
                result.loc[ids,'interval_high']=point+cal['radius']
                result.loc[ids,'interval_kind']='horizon_conditioned_symmetric_split_conformal_with_floor'
                residuals=np.asarray(cal.get('residuals',[]),float)
                if len(residuals) and np.isfinite(residuals).all():
                    floor=float(cal.get('minimum_half_width_lbp',5000.))
                    q10=float(cal.get('residual_quantile_10',np.quantile(residuals,.10,method='lower')))
                    q90=float(cal.get('residual_quantile_90',np.quantile(residuals,.90,method='higher')))
                    result.loc[ids,'interval_80_low']=point+min(q10,-floor)
                    result.loc[ids,'interval_80_high']=point+max(q90,floor)
    return result


def metrics(frame):
    records=[]
    for keys,f in frame.groupby(['regime','horizon','family']):
        e=f.prediction-f.target_change_lbp_20l;y=f.target_change_lbp_20l
        ok=f.interval_low.notna()&f.interval_high.notna()
        ok80=f.interval_80_low.notna()&f.interval_80_high.notna()
        p=f[['p_decrease','p_unchanged_price','p_increase']].to_numpy();classes=direction_class(y)+1
        prob_ok=np.isfinite(p).all(axis=1)
        onehot=np.eye(3)[classes];w=weights(f)
        records.append(dict(zip(['regime','horizon','family'],keys),n=len(f),unique_base_decisions=f.base_revision_id.nunique(),
            first_origin=f.origin.min(),last_origin=f.origin.max(),mae=float(abs(e).mean()),rmse=float(np.sqrt(np.mean(e**2))),
            bias=float(e.mean()),base_balanced_mae=float(np.average(abs(e),weights=w)),
            direction_accuracy=float((direction_class(f.prediction)==direction_class(y)).mean()),
            exact_sign_direction_accuracy=float((np.sign(f.prediction)==np.sign(y)).mean()),
            no_change_target_fraction=float((y==0).mean()),interval_n=int(ok.sum()),
            interval_coverage=float(((f.interval_low<=y)&(y<=f.interval_high))[ok].mean()) if ok.any() else np.nan,
            interval_mean_width=float((f.interval_high-f.interval_low)[ok].mean()) if ok.any() else np.nan,
            interval_80_n=int(ok80.sum()),
            interval_80_coverage=float(((f.interval_80_low<=y)&(y<=f.interval_80_high))[ok80].mean()) if ok80.any() else np.nan,
            interval_80_mean_width=float((f.interval_80_high-f.interval_80_low)[ok80].mean()) if ok80.any() else np.nan,
            probability_n=int(prob_ok.sum()),probability_calibration_ready_n=int((prob_ok & f.calibration_n.ge(20)).sum()),
            brier_multiclass=float(np.mean(np.sum((p-onehot)**2,axis=1)[prob_ok])) if prob_ok.any() else np.nan,
            shared_direction_brier=float(np.mean(np.sum((p-onehot)**2,axis=1)[prob_ok])) if prob_ok.any() else np.nan,
            shared_direction_log_loss=float(-np.mean(np.log(np.clip(p[np.arange(len(p)),classes],1e-12,1))[prob_ok])) if prob_ok.any() else np.nan,
            deadband_lbp=3000.,zero_width_interval_n=int((ok & f.interval_high.eq(f.interval_low)).sum())))
    return pd.DataFrame(records)


def comparisons(frame):
    records=[]
    for (regime,horizon),g in frame.groupby(['regime','horizon']):
        base=g[g.family=='A_no_change'].set_index('origin')
        for family,rows in g.groupby('family'):
            common=base.index.intersection(rows.origin);other=rows.set_index('origin').loc[common];b=base.loc[common]
            error=abs(other.prediction-other.target_change_lbp_20l);be=abs(b.prediction-b.target_change_lbp_20l)
            mae=float(error.mean());baseline=float(be.mean());bw=weights(other)
            records.append(dict(regime=regime,horizon=horizon,family=family,common_origins=len(common),
                eligible_baseline_origins=len(base),coverage_fraction=len(common)/len(base),
                unique_base_decisions=other.base_revision_id.nunique(),mae=mae,baseline_mae=baseline,
                improvement_percent=(1-mae/baseline)*100 if baseline else np.nan,
                base_balanced_mae=float(np.average(error,weights=bw)),base_balanced_baseline_mae=float(np.average(be,weights=bw))))
    return pd.DataFrame(records)


def save_bundle(path,bundle):
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    joblib.dump(bundle,path/'bundle.joblib',compress=3)
    native=[]
    for family,model in bundle['models'].items():
        if family in {'E_lightgbm','G_hybrid'} and hasattr(model.fitted,'booster_'):
            name=f'{family}.txt';model.fitted.booster_.save_model(str(path/name));native.append(name)
        elif family=='F_catboost':
            name=f'{family}.cbm';model.fitted.save_model(str(path/name));native.append(name)
    metadata={k:v for k,v in bundle.items() if k not in {'models','direction'}}
    metadata['model_metadata']={n:{k:v for k,v in m.extra.items() if k!='quantile_models'} for n,m in bundle['models'].items()}
    metadata['direction_metadata']=bundle['direction'].metadata
    metadata['files']={name:digest(path/name) for name in ['bundle.joblib']+native}
    dump(path/'manifest.json',metadata)


def load_bundle(path):
    """Only load trusted locally generated artifacts. Hashes detect accidental changes, not malicious pickle files."""
    path=Path(path);meta=json.loads((path/'manifest.json').read_text())
    if digest(path/'bundle.joblib')!=meta['files']['bundle.joblib']:raise ValueError('Model artifact digest mismatch')
    return joblib.load(path/'bundle.joblib')


def preview(root,regime,horizon):
    """Regenerate a historical preview at the saved fit cutoff; never silently forecast today."""
    root=Path(root);path=root/'data/models/part5'/regime/horizon
    bundle=load_bundle(path)
    if 'historical_preview' in bundle:
        return dict(status='saved_historical_oof_not_final_fit_or_current_forecast',regime=regime,horizon=horizon,
                    fit_cutoff=bundle['fit_cutoff'],forecasts=bundle['historical_preview'],gates=bundle['gates'],production_approved=False)
    features=root/'data/exports/forecasting/origin_features.csv'
    if digest(features)!=bundle['input_manifest']['feature_sha256']:raise ValueError('Feature snapshot hash differs from trained artifact')
    frame=pd.read_csv(features);cutoff=pd.Timestamp(bundle['fit_cutoff'])
    origin=frame[(frame.regime==regime)&(pd.to_datetime(frame.origin,utc=True)==cutoff)].copy()
    if len(origin)!=1:raise ValueError('Exactly one saved historical origin is required')
    origin['horizon']=horizon
    forecasts=forecast(bundle['models'],bundle['ensemble'],bundle['direction'],bundle['calibrations'],origin,bundle['config'])
    return dict(status='historical_research_preview_not_current_forecast',regime=regime,horizon=horizon,
        origin=bundle['fit_cutoff'],forecasts=json.loads(forecasts.to_json(orient='records')),
        gates=bundle['gates'],official_structural=bundle['B_official_structural'],production_approved=False)


def run(root):
    """Train the requested unified regime using the frozen development CSV only."""
    root=Path(root);cfg_path=root/'config/forecasting_research.json'
    config=json.loads(cfg_path.read_text())
    config=dict(config,regimes=[r for r in config['regimes'] if r['id']=='stabilized_fx_2023_2026'],
                families=list(dict.fromkeys(config['families']+['Z_last_change'])),coverage=.9,
                calibration_max=60,probability_deadband_lbp=3000.,probability_smoothing_alpha=.03)
    if len(config['regimes'])!=1:raise ValueError('Unified development regime is required')
    report=root/'reports/forecasting';report.mkdir(parents=True,exist_ok=True)
    design_path=root/'data/exports/forecasting/development_design.csv'
    data=pd.read_csv(design_path)
    if 'partition' not in data or not data.partition.eq('development').all():
        raise ValueError('Training input contains non-development rows')
    data=data[data.regime.eq(config['regimes'][0]['id'])].copy()
    end=midnight(config['regimes'][0]['development_end'])+timedelta(days=1)
    if data.empty or (pd.to_datetime(data.origin,utc=True)>=pd.Timestamp(end)).any() or (pd.to_datetime(data.label_end,utc=True)>pd.Timestamp(end)).any():
        raise ValueError('Development origins or matured labels violate the cutoff')
    source_paths=sorted((root/'src/lebanon_fuel/forecasting').glob('*.py'))
    freeze=dict(started_at=datetime.now(timezone.utc).isoformat(),stage='part2_retraining_v2',
        config_sha256=digest(cfg_path),design_sha256=digest(design_path),data_input=str(design_path),
        code_hashes={str(p.relative_to(root)):digest(p) for p in source_paths},
        packages={p:version(p) for p in ['numpy','pandas','scipy','scikit-learn','statsmodels','lightgbm','catboost','joblib']},
        data_first_origin=data.origin.min(),data_last_origin=data.origin.max(),data_maximum_label_end=data.label_end.max(),
        effective_config=config,holdout_read=False,
        status='Chronological development only; assumed close times and revised histories; no production approval')
    # This user-authorized protocol supersedes the original Part 5 freeze, which is preserved.
    dump(report/'part2_protocol_freeze.json',freeze)
    dump(report/'training_inputs.json',freeze)
    all_oof=[];foldlog=[];all_preliminary=[];availability=[]
    for regime in config['regimes']:
        for horizon in horizon_ids(config):
            print(f"Training {regime['id']} {horizon}",flush=True)
            group=data[(data.regime==regime['id'])&(data.horizon==horizon)].sort_values('origin')
            past=[]
            for fold,cutday in enumerate(regime['fold_starts']):
                cutoff=midnight(cutday)
                endpoint=midnight(regime['fold_starts'][fold+1]) if fold+1<len(regime['fold_starts']) else end
                train=mature_training(group,cutoff)
                test=group[(pd.to_datetime(group.origin,utc=True)>=pd.Timestamp(cutoff))&(pd.to_datetime(group.origin,utc=True)<pd.Timestamp(endpoint))]
                if train.base_revision_id.nunique()<config['minimum_train'] or test.empty:
                    foldlog.append(dict(regime=regime['id'],horizon=horizon,fold=fold,cutoff=cutoff.isoformat(),status='insufficient_train_or_no_eligible_validation',train_rows=len(train),validation_rows=len(test)))
                    continue
                models,gates=fit_set(train,config)
                history=pd.concat(past,ignore_index=True) if past else pd.DataFrame()
                previous=past_predictions(history,cutoff)
                ensemble=fit_ensemble(previous,set(models),config);direction=fit_direction(train)
                predictions=forecast(models,ensemble,direction,{},test,config)
                predictions=walk_calibration(predictions,history,config)
                predictions['fold']=fold;predictions['fit_cutoff']=cutoff.isoformat();predictions['maximum_training_label_end']=train.label_end.max()
                past.append(predictions);all_oof.append(predictions)
                foldlog.append(dict(regime=regime['id'],horizon=horizon,fold=fold,cutoff=cutoff.isoformat(),status='evaluated',
                    train_rows=len(train),train_base_decisions=train.base_revision_id.nunique(),validation_rows=len(test),
                    maximum_training_label_end=train.label_end.max(),gates=gates,ensemble=ensemble,
                    uncertainty='Updated per origin from matured prior OOF; never from the current target',
                    models={n:{k:v for k,v in m.extra.items() if k!='quantile_models'} for n,m in models.items()}))
            cutoff=end;train=mature_training(group,cutoff)
            models,gates=fit_set(train,config)
            previous=past_predictions(pd.concat(past,ignore_index=True) if past else pd.DataFrame(),cutoff)
            ensemble=fit_ensemble(previous,set(models),config);direction=fit_direction(train)
            calibration={f:calibrate(previous[previous.family==f],config) for f in config['families']} if len(previous) else {}
            calibration_by_ovx_regime={f:available_ovx_regime_calibrations(previous[previous.family==f],config)
                for f in config['families']} if len(previous) else {}
            # A future-origin feature row is not available in the authorized input.
            # Preserve an actual OOF preview; do not relabel a final-fit in-sample prediction.
            preview_rows=previous.sort_values('origin').groupby('family',sort=False).tail(1).copy() if len(previous) else pd.DataFrame()
            if not preview_rows.empty:
                preview_rows['preview_status']='saved_historical_oof_not_final_fit_or_current_forecast'
                all_preliminary.append(preview_rows)
            bundle=dict(models=models,direction=direction,ensemble=ensemble,calibrations=calibration,
                calibrations_by_ovx_regime=calibration_by_ovx_regime,config=config,
                regime=regime['id'],horizon=horizon,fit_cutoff=cutoff.isoformat(),gates=gates,input_manifest=freeze,
                training_maximum_label_end=train.label_end.max(),
                historical_preview=json.loads(preview_rows.to_json(orient='records')),
                live_prediction_status='No current feature snapshot supplied to this development-only stage',
                B_official_structural=official_structural_forecast(None,float(train.base_price_lbp_20l.iloc[-1])),production_approved=False)
            directory=root/'data/models/part5'/regime['id']/horizon
            save_bundle(directory,bundle)
            loaded=load_bundle(directory)
            # Serialization smoke checks on training inputs are explicitly not accuracy tests.
            for family,model in models.items():
                tail=train.tail(1).copy()
                if family=='D_sarimax':
                    index=model.extra['index_column'];tail[index]=model.extra['last_index']+1
                np.testing.assert_allclose(model.predict(tail),loaded['models'][family].predict(tail),equal_nan=True)
            for family in config['families']+['B_official_structural']:
                present=family in models or (family=='H_ensemble' and bool(ensemble['weights']))
                availability.append(dict(regime=regime['id'],horizon=horizon,family=family,
                    status='saved_and_reload_verified' if present else 'abstained',
                    reason=gates.get(family,'Missing complete dated official parameters' if family=='B_official_structural' else ''),
                    train_rows=len(train),train_base_decisions=train.base_revision_id.nunique(),origin=cutoff.isoformat()))
            print(f"  {len(train)} training rows; {len(models)} fitted point models; {len(previous)} matured OOF model rows",flush=True)
    oof=pd.concat(all_oof,ignore_index=True);oof.to_csv(report/'development_predictions.csv',index=False)
    metrics(oof).to_csv(report/'model_metrics.csv',index=False)
    comparisons(oof).to_csv(report/'baseline_comparisons.csv',index=False)
    pd.concat(all_preliminary,ignore_index=True).to_csv(report/'historical_preliminary_forecasts.csv',index=False)
    pd.DataFrame(availability).to_csv(report/'model_availability.csv',index=False)
    dump(report/'fold_log.json',foldlog)
    coverage=data.groupby(['regime','horizon']).agg(rows=('origin','size'),distinct_base_decisions=('base_revision_id','nunique'),first_origin=('origin','min'),last_origin=('origin','max'))
    coverage.to_csv(report/'target_coverage.csv')
    dump(report/'live_forecast_gate.json',dict(checked_at=datetime.now(timezone.utc).isoformat(),production_approved=False,
        horizons={h:dict(status='development_only',reasons=['Production selection and dashboard integration are outside this stage',
            'Residual probabilities and intervals require independent evaluation; current official timing and policy remain unresolved']) for h in horizon_ids(config)}))
    dump(report/'run_manifest.json',dict(**freeze,completed_at=datetime.now(timezone.utc).isoformat(),
        prediction_rows=len(oof),development_origin_horizon_rows=len(oof.drop_duplicates(['regime','horizon','origin'])),
        saved_bundles=len(config['regimes'])*len(horizon_ids(config)),production_winner=None,
        output_hashes={p.name:digest(p) for p in sorted(report.glob('*.csv'))}))
    return {'prediction_rows':len(oof),'saved_bundles':len(config['regimes'])*len(horizon_ids(config)),'production_winner':None}
