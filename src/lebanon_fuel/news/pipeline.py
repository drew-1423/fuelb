"""Primary EIA RSS ingestion and conservative, free rule-based transmission tags."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse
import json
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from lebanon_fuel.domain import utc_timestamp
from lebanon_fuel.storage.database import Store
from lebanon_fuel.ingestion.http import PublicClient

FEEDS=['https://www.eia.gov/rss/todayinenergy.xml','https://www.eia.gov/about/new/WNtest3.php']
CHANNELS={
 'opec_supply_policy':r'\bopec\b|declaration of cooperation|production (cut|quota)',
 'refining_capacity':r'refiner(y|ies|s)|refining|refinery outage',
 'physical_supply':r'supply (interrupt|disrupt|shortage)|pipeline|production (outage|disruption)|inventory|inventories',
 'shipping_freight_insurance':r'shipping|tanker|maritime|strait|freight|insurance|red sea|hormuz',
 'geopolitical_risk':r'geopolit|conflict|war\b|sanction|attack|middle east',
 'lebanese_fiscal_regulation':r'lebanon|lebanese|لبنان|المحروقات|ضريبة|الرسوم'
}
SCHEMA='''
CREATE TABLE IF NOT EXISTS news_items(
 id INTEGER PRIMARY KEY, semantic_hash TEXT NOT NULL UNIQUE, source_id TEXT NOT NULL,
 url TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,publication_timestamp TEXT,
 timestamp_raw TEXT,first_known_at TEXT NOT NULL,capture_id INTEGER NOT NULL REFERENCES captures(id),
 channels_json TEXT NOT NULL,classifier_version TEXT NOT NULL,issues_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS news_sightings(item_id INTEGER REFERENCES news_items(id),capture_id INTEGER REFERENCES captures(id),
 PRIMARY KEY(item_id,capture_id));
CREATE TRIGGER IF NOT EXISTS news_no_update BEFORE UPDATE ON news_items BEGIN SELECT RAISE(ABORT,'news observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS news_no_delete BEFORE DELETE ON news_items BEGIN SELECT RAISE(ABORT,'news observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS news_sightings_no_update BEFORE UPDATE ON news_sightings BEGIN SELECT RAISE(ABORT,'news sightings are immutable'); END;
CREATE TRIGGER IF NOT EXISTS news_sightings_no_delete BEFORE DELETE ON news_sightings BEGIN SELECT RAISE(ABORT,'news sightings are immutable'); END;
'''


def classify(title,summary):
    text=title+' '+summary
    return {key:bool(re.search(pattern,text,re.I)) for key,pattern in CHANNELS.items()}


def timestamp(raw):
    if not raw:return None
    try:
        dt=parsedate_to_datetime(raw)
    except (ValueError,TypeError):
        try:dt=datetime.fromisoformat(raw)
        except ValueError:return None
    if dt.utcoffset() is None:return None
    return utc_timestamp(dt.isoformat())


def initialize(store):
    store.db.executescript(SCHEMA)
    with store.db:store.db.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?)',('news_eia',10,'eia_primary'))


def parse_feed(raw):
    # ElementTree does not resolve external entities; reject DTDs explicitly as well.
    if b'<!DOCTYPE' in raw.upper():raise ValueError('DTD not accepted in public news feeds')
    tree=ET.fromstring(raw)
    for item in tree.findall('.//item'):
        url=item.findtext('link') or ''
        if urlparse(url).hostname not in {'www.eia.gov','eia.gov'}:continue
        title=BeautifulSoup(item.findtext('title') or '', 'html.parser').get_text(' ',strip=True)
        summary=BeautifulSoup(item.findtext('description') or '', 'html.parser').get_text(' ',strip=True)
        yield dict(url=url,title=title,summary=summary,timestamp_raw=item.findtext('pubDate'))


def ingest(store,capture_id,rows):
    initialize(store)
    cap=store.db.execute('SELECT * FROM captures WHERE id=?',(capture_id,)).fetchone()
    if cap['source_id']!='news_eia' or cap['http_status']!=200:raise ValueError('Successful approved primary-source capture required')
    count=added=timestamped=0
    with store.db:
        for row in rows:
            count+=1;pub=timestamp(row.get('timestamp_raw'));issues=[]
            if pub is None:issues.append('original_publication_timestamp_missing')
            elif pub>cap['retrieved_at']:issues.append('future_publication_timestamp')
            else:timestamped+=1
            digest=sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            c=store.db.execute('''INSERT OR IGNORE INTO news_items
              (semantic_hash,source_id,url,title,summary,publication_timestamp,timestamp_raw,first_known_at,capture_id,channels_json,classifier_version,issues_json)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',(digest,'news_eia',row['url'],row['title'],row['summary'],pub,row.get('timestamp_raw'),cap['retrieved_at'],capture_id,
              json.dumps(classify(row['title'],row['summary'])),'economic_channels_v1',json.dumps(issues)))
            added+=c.rowcount
            item=store.db.execute('SELECT id FROM news_items WHERE semantic_hash=?',(digest,)).fetchone()[0]
            store.db.execute('INSERT OR IGNORE INTO news_sightings VALUES (?,?)',(item,capture_id))
    return dict(parsed=count,new_items=added,with_source_timestamps=timestamped,capture_id=capture_id)


def collect(root):
    store=Store(Path(root));initialize(store);run=store.start_run('news_eia');client=PublicClient(store,'news_eia',run)
    results=[]
    try:
        for url in FEEDS:
            cap=client.fetch(url);results.append(ingest(store,cap.capture_id,parse_feed(cap.response.content)))
        store.finish_run(run,'success',results);return results
    except Exception as exc:
        store.finish_run(run,'failed',{'completed':results,'error':str(exc)});raise
    finally:client.close();store.close()


def snapshot(store,origin,lookback_days=7):
    initialize(store);origin=utc_timestamp(origin)
    start=(datetime.fromisoformat(origin)-timedelta(days=lookback_days)).isoformat()
    # Counts are qualified by feed collection coverage; no historical zeros are manufactured.
    runs=store.db.execute("SELECT started_at,finished_at FROM collection_runs WHERE source_id='news_eia' AND status='success' AND finished_at<=? ORDER BY finished_at",(origin,)).fetchall()
    days=[datetime.fromisoformat(r['finished_at']) for r in runs]
    coverage=bool(days and days[0]<=datetime.fromisoformat(start) and (datetime.fromisoformat(origin)-days[-1]).total_seconds()<=2*86400)
    inside=[d for d in days if d>=datetime.fromisoformat(start)-timedelta(days=2)]
    if not inside or inside[0]>datetime.fromisoformat(start):coverage=False
    if any((b-a).total_seconds()>2*86400 for a,b in zip(inside,inside[1:])):coverage=False
    rows=store.db.execute('SELECT * FROM news_items WHERE first_known_at<=? AND publication_timestamp>? AND publication_timestamp<=? ORDER BY first_known_at',(origin,start,origin)).fetchall()
    latest={r['url']:dict(r) for r in rows if not json.loads(r['issues_json'])}
    counts={key:sum(json.loads(r['channels_json'])[key] for r in latest.values()) for key in CHANNELS}
    return dict(origin=origin,coverage_status='collected_feed_window' if coverage else 'unknown_or_incomplete',
                features=counts if coverage else {key:None for key in CHANNELS},available_items=len(latest),
                item_ids=[r['id'] for r in latest.values()],claim='Rule tags identify topics/transmission channels, not realized event facts or numeric price effects')


def report(root):
    root=Path(root);s=Store(root);initialize(s)
    rows=[dict(r) for r in s.db.execute('SELECT * FROM news_items ORDER BY first_known_at,id')]
    payload=dict(items=len(rows),source_timestamped=sum(r['publication_timestamp'] is not None and not json.loads(r['issues_json']) for r in rows),
                 oldest_publication=min((r['publication_timestamp'] for r in rows if r['publication_timestamp']),default=None),
                 latest_publication=max((r['publication_timestamp'] for r in rows if r['publication_timestamp']),default=None),
                 first_known_at=min((r['first_known_at'] for r in rows),default=None),
                 historical_ablation_status='not_evaluable_no_news_versions_known_at_development_origins',
                 historical_ablation_n=0,incremental_skill=None,
                 current=snapshot(s,datetime.now(timezone.utc).isoformat()),rows=rows)
    (root/'reports/forecasting/news_research.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n');s.close()
    return {k:v for k,v in payload.items() if k not in {'rows','current'}}
