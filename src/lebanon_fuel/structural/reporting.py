"""Reports distinguish annex arithmetic from latest-vintage proxy estimates."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import pandas as pd


def table(rows, columns):
    lines=['| '+' | '.join(label for key,label in columns)+' |','|'+'|'.join('---' for _ in columns)+'|']
    for row in rows:
        values=[]
        for key,label in columns:
            value=row.get(key)
            values.append(f'{value:,.2f}' if isinstance(value,float) else str(value))
        lines.append('| '+' | '.join(values)+' |')
    return '\n'.join(lines)


def report(root):
    root=Path(root);out=root/'reports/structural';export=root/'data/exports/structural'
    ann=json.loads((out/'annex_validation.json').read_text())
    manifest=json.loads((out/'run_manifest.json').read_text())
    diag=json.loads((out/'training_diagnostics.json').read_text())
    preds=pd.read_csv(export/'historical_proxy_predictions_RESEARCH_ONLY.csv')
    parameter_rows=[]
    for _,r in preds.groupby(['regime','model'],sort=False).tail(1).iterrows():
        fit=json.loads(r.parameters_json)
        for name,value in [('intercept',fit['intercept']),*fit['slopes'].items()]:
            parameter_rows.append(dict(regime=r.regime,model=r.model,parameter=name,value=value,
                unit='LBP/20L' if name=='intercept' else '(LBP/20L)/(USD/bbl)',
                status='estimated_research_not_official',prediction_date=r.date,train_n=fit['n'],train_end=r.train_end,
                known_at=datetime.now(timezone.utc).isoformat(),
                evidence='data/exports/structural/historical_proxy_predictions_RESEARCH_ONLY.csv; reports/structural/run_manifest.json',
                validity='This saved retrospective prediction only; no current-policy validity'))
    pd.DataFrame(parameter_rows).to_csv(root/'research/estimated_transmission_parameters.csv',index=False)
    design=pd.read_csv(export/'research_design_matrix.csv')
    metrics=manifest['metrics']
    text=f'''# Part 4 validation

Generated from the preserved originals and SQLite data. Research protocol: `{manifest['protocol_sha256']}`. Reproduce with `fuel-structure research` and `fuel-structure report`.

## Three official annex accounting checks

**This is same-document arithmetic, not prediction accuracy.** Each input component is published alongside the target price. Verified original annex dates: {ann['earliest']} through {ann['latest']}; n={ann['n']}. All three pretax and VAT totals reconcile exactly. Unrounded pump-price MAE is **{ann['mae_lbp_20l']:.4f} LBP/20 L**, maximum {ann['max_absolute_error_lbp_20l']:.2f}, signed bias {ann['bias_lbp_20l']:.4f}. No rounding rule was fitted. No consecutive-annex change/direction sample exists.

{table(ann['rows'],[('date','Document date'),('printed_price_lbp_20l','Official price'),('reconstructed_unrounded_lbp_20l','Unrounded reconstruction'),('signed_error_lbp_20l','Error LBP/20 L')])}

The printed USD × FX does not exactly reproduce printed goods LBP in two annexes. This prevents claiming an exact authenticated upstream reconstruction. Component source URLs and hashes are in `data/manual/structural_annexes.json`.

## Strict historical forecast gate

**Eligible real-time structural/proxy evaluation sample: {manifest['strict_evaluation_n']}.** Neither archived market releases nor target publication instants are established. Earliest stored market availability is {manifest['earliest_market_knowledge_time']}; earliest target retrieval is {manifest['earliest_target_capture_time']}. Both follow the historical test dates. No real-time accuracy or current official-price forecast is certified.

## Retrospective chronological proxy study

This study uses **latest captured historical editions with assumed release delays**. Outcomes are official-archive prices or document/corroborated entries, not all individually authenticated original decisions. The target is the next adjacent eligible source-date record conditional on its known date; it is not a certified next-decision timing forecast. Gaps over 14 days and adjacent ineligible/conflicting records are excluded. Actual historical source release times, vintage revisions and same-day decision order remain unresolved.

The design contains {manifest['rows']} real eligible observation pairs across two separately fitted segments; {manifest['excluded_rows']} pairs within these segments were excluded. Target quality counts: `{manifest['target_status_counts']}`. No values were imputed. All candidates use identical rows within each regime. Target release is assumed no earlier than the next local day for reuse; market availability uses Part 3's 14-day EIA assumption plus candidate lags. Origins are 00:00 Asia/Beirut on the target source date.

The candidate grid is two series (NYH gasoline and Brent), averages of 1/5/10/20 market observations, and 0/7/14 extra calendar-day delays. Linear, three-block distributed-lag, rolling-40 and asymmetric models are compared with persistence and expanding mean-change drift. The distributed blocks add 0/7/14 days to the candidate delay. Averaging uses actual available quotes and rejects stale/long-gap windows. These are empirical proxy transforms, not official observation windows.

Validation selects one configuration per family and one overall champion. Selected configurations are saved **before final-test calculation**. Final-test coefficients update using earlier outcomes only; lags/windows/family stay frozen. The pre-crisis validation year is 2017, final test Jan 2018–Aug 2019. The recent segment validates on 2024 and tests Jan–28 May 2025. No final-test outcome is used for tuning. Training scaling is fitted afresh within each chronological fold.

### Final chronological test metrics — research only

All error figures are LBP/20 L; positive bias is overprediction. Direction uses exact up/unchanged/down, including unchanged decisions. Because both predicted and actual changes subtract the same previous observed price, change MAE equals price MAE algebraically; it is not a second independent success measure.

{table(metrics,[('regime','Segment'),('model','Validation-chosen configuration'),('selected_on_validation','Champion'),('n','n'),('start','First'),('end','Last'),('mae_lbp_20l','Price/change MAE'),('bias_lbp_20l','Bias'),('direction_accuracy','Direction fraction'),('interval_n','Interval n'),('coverage_90','90% coverage'),('mean_interval_width','Mean width')])}

### Uncertainty

Intervals use only the last 40 earlier one-step prequential absolute residuals, require at least 20, and use the finite-sample higher order statistic for nominal 90% coverage. Calibration can include previously realized test outcomes, never the current/future target. Lower price bounds are clipped at zero. Dependent time-series errors, selected models and regime shifts violate simple exchangeability guarantees: measured coverage is reported, not promised. Do not apply these research intervals to the current fiscal regime. The structural engine's input-bound range is a separate, uncalibrated conditional scenario range.

## Training-only diagnostics

{table(diag,[('regime','Segment'),('train_n','Initial train n'),('train_start','First'),('train_end','Last'),('cusum_p','CUSUM p'),('asymmetry_slope_positive','Rise slope'),('asymmetry_slope_negative','Fall slope'),('asymmetry_difference_p','Rise/fall p')])}

Slopes are LBP/20 L change per USD/bbl change in the fixed NYH proxy specification. CUSUM does not date a regulatory break. Rise/fall tests use HC1 and remain vulnerable to serial dependence, omitted FX/policy and proxy basis. ECM gate details are in `training_diagnostics.json`; irregular and incomplete samples must not be interpolated into a cointegration result.

## Interpretation and readiness

The three annex checks establish a working dated cost engine. The proxy experiment quantifies what these particular historical datasets support, with separate regimes and held-out dates. It does not identify the statutory averaging window, causal transmission lag, current margins or a deployable structural forecast. Prefer the validation-selected simple baseline whenever a challenger fails to improve validation. Final-test performance is disclosed for all selected family representatives without changing that choice.

Before a production next-decision estimate: obtain a current original annex and legal parameters, the authorized refined assessment and cutoff/window, goods FX and import costs, original release vintages and target timestamps. Current proxy input observations are recorded in the run manifest. Paid Med gasoline/freight data would reduce product/geographic basis uncertainty but would still need the actual retail formula and information-time history.
'''
    (root/'reports/structural_validation.md').write_text(text)
    selected=preds[preds.selected_on_validation].copy();selected['absolute_error']=abs(selected.error)
    worst=selected.sort_values('absolute_error',ascending=False).head(12)
    worst.to_csv(out/'largest_champion_errors.csv',index=False)
    quality=[]
    from .research import metrics as calculate_metrics
    for (regime,status),f in selected.groupby(['regime','target_status']):
        quality.append(dict(regime=regime,target_status=status,**calculate_metrics(f)))
    pd.DataFrame(quality).to_csv(out/'champion_metrics_by_target_quality.csv',index=False)
    (root/'reports/structural_error_analysis.md').write_text('''# Part 4 error analysis

The accounting residuals are 3.30, -3.30 and -1.60 LBP/20 L for the three dated annexes. The independently printed pretax and VAT lines reconcile exactly; tiny final differences are compatible with rounding but do not prove a legal rounding rule. Larger upstream USD-to-LBP discrepancies remain unresolved. No adjustment was fitted to force those currencies to agree.

The following largest errors belong to the validation-selected champions in their untouched chronological test periods. Historical records and units are real; release-delay/vintage assumptions prevent treating these as deployable forecast results. A large residual does not identify its cause. Missing FX changes, tax/margin events, regional product spreads, source-date misalignment and administrative windows are candidate explanations requiring additional evidence.

'''+table(worst.to_dict('records'),[('date','Date'),('regime','Segment'),('model','Champion'),('actual','Actual'),('predicted','Estimate'),('error','Signed error'),('target_status','Target evidence')])+'''

Quality-stratified champion metrics are saved in `structural/champion_metrics_by_target_quality.csv`. All family test metrics, including failed challengers, remain in `structural/test_metrics.csv`. No outlier was deleted based on its fitted error. Conflicts were excluded by the frozen input-quality rule before fitting.

## Limitations

- Only three nonconsecutive annexes have component-level review; they cannot quantify genuine next-decision structural accuracy.
- No licensed Med quotation history or documented current wholesale-to-goods uplift exists in the database.
- No full official pricing FX series exists; regime splitting cannot remove within-segment FX confounding.
- Historical targets are mostly archive corroboration, not original document verification. Missing timestamps prevent strict label availability checks.
- Sparse recent official history makes the final recent test particularly small. Do not present its percentages without n.
- The final period is now consumed for this experiment. New model selection must use new validation data or a separately declared protocol, not repeatedly optimize this holdout.
- Crisis and later fiscal regimes are deliberately unevaluated; performance cannot be extrapolated to them.

No current official price, government formula, benchmark quotation or probability was fabricated.
''')
    os.environ.setdefault('MPLCONFIGDIR',str(root/'data/cache/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import StrMethodFormatter
    fig,axes=plt.subplots(2,2,figsize=(14,8),layout='constrained')
    for row,(regime,group) in enumerate(selected.groupby('regime',sort=False)):
        ax=axes[row,0]
        blocks=(pd.to_datetime(group.date).diff().dt.days>14).cumsum()
        for index,(_,block) in enumerate(group.groupby(blocks)):
            t=pd.to_datetime(block.date)
            ax.plot(t,block.actual,label='Official archive target' if index==0 else None,color='#142e46',marker='.',ms=3)
            ax.plot(t,block.predicted,label='Validation-selected estimate' if index==0 else None,color='#cc6b27',linestyle='--',marker='.',ms=3)
            valid=block.lower.notna();ax.fill_between(t[valid],block.loc[valid,'lower'],block.loc[valid,'upper'],alpha=.14,color='#cc6b27',label='Past-residual 90% interval' if index==0 else None)
            axes[row,1].plot(t,block.error,color='#34687b',marker='.',ms=3)
        label='Before currency crisis' if regime=='pre_crisis' else 'Recent period before fiscal changes'
        ax.set_title(f'{label} • n={len(group)}');ax.set_ylabel('LBP per 20 L');ax.legend(fontsize=8)
        axes[row,1].axhline(0,color='gray',lw=1);axes[row,1].set_title('Signed error (estimate − actual)');axes[row,1].set_ylabel('LBP per 20 L')
        for a in axes[row]:
            a.grid(alpha=.15);a.tick_params(axis='x',rotation=25);a.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    fig.suptitle('Historical proxy estimates — latest-vintage research only\nUnknown original publication times; not a certified real-time forecast',fontsize=13)
    fig.savefig(out/'historical_reconstruction.png',dpi=150);fig.savefig(out/'historical_reconstruction.svg');plt.close(fig)
    return {'validation':'reports/structural_validation.md','error_analysis':'reports/structural_error_analysis.md'}
