"""Reconcile only visually transcribed, hash-bound official annexes."""
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path
import csv
import json
from .engine import price, parameters


def reconcile(root):
    root = Path(root)
    records = json.loads((root/'data/manual/structural_annexes.json').read_text())
    parameter_rows = [dict(document_date=r['date'], parameter=name, **p)
                      for r in records for name,p,_ in parameters(r['request'])]
    with (root/'research/structural_parameters.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in parameter_rows for k in r)))
        writer.writeheader();writer.writerows(parameter_rows)
    rows, outputs = [], []
    for record in records:
        if sha256((root/record['raw_path']).read_bytes()).hexdigest() != record['raw_sha256']:
            raise ValueError('Original annex evidence hash mismatch')
        result = price(record['request'])
        row = {k:record[k] for k in ('date','decision_number','source_url','raw_sha256','printed_price_lbp_20l')}
        row.update(reconstructed_unrounded_lbp_20l=result['unrounded_lbp_20l'],
                   signed_error_lbp_20l=str(D(result['unrounded_lbp_20l'])-D(record['printed_price_lbp_20l'])),
                   pretax_error_lbp_kl=str(D(result['pretax_lbp_kl'])-D(record['printed_pretax_lbp_kl'])),
                   vat_error_lbp_kl=str(D(result['vat_lbp_kl'])-D(record['printed_vat_lbp_kl'])),
                   printed_fx_lbp_usd=record['printed_fx_lbp_usd'], printed_goods_usd_kl=record['printed_goods_usd_kl'],
                   goods_conversion_discrepancy_lbp_kl=None, evaluation_kind='same_document_accounting_NOT_FORECAST')
        if record['printed_fx_lbp_usd']:
            row['goods_conversion_discrepancy_lbp_kl'] = str(D(record['request']['goods_lbp_kl']['value'])-D(record['printed_goods_usd_kl'])*D(record['printed_fx_lbp_usd']))
        rows.append(row); outputs.append(dict(date=record['date'],**result))
    output = root/'data/exports/structural'; output.mkdir(parents=True,exist_ok=True)
    with (output/'annex_reconstructions.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (output/'annex_breakdowns.json').write_text(json.dumps(outputs,indent=2))
    result=dict(n=len(rows), earliest=rows[0]['date'], latest=rows[-1]['date'],
                mae_lbp_20l=float(sum(abs(D(r['signed_error_lbp_20l'])) for r in rows)/len(rows)),
                max_absolute_error_lbp_20l=float(max(abs(D(r['signed_error_lbp_20l'])) for r in rows)),
                bias_lbp_20l=float(sum(D(r['signed_error_lbp_20l']) for r in rows)/len(rows)),
                prediction_sample_size=0, directional_accuracy=None, change_error=None,
                caveat='These checks use components from the same published decision. They are not forecasts; no consecutive-annex sample exists.',rows=rows)
    (root/'reports/structural/annex_validation.json').write_text(json.dumps(result,indent=2))
    return result
