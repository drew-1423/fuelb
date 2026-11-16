import argparse,json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='Model risk validation; strict and research evidence are separate')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('command',choices=['run','report','stress','ledger-check','settle','freeze-shadow','issue-shadow','replay-shadow','report-shadow'])
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--origin', help='Explicit timezone-aware replay origin')
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
    elif args.command.endswith('-shadow'):
        from . import shadow
        if args.manifest is None:
            parser.error(f'{args.command} requires --manifest')
        if args.command == 'replay-shadow':
            if args.origin is None:
                parser.error('replay-shadow requires --origin')
            result = shadow.replay(args.root, args.manifest, args.origin)
        else:
            handlers = {'freeze-shadow': shadow.freeze, 'issue-shadow': shadow.issue, 'report-shadow': shadow.report}
            result = handlers[args.command](args.root, args.manifest)
    else:
        from .ledger import ForecastLedger
        s=ForecastLedger(args.root/'data/forecast_ledger.sqlite');result=s.integrity();s.close()
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
