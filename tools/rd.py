#!/usr/bin/env python3
"""Správa appky Schvalování ŘD Oázy klidu z příkazové řádky (REST API Firestore).

Klíč se bere z proměnné RD_KLIC, ze souboru ~/.config/oaza-rd/klic nebo z --klic.
Balíčky a dokumenty se čtou z index.html (blok <script id="data">). Jen standardní knihovna.

  rd.py stav [--kdo dasa|helca|jitka|jarda]   přehled balíčků a u koho jsou
  rd.py detail ID                              stav jednoho balíčku jako JSON (ID = číslo balíčku 1–42 nebo kód A2)
  rd.py krok ID [KROK] [--kdo U] [--kdy ISO]   potvrdí další krok (precteno, odeslano, gestor, predano, reditelka)
  rd.py zpet ID [--kdo U]                      vezme zpět poslední krok
  rd.py vratit ID TEXT [--kdo U]               vrátí balíček Jardovi s připomínkami
  rd.py pozn ID KOD TEXT [--kdo U]             poznámka k dokumentu (prázdný TEXT ji smaže)
  rd.py vlna W [--rozhodnuti C] [--ucinnost RRRR-MM-DD] [--podepsano ano|ne] [--seznameni ano|ne]
  rd.py export [SOUBOR]                        záloha všech dat do JSON
"""
import argparse, json, os, re, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

API_KEY = 'AIzaSyDowhduH6_0zkbfVn_VDKVS3Ztz6XJqjto'
BASE = 'https://firestore.googleapis.com/v1/projects/oaza-luzka/databases/(default)/documents'
ROOT = 'oaza_rd'
HERE = os.path.dirname(os.path.abspath(__file__))
JMENA = {'jarda': 'Jarda', 'dasa': 'Dáša', 'helca': 'Helča', 'jitka': 'Jitka'}


def data():
    html = open(os.path.join(HERE, '..', 'index.html'), encoding='utf-8').read()
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
    return json.loads(m.group(1).replace('<\\/', '</'))


D = data()
BAL = {b['id']: b for b in D['balicky']}


def steps(b):
    if b['g'] == 'jarda': return ['precteno', 'predano', 'reditelka']
    if b['g'] == 'jitka': return ['precteno', 'odeslano', 'reditelka']
    return ['precteno', 'odeslano', 'gestor', 'predano', 'reditelka']


def actor(b, k):
    return 'jarda' if k in ('precteno', 'odeslano') else 'jitka' if k == 'reditelka' else b['g']


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def klic(a):
    k = a.klic or os.environ.get('RD_KLIC')
    if not k:
        p = os.path.expanduser('~/.config/oaza-rd/klic')
        if os.path.exists(p): k = open(p).read().strip()
    if not k: sys.exit('Chybí klíč: nastavte RD_KLIC, soubor ~/.config/oaza-rd/klic nebo --klic.')
    return k


def dec(v):
    if 'stringValue' in v: return v['stringValue']
    if 'integerValue' in v: return int(v['integerValue'])
    if 'doubleValue' in v: return float(v['doubleValue'])
    if 'booleanValue' in v: return v['booleanValue']
    if 'nullValue' in v: return None
    if 'arrayValue' in v: return [dec(x) for x in v['arrayValue'].get('values', [])]
    if 'mapValue' in v: return {k: dec(x) for k, x in v['mapValue'].get('fields', {}).items()}
    raise ValueError(v)


def enc(v):
    if isinstance(v, bool): return {'booleanValue': v}
    if isinstance(v, int): return {'integerValue': str(v)}
    if isinstance(v, float): return {'doubleValue': v}
    if isinstance(v, str): return {'stringValue': v}
    if v is None: return {'nullValue': None}
    if isinstance(v, list): return {'arrayValue': {'values': [enc(x) for x in v]}}
    if isinstance(v, dict): return {'mapValue': {'fields': {k: enc(x) for k, x in v.items()}}}
    raise ValueError(v)


