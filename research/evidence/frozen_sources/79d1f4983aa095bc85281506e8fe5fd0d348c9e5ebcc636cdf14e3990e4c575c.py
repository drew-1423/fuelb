"""Small CPU models, fitted only to purged historical development labels."""
from dataclasses import dataclass, field
import warnings
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import Ridge
from scipy.optimize import lsq_linear

from .data import feature_columns, mature_training
from lebanon_fuel.structural.engine import price


class InadequateData(ValueError):
    """An explicit abstention, not a failed prediction replaced by a baseline."""


def weights(frame):
    # Each observed base decision has equal total weight despite daily derived rows.
    counts=frame.groupby('base_revision_id').base_revision_id.transform('size')
    return 1.0/counts.to_numpy(float)


def preprocess():
    return make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler())


def inner_split(frame,fraction=.7):
    cut=frame.iloc[min(len(frame)-1,max(1,int(len(frame)*fraction)))].origin
    before=mature_training(frame,cut)
    after=frame[pd.to_datetime(frame.origin,utc=True)>=pd.Timestamp(cut)].copy()
    return before,after


def tree(config,kind='lightgbm',quantile=None):
    p=config['trees']
    if kind=='catboost':
        from catboost import CatBoostRegressor
        return CatBoostRegressor(iterations=p['iterations'],depth=p['depth'],learning_rate=p['learning_rate'],
            l2_leaf_reg=p['regularization'],random_seed=config['random_seed'],thread_count=config['threads'],
            loss_function='RMSE',verbose=False,allow_writing_files=False)
    from lightgbm import LGBMRegressor
    kwargs=dict(objective='regression' if quantile is None else 'quantile',n_estimators=p['iterations'],
        max_depth=p['depth'],num_leaves=2**p['depth'],min_child_samples=p['minimum_leaf'],
        learning_rate=p['learning_rate'],reg_lambda=p['regularization'],verbosity=-1,
        random_state=config['random_seed'],n_jobs=config['threads'],deterministic=True,force_col_wise=True)
    if quantile is not None:kwargs['alpha']=quantile
    return LGBMRegressor(**kwargs)


def composite_slope(frame):
    x=frame.x_structural_cost_gap.to_numpy(float);y=frame.target_change_lbp_20l.to_numpy(float);w=weights(frame)
    valid=np.isfinite(x)&np.isfinite(y)
    if valid.sum()<12 or np.sum(w[valid]*x[valid]**2)<=0:raise InadequateData('Too few observed product-gap inputs')
    # Unit: (LBP/20 L)/(USD/bbl). Composite coefficient, NOT an exchange rate.
    return max(0.0,float(np.sum(w[valid]*x[valid]*y[valid])/np.sum(w[valid]*x[valid]**2)))


STRUCTURAL_COLUMNS=['x_structural_delta_lbp_20l','x_domestic_change_lag1','x_fiscal_shock_lag1']


def structural_matrix(frame, fills):
    columns=[]
    for name in STRUCTURAL_COLUMNS:
        series=frame[name] if name in frame else pd.Series(np.nan,index=frame.index)
        columns.append(series.fillna(fills[name]).to_numpy(float) if name in fills else series.to_numpy(float))
    return np.column_stack(columns)


def differential_fit(frame):
    if STRUCTURAL_COLUMNS[0] not in frame:
        raise InadequateData('Differential structural feature is missing')
    usable=frame[np.isfinite(frame[STRUCTURAL_COLUMNS[0]])].copy()
    if usable.base_revision_id.nunique()<12:
        raise InadequateData('Too few observed structural-delta inputs')
    lag=usable['x_domestic_change_lag1'].median()
    fills={'x_domestic_change_lag1':float(lag) if pd.notna(lag) else 0.,'x_fiscal_shock_lag1':0.}
    x=structural_matrix(usable,fills);scales=np.maximum(np.std(x,axis=0),1.)
    design=np.c_[x/scales,np.ones(len(x))];w=np.sqrt(weights(usable));y=usable.target_change_lbp_20l.to_numpy(float)
    # Fixed ridge regularization, no intercept penalty. Only economic pass-through
    # is constrained nonnegative; lag response and shock adjustment may have either sign.
    penalty=np.diag([1.,1.,1.,0.])
    result=lsq_linear(np.r_[design*w[:,None],penalty],np.r_[y*w,np.zeros(4)],
                      bounds=([0.,-np.inf,-np.inf,-np.inf],np.full(4,np.inf)))
    if not result.success:raise InadequateData('Constrained structural fit did not converge')
    return dict(structural_coefficients=(result.x[:3]/scales).tolist(),intercept_lbp=float(result.x[3]),
                structural_fill_values=fills,structural_columns=STRUCTURAL_COLUMNS,structural_version=2,
                observed_structural_train_rows=len(usable),
                interpretation='Estimated differential pass-through with lag and shock flag; not official pricing parameters')


