"""Adapters for inspected, public source structures; no endpoint guessing."""
from datetime import date, datetime
from io import BytesIO, StringIO
from urllib.parse import urljoin, urlparse
import csv
import json
import re
from bs4 import BeautifulSoup
from openpyxl import load_workbook

from lebanon_fuel.domain import Observation, UNIT

IPT_URL="https://www.iptgroup.com.lb/ipt/en/our-stations/fuel-prices"
MINISTRY_URL="https://energyandwater.gov.lb/ar/prices"
TAQTEK_URL="https://taqteklb.com/en/fuel/"


def soup(raw):
    return BeautifulSoup(raw.decode('utf-8',errors='replace') if isinstance(raw,bytes) else raw,'html.parser')


def parse_ipt(raw):
    if not raw.startswith(b'PK'):
        raise ValueError("IPT export is not an XLSX ZIP container")
    workbook=load_workbook(BytesIO(raw),read_only=True,data_only=True)
    try:
        sheet=workbook['Fuel Prices']
        values=iter(sheet.values)
        headers=next(values)
        if tuple(headers)!=("Date","Octane98","Octane95","Diesel","GasOil","Gas"):
            raise ValueError("IPT schema changed: expected exact inspected headers")
        for number,row in enumerate(values,2):
            if all(x is None for x in row):
                continue
            original=dict(zip(headers,row))
            d=row[0]
            day=d.date().isoformat() if isinstance(d,datetime) else d.isoformat() if isinstance(d,date) else str(d)
            yield Observation('ipt',day,row[2],IPT_URL,original,str(number))
    finally:
        workbook.close()


def form_post(html, suffix):
    doc=soup(html)
    form=doc.select_one('form#form1')
    button=next((a for a in doc.select('a[id]') if a['id'].endswith(suffix)),None)
    if form is None or button is None:
        raise ValueError("IPT form/export control missing; use manual XLSX import")
    match=re.search(r'WebForm_PostBackOptions\("([^\"]+)"',button.get('href',''))
    if not match:
        raise ValueError("Unrecognized IPT postback control")
    fields={}
    for el in form.select('input[name]'):
        typ=el.get('type','text').lower()
        if typ in {'submit','button','image','file','radio','checkbox'}:
            continue
        fields[el['name']]=el.get('value','')
    for el in form.select('select[name]'):
        option=el.select_one('option[selected]') or el.select_one('option')
        if option:
            fields[el['name']]=option.get('value',option.get_text())
    fields['__EVENTTARGET']=match[1]
    fields['__EVENTARGUMENT']=''
    return form.get('action'),fields


def collect_ipt(client):
    page=client.fetch(IPT_URL)
    action,fields=form_post(page.response.content,'lbtnFilterAll')
    url=urljoin(str(page.response.url),action)
    page=client.fetch(url,'POST',data=fields)
    action,fields=form_post(page.response.content,'lbtnExport')
    page=client.fetch(urljoin(str(page.response.url),action),'POST',data=fields)
    if not page.response.content.startswith(b'PK'):
        export=soup(page.response.content).select_one('a[id$="_aExport"][href]')
        # Full form POST returns the same public download URL through a small
        # DOM assignment script rather than an already-populated anchor.
        generated=re.search(r"_aExport'\)\.attr\('href',\s*'([^']+)'\)",page.response.text)
        href=export['href'] if export else generated[1] if generated else None
        if not href:
            raise ValueError("Public export did not expose a download; use browser/manual import")
        download=urljoin(str(page.response.url),href)
        if urlparse(download).hostname!=urlparse(IPT_URL).hostname:
            raise ValueError("Unexpected export host")
        page=client.fetch(download)
    return client.store.ingest(page.capture_id,parse_ipt(page.response.content))


MONTHS={
 'كانون ثاني':1,'كانون الثاني':1,'شباط':2,'آذار':3,'اذار':3,'نيسان':4,'أيار':5,'ايار':5,'حزيران':6,
 'تموز':7,'آب':8,'اب':8,'أيلول':9,'ايلول':9,'تشرين أول':10,'تشرين الاول':10,'تشرين الأول':10,
 'تشرين ثاني':11,'تشرين الثاني':11,'كانون أول':12,'كانون الاول':12,'كانون الأول':12,
}


def arabic_date(text):
    cleaned=''.join(str(int(c)) if c.isdecimal() else c for c in text)
    cleaned=' '.join(cleaned.split())
    match=re.search(r'(\d{1,2})\s+([^\d]+?)\s+(\d{4})',cleaned)
    if not match or match[2].strip() not in MONTHS:
        raise ValueError(f"Unrecognized Arabic date {text!r}")
    return date(int(match[3]),MONTHS[match[2].strip()],int(match[1])).isoformat()


