"""Abstract sentences -> Korean, by a translation API (no manual copy-and-paste).

Usage
  python translate_abstracts.py --provider deepl            # key: DEEPL_API_KEY in .env
  python translate_abstracts.py --provider papago           # keys: PAPAGO_CLIENT_ID / PAPAGO_CLIENT_SECRET in .env
  python translate_abstracts.py --provider deepl --include validation/final_papers.json   # only human-confirmed papers
  python translate_abstracts.py --dry-run                   # split sentences, translate nothing

Why sentence by sentence: the analysis unit is the sentence, and the translation check (English lexicon
category vs Korean lexicon category on 30-50 sentences) needs every Korean sentence paired with its source.

What is translated: the analysis part of each abstract only. Structured abstracts: every section except
background / objective (README §5). Unstructured abstracts: all sentences, each marked
section_category='unlabelled'; `position` lets the analysis drop the opening sentence by rule.

One provider is used for the whole study and recorded on every row (provider, endpoint, date), together
with the English and the Korean text. Results are cached by (provider, sentence text), so a second run
sends only new sentences and an interrupted run can be resumed.

Input   scripts/papers_v2_internal.json   (collect_papers_v2.py)
Output  scripts/abstract_translations.json  NOT committed (abstract text)
"""
import argparse, datetime, hashlib, json, pathlib, re, sys, time, urllib.error, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).parent
REPO = ROOT.parent
BACKGROUND = r'^(background|importance|introduction|objectives?|aims?|purpose|context|rationale|trial registration|funding)\b'
ABBREV = r'(?:vs|etc|e\.g|i\.e|al|Dr|Fig|No|approx|resp|ca|cf|St)\.$'
ENDPOINTS = {'deepl': 'https://api-free.deepl.com/v2/translate', 'papago': 'https://papago.apigw.ntruss.com/nmt/v1/translation'}


def env():
    p = REPO / '.env'
    if not p.exists():
        return {}
    return {k.strip(): v.strip().strip('"\'') for k, _, v in (l.partition('=') for l in p.read_text(encoding='utf-8-sig').splitlines()) if k.strip() and not k.startswith('#')}


def split_sentences(text):
    """English sentence split without extra packages: break after . ! ? before a capital / digit / bracket,
    but not after a known abbreviation, a single initial, or inside a decimal number."""
    out, buf = [], ''
    for piece in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9(\[])', ' '.join(text.split())):
        buf = f'{buf} {piece}'.strip() if buf else piece
        if re.search(ABBREV, buf) or re.search(r'\b[A-Z]\.$', buf):
            continue
        out.append(buf)
        buf = ''
    if buf:
        out.append(buf)
    return [s for s in out if s]


def analysis_sentences(paper):
    """paper: {'pmid', 'sections': [[label, text], ...]} -> rows without translation."""
    secs = paper['sections']
    structured = len(secs) > 1 or bool(secs[0][0])
    rows = []
    for label, text in secs:
        if structured and (not label or re.match(BACKGROUND, label, re.I)):
            continue
        for s in split_sentences(text):
            rows.append({'pmid': paper['pmid'], 'section_label': label, 'section_category': 'analysis' if structured else 'unlabelled', 'text_en': s})
    for i, r in enumerate(rows):
        r['sentence_id'] = f"{paper['pmid']}_s{i:03d}"
        r['position'] = i
    return rows


def _post(url, data, headers, timeout=40):
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def deepl(texts, keys, post=_post):
    url = keys.get('DEEPL_ENDPOINT') or ENDPOINTS['deepl']
    body = json.dumps({'text': texts, 'source_lang': 'EN', 'target_lang': 'KO'}).encode()
    res = post(url, body, {'Authorization': 'DeepL-Auth-Key ' + keys['DEEPL_API_KEY'], 'Content-Type': 'application/json'})
    return [t['text'] for t in res['translations']]