def differential_predict(frame,extra):
    return structural_matrix(frame,extra['structural_fill_values'])@np.asarray(extra['structural_coefficients'])+extra['intercept_lbp']


@dataclass
class Model:
    family:str
    columns:list=field(default_factory=list)
    transform:object=None
    fitted:object=None
    extra:dict=field(default_factory=dict)

    def predict(self,frame):
        if self.family in {'A_no_change','A_mean','A_median'}:
            return np.repeat(self.extra['constant'],len(frame)).astype(float)
        if self.family=='B_structural_proxy':
            if 'structural_coefficients' in self.extra:return differential_predict(frame,self.extra)
            return frame.x_structural_cost_gap.to_numpy(float)*self.extra['slope']
        if self.family=='Z_last_change':
            kind,n=str(frame.horizon.iloc[0]).split('_')
            factor=int(n) if kind=='decision' else int(n)/frame.x_interval_median.clip(lower=1).to_numpy(float)
            return frame.x_domestic_change_lag1.to_numpy(float)*factor
        x=self.transform.transform(frame[self.columns])
        if self.family=='D_sarimax':
            x=x[:,self.extra['sarimax_keep']]
            values=[]
            for (_,row),features in zip(frame.iterrows(),x):
                steps=int(row[self.extra['index_column']])-self.extra['last_index']
                if steps<=0:raise ValueError('SARIMAX prediction must follow fitted sequence')
                # AR errors with contemporaneous exog. Intermediate exog is held at
                # currently observed values; it never uses later market observations.
                forecast=self.fitted.get_forecast(steps=steps,exog=np.tile(features,(steps,1)) if len(features) else None)
                values.append(float(np.asarray(forecast.predicted_mean)[-1])*self.extra['y_scale'])
            return np.array(values)
        result=np.asarray(self.fitted.predict(x),float)
        if self.family=='G_hybrid':
            result+=differential_predict(frame,self.extra) if 'structural_coefficients' in self.extra else frame.x_structural_cost_gap.to_numpy(float)*self.extra['slope']
        return result

    def quantiles(self,frame):
        if 'quantile_models' not in self.extra:return None
        x=self.transform.transform(frame[self.columns])
        a,b=[np.asarray(m.predict(x),float) for m in self.extra['quantile_models']]
        return np.minimum(a,b),np.maximum(a,b)


