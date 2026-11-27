"""One-shot commands suitable for a user-managed local scheduler."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
import tomllib

from lebanon_fuel.features.market import snapshot
from .catalog import SERIES
from .collectors import (collect, collect_options_chain, collect_fred_ovx,
                         collect_ovx_csv_input, ENERGY_OPTIONS, manual_import, parse_capture)
from .store import MarketStore


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('collect');p.add_argument('--source',choices=['all','eia','ec','fed','cboe','fred'],default='all');p.add_argument('--input',type=Path)
    p=sub.add_parser('options');p.add_argument('--symbol',choices=ENERGY_OPTIONS,default='USO');p.add_argument('--input',type=Path,required=True)
    p=sub.add_parser('replay');p.add_argument('--capture-id',type=int,required=True);p.add_argument('--series',choices=SERIES,required=True)
    p=sub.add_parser('import-csv');p.add_argument('path',type=Path);p.add_argument('--series',choices=SERIES,required=True)
    p.add_argument('--source-url',required=True);p.add_argument('--license-note',required=True)
    p=sub.add_parser('snapshot');p.add_argument('--origin',required=True);p.add_argument('--mode',choices=['captured','strict','research','as_of_close'],default='captured');p.add_argument('--output',type=Path)
    p=sub.add_parser('report');p.add_argument('--as-of',default=datetime.now(timezone.utc).isoformat())
    args=parser.parse_args(argv)
    root=args.root.resolve()
    config=tomllib.loads((root/'config/project.toml').read_text()) if (root/'config/project.toml').exists() else {}
    store=MarketStore(root,config.get('storage',{}).get('database','data/lebanon_fuel.sqlite'))
    try:
        if args.command=='collect':
            if args.input is not None:
                if args.source != 'cboe':
                    print(json.dumps({"status":"error","error":"--input is supported with --source cboe only"}))
                    return 2
                result = collect_ovx_csv_input(store, args.input)
                print(json.dumps(result, indent=2))
                return int(result['status'] != 'ok')
            if args.source == 'fred':
                result = collect_fred_ovx(store)
                print(json.dumps(result, indent=2))
                return int(result['status'] != 'ok')
            failures=[]
            for source in (['eia','ec','fed'] if args.source=='all' else [args.source]):
                try:
                    results = collect(store,'market_'+source)
                    print(json.dumps(results),flush=True)
                    if any(result.get('status') == 'error' for result in results):
                        failures.append(source)
                except Exception as exc:
                    failures.append(source)
                    print(f'{source}: FAILED: {exc}',file=sys.stderr,flush=True)
            return int(bool(failures))
        if args.command=='options':
            result = collect_options_chain(store, args.symbol, input_path=args.input)
            print(json.dumps(result, indent=2))
            return int(result['status'] != 'ok')
        if args.command=='replay':
            result=parse_capture(store,args.capture_id,args.series)
        elif args.command=='import-csv':
            result=manual_import(store,args.path,args.series,args.source_url,args.license_note)
        elif args.command=='snapshot':
            result=snapshot(store,args.origin,args.mode)
            if args.output:
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_text(json.dumps(result,indent=2))
        else:
            from .reports import report
            result=report(store,args.as_of)
        print(json.dumps(result,indent=2))
        return 1 if args.command=='report' and result['raw_hash_failures'] else 0
    finally:
        store.close()


if __name__=='__main__':
    raise SystemExit(main())
