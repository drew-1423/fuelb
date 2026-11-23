"""News fixtures are synthetic; collectors retain the actual EIA responses separately."""
import json
import sqlite3
import pytest
from lebanon_fuel.news.pipeline import timestamp,parse_feed,classify,ingest,snapshot,initialize
from lebanon_fuel.storage.database import Store


def test_publication_needs_clock_and_zone():
    assert timestamp('Tue, 10 Nov 2026 10:00:00 -0500')=='2026-11-10T15:00:00+00:00'
    assert timestamp('2026-11-10') is None
    assert timestamp('2026-11-10T10:00:00') is None


def test_rule_tags_are_transmission_channels():
    c=classify('OPEC refinery disruption','Lebanon tax and Red Sea tanker insurance')
    assert c['opec_supply_policy'] and c['refining_capacity'] and c['shipping_freight_insurance'] and c['lebanese_fiscal_regulation']
    assert all(isinstance(x,bool) for x in c.values())


def test_feed_host_allowlist_and_dtd():
    raw=b'<rss><channel><item><title>Example</title><link>https://evil.example/fake</link></item><item><title>EIA item</title><link>https://www.eia.gov/test</link></item></channel></rss>'
    assert len(list(parse_feed(raw)))==1
    with pytest.raises(ValueError):list(parse_feed(b'<!DOCTYPE rss><rss/>'))


def test_append_only_idempotent_and_no_historical_backfill_of_news_features(tmp_path):
    s=Store(tmp_path);initialize(s)
    row=dict(url='https://www.eia.gov/test',title='OPEC supply',summary='Test fixture',timestamp_raw='Tue, 10 Nov 2026 10:00:00 -0500')
    cap=s.capture('news_eia','https://www.eia.gov/feed',b'fixture','text/xml',http_status=200,retrieved_at='2026-11-11T00:00:00+00:00')
    assert ingest(s,cap,[row])['new_items']==1 and ingest(s,cap,[row])['new_items']==0
    past=snapshot(s,'2026-11-10T18:00:00+00:00')
    assert past['available_items']==0 and all(v is None for v in past['features'].values())
    row['summary']='Revised fixture';ingest(s,cap,[row])
    assert s.db.execute('SELECT COUNT(*) FROM news_items').fetchone()[0]==2
    with pytest.raises(sqlite3.IntegrityError):s.db.execute('UPDATE news_items SET title="changed"')
    with pytest.raises(sqlite3.IntegrityError):s.db.execute('DELETE FROM news_sightings')
    s.close()
