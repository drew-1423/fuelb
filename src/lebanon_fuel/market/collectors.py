"""Public file adapters. Discover links on served pages; fail on schema drift."""
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote, urlencode
from zoneinfo import ZoneInfo
import csv
from hashlib import sha256
import json
import math
import os
import re
import tempfile

import httpx
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from openpyxl import load_workbook

from lebanon_fuel.ingestion.http import PublicClient, AccessStopped, Fetch
from .catalog import SERIES, EC, FUTURES, CBOE_OVX_URL, FRED_OVX_URL
from .store import close_availability


def yahoo_rows(raw, series_id, *, at=None):
    """Unadjusted daily vendor close, never an authenticated exchange settlement.

    Yahoo's rolling symbol does not establish a historical contract roll calendar.
    Retain that limitation and the complete bar; never ingest a still-open UTC day.
    """
    at = at or datetime.now(timezone.utc)
    if at.utcoffset() is None:
        raise ValueError('Aware retrieval cutoff required')
    payload = json.loads(raw)
    chart = payload['chart']
    if chart.get('error') or len(chart.get('result') or []) != 1:
        raise ValueError('Yahoo returned no unique futures history')
    result = chart['result'][0]; meta = result['meta']; spec = SERIES[series_id]
    if meta.get('symbol') != FUTURES[series_id]['symbol'] or meta.get('currency') != 'USD' or meta.get('instrumentType') != 'FUTURE':
        raise ValueError('Unexpected futures symbol, currency or instrument type')
    zone = ZoneInfo(meta['exchangeTimezoneName'])
    stamps = result.get('timestamp') or []
    quotes = result['indicators']['quote']
    if len(quotes) != 1 or len(quotes[0].get('close', [])) != len(stamps):
        raise ValueError('Unexpected Yahoo daily quote schema')
    for i, stamp in enumerate(stamps):
        day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone).date()
        if datetime.combine(day, time(23,59,59), timezone.utc) >= at:
            continue
        bar = {k:v[i] for k,v in quotes[0].items() if len(v)==len(stamps)}
        yield dict(date=day.isoformat(),value=bar['close'],unit=spec.unit,row_key=str(stamp),
                   raw=dict(bar=bar, vendor_bar_timestamp=stamp, meta=meta,
                            price_semantics='unadjusted_vendor_daily_close_not_verified_settlement',
                            roll_policy='vendor_continuous_symbol_roll_calendar_unverified',
                            publication_timestamp=None))


def collect_futures(store, start='2000-01-01', end=None):
    """Public unauthenticated chart API; one denial stops this provider.

    EIA fallback remains in its original series, never relabeled as a futures quote.
    Stooq currently presents a browser-verification barrier; no bypass is attempted.
    """
    at = datetime.now(timezone.utc)
    end_day = date.fromisoformat(end) if end else at.date()
    first = datetime.combine(date.fromisoformat(start), time(), timezone.utc)
    last = min(datetime.combine(end_day+timedelta(days=1), time(), timezone.utc), at)
    if first >= last:
        raise ValueError('Futures start must precede the collection endpoint')
    run = store.start_run('market_yahoo')
    client = PublicClient(store, 'market_yahoo', run)
    results = []; stopped = None
    try:
        for sid, instrument in FUTURES.items():
            outcome = dict(series=sid, symbol=instrument['symbol'], new_observations=0)
            try:
                if stopped:
                    raise AccessStopped(stopped)
                url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(instrument['symbol'],safe='') + '?' + urlencode(dict(
                    period1=int(first.timestamp()),period2=int(last.timestamp()),interval='1d',events='history'))
                fetched = client.fetch(url)
                rows = list(yahoo_rows(fetched.response.content,sid,at=at))
                if not rows:
                    raise ValueError('No finalized daily bars returned')
                outcome.update(store.ingest_market(fetched.capture_id,sid,rows), status='success')
            except Exception as exc:
                if isinstance(exc, AccessStopped):
                    stopped = str(exc)
                fallback = instrument['fallback']
                history = store.history(fallback,at.isoformat(),'strict') if fallback else []
                outcome.update(status='unavailable',reason=f'{type(exc).__name__}: {exc}',
                               fallback_series=fallback,stored_fallback_rows=len(history),
                               fallback_latest_date=history[-1]['observation_date'] if history else None,
                               fallback_note='Use the named spot proxy only when fresh. No futures rows fabricated.')
            results.append(outcome)
        store.finish_run(run, 'success' if all(r['status']=='success' for r in results) else 'partial', {'results':results})
        return results
    except Exception as exc:
        store.finish_run(run,'failed',{'results':results,'error':str(exc)})
        raise
    finally:
        client.close()


