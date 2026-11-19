"""Part 5 command-line entry points."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='Lebanese gasoline development research; not approved for live forecasts')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('command',choices=['build','train','report','preview','news','news-ablation','forecast-gate'])
    parser.add_argument('--regime',choices=['pre_crisis','recent_pre_fiscal'],default='recent_pre_fiscal')
    parser.add_argument('--horizon',choices=['decision_1','decision_2','decision_4','day_1','day_3','day_7','day_14','day_30'],default='decision_1')
    args=parser.parse_args();root=args.root
    if args.command=='build':
        from .data import build
        data,snap=build(root,json.loads((root/'config/forecasting_research.json').read_text()))
        result={'target_rows':len(data),'origin_feature_rows':len(snap)}
    elif args.command=='train':
        from .pipeline import run
        result=run(root)
    elif args.command=='report':
        from .reporting import report
        result=report(root)
    elif args.command=='preview':
        from .pipeline import preview
        result=preview(root,args.regime,args.horizon)
    elif args.command=='news':
        from lebanon_fuel.news.pipeline import collect,report
        result={'collection':collect(root),'report':report(root)}
    elif args.command=='news-ablation':
        from lebanon_fuel.news.ablation import run
        result=run(root)
    else:result=json.loads((root/'reports/forecasting/live_forecast_gate.json').read_text())
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
