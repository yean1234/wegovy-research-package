"""Body extraction for candidate URLs (v2 of scrape_news.py).

Usage:  python scrape_articles.py news_candidates_fullperiod.json   (default: that file)
        RESPECT_AI_RULES=1 python scrape_articles.py ...            (when an AI assistant runs the crawl)

Differences from scrape_news.one (the record layout is a superset, so analyze_pilot.py and
label_articles.py read the output unchanged):
  - every request goes through crawl_common.polite_get: robots.txt, per-host delay, retries;
  - body/title/date come from extract_article.extract (selector / trafilatura / JSON-LD, see there);
  - a page that robots.txt disallows is recorded as crawl_status='robots_disallowed', not fetched;
  - `selector` holds the extractor name for non-selector methods, so the pilot rule
    "specific_body_selector = selector != 'body_fallback'" keeps its meaning;
  - already-extracted ids are skipped, so an interrupted run can simply be started again.
Hosts are crawled in parallel, pages of one host one after another (crawl_common.Throttle).
"""
import concurrent.futures, datetime, hashlib, json, pathlib, re, sys

from crawl_common import ROBOTS, article_id, decode, polite_get
from extract_article import DRUG, MIN_CHARS, extract
from scrape_news import PATTERNS

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / 'raw_news'


def one(r, out_dir=OUT, getter=polite_get):
    aid = article_id(r['canonical_url'])
    out = {**r, 'article_id': aid, 'collected_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'crawl_status': 'failed',
           'body': '', 'title_verified': '', 'published_at': '', 'selector': '', 'extractor': '', 'scraper_version': 2}
    try:
        res, robots = getter(r['url'], cache_key=aid)
        out.update(http_status=res.status, attempts=res.attempts, resolved_url=res.url, robots_ai_blocked=robots['ai_blocked'])
        if robots['reason']:
            out['crawl_status'] = 'robots_disallowed'
            out['error'] = robots['reason']
        elif not res.ok:
            out['error'] = res.error or f'http_{res.status}'
        else:
            page, charset = decode(res.data, res.charset)
            ex = extract(page, res.url)
            body = ex['body']
            out.update(body=body, title_verified=ex['title'] or r.get('title', ''), published_at=ex['published_at'], date_source=ex['date_source'],
                       extractor=ex['extractor'], selector=ex['xpath'] or ex['extractor'], extractor_candidates=ex['candidates'], charset=charset)
            enough = len(body) > MIN_CHARS and re.search(DRUG, body, re.I) is not None
            # Whole-page text is kept for inspection but is not an extracted article body (menus, related links).
            out['crawl_status'] = 'insufficient_text' if not enough else ('body_fallback_only' if ex['extractor'] == 'body_fallback' else 'body_extracted')
            out['detected_groups'] = [g for g, pat in PATTERNS.items() if re.search(pat, body, re.I)]
            out['has_wegovy'] = bool(re.search('위고비|Wegovy', body, re.I))
            out['has_semaglutide'] = bool(re.search('세마글루[타티]이드|세마글루티드|semaglutide', body, re.I))
            out['research_cue'] = bool(re.search(r'연구팀|연구진|메타분석|코호트|학술지|[Jj][Aa][Mm][Aa]|무작위|임상시험|논문|[Nn]ature', body))
            out['body_sha256'] = hashlib.sha256(re.sub(r'\s', '', body).encode()).hexdigest()
            out['evidence'] = {}
            for g in out['detected_groups']:
                m = re.search(PATTERNS[g], body, re.I)
                out['evidence'][g] = body[max(0, m.start() - 120):m.end() + 260]
    except Exception as e:  # a single bad page must not stop the run
        out['error'] = f'{type(e).__name__}: {e}'[:300]
    out_dir.mkdir(exist_ok=True)
    (out_dir / (aid + '.json')).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(aid, out['crawl_status'], out.get('extractor', ''), len(out['body']), r['canonical_url'], flush=True)
    return out


if __name__ == '__main__':
    src = ROOT / (sys.argv[1] if len(sys.argv) > 1 else 'news_candidates_fullperiod.json')
    rows = json.loads(src.read_text(encoding='utf-8'))
    todo = [r for r in rows if not (OUT / (article_id(r['canonical_url']) + '.json')).exists()]
    print('TODO', len(todo), 'OF', len(rows), flush=True)
    # Threads only parallelise across hosts; crawl_common.Throttle keeps each host sequential and delayed.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, todo))
    c = {}
    for x in results:
        c[x['crawl_status']] = c.get(x['crawl_status'], 0) + 1
    print('DONE', len(results), c, flush=True)