def eia_rows(raw, series_id):
    import xlrd
    workbook = xlrd.open_workbook(file_contents=raw)
    spec = SERIES[series_id]
    sheet = workbook.sheet_by_name('Data 1')
    expected = {
        'brent_spot': ('Europe Brent Spot Price FOB', 'Dollars per Barrel'),
        'nyh_gasoline': ('New York Harbor Conventional Gasoline Regular Spot Price FOB', 'Dollars per Gallon'),
        'us_gasoline_stocks': ('Ending Stocks of Total Gasoline', 'Thousand Barrels'),
        'us_crude_stocks': ('Ending Stocks excluding SPR of Crude Oil', 'Thousand Barrels'),
        'us_refinery_utilization': ('Percent Utilization of Refinery Operable Capacity', 'Percent'),
    }[series_id]
    heading = str(sheet.cell_value(2,1))
    if not all(part.lower() in heading.lower() for part in expected) or sheet.cell_value(2,0) != 'Date':
        raise ValueError(f'EIA header drift for {series_id}: {heading}')
    if series_id == 'us_crude_stocks' and 'excluding spr' not in heading.lower():
        raise ValueError('Crude inventory must exclude SPR')
    for i in range(3,sheet.nrows):
        cell = sheet.cell(i,0)
        if cell.ctype == xlrd.XL_CELL_EMPTY:
            continue
        if cell.ctype != xlrd.XL_CELL_DATE:
            raise ValueError(f'Unexpected EIA date type at row {i+1}')
        day = xlrd.xldate_as_datetime(cell.value,workbook.datemode).date().isoformat()
        value = sheet.cell_value(i,1)
        yield {'date':day,'value':value if value != '' else None,'unit':spec.unit,
               'row_key':f'Data 1:{i+1}', 'raw':{'sheet':'Data 1','row':i+1,'excel_date':cell.value,'value':value,'heading':heading}}


def ec_rows(raw, series_id):
    prefix = {'italy_gasoline_ex_tax':'IT', 'greece_gasoline_ex_tax':'GR'}[series_id]
    workbook = load_workbook(BytesIO(raw),read_only=True,data_only=True)
    try:
        sheet = workbook['Prices wo taxes']
        rows = sheet.iter_rows(values_only=True)
        header, product, units = next(rows),next(rows),next(rows)
        column = header.index(prefix+'_price_wo_tax_euro95')
        if units[column] != '1000 l' or 'Euro-super 95' not in product[column]:
            raise ValueError('Unexpected EC gasoline unit/product')
        footer=False
        for i,row in enumerate(rows,4):
            if row[0] is None:
                continue
            if row[0]=='Notes:' and row[column] is None:
                footer=True
                continue
            if footer:
                raise ValueError('Unexpected dated/value row after EC notes footer')
            if not isinstance(row[0],datetime):
                raise ValueError(f'Unexpected EC date row {i}')
            yield {'date':row[0].date().isoformat(),'value':row[column],'unit':'EUR/1000L',
                   'row_key':f'{sheet.title}:{i}:{column+1}',
                   'raw':{'sheet':sheet.title,'row':i,'column':column+1,'date':row[0].isoformat(),
                          'header':header[column],'product':product[column],'volume_unit':units[column],
                          'country':prefix,'value':row[column]}}
    finally:
        workbook.close()