def req(method, path, body=None, params=None):
    q = {'key': API_KEY, **(params or {})}
    url = f'{BASE}/{path}?{urllib.parse.urlencode(q, doseq=True)}'
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                               headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == 'GET': return None
        msg = e.read().decode(errors='replace')
        if e.code == 403: sys.exit('Přístup odepřen: klíč neplatí, nebo data neodpovídají pravidlům.\n' + msg[:400])
        if e.code in (400, 409) and 'precondition' in msg.lower(): sys.exit('Data se mezitím změnila, zkuste příkaz znovu.')
        sys.exit(f'Chyba {e.code}: {msg[:600]}')


def load_all(k, coll):
    out, token = {}, None
    while True:
        params = {'pageSize': 300, **({'pageToken': token} if token else {})}
        r = req('GET', f'{ROOT}/{k}/{coll}', params=params) or {}
        for d in r.get('documents', []):
            out[d['name'].rsplit('/', 1)[1]] = {f: dec(v) for f, v in d.get('fields', {}).items()}
        token = r.get('nextPageToken')
        if not token: return out


EMPTY = {'bal': lambda: {'kroky': {}, 'vraceno': None, 'pozn': {}, 'hist': [], 'upr': ''},
         'vlny': lambda: {'rozhodnuti': '', 'ucinnost': '', 'podepsano': None, 'seznameni': None, 'upr': ''}}


def update(k, coll, did, fn):
    path = f'{ROOT}/{k}/{"balicky" if coll == "bal" else "vlny"}/{did}'
    r = req('GET', path)
    cur = EMPTY[coll]()
    if r: cur.update({f: dec(v) for f, v in r.get('fields', {}).items()})
    fn(cur)
    cur['upr'] = now()
    pre = {'currentDocument.updateTime': r['updateTime']} if r else {'currentDocument.exists': 'false'}
    req('PATCH', path, {'fields': {f: enc(v) for f, v in cur.items()}}, pre)
    return cur


def next_step(b, s):
    return next((x for x in steps(b) if not (s.get('kroky') or {}).get(x)), None)


def holder_txt(b, s):
    n = next_step(b, s)
    if not n: return 'schváleno'
    return 'u ředitelky' if n == 'reditelka' else 'u ' + {'jarda': 'Jardy', 'dasa': 'Dáši', 'helca': 'Helči', 'jitka': 'Jitky'}[actor(b, n)]