def fit_model(family,frame,config):
    frame=frame.sort_values('origin').copy()
    if frame.base_revision_id.nunique()<config['minimum_train']:raise InadequateData('Fewer than minimum distinct base decisions')
    y=frame.target_change_lbp_20l.to_numpy(float);w=weights(frame)
    model=Model(family,extra={'train_rows':len(frame),'train_base_decisions':frame.base_revision_id.nunique(),
        'maximum_training_label_end':frame.label_end.max(),'first_training_origin':frame.origin.min(),
        'last_training_origin':frame.origin.max()})
    if family.startswith('A_'):
        order=np.argsort(y);median=y[order][np.searchsorted(np.cumsum(w[order]),sum(w)/2)]
        model.extra['constant']={'A_no_change':0.0,'A_mean':float(np.average(y,weights=w)),'A_median':float(median)}[family]
        return model
    if family=='B_structural_proxy':
        model.extra.update(differential_fit(frame))
        return model
    if family=='Z_last_change':return model
    if family in {'E_lightgbm','F_catboost'} and frame.base_revision_id.nunique()<config['minimum_tree_train']:
        raise InadequateData('Too few distinct decisions for tree model')
    columns=feature_columns(frame,distributed=family=='C_distributed')
    if family=='D_sarimax':
        index_column='sequence_index' if str(frame.horizon.iloc[0]).startswith('decision_') else 'day_index'
        runs=frame[index_column].diff().ne(1).cumsum();frame=frame[runs==runs.iloc[-1]].copy()
        if len(frame)<config['minimum_sarimax_run']:raise InadequateData('Latest contiguous sequence has fewer than minimum SARIMAX observations')
        columns=['x_domestic_change_lag1','x_structural_cost_gap','x_brent_spot_return7','x_days_since_source_date']
        y=frame.target_change_lbp_20l.to_numpy(float);w=weights(frame)
        model.extra.update(train_rows=len(frame),train_base_decisions=frame.base_revision_id.nunique(),
                           last_index=int(frame[index_column].iloc[-1]),index_column=index_column)
    model.columns=columns;model.transform=preprocess();x=model.transform.fit_transform(frame[columns])
    if family.startswith('C_'):
        before,after=inner_split(frame);scores={}
        if before.base_revision_id.nunique()>=12 and after.base_revision_id.nunique()>=8:
            prep=preprocess();xi=prep.fit_transform(before[columns]);xv=prep.transform(after[columns])
            for alpha in config['ridge_alphas']:
                m=Ridge(alpha=alpha).fit(xi,before.target_change_lbp_20l,sample_weight=weights(before))
                scores[alpha]=float(np.average(abs(m.predict(xv)-after.target_change_lbp_20l),weights=weights(after)))
        alpha=min(scores,key=scores.get) if scores else config['ridge_alphas'][-1]
        model.fitted=Ridge(alpha=alpha).fit(x,y,sample_weight=w)
        model.extra.update(alpha=alpha,inner_mae=scores,inner_tuning='chronological_purged' if scores else 'fixed_strong_regularization_insufficient_inner_data')
    elif family=='D_sarimax':
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        # Constant columns add no information and can duplicate the intercept.
        keep=np.std(x,axis=0)>1e-10;model.extra['sarimax_keep']=keep
        scale=max(float(np.std(y)),1.0);model.extra['y_scale']=scale
        with warnings.catch_warnings(record=True) as caught:
            result=SARIMAX(y/scale,exog=x[:,keep] if keep.any() else None,order=(1,0,0),trend='c',
                           enforce_stationarity=True,enforce_invertibility=True).fit(disp=False,maxiter=300)
        if not result.mle_retvals.get('converged',False):raise InadequateData('SARIMAX optimizer did not converge')
        model.fitted=result;model.extra['fit_warnings']=[str(w.message) for w in caught]
    elif family in {'E_lightgbm','F_catboost'}:
        model.fitted=tree(config,'catboost' if family=='F_catboost' else 'lightgbm').fit(x,y,sample_weight=w)
        if family=='E_lightgbm':
            alpha=(1-config['coverage'])/2
            model.extra['quantile_models']=[tree(config,quantile=q).fit(x,y,sample_weight=w) for q in (alpha,1-alpha)]
    elif family=='G_hybrid':
        # Cross-fitted differential-base residuals, with label purging at each block.
        residual_rows=[];residual_y=[];residual_folds=[]
        for fraction,next_fraction in ((.35,.55),(.55,.75),(.75,1.0)):
            start=int(len(frame)*fraction);end=int(len(frame)*next_fraction)
            block=frame.iloc[start:end];past=mature_training(frame,block.origin.iloc[0])
            if past.base_revision_id.nunique()<12:continue
            try:base=differential_fit(past)
            except InadequateData:continue
            predicted=differential_predict(block,base);ok=np.isfinite(predicted);block=block[ok]
            if block.empty:continue
            residual_rows.append(block);residual_y.extend(block.target_change_lbp_20l-predicted[ok])
            residual_folds.append(dict(first_residual_origin=block.origin.min(),last_residual_origin=block.origin.max(),
                                       maximum_base_fit_label_end=past.label_end.max(),n=len(block)))
        residual=pd.concat(residual_rows) if residual_rows else frame.iloc[:0]
        if residual.base_revision_id.nunique()<24:raise InadequateData('Insufficient past-only base residuals for hybrid')
        model.extra.update(differential_fit(frame),cross_fitted_residual_rows=len(residual),residual_folds=residual_folds)
        model.fitted=tree(config) if residual.base_revision_id.nunique()>=config['minimum_tree_train'] else Ridge(alpha=100.)
        model.extra['residual_model']='lightgbm' if hasattr(model.fitted,'num_leaves') else 'ridge_fixed_alpha_100'
        model.fitted.fit(model.transform.transform(residual[columns]),residual_y,sample_weight=weights(residual))
    else:raise ValueError(f'Unknown family: {family}')
    return model


def official_structural_forecast(request,base_price_lbp_20l):
    """Use the actual Part 4 engine; never silently substitute a regression."""
    if request is None:
        return {'status':'abstain','reason':'Missing dated benchmark, FX, cost/tax components and future input scenarios',
                'predicted_change_lbp_20l':None,'family':'B_official_structural'}
    if request['mode']=='reconciliation':raise ValueError('Same-annex reconciliation is not a forecast')
    result=price(request)
    return {'status':'conditional_scenario' if request['mode']=='scenario' else 'estimated_as_of',
            'predicted_change_lbp_20l':float(result['price_lbp_20l'])-float(base_price_lbp_20l),
            'family':'B_official_structural','structural_output':result}