def fed_rows(raw):
    with ZipFile(BytesIO(raw)) as archive:
        info=archive.getinfo('H10_data.xml')
        if info.file_size>100_000_000:
            raise ValueError('Unexpected H10 XML size')
        root=ET.fromstring(archive.read(info))
    series=[e for e in root.iter() if e.attrib.get('SERIES_NAME')=='RXI$US_N.B.EU']
    if len(series)!=1 or series[0].attrib.get('FREQ')!='9' or series[0].attrib.get('CURRENCY')!='EUR':
        raise ValueError('Federal Reserve daily euro series schema changed')
    element=series[0]
    if not any('USD per EUR' in (e.text or '') for e in element.iter()):
        raise ValueError('H10 exchange-rate direction must be USD per EUR')
    prepared=next((e.text for e in root.iter() if e.tag.endswith('Prepared')),None)
    for i,obs in enumerate((e for e in element if e.tag.endswith('Obs')),1):
        row=dict(obs.attrib)
        date.fromisoformat(row['TIME_PERIOD'])
        status=row.get('OBS_STATUS')
        if status not in {'A','ND'}:
            raise ValueError('Unknown H10 observation status')
        yield {'date':row['TIME_PERIOD'],'value':row.get('OBS_VALUE') if status=='A' else None,
               'unit':'USD/EUR','row_key':f'RXI$US_N.B.EU:{i}',
               'raw':{'series':dict(element.attrib),'observation':row,'package_prepared_timestamp_timezone_unspecified':prepared}}


def parse_capture(store,capture_id,series_id):
    cap = store.db.execute('SELECT * FROM captures WHERE id=?',(capture_id,)).fetchone()
    if not cap or cap['http_status'] != 200:
        raise ValueError('A successful original response is required')
    raw = (store.root/cap['raw_path']).read_bytes()
    from hashlib import sha256
    if sha256(raw).hexdigest() != cap['sha256']:
        raise ValueError('Raw market artifact hash mismatch')
    if SERIES[series_id].source == 'market_eia':
        rows = eia_rows(raw,series_id)
    elif SERIES[series_id].source == 'market_ec':
        rows = ec_rows(raw,series_id)
    elif series_id == 'eurusd':
        rows = fed_rows(raw)
    elif series_id == 'cboe_ovx':
        rows = ovx_rows(raw, datetime.fromisoformat(cap['retrieved_at']))
    elif series_id in FUTURES:
        rows = yahoo_rows(raw,series_id,at=datetime.fromisoformat(cap['retrieved_at']))
    else:
        raise ValueError('No automatic adapter for this series')
    return store.ingest_market(capture_id,series_id,rows)


def collect(store,source):
    if source == 'market_cboe':
        return [collect_cboe_ovx(store)]
    if source == 'market_fred_ovx':
        return [collect_fred_ovx(store)]
    if source == 'market_yahoo':
        return collect_futures(store)
    if source not in {'market_eia','market_ec','market_fed'}:
        raise ValueError('Unknown public market collector')
    run = store.start_run(source)
    client = PublicClient(store,source,run)
    results = []
    try:
        if source == 'market_eia':
            for sid,spec in SERIES.items():
                if spec.source != source:
                    continue
                page = client.fetch(spec.url)
                soup = BeautifulSoup(page.response.text,'html.parser')
                links = [urljoin(spec.url,a['href']) for a in soup.find_all('a',href=True)
                         if a.get_text(' ',strip=True)=='Download Data (XLS File)']
                if len(links)!=1 or urlparse(links[0]).netloc!='www.eia.gov':
                    raise ValueError('Expected one EIA-hosted history download')
                downloaded = client.fetch(links[0])
                results.append(parse_capture(store,downloaded.capture_id,sid))
        elif source == 'market_ec':
            page = client.fetch(EC)
            soup = BeautifulSoup(page.response.text,'html.parser')
            links = [urljoin(EC,a['href']) for a in soup.find_all('a',href=True)
                     if 'Prices_History' in a['href']]
            if len(links)!=1 or urlparse(links[0]).netloc!='energy.ec.europa.eu':
                raise ValueError('Expected one Commission-hosted history workbook')
            downloaded = client.fetch(links[0])
            for sid in ('italy_gasoline_ex_tax','greece_gasoline_ex_tax'):
                results.append(parse_capture(store,downloaded.capture_id,sid))
        else:
            page=client.fetch(SERIES['eurusd'].url)
            soup=BeautifulSoup(page.response.text,'html.parser')
            links=[urljoin(SERIES['eurusd'].url,a['href']) for a in soup.find_all('a',href=True)
                   if a.get_text(' ',strip=True)=='XML']
            if len(links)!=1 or urlparse(links[0]).netloc!='www.federalreserve.gov':
                raise ValueError('Expected one Federal Reserve XML history download')
            downloaded = client.fetch(links[0])
            results.append(parse_capture(store,downloaded.capture_id,'eurusd'))
        store.finish_run(run,'success',{'results':results})
        return results
    except Exception as exc:
        store.finish_run(run,'failed',{'completed':results,'error':str(exc)})
        raise
    finally:
        client.close()


