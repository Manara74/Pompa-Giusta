#!/usr/bin/env python3
"""Raccoglie da OpenStreetMap i servizi presenti nei distributori italiani
(lavaggio, aria, bar, negozio, ricarica elettrica, officina, WC, 24 ore...)
e salva data/services.json.

Attenzione: OpenStreetMap e' scritta da volontari. Un servizio assente dall'elenco
non significa che il distributore non lo abbia, solo che nessuno l'ha ancora mappato.

Uso:  python scripts/build_services.py
Prova con una risposta salvata:  python scripts/build_services.py --from-json risposta.json
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENDPOINTS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
]
UA = 'PompaGiusta/1.0 (+https://github.com/Manara74/pompa-giusta)'

REGIONS = {
    'IT-65': 'Abruzzo', 'IT-77': 'Basilicata', 'IT-78': 'Calabria', 'IT-72': 'Campania',
    'IT-45': 'Emilia-Romagna', 'IT-36': 'Friuli-Venezia Giulia', 'IT-62': 'Lazio',
    'IT-42': 'Liguria', 'IT-25': 'Lombardia', 'IT-57': 'Marche', 'IT-67': 'Molise',
    'IT-21': 'Piemonte', 'IT-75': 'Puglia', 'IT-88': 'Sardegna', 'IT-82': 'Sicilia',
    'IT-52': 'Toscana', 'IT-32': 'Trentino-Alto Adige', 'IT-55': 'Umbria',
    'IT-23': "Valle d'Aosta", 'IT-34': 'Veneto',
}

QUERY = """[out:json][timeout:240];
area["ISO3166-2"="%s"]->.a;
nwr["amenity"="fuel"](area.a)->.f;
(
  .f;
  nwr(around.f:100)["amenity"~"^(car_wash|compressed_air|vacuum_cleaner|toilets|cafe|fast_food|restaurant|bar)$"];
  nwr(around.f:100)["shop"~"^(convenience|kiosk|supermarket|car_repair|tyres)$"];
  nwr(around.f:150)["amenity"="charging_station"];
);
out center tags;
"""

NEAR_AMENITY = {
    'car_wash': ['LAV'], 'compressed_air': ['ARIA'], 'vacuum_cleaner': ['VAC'],
    'toilets': ['WC'], 'cafe': ['BAR'], 'fast_food': ['BAR'], 'restaurant': ['BAR'],
    'bar': ['BAR'], 'charging_station': ['EV'],
}
NEAR_SHOP = {
    'convenience': ['SHOP'], 'kiosk': ['SHOP'], 'supermarket': ['SHOP'],
    'car_repair': ['OFF'], 'tyres': ['GOM'],
}
FAST_SOCKETS = ('socket:type2_combo', 'socket:chademo', 'socket:ccs')


def post(endpoint, query):
    data = urllib.parse.urlencode({'data': query}).encode()
    req = urllib.request.Request(endpoint, data=data, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode('utf-8'))


def overpass(query, tries=4):
    last = None
    for attempt in range(tries):
        endpoint = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            return post(endpoint, query)
        except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError) as e:
            last = e
            print('  tentativo %d non riuscito (%s)' % (attempt + 1, e), file=sys.stderr)
            time.sleep(30 * (attempt + 1))
    raise RuntimeError(last)


def coords(el):
    if 'lat' in el:
        return el['lat'], el['lon']
    c = el.get('center')
    return (c['lat'], c['lon']) if c else (None, None)


def haversine(a, b, c, d):
    r, t = 6371.0, math.pi / 180
    x = (math.sin((c - a) * t / 2) ** 2 +
         math.cos(a * t) * math.cos(c * t) * math.sin((d - b) * t / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(x))


def own_flags(tags):
    """Servizi dichiarati direttamente sul distributore."""
    f = set()
    yes = lambda k: tags.get(k) == 'yes'
    if yes('car_wash') or tags.get('amenity') == 'car_wash':
        f.add('LAV')
    if yes('automated') and 'LAV' in f:
        f.add('LAVA')
    if yes('self_service') and 'LAV' in f:
        f.add('LAVS')
    if yes('compressed_air'):
        f.add('ARIA')
    if yes('vacuum_cleaner'):
        f.add('VAC')
    if yes('toilets'):
        f.add('WC')
    if tags.get('shop') in NEAR_SHOP:
        f.update(NEAR_SHOP[tags['shop']])
    if yes('cafe') or yes('bar') or yes('fast_food'):
        f.add('BAR')
    if tags.get('opening_hours', '').strip() == '24/7':
        f.add('H24')
    if yes('service:vehicle:car_repair'):
        f.add('OFF')
    if yes('service:vehicle:oil_change'):
        f.add('OLIO')
    if yes('service:vehicle:tyres'):
        f.add('GOM')
    return f


def feature_flags(tags):
    f = set()
    f.update(NEAR_AMENITY.get(tags.get('amenity'), []))
    f.update(NEAR_SHOP.get(tags.get('shop'), []))
    if tags.get('amenity') == 'charging_station' and any(k in tags for k in FAST_SOCKETS):
        f.add('EVF')
    if tags.get('amenity') == 'car_wash':
        if tags.get('automated') == 'yes':
            f.add('LAVA')
        if tags.get('self_service') == 'yes':
            f.add('LAVS')
    return f


def process(elements, region):
    stations, feats = [], []
    for el in elements:
        la, lo = coords(el)
        if la is None:
            continue
        tags = el.get('tags', {})
        if tags.get('amenity') == 'fuel':
            stations.append({'r': tags.get('ref:mise', '').strip(), 'la': round(la, 6),
                             'lo': round(lo, 6), 'g': region, 'f': own_flags(tags)})
        else:
            feats.append((la, lo, tags, feature_flags(tags)))
    # assegno ogni servizio vicino al distributore piu' prossimo (entro 150 m)
    grid = {}
    for i, s in enumerate(stations):
        grid.setdefault((int(s['la'] * 100), int(s['lo'] * 100)), []).append(i)
    for la, lo, tags, flags in feats:
        if not flags:
            continue
        limit = 0.15 if tags.get('amenity') == 'charging_station' else 0.10
        best, bd = None, limit
        gx, gy = int(la * 100), int(lo * 100)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in grid.get((gx + dx, gy + dy), []):
                    d = haversine(la, lo, stations[i]['la'], stations[i]['lo'])
                    if d < bd:
                        best, bd = i, d
        if best is not None:
            stations[best]['f'] |= flags
    out = []
    for s in stations:
        if s['f']:
            out.append({'r': s['r'], 'la': s['la'], 'lo': s['lo'], 'g': s['g'], 's': sorted(s['f'])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from-json', help='risposta Overpass salvata (prova locale)')
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'services.json'))
    args = ap.parse_args()

    if args.from_json:
        elements = json.load(open(args.from_json, encoding='utf-8'))['elements']
        result = process(elements, 'Prova')
        json.dump(result, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print('Servizi su %d distributori.' % len(result))
        return

    try:
        previous = json.load(open(args.out, encoding='utf-8'))
    except (OSError, ValueError):
        previous = []
    fresh, failed = [], []
    for iso, name in REGIONS.items():
        print('Regione %s (%s)...' % (name, iso))
        try:
            data = overpass(QUERY % iso)
            part = process(data.get('elements', []), name)
            if not part:
                raise RuntimeError('risposta vuota')
            fresh.extend(part)
            print('  %d distributori con servizi' % len(part))
        except Exception as e:
            print('  ERRORE: %s -> mantengo i dati precedenti' % e, file=sys.stderr)
            failed.append(name)
            fresh.extend([e2 for e2 in previous if e2.get('g') == name])
        time.sleep(20)  # cortesia verso il servizio pubblico
    if len(failed) > 10:
        sys.exit('Troppe regioni non riuscite (%s): non salvo.' % ', '.join(failed))
    json.dump(fresh, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('Totale: %d distributori con servizi. Regioni non aggiornate: %s' %
          (len(fresh), ', '.join(failed) or 'nessuna'))


if __name__ == '__main__':
    main()
