"""Offline structural calculations using retained source evidence."""
from pathlib import Path
import argparse
import json


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path.cwd())
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('reconcile');sub.add_parser('research');sub.add_parser('report')
    p=sub.add_parser('price');p.add_argument('input',type=Path);p.add_argument('--output',type=Path)
    pdf=sub.add_parser('parse-pdf');pdf.add_argument('pdf_path',type=Path);pdf.add_argument('--url',type=str,default=None)
    args=parser.parse_args(argv);root=args.root.resolve()
    if args.command=='parse-pdf':
        from .pdf_parser import parse_official_pdf
        result=parse_official_pdf(args.pdf_path,source_url=args.url)
    elif args.command=='price':
        from .engine import price
        result=price(json.loads(args.input.read_text()))
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    elif args.command=='reconcile':
        from .annexes import reconcile
        result=reconcile(root)
    elif args.command=='research':
        from .research import run
        result=run(root)
    else:
        from .reporting import report
        result=report(root)
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':
    raise SystemExit(main())