def manual_import(store,path,series_id,source_url,license_note):
    """Import authorized files; the note is recorded, not a licence inferred by code."""
    if not source_url.startswith('https://') or not license_note.strip():
        raise ValueError('Provide source URL and authorization/licence note')
    spec = SERIES[series_id]
    raw = Path(path).read_bytes()
    rows = list(csv.DictReader(StringIO(raw.decode('utf-8-sig'))))
    if not rows or not {'date','value','unit'} <= rows[0].keys():
        raise ValueError('CSV needs date,value,unit')
    evidence_ids=[]
    if series_id=='lbp_payment_fx':
        for row in rows:
            if not all(row.get(k) for k in ('reviewer','evidence_locator','evidence_sha256')):
                raise ValueError('Official FX requires original document review and hash')
            found=store.db.execute("SELECT id,raw_path FROM captures WHERE source_id='official_document' AND url=? AND sha256=?",
                                   (source_url,row['evidence_sha256'])).fetchone()
            if found is None:
                raise ValueError('Capture the original government document first')
            from hashlib import sha256
            if sha256((store.root/found['raw_path']).read_bytes()).hexdigest()!=row['evidence_sha256']:
                raise ValueError('Government evidence hash mismatch')
            evidence_ids.append(found['id'])
    run = store.start_run(spec.source)
    try:
        cap = store.capture(spec.source,source_url,raw,'text/csv',run,200,{'manual_import':str(path),'authorization':license_note,'original_evidence_capture_ids':evidence_ids})
        parsed=[]
        for i,row in enumerate(rows,2):
            record = {k:v for k,v in row.items() if v}
            record.update(row_key=str(i),raw=row)
            parsed.append(record)
        result=store.ingest_market(cap,series_id,parsed)
        store.finish_run(run,'success',result)
        return result
    except Exception as exc:
        store.finish_run(run,'failed',{'error':str(exc)})
        raise


if __name__ == '__main__':
    # Kept here because this stage's scope excludes market/cli.py and scheduler changes.
    import argparse
    from contextlib import closing
    from .store import MarketStore
    from lebanon_fuel.automation.state import refresh_lock
    parser = argparse.ArgumentParser(description='Public daily futures collection with explicit spot fallback')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--start',default='2000-01-01')
    parser.add_argument('--end')
    args = parser.parse_args()
    with refresh_lock(args.root), closing(MarketStore(args.root)) as market:
        result = collect_futures(market,args.start,args.end)
    print(json.dumps(result,indent=2))


CBOE_OPTIONS_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
ENERGY_OPTIONS = ("USO", "BNO", "UGA")


def ovx_rows(raw, at):
    reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")), strict=True)
    if reader.fieldnames is None:
        raise ValueError("Empty OVX CSV")
    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
    if not {"date", "close"}.issubset(reader.fieldnames):
        raise ValueError("OVX CSV requires Date and Close columns")
    rows = []
    dates = set()
    spec = SERIES["cboe_ovx"]
    for row in reader:
        if None in row or row["close"] is None or row["date"] is None:
            raise ValueError("Malformed OVX CSV row")
        raw_date = row["date"].strip()
        day = (datetime.strptime(raw_date, "%m/%d/%Y").date()
               if "/" in raw_date else date.fromisoformat(raw_date)).isoformat()
        close = close_availability(day, spec)
        if not row["close"].strip() or datetime.fromisoformat(close) > at:
            continue
        if day in dates or positive_number(row["close"]) is None:
            raise ValueError(f"Duplicate date or invalid OVX close: {day}")
        dates.add(day)
        rows.append(dict(date=day, value=row["close"], row_key=day, unit=spec.unit,
                         raw=dict(csv=row, assumed_close_utc=close)))
    if not rows:
        raise ValueError("No finalized OVX closes returned")
    return rows


