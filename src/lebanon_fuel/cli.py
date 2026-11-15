"""Explicit, local data operations. No background jobs or training."""
import argparse
from datetime import datetime
from pathlib import Path
import json
import sys
import tomllib

from lebanon_fuel.domain import BEIRUT, now_utc
from lebanon_fuel.storage.database import Store
from lebanon_fuel.ingestion.http import PublicClient
from lebanon_fuel.ingestion.adapters import (collect_ipt, collect_ministry, collect_taqtek, parse_ipt, parse_manual, parse_ministry, parse_taqtek)


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.cwd())
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    c=sub.add_parser('collect')
    c.add_argument('--source',choices=['ipt','ministry','taqtek','all'],default='all')
    c.add_argument('--start',default='2008-01-01',help='Ministry lower bound; IPT/Taqtek collect complete exposed history')
    c.add_argument('--end',default=datetime.now(BEIRUT).date().isoformat(),help='Ministry upper date bound')
    x=sub.add_parser('import-ipt');x.add_argument('path',type=Path)
    x.add_argument('--source-url',required=True);x.add_argument('--retrieved-at')
    x=sub.add_parser('import-csv');x.add_argument('path',type=Path)
    x.add_argument('--source',choices=['manual','official_document'],default='manual')
    x.add_argument('--evidence',type=Path);x.add_argument('--retrieved-at')
    x=sub.add_parser('import-html');x.add_argument('path',type=Path)
    x.add_argument('--source',choices=['ministry','taqtek'],required=True)
    x.add_argument('--source-url',required=True);x.add_argument('--retrieved-at')
    x=sub.add_parser('download-official');x.add_argument('--url',required=True)
    x=sub.add_parser('resolve')
    x.add_argument('--date',required=True);x.add_argument('--observation-id',required=True,type=int)
    x.add_argument('--reason',required=True);x.add_argument('--evidence-url',required=True);x.add_argument('--reviewer',required=True)
    x=sub.add_parser('observations');x.add_argument('--date',required=True)
    sub.add_parser('export')
    x=sub.add_parser('report');x.add_argument('--as-of',default=datetime.now(BEIRUT).date().isoformat())
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    cfg_path=args.root/'config/project.toml'
    cfg=tomllib.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    store=Store(args.root,cfg.get('storage',{}).get('database','data/lebanon_fuel.sqlite'))
    try:
        if args.command=='collect':
            failures=[]
            for source in (['ipt','ministry','taqtek'] if args.source=='all' else [args.source]):
                run=store.start_run(source)
                client=PublicClient(store,source,run,cfg.get('collection',{}).get('minimum_request_interval_seconds',3))
                try:
                    if source=='ipt': result=collect_ipt(client)
                    elif source=='ministry': result=collect_ministry(client,args.start,args.end)
                    else: result=collect_taqtek(client)
                    store.finish_run(run,'success',result)
                    print(json.dumps({'source':source,**result}),flush=True)
                except Exception as exc:
                    failures.append(source)
                    store.finish_run(run,'failed',{'error':str(exc),'type':type(exc).__name__})
                    print(f'{source}: FAILED: {exc}',file=sys.stderr,flush=True)
                finally: client.close()
            store.reconcile()
            return 1 if failures else 0
        if args.command.startswith('import-'):
            source='ipt' if args.command=='import-ipt' else args.source
            run=store.start_run(source)
            try:
                raw=args.path.read_bytes()
                evidence_cap=None
                manual_rows=list(parse_manual(raw,source)) if args.command=='import-csv' else None
                if args.command=='import-csv' and source=='official_document':
                    if not args.evidence:
                        raise ValueError('Official document import requires the original PDF via --evidence')
                    evidence=args.evidence.read_bytes()
                    if not evidence.startswith(b'%PDF'):
                        raise ValueError('Evidence must be an original PDF')
                    urls={row.source_url for row in manual_rows}
                    if len(urls)!=1:
                        raise ValueError('One original PDF per official CSV import; use separate files for different documents')
                    evidence_url=urls.pop()
                    from hashlib import sha256
                    existing=store.db.execute('SELECT id FROM captures WHERE source_id=? AND url=? AND sha256=? ORDER BY id DESC LIMIT 1',(source,evidence_url,sha256(evidence).hexdigest())).fetchone()
                    evidence_cap=existing[0] if existing else store.capture(source,evidence_url,evidence,'application/pdf',run,metadata={'kind':'manual_evidence','evidence_path':str(args.evidence),'retrieval_basis':'local_import_time'})
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if source=='ipt' else 'text/csv' if args.command=='import-csv' else 'text/html'
                url=getattr(args,'source_url',None) or args.path.resolve().as_uri()
                cap=store.capture(source,url,raw,content_type,run,metadata={'kind':'manual_file_import','original_path':str(args.path),'retrieval_basis':'supplied' if args.retrieved_at else 'local_import_time','evidence_capture_id':evidence_cap},retrieved_at=args.retrieved_at)
                if source=='ipt': rows=parse_ipt(raw)
                elif args.command=='import-csv': rows=manual_rows
                elif source=='ministry': rows=parse_ministry(raw,args.source_url)
                else: rows=parse_taqtek(raw)
                if evidence_cap:
                    rows=list(rows)
                    digest=store.db.execute('SELECT sha256 FROM captures WHERE id=?',(evidence_cap,)).fetchone()[0]
                    for row in rows: row.raw['evidence_sha256']=digest
                result=store.ingest(cap,rows)
                store.finish_run(run,'success',result)
                store.reconcile()
                print(json.dumps(result))
            except Exception as exc:
                store.finish_run(run,'failed',{'error':str(exc)})
                raise
        elif args.command=='download-official':
            from urllib.parse import urlparse
            if not (urlparse(args.url).hostname or '').endswith('.gov.lb'):
                raise ValueError('Official evidence must come from a government host')
            run=store.start_run('official_document')
            client=PublicClient(store,'official_document',run)
            try:
                result=client.fetch(args.url)
                if not result.response.content.startswith(b'%PDF'):
                    raise ValueError('Official URL did not return a PDF')
                capture=dict(store.db.execute('SELECT * FROM captures WHERE id=?',(result.capture_id,)).fetchone())
                store.finish_run(run,'success',{'capture_id':result.capture_id,'evidence_only':True})
                print(json.dumps(capture))
            except Exception as exc:
                store.finish_run(run,'failed',{'error':str(exc)})
                raise
            finally: client.close()
        elif args.command=='resolve':
            store.resolve(args.date,args.observation_id,args.reason,args.evidence_url,args.reviewer)
            print(json.dumps({'new_decision_versions':store.reconcile()}))
        elif args.command=='observations':
            for row in store.db.execute('SELECT * FROM observations WHERE source_date=? ORDER BY source_id,id',(args.date,)):
                print(json.dumps(dict(row),ensure_ascii=False))
        elif args.command in {'export','report'}:
            from lebanon_fuel.validation.quality import export_data, report
            store.reconcile()
            export_data(store,args.root/cfg.get('storage',{}).get('export_dir','data/exports'))
            if args.command=='report':
                summary=report(store,args.root/cfg.get('storage',{}).get('report_dir','reports'),args.as_of,cfg.get('collection',{}).get('stale_after_days',10))
                print(json.dumps(summary,ensure_ascii=False,indent=2))
        else:
            print('SQLite schema initialized')
        return 0
    except Exception as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__=='__main__':
    raise SystemExit(main())