def bal_arg(i):
    if i.isdigit():
        m = [b for b in BAL.values() if b.get('n') == int(i)]
        if m: return m[0]
    if i not in BAL: sys.exit(f'Neznámý balíček {i}. Zadejte číslo 1 až {len(BAL)} nebo kód typu A2.')
    return BAL[i]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--klic')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('stav'); p.add_argument('--kdo')
    p = sub.add_parser('detail'); p.add_argument('id')
    p = sub.add_parser('krok'); p.add_argument('id'); p.add_argument('krok', nargs='?'); p.add_argument('--kdo', default='jarda'); p.add_argument('--kdy')
    p = sub.add_parser('zpet'); p.add_argument('id'); p.add_argument('--kdo', default='jarda')
    p = sub.add_parser('vratit'); p.add_argument('id'); p.add_argument('text'); p.add_argument('--kdo', default='jitka')
    p = sub.add_parser('pozn'); p.add_argument('id'); p.add_argument('kod'); p.add_argument('text'); p.add_argument('--kdo', default='jarda')
    p = sub.add_parser('vlna'); p.add_argument('w'); p.add_argument('--rozhodnuti'); p.add_argument('--ucinnost'); p.add_argument('--podepsano'); p.add_argument('--seznameni'); p.add_argument('--kdo', default='jarda')
    p = sub.add_parser('export'); p.add_argument('soubor', nargs='?')
    a = ap.parse_args()
    k = klic(a)
    if getattr(a, 'kdo', None) and a.kdo not in JMENA: sys.exit('--kdo musí být jarda, dasa, helca nebo jitka')

    if a.cmd == 'stav':
        s_all, v_all = load_all(k, 'balicky'), load_all(k, 'vlny')
        for w in D['waves']:
            rows = [b for b in D['balicky'] if b['w'] == w['id']]
            v = v_all.get(w['id'], {})
            extra = ' · '.join(x for x in [v.get('rozhodnuti'), v.get('ucinnost'), 'podepsáno' if v.get('podepsano') else '', 'seznámeno' if v.get('seznameni') else ''] if x)
            print(f"\n{w['id']}  {w['t']}" + (f'  [{extra}]' if extra else ''))
            for b in rows:
                s = s_all.get(b['id'], {})
                n = next_step(b, s)
                if a.kdo and (not n or actor(b, n) != a.kdo): continue
                vr = '  VRÁCENO: ' + s['vraceno']['x'] if s.get('vraceno') else ''
                print(f"  {b['n']:>2} {b['id']:3} {b['t'][:44]:44} {JMENA[b['g']]:6} {holder_txt(b, s):12} {len([x for x in steps(b) if (s.get('kroky') or {}).get(x)])}/{len(steps(b))}{vr}")
    elif a.cmd == 'detail':
        b = bal_arg(a.id)
        r = req('GET', f'{ROOT}/{k}/balicky/{b["id"]}')
        print(json.dumps({**b, 'stav': {f: dec(v) for f, v in (r or {}).get('fields', {}).items()}}, ensure_ascii=False, indent=1))
    elif a.cmd == 'krok':
        b = bal_arg(a.id); t = a.kdy or now()
        def fn(cur):
            n = next_step(b, cur)
            if not n: sys.exit('Balíček je už schválený.')
            if a.krok and a.krok != n: sys.exit(f'Další krok je {n}, ne {a.krok}.')
            cur['kroky'][n] = {'u': a.kdo, 't': t}
            if n == 'precteno': cur['vraceno'] = None
            cur['hist'].append({'k': n, 'u': a.kdo, 't': t})
            print(f'{b["id"]}: {n} ({JMENA[a.kdo]}) → {holder_txt(b, cur)}')
        update(k, 'bal', b['id'], fn)
    elif a.cmd == 'zpet':
        b = bal_arg(a.id)
        def fn(cur):
            done = [x for x in steps(b) if cur['kroky'].get(x)]
            if not done: sys.exit('Není co brát zpět.')
            del cur['kroky'][done[-1]]
            cur['hist'].append({'k': 'zpet', 'u': a.kdo, 't': now(), 'x': done[-1]})
            print(f'{b["id"]}: vzato zpět {done[-1]}')
        update(k, 'bal', b['id'], fn)
    elif a.cmd == 'vratit':
        b = bal_arg(a.id); t = now()
        def fn(cur):
            cur['kroky'] = {}; cur['vraceno'] = {'u': a.kdo, 't': t, 'x': a.text}
            cur['hist'].append({'k': 'vraceno', 'u': a.kdo, 't': t, 'x': a.text})
        update(k, 'bal', b['id'], fn); print(f'{b["id"]}: vráceno Jardovi')
    elif a.cmd == 'pozn':
        b = bal_arg(a.id)
        if a.kod not in b['d']: sys.exit(f'{a.kod} není v balíčku {b["id"]} ({", ".join(b["d"])})')
        def fn(cur):
            if a.text.strip(): cur['pozn'][a.kod] = {'x': a.text.strip(), 'u': a.kdo, 't': now()}
            else: cur['pozn'].pop(a.kod, None)
        update(k, 'bal', b['id'], fn); print('Uloženo')
    elif a.cmd == 'vlna':
        if a.w not in {w['id'] for w in D['waves']}: sys.exit('Neznámá vlna')
        def fn(cur):
            if a.rozhodnuti is not None: cur['rozhodnuti'] = a.rozhodnuti
            if a.ucinnost is not None: cur['ucinnost'] = a.ucinnost
            for f in ('podepsano', 'seznameni'):
                v = getattr(a, f)
                if v is not None: cur[f] = {'u': a.kdo, 't': now()} if v == 'ano' else None
        print(json.dumps(update(k, 'vlny', a.w, fn), ensure_ascii=False))
    elif a.cmd == 'export':
        out = json.dumps({'balicky': load_all(k, 'balicky'), 'vlny': load_all(k, 'vlny')}, ensure_ascii=False, indent=1)
        if a.soubor: open(a.soubor, 'w', encoding='utf-8').write(out); print('Uloženo do', a.soubor)
        else: print(out)


if __name__ == '__main__':
    main()