def fred_ovx_rows(raw, at):
    """Parse FRED's OVXCLS history; daily-close availability is a research convention."""
    if at.utcoffset() is None:
        raise ValueError('Aware OVX retrieval cutoff required')
    reader = csv.DictReader(StringIO(raw.decode('utf-8-sig')), strict=True)
    if reader.fieldnames is None:
        raise ValueError('Empty FRED OVX CSV')
    fields = {name.strip().lower(): name for name in reader.fieldnames}
    date_field = fields.get('observation_date') or fields.get('date')
    value_field = fields.get('ovxcls')
    if date_field is None or value_field is None or len(reader.fieldnames) != 2:
        raise ValueError('FRED OVX CSV requires observation_date/DATE and OVXCLS columns')
    rows = []
    seen = set()
    spec = SERIES['cboe_ovx']
    for row in reader:
        if None in row or row.get(date_field) is None or row.get(value_field) is None:
            raise ValueError('Malformed FRED OVX CSV row')
        raw_date = row[date_field].strip()
        raw_value = row[value_field].strip()
        if not raw_value or raw_value == '.':
            continue
        day = date.fromisoformat(raw_date).isoformat()
        if day in seen or positive_number(raw_value) is None:
            raise ValueError(f'Duplicate date or invalid FRED OVX value: {day}')
        seen.add(day)
        close = close_availability(day, spec)
        if datetime.fromisoformat(close) > at.astimezone(timezone.utc):
            continue
        rows.append(dict(date=day, value=raw_value, row_key=day, unit=spec.unit,
                         raw={"csv": row, "assumed_close_utc": close,
                              "publisher": "Federal Reserve Bank of St. Louis FRED",
                              "series_id": "OVXCLS"}))
    if not rows:
        raise ValueError('No finalized FRED OVX observations returned')
    return rows


def _parse_ovx_csv(raw, at):
    """Detect the two supported historical CSV layouts without changing series identity."""
    reader = csv.reader(StringIO(raw.decode('utf-8-sig')), strict=True)
    try:
        headers = [cell.strip().lower() for cell in next(reader)]
    except StopIteration as exc:
        raise ValueError('Empty OVX CSV') from exc
    if len(headers) == 2 and (headers[0], headers[1]) in {
        ('observation_date', 'ovxcls'), ('date', 'ovxcls')
    }:
        return 'fred', fred_ovx_rows(raw, at)
    if {'date', 'close'}.issubset(headers):
        return 'cboe', ovx_rows(raw, at)
    raise ValueError('OVX CSV headers must be Cboe Date/Open/High/Low/Close or FRED observation_date/OVXCLS')


def finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def positive_number(value):
    number = finite_number(value)
    return number if number is not None and number > 0 else None


def parse_occ_option_symbol(symbol):
    match = re.fullmatch(r"[A-Z0-9]{1,6}\s*([0-9]{2})([0-9]{2})([0-9]{2})([CP])([0-9]{8})",
                         symbol.strip().upper(), flags=re.ASCII)
    if match is None:
        raise ValueError(f"Invalid OCC option symbol: {symbol!r}")
    year, month, day, kind, strike = match.groups()
    return date(2000 + int(year), int(month), int(day)), ("call" if kind == "C" else "put"), int(strike) / 1000


