#!/usr/bin/env python3
"""Scarica i dati aperti del MIMIT (prezzi alle 8 + anagrafica impianti) e prepara
i file che legge l'app:

  data/pompe.json    impianti con prezzi e servizi (non viene salvato nel repository)
  data/meta.json     data dei prezzi e versione del file
  data/history.json  media giornaliera per regione (si accumula nel tempo)

Uso normale (GitHub Actions):   python scripts/build_data.py
Prova con file locali:           python scripts/build_data.py --prezzi p.csv --anagrafica a.csv
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = ('https://www.mimit.gov.it/it/open-data/elenco-dataset/'
        'carburanti-prezzi-praticati-e-anagrafica-degli-impianti')
FALLBACK_PRICES = ['https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv']
FALLBACK_ANAG = [
    'https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivo.csv',
    'https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv',
]
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36 PompaGiusta/1.0')
FUEL_KEY = {'benzina': 'B', 'gasolio': 'D', 'gpl': 'G', 'metano': 'M'}
MAX_AGE_DAYS = 8


# ---------------------------------------------------------------- rete
def http_get(url, retries=3, timeout=90):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(4 * (attempt + 1))
    raise RuntimeError('Download non riuscito: %s (%s)' % (url, last))


def decode(raw):
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1252')


def discover_urls():
    """Cerca nella pagina del MIMIT i link ai CSV, per non dipendere da un indirizzo fisso."""
    anag, prices = [], []
    try:
        html = decode(http_get(PAGE, retries=2))
        for href in re.findall(r'href=["\']([^"\']+\.csv[^"\']*)["\']', html, re.I):
            full = urllib.parse.urljoin(PAGE, href)
            low = full.lower()
            if 'media' in low or 'archivio' in low:
                continue
            if 'anagrafica' in low:
                anag.append(full)
            elif 'prezzo' in low:
                prices.append(full)
    except Exception as e:  # la scoperta e' solo un aiuto: si prosegue con gli indirizzi noti
        print('Avviso: pagina dati non letta (%s)' % e, file=sys.stderr)
    return anag + FALLBACK_ANAG, prices + FALLBACK_PRICES


def fetch_first(urls, label):
    errors = []
    seen = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        try:
            text = decode(http_get(u))
            if 'idimpianto' in text[:4000].lower():
                print('%s: %s (%d byte)' % (label, u, len(text)))
                return text
            errors.append('%s: contenuto inatteso' % u)
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError('Impossibile scaricare %s.\n  ' % label + '\n  '.join(errors))


# --------------------------------------------------------------- parsing
def parse_table(text):
    lines = text.splitlines()
    h = next((i for i, l in enumerate(lines) if re.search(r'idimpianto', l, re.I)), -1)
    if h < 0:
        raise ValueError("Non trovo l'intestazione con idImpianto")
    head = lines[h]
    sep = '|' if '|' in head else (';' if ';' in head else ',')
    quoting = csv.QUOTE_NONE if sep == '|' else csv.QUOTE_MINIMAL
    reader = csv.reader(io.StringIO('\n'.join(lines[h:])), delimiter=sep, quoting=quoting)
    rows = list(reader)
    cols = [c.strip().lower() for c in rows[0]]

    def col(name):
        for i, c in enumerate(cols):
            if c == name:
                return i
        for i, c in enumerate(cols):
            if name in c:
                return i
        return -1

    return {'meta': ' '.join(lines[:h]), 'col': col, 'cols': cols, 'rows': rows[1:]}


def norm(s):
    s = unicodedata.normalize('NFD', str(s or ''))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper()
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Z ]', ' ', s)).strip()


def title(s):
    s = str(s or '').lower()
    return re.sub(r"(^|[\s'’\-.(])([a-zà-ÿ])",
                  lambda m: m.group(1) + m.group(2).upper(), s)


ACRONYMS = {'ip', 'q8', 'gpl', 'srl', 'spa', 'sas', 'snc', 'gnl', 'cng'}


def brand_title(s):
    return ' '.join(w.upper() if w.lower() in ACRONYMS else title(w) for w in str(s or '').split())


class Province:
    def __init__(self, path):
        data = json.load(open(path, encoding='utf-8'))
        self.by_code = {c: (n, r) for c, n, r in data}
        self.by_name = {norm(n): c for c, n, r in data}
        for a, b in [('FORLI CESENA', 'FC'), ('MASSA CARRARA', 'MS'), ('REGGIO NELL EMILIA', 'RE'),
                     ('REGGIO DI CALABRIA', 'RC'), ('VALLE D AOSTA', 'AO'), ('BOLZANO BOZEN', 'BZ')]:
            self.by_name[a] = b

    def sigla(self, raw):
        r = str(raw or '').strip()
        u = r.upper()
        if len(u) == 2 and u in self.by_code:
            return u
        return self.by_name.get(norm(r), u)

    def region(self, code):
        return self.by_code.get(code, (code, code))[1]


def parse_dt(s):
    s = str(s or '').strip()
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?', s)
    if m:
        return datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4] or 0), int(m[5] or 0))
    try:
        return datetime.fromisoformat(s.replace('Z', ''))
    except ValueError:
        return None


def to_float(s):
    try:
        return float(str(s).strip().replace(',', '.'))
    except ValueError:
        return None


def realign(row, ncols):
    """Se un nome o un indirizzo contiene il separatore, la riga ha colonne in piu' e i campi
    si spostano. Riallineo ancorandomi al tipo impianto (inizio) e ad comune/provincia/lat/lon (fine)."""
    if len(row) <= ncols:
        return row
    j = next((i for i in range(3, len(row) - 4) if row[i].strip().lower() in ('stradale', 'autostradale')), None)
    if j is None:
        return row
    mid = row[j + 1:-4]
    if not mid:
        return row
    gestore = ' '.join(x.strip() for x in row[1:j - 1])
    return [row[0], gestore, row[j - 1], row[j], mid[0], ' '.join(x.strip() for x in mid[1:])] + row[-4:]


def read_anagrafica(text, prov):
    t = parse_table(text)
    c = {k: t['col'](v) for k, v in dict(
        id='idimpianto', brand='bandiera', tipo='tipo', name='nome', addr='indirizzo',
        com='comune', prov='provincia', lat='latitudine', lon='longitudine').items()}
    out = {}
    ncols = max(c.values()) + 1
    anomalies = []

    def get(row, k):
        i = c[k]
        return row[i].strip() if 0 <= i < len(row) else ''

    for row in t['rows']:
        sid = get(row, 'id')
        if not sid:
            continue
        if len(row) != len(t['cols']):
            anomalies.append(('colonne %d invece di %d' % (len(row), len(t['cols'])), '|'.join(row)))
            row = realign(row, len(t['cols']))
        lat, lon = to_float(get(row, 'lat')), to_float(get(row, 'lon'))
        if lat is None or lon is None or not (35 < lat < 48 and 6 < lon < 19):
            lat = lon = None
        code = prov.sigla(get(row, 'prov'))
        if code not in prov.by_code:
            anomalies.append(('provincia sconosciuta', '|'.join(row)))
            continue
        out[sid] = {
            'i': sid,
            'b': brand_title(get(row, 'brand')) or 'Altro',
            'n': get(row, 'name') or ('Impianto ' + sid),
            'a': get(row, 'addr'),
            'c': title(get(row, 'com')),
            'p': code,
            'la': lat, 'lo': lon,
            'h': 1 if 'autostrad' in get(row, 'tipo').lower() else 0,
        }
    return out, anomalies


def read_prezzi(text):
    t = parse_table(text)
    ci = t['col']('idimpianto')
    cd = t['col']('desccarburante')
    if cd < 0:
        cd = t['col']('carburante')
    cp, cs, ct = t['col']('prezzo'), t['col']('isself'), t['col']('dtcomu')
    if min(ci, cd, cp, cs) < 0:
        raise ValueError('Il file dei prezzi non ha le colonne attese')
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', t['meta']) or None
    ref = None
    if m:
        ref = datetime(int(m[1]), int(m[2]), int(m[3]), 23, 59)
    else:
        m2 = re.search(r'(\d{2})/(\d{2})/(\d{4})', t['meta'])
        if m2:
            ref = datetime(int(m2[3]), int(m2[2]), int(m2[1]), 23, 59)
    rows = []
    newest = None
    for r in t['rows']:
        if len(r) <= max(ci, cd, cp, cs):
            continue
        k = FUEL_KEY.get(r[cd].strip().lower())
        pr = to_float(r[cp])
        if not k or pr is None or not (0.4 < pr < 5):
            continue
        selfv = 1 if r[cs].strip().lower() in ('1', 'true', 'si', 'sì') else 0
        dt = parse_dt(r[ct]) if 0 <= ct < len(r) else None
        if dt and (newest is None or dt > newest):
            newest = dt
        rows.append((r[ci].strip(), '%s%d' % (k, selfv), pr, dt))
    if ref is None:
        ref = newest or datetime.now()
    prices, stale = {}, 0
    for sid, key, pr, dt in rows:
        if dt and (ref - dt).total_seconds() / 86400 > MAX_AGE_DAYS:
            stale += 1
            continue
        d = prices.setdefault(sid, {})
        if key not in d or pr < d[key]:
            d[key] = round(pr, 3)
    return prices, ref.strftime('%Y-%m-%d'), stale


# ------------------------------------------------------------- servizi OSM
def load_services(path):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        return []


def attach_services(stations, services):
    """Collega i servizi di OpenStreetMap: prima per codice MIMIT, poi per vicinanza (60 m)."""
    by_ref = {}
    grid = {}
    for e in services:
        if e.get('r'):
            by_ref[str(e['r'])] = e
        if e.get('la') is not None:
            grid.setdefault((int(e['la'] * 100), int(e['lo'] * 100)), []).append(e)
    matched = 0
    for s in stations:
        e = by_ref.get(s['i'])
        if e is None and s.get('la') is not None:
            gx, gy = int(s['la'] * 100), int(s['lo'] * 100)
            best, bd = None, 0.06
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for cand in grid.get((gx + dx, gy + dy), []):
                        d = haversine(s['la'], s['lo'], cand['la'], cand['lo'])
                        if d < bd:
                            best, bd = cand, d
            e = best
        if e and e.get('s'):
            s['s'] = sorted(set(e['s']))
            matched += 1
    return matched


def haversine(a, b, c, d):
    r, t = 6371.0, math.pi / 180
    x = (math.sin((c - a) * t / 2) ** 2 +
         math.cos(a * t) * math.cos(c * t) * math.sin((d - b) * t / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(x))


# ------------------------------------------------------------------ medie
def averages(stations, prov):
    acc = {}
    for s in stations:
        if s.get('h'):
            continue
        reg = prov.region(s['p'])
        for k, v in s['x'].items():
            a = acc.setdefault(k, {'sum': 0.0, 'n': 0, 'r': {}})
            a['sum'] += v
            a['n'] += 1
            r = a['r'].setdefault(reg, [0.0, 0])
            r[0] += v
            r[1] += 1
    out = {}
    for k, a in acc.items():
        out[k] = {'ALL': round(a['sum'] / a['n'], 4)}
        for reg, (sm, n) in a['r'].items():
            out[k][reg] = round(sm / n, 4)
    return out


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prezzi')
    ap.add_argument('--anagrafica')
    ap.add_argument('--out', default=os.path.join(ROOT, 'data'))
    ap.add_argument('--min-stations', type=int, default=8000,
                    help='sotto questa soglia i dati sono considerati incompleti')
    args = ap.parse_args()

    prov = Province(os.path.join(ROOT, 'province.json'))
    if args.prezzi and args.anagrafica:
        p_text = decode(open(args.prezzi, 'rb').read())
        a_text = decode(open(args.anagrafica, 'rb').read())
    else:
        a_urls, p_urls = discover_urls()
        a_text = fetch_first(a_urls, 'anagrafica')
        p_text = fetch_first(p_urls, 'prezzi')

    anag, anomalies = read_anagrafica(a_text, prov)
    prices, date, stale = read_prezzi(p_text)

    stations = []
    for sid, rec in anag.items():
        if sid in prices:
            rec = dict(rec)
            rec['x'] = prices[sid]
            stations.append(rec)
    if len(stations) < args.min_stations:
        sys.exit('Troppo pochi impianti con prezzi (%d): non pubblico dati incompleti.' % len(stations))

    matched = attach_services(stations, load_services(os.path.join(args.out, 'services.json')))
    stations.sort(key=lambda s: (s['p'], s['c'], s['n']))
    for s in stations:  # tolgo i campi vuoti per tenere il file leggero
        for k in [k for k, v in s.items() if v in (None, '', 0) and k not in ('x',)]:
            del s[k]

    payload = {'date': date, 'n': len(stations), 's': stations}
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    version = hashlib.sha1(body.encode('utf-8')).hexdigest()[:10]
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'pompe.json'), 'w', encoding='utf-8') as f:
        f.write(body)
    meta = {'date': date, 'n': len(stations), 'v': version, 'stale': stale, 'servizi': matched,
            'generated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    with open(os.path.join(args.out, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, separators=(',', ':'))

    hist_path = os.path.join(args.out, 'history.json')
    try:
        hist = json.load(open(hist_path, encoding='utf-8'))
    except (OSError, ValueError):
        hist = {}
    hist[date] = averages([dict(s, x=s['x']) for s in stations], prov)
    for d in sorted(hist)[:-400]:
        del hist[d]
    with open(hist_path, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, separators=(',', ':'), sort_keys=True)

    with open(os.path.join(args.out, 'anomalie.json'), 'w', encoding='utf-8') as f:
        json.dump({'date': date, 'totale': len(anomalies),
                   'righe': [{'motivo': m, 'riga': r} for m, r in anomalies[:80]]},
                  f, ensure_ascii=False, indent=1)

    # diagnostica: distribuzione dei prezzi, per controllare che non ci siano valori strani
    diag = {'date': date, 'keys': {}}
    for k in sorted({k for s in stations for k in s['x']}):
        vals = sorted((v, s['i'], s['n'], s['c'], s['p'], bool(s.get('h'))) for s in stations for kk, v in s['x'].items() if kk == k)
        only = [v[0] for v in vals]
        n = len(only)
        diag['keys'][k] = {'n': n, 'min': only[0], 'p5': only[n // 20], 'med': only[n // 2], 'p95': only[n - 1 - n // 20], 'max': only[-1],
                           'sotto_1.7': sum(1 for v in only if v < 1.7), 'sopra_2.4': sum(1 for v in only if v > 2.4),
                           'piu_bassi': vals[:6], 'piu_alti': vals[-4:]}
    with open(os.path.join(args.out, 'diagnostica.json'), 'w', encoding='utf-8') as f:
        json.dump(diag, f, ensure_ascii=False, indent=1)

    print('Fatto: %d impianti, prezzi del %s, %d prezzi scartati perche\' vecchi, %d con servizi.' %
          (len(stations), date, stale, matched))


if __name__ == '__main__':
    main()
