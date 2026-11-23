import argparse,json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='Model risk validation; strict and research evidence are separate')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('command',choices=['run','report','stress','ledger-check','settle'])
    parser.add_argument('--manifest',type=Path)
    args=parser.parse_args()
    if args.command=='run':
        from .runner import run
        result=run(args.root)
    elif args.command=='report':
        from .reporting import report
        result=report(args.root)
    elif args.command=='stress':
        from .stress import run
        result=run(args.root)
    elif args.command=='settle':
        if args.manifest is None:parser.error('settle requires --manifest')
        from .settlement import settle
        result=settle(args.root,args.manifest)
    else:
        from .ledger import ForecastLedger
        s=ForecastLedger(args.root/'data/forecast_ledger.sqlite');result=s.integrity();s.close()
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