def _cboe_request(store, client, url, consume, *, input_path=None, source_id="market_cboe", **identity):
    source = source_id
    run = store.start_run(source)
    owned = client is None and input_path is None
    capture_id = None
    try:
        if owned:
            client = PublicClient(store, source, run)
        if input_path is None:
            fetched = client.fetch(url)
        else:
            raw = Path(input_path).read_bytes()
            capture_id = store.capture(source, url, raw, "application/json", run=run,
                                       metadata={"acquisition": "authorized_local_import"})
            fetched = Fetch(httpx.Response(200, content=raw, request=httpx.Request("GET", url)), capture_id)
        capture_id = fetched.capture_id
        fetched.response.raise_for_status()
        result = dict(status="ok", source_id=source, source_url=url, capture_id=capture_id, **identity)
        result = consume(fetched, result)
    except (AccessStopped, httpx.HTTPError, OSError, ValueError, TypeError, csv.Error) as exc:
        result = dict(status="error", source_id=source, source_url=url, capture_id=capture_id,
                      error=f"{type(exc).__name__}: {exc}", **identity)
        if "series" in identity:
            result["rows_ingested"] = 0
    finally:
        if owned and client is not None:
            client.close()
    store.finish_run(run, "success" if result["status"] == "ok" else "failed", result)
    return result


def collect_cboe_ovx(store, client=None, *, url=CBOE_OVX_URL):
    def consume(fetched, result):
        capture = store.db.execute("SELECT retrieved_at FROM captures WHERE id=?",
                                   (fetched.capture_id,)).fetchone()
        rows = ovx_rows(fetched.response.content, datetime.fromisoformat(capture["retrieved_at"]))
        result.update(store.ingest_market(fetched.capture_id, "cboe_ovx", rows),
                      rows_ingested=len(rows), latest_observation_date=max(row["date"] for row in rows))
        return result

    return _cboe_request(store, client, url, consume, series="cboe_ovx")


def collect_fred_ovx(store, client=None, *, url=FRED_OVX_URL):
    """Collect FRED's public OVXCLS history into the existing cboe_ovx series."""
    def consume(fetched, result):
        capture = store.db.execute("SELECT retrieved_at FROM captures WHERE id=?",
                                   (fetched.capture_id,)).fetchone()
        rows = fred_ovx_rows(fetched.response.content, datetime.fromisoformat(capture["retrieved_at"]))
        result.update(store.ingest_market(fetched.capture_id, "cboe_ovx", rows),
                      rows_ingested=len(rows), latest_observation_date=max(row["date"] for row in rows),
                      publisher="FRED", fred_series_id="OVXCLS")
        return result

    return _cboe_request(store, client, url, consume, source_id="market_fred_ovx", series="cboe_ovx", publisher="FRED")


def collect_ovx_csv_input(store, input_path):
    """Validate then capture and ingest a user-provided Cboe or FRED OVX CSV."""
    source = "market_cboe"
    result = {"status": "error", "source_id": source, "capture_id": None,
              "input_path": str(input_path)}
    try:
        path = Path(input_path).expanduser().resolve()
        raw = path.read_bytes()
        captured_at = datetime.now(timezone.utc)
        detected_format, rows = _parse_ovx_csv(raw, captured_at)
        source = "market_fred_ovx" if detected_format == "fred" else "market_cboe"
        url = FRED_OVX_URL if detected_format == "fred" else CBOE_OVX_URL
        run = store.start_run(source)
        capture_id = store.capture(source, url, raw, "text/csv", run=run, http_status=200,
            metadata={"acquisition": "authorized_local_import", "status": "ok", "local_path": str(path),
                      "input_sha256": sha256(raw).hexdigest(),
                      "detected_format": detected_format})
        ingestion = store.ingest_market(capture_id, "cboe_ovx", rows)
        result.update(status="ok", source_id=source, source_url=url, format=detected_format,
                      rows_ingested=len(rows), latest_observation_date=max(row["date"] for row in rows))
        result.update(ingestion)
        store.finish_run(run, "success", result)
    except (OSError, UnicodeDecodeError, ValueError, TypeError, csv.Error) as exc:
        run = store.start_run(source)
        result["error"] = f"{type(exc).__name__}: {exc}"
        store.finish_run(run, "failed", result)
    return result