def papago(texts, keys, post=_post):
    url = keys.get('PAPAGO_ENDPOINT') or ENDPOINTS['papago']
    out = []
    for t in texts:   # one sentence per request
        body = urllib.parse.urlencode({'source': 'en', 'target': 'ko', 'text': t}).encode()
        res = post(url, body, {'X-NCP-APIGW-API-KEY-ID': keys['PAPAGO_CLIENT_ID'], 'X-NCP-APIGW-API-KEY': keys['PAPAGO_CLIENT_SECRET'],
                               'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})
        out.append(res['message']['result']['translatedText'])
        time.sleep(0.1)
    return out


PROVIDERS = {'deepl': (deepl, ('DEEPL_API_KEY',)), 'papago': (papago, ('PAPAGO_CLIENT_ID', 'PAPAGO_CLIENT_SECRET'))}


def translate_rows(rows, provider, keys, cache, translator=None, batch=20, today=None, log=print):
    fn = translator or PROVIDERS[provider][0]
    today = today or datetime.date.today().isoformat()
    key = lambda t: hashlib.sha1(f'{provider}\n{t}'.encode()).hexdigest()
    todo = sorted({r['text_en'] for r in rows if key(r['text_en']) not in cache})
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        for attempt in range(4):
            try:
                result = fn(chunk, keys)
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise SystemExit(f'{provider}: the key was rejected (HTTP {e.code}). Check .env.')
                if e.code == 456:
                    raise SystemExit('deepl: monthly character quota used up (HTTP 456).')
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt * 2)
        for t, ko in zip(chunk, result):
            cache[key(t)] = {'text_ko': ko, 'provider': provider, 'endpoint': keys.get(provider.upper() + '_ENDPOINT') or ENDPOINTS[provider], 'translated_at': today}
        log(f'translated {min(i + batch, len(todo))}/{len(todo)}')
    for r in rows:
        r.update(cache[key(r['text_en'])])
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--provider', choices=sorted(PROVIDERS), default='deepl')
    ap.add_argument('--include', help='JSON list of {"pmid", "side_effect"} to translate; default: the human-screening shortlist')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    internal = json.loads((ROOT / 'papers_v2_internal.json').read_text(encoding='utf-8'))
    if a.include:
        wanted = {(x['side_effect'], x['pmid']) for x in json.loads(pathlib.Path(a.include).read_text(encoding='utf-8'))}
    else:
        wanted = {(x['side_effect'], x['pmid']) for x in json.loads((REPO / 'paper_screening_v2.json').read_text(encoding='utf-8')) if x['shortlist']}
    papers = {}
    for g, pmid in sorted(wanted):
        p = papers.setdefault(pmid, {'pmid': pmid, 'sections': internal[f'{g}:{pmid}']['sections'], 'side_effects': []})
        p['side_effects'].append(g)
    rows = []
    for p in papers.values():
        for r in analysis_sentences(p):
            rows.append({**r, 'side_effects': p['side_effects']})
    chars = sum(len(r['text_en']) for r in rows)
    print(f'{len(papers)} papers, {len(rows)} sentences, {chars:,} characters; unlabelled (unstructured) sentences: {sum(r["section_category"] == "unlabelled" for r in rows)}')
    if a.dry_run:
        return rows
    keys = env()
    missing = [k for k in PROVIDERS[a.provider][1] if not keys.get(k)]
    if missing:
        sys.exit(f'{", ".join(missing)} not found in .env (see .env.example).')
    out = ROOT / 'abstract_translations.json'
    old = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {'cache': {}}
    rows = translate_rows(rows, a.provider, keys, old['cache'])
    out.write_text(json.dumps({'provider': a.provider, 'rows': rows, 'cache': old['cache']}, ensure_ascii=False, indent=1), encoding='utf-8')
    print('wrote', out.name, len(rows), 'sentences')
    return rows


if __name__ == '__main__':
    main()