def parse_ministry(html, source_url=MINISTRY_URL):
    doc=soup(html)
    table=doc.select_one('table')
    if not table or not all(x in table.get_text() for x in ('95','98','20')) and not (table and 'أوكتان' in table.get_text()):
        raise ValueError("Ministry table schema missing")
    headers=[th.get_text(' ',strip=True) for th in table.select('thead th')]
    if not headers or not any('95' in h for h in headers):
        raise ValueError("Ministry 95-octane header absent")
    price_col=next(i for i,h in enumerate(headers) if '95' in h)
    for i,tr in enumerate(table.select('tbody tr'),1):
        cells=tr.find_all('td',recursive=False)
        if len(cells)!=len(headers):
            raise ValueError("Ministry table column alignment changed")
        text=[c.get_text(' ',strip=True) for c in cells]
        links=[urljoin(source_url,a['href']) for a in tr.select('a[href]')]
        issues=[]
        try: day=arabic_date(text[0])
        except ValueError: day=None;issues.append('source_date_invalid')
        yield Observation('ministry',day,text[price_col],source_url,{'cells':text,'headers':headers,'links':links,'html':str(tr)},str(i),date_role='decision_date',decision_number=text[1] or None,issues=issues)


def collect_ministry(client, start, end):
    docpage=client.fetch(MINISTRY_URL)
    doc=soup(docpage.response.content)
    root=doc.select_one('#hdnRootFldr')
    typ=doc.select_one('#hdnPriceTypeId')
    script=next((s.get('src') for s in doc.select('script[src]') if s['src'].endswith('/pricesCtrl.js')),None)
    if not (root and typ and script and typ.get('value')=='1'):
        raise ValueError("Ministry public search form changed")
    js=client.fetch(urljoin(MINISTRY_URL,script)).response.text
    endpoint=re.search(r'pricesAjaxFile\s*=.*?\+\s*"([^\"]+)"',js)
    if not endpoint or 'RenderPrices' not in js:
        raise ValueError("Public price-search request not identified")
    url=urljoin(MINISTRY_URL,root['value']+endpoint[1])
    if urlparse(url).hostname!=urlparse(MINISTRY_URL).hostname:
        raise ValueError("Unexpected ministry search host")
    pending=[0];seen=set();parsed=added=0
    while pending:
        page=pending.pop(0)
        if page in seen: continue
        if len(seen)>=200:
            raise ValueError('Archive exceeded bounded 200-page run; review coverage before continuing')
        result=client.fetch(url,'POST',data={'action':'RenderPrices','priceTypeId':'1','page':str(page),'fromDate':start,'toDate':end})
        html=result.response.json()['html']
        batch=client.store.ingest(result.capture_id,parse_ministry(html))
        parsed+=batch['parsed_rows'];added+=batch['new_observations'];seen.add(page)
        # Follow only page numbers actually exposed by the public navigation.
        pending+=sorted({int(n) for n in re.findall(r'loadPrices\(\s*(\d+)',html)}-seen-set(pending))
    return {'parsed_rows':parsed,'new_observations':added,'pages':len(seen)}


def parse_taqtek(raw):
    doc=soup(raw)
    if '20-litre' not in doc.get_text(' ',strip=True) and '20 L' not in doc.get_text(' ',strip=True):
        raise ValueError("Taqtek page no longer confirms 20 L units")
    chunks=[]
    for script in doc.select('script'):
        text=script.string or script.get_text()
        match=re.fullmatch(r'self\.__next_f\.push\((.*)\)',text,re.S)
        if match:
            arr=json.loads(match[1])
            if len(arr)>1 and isinstance(arr[1],str): chunks.append(arr[1])
    stream=''.join(chunks)
    rows={}
    for match in re.finditer(r'"series":',stream):
        try: series=json.JSONDecoder().raw_decode(stream[match.end():].lstrip())[0]
        except ValueError: continue
        if not isinstance(series,list): continue
        for item in series:
            if isinstance(item,dict) and item.get('id')=='gasoline_95':
                for point in item['points']:
                    rows[(point['d'],str(point['p']))]=point
    if not rows:
        raise ValueError("No inspected LBP gasoline_95 series in public HTML payload")
    for i,point in enumerate(rows.values(),1):
        yield Observation('taqtek',point['d'],point['p'],TAQTEK_URL,point,str(i))


def collect_taqtek(client):
    result=client.fetch(TAQTEK_URL)
    return client.store.ingest(result.capture_id,parse_taqtek(result.response.content))


def parse_manual(raw, source='manual'):
    reader=csv.DictReader(StringIO(raw.decode('utf-8-sig')))
    required={'source_date','price_lbp_20l','unit','source_url'}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('Manual CSV missing required columns')
    for i,row in enumerate(reader,2):
        if not row['source_url'].startswith('https://'):
            raise ValueError('Manual CSV needs public HTTPS source URL')
        verified=row.get('verification_status')=='document_verified'
        if source=='official_document':
            host=urlparse(row['source_url']).hostname or ''
            if not host.endswith('.gov.lb') or not verified or not row.get('evidence_locator') or not row.get('reviewer'):
                raise ValueError('Official document rows need government URL, reviewer, locator, explicit verification')
        yield Observation(source,row['source_date'],row['price_lbp_20l'],row['source_url'],row,str(i),unit=row['unit'],
            date_role='effective_date' if row.get('official_effective_date') else 'source_label',
            official_effective_date=row.get('official_effective_date') or None,publication_date=row.get('publication_date') or None,
            publication_timestamp=row.get('publication_timestamp') or None,decision_number=row.get('decision_number') or None,
            document_verified=verified)