def _atomic_options_export(path, summary):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.stem}.", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(summary, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def collect_options_chain(store, symbol="USO", *, output_path=None, as_of_date=None, input_path=None):
    symbol = symbol.strip().upper()
    if symbol not in ENERGY_OPTIONS:
        raise ValueError("Supported Cboe options symbols are USO, BNO and UGA")
    output_path = Path(output_path) if output_path is not None else store.root / "data/exports/options_chain_latest.json"

    def consume(fetched, result):
        payload = fetched.response.json()
        chain = payload.get("data") if isinstance(payload, dict) else None
        options = chain.get("options") if isinstance(chain, dict) else None
        if not isinstance(options, list) or not options:
            raise ValueError("Cboe returned no options chain")
        capture = store.db.execute("SELECT retrieved_at FROM captures WHERE id=?",
                                   (fetched.capture_id,)).fetchone()
        captured_at = capture["retrieved_at"]
        ref = as_of_date or datetime.fromisoformat(captured_at).astimezone(ZoneInfo("America/New_York")).date()
        spot = positive_number(chain.get("current_price"))
        contracts = {}
        recognized = 0
        for quote in options:
            if not isinstance(quote, dict) or not isinstance(quote.get("option"), str):
                continue
            contract = quote["option"].strip().upper()
            try:
                expiry, kind, strike = parse_occ_option_symbol(contract)
            except ValueError:
                continue
            if contract[:-15].strip() != symbol:
                continue
            recognized += 1
            contract = symbol + contract[-15:]
            dte = (expiry - ref).days
            iv = positive_number(quote.get("iv"))
            bid, ask = (finite_number(quote.get(key)) for key in ("bid", "ask"))
            oi = positive_number(quote.get("open_interest")) or 0
            if not 7 <= dte <= 60 or iv is None or not (oi > 0 or (bid or 0) > 0):
                continue
            mid = (bid + (ask - bid) / 2) if bid is not None and ask is not None and 0 <= bid <= ask else None
            contracts[contract] = dict(contract_symbol=contract, expiration_date=expiry.isoformat(),
                option_type=kind, strike=strike, dte=dte, iv=iv, bid=bid, ask=ask, mid=mid,
                open_interest=int(oi), volume=int(positive_number(quote.get("volume")) or 0),
                **{key: finite_number(quote.get(key)) for key in ("delta", "gamma", "theta", "vega")})
        rows = sorted(contracts.values(), key=lambda row: (row["dte"], row["strike"], row["option_type"]))
        if not recognized:
            raise ValueError("No recognizable contract fields")
        calls = [row for row in rows if row["option_type"] == "call"]
        puts = [row for row in rows if row["option_type"] == "put"]
        call_oi = sum(row["open_interest"] for row in calls)
        put_oi = sum(row["open_interest"] for row in puts)
        nearest = min(rows, key=lambda row: (abs(row["dte"] - 30), abs(row["strike"] - spot))) if rows and spot else None
        result.update(captured_at=captured_at, vendor_timestamp=payload.get("timestamp"),
            as_of_date=ref.isoformat(), spot_price=spot, dte_window=[7, 60],
            iv_unit="fraction_annualized", contracts_total_raw=len(options), contracts_filtered=len(rows),
            calls_count=len(calls), puts_count=len(puts), total_call_open_interest=call_oi,
            total_put_open_interest=put_oi, put_call_oi_ratio=round(put_oi / call_oi, 4) if call_oi else None,
            mean_iv=round(sum(row["iv"] / len(rows) for row in rows), 6) if rows else None,
            atm_30d_iv=round(nearest["iv"], 6) if nearest else None,
            atm_30d_method="nearest listed maturity to 30 days, then nearest strike; no interpolation",
            contracts=rows)
        _atomic_options_export(output_path, result)
        return result

    url = CBOE_OPTIONS_URL.format(symbol=symbol)
    if input_path is None:
        return dict(status="error", symbol=symbol, source_url=url,
                    error="Provide an authorized local JSON export via input_path.")
    # The Delayed Quotes dashboard prohibits automated downloads.
    return _cboe_request(store, None, url, consume, input_path=input_path, symbol=symbol)
