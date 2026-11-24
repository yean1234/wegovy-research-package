"""Article body / title / date extraction (v2, 2026-11-24).

The pilot extractor (scrape_news.py) tried a fixed list of 16 XPath selectors and, when none matched,
took the text of the whole <body>. That fallback pulls in menus, related-article lists and footers, and
analyze_pilot.py then had to discard those articles ("specific_body_selector"). The selector list also
has to be extended by hand whenever an outlet changes its template.

v2 keeps the selectors but adds two template-independent methods and records which one produced the text:

  jsonld        schema.org NewsArticle "articleBody" embedded in the page, when the outlet provides it.
  trafilatura   Barbaresi (2021, ACL-IJCNLP system demonstrations). Heuristic main-content extraction that
                needs no per-site rules. Bevendorff et al. (2023, SIGIR) compared 14 extractors on 8 datasets;
                later summaries name Trafilatura and Readability as the strong heuristic ones (we have not
                checked the paper's tables ourselves, and none of its datasets is Korean news).
  selector      the pilot XPath list (unchanged), i.e. the outlet's own article container.
  body_fallback whole <body>; kept only so the row is not lost. Flagged, never counted as extracted.

Choice rule (decided before looking at results): take the first of [selector by element id, trafilatura,
jsonld, other selector] that is long enough and mentions the drug; if two candidates qualify and one is
contained in the other (>= 90 % of its sentences), prefer the shorter one, because the longer one is the
same article plus page furniture. `extractor` and the length of every candidate are stored, so the choice
can be audited and the methods compared (scripts/compare_extractors.py).

Dates: JSON-LD datePublished -> article meta tags -> htmldate (Barbaresi 2020) -> "입력 2024.07.03" in text.
"""
import json, re
from lxml import html as lxml_html

try:
    import trafilatura
    from htmldate import find_date
except ImportError:  # the pilot environment had only lxml; v2 degrades to the pilot behaviour
    trafilatura = None
    find_date = None

DRUG = r'위고비|세마글루|Wegovy|semaglutide'
MIN_CHARS = 350
SELECTORS = ['//*[@id="dic_area"]', '//*[@id="harmonyContainer"]', '//*[@id="article-view-content-div"]', '//*[@id="newsct_article"]',
             '//*[@id="articleBodyContents"]', '//*[@id="articleBody"]', '//*[@id="article_body"]', '//*[@id="newsEndContents"]',
             '//*[@id="newsContent"]', '//*[@id="article_txt"]', '//*[@id="newsView"]', '//*[contains(@class,"article-body")]',
             '//*[contains(@class,"article_body")]', '//*[contains(@class,"news_body")]', '//*[contains(@class,"article_view")]', '//article']
DATE_META = ('//meta[@property="article:published_time"]/@content|//meta[@name="date"]/@content|//meta[@name="publish-date"]/@content'
             '|//meta[@property="og:regDate"]/@content|//meta[@name="article:published_time"]/@content|//time/@datetime')


def clean(node):
    """Text of an element, one line per block, scripts/menus removed (same rules as the pilot)."""
    node = lxml_html.fromstring(lxml_html.tostring(node))
    for e in node.xpath('.//script|.//style|.//nav|.//footer|.//header|.//aside|.//form|.//iframe|.//noscript|.//figcaption'):
        e.drop_tree()
    for e in node.xpath('.//br'):
        e.tail = '\n' + (e.tail or '')
    for e in node.xpath('.//p|.//div|.//section|.//li'):
        e.tail = '\n' + (e.tail or '')
    return '\n'.join(' '.join(x.split()) for x in node.text_content().splitlines() if x.strip())


def _qualifies(text):
    return bool(text) and len(text) > MIN_CHARS and re.search(DRUG, text, re.I) is not None


def _sentences(text):
    return {s.strip() for s in re.split(r'(?<=[다요음임됨][.!?])\s+|\n', text) if len(s.strip()) >= 15}


def _contained(short, long, share=0.9):
    a, b = _sentences(short), _sentences(long)
    return bool(a) and len(a & b) / len(a) >= share


def jsonld_objects(doc):
    out = []
    for raw in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                out.append(o)
                stack.extend(v for v in o.get('@graph', []) if isinstance(v, dict))
    return out


def _is_article(o):
    t = o.get('@type')
    return any('Article' in str(x) for x in (t if isinstance(t, list) else [t]))


def extract(page, url=''):
    """page: decoded HTML string -> dict(title, body, published_at, extractor, candidates, date_source)."""
    doc = lxml_html.fromstring(page)
    ld = [o for o in jsonld_objects(doc) if _is_article(o)]

    cands = {}   # name -> text
    for xp in SELECTORS:
        texts = [t for t in (clean(n) for n in doc.xpath(xp)) if _qualifies(t)]
        if texts:
            cands['selector_id' if '@id=' in xp else 'selector_class'] = max(texts, key=len)
            cands['_xpath'] = xp
            break
    if trafilatura is not None:
        try:
            t = trafilatura.extract(page, url=url or None, include_comments=False, include_tables=False, favor_precision=True, deduplicate=True)
        except Exception:
            t = None
        if _qualifies(t):
            cands['trafilatura'] = t
    for o in ld:
        b = o.get('articleBody')
        if isinstance(b, str) and _qualifies(b):
            cands['jsonld'] = '\n'.join(' '.join(x.split()) for x in b.splitlines() if x.strip())
            break

    order = [k for k in ('selector_id', 'trafilatura', 'jsonld', 'selector_class') if k in cands]
    chosen = order[0] if order else ''
    for k in order[1:]:   # a shorter candidate that is contained in the chosen one is the cleaner copy
        if len(cands[k]) < len(cands[chosen]) and _contained(cands[k], cands[chosen]):
            chosen = k
    if chosen:
        body, extractor = cands[chosen], chosen
    else:
        nodes = doc.xpath('//body')
        body, extractor = (clean(nodes[0]) if nodes else clean(doc)), 'body_fallback'

    title = ''
    for cand in doc.xpath('//meta[@property="og:title"]/@content') + [o.get('headline') for o in ld if isinstance(o.get('headline'), str)] + doc.xpath('//title/text()'):
        if cand and cand.strip():
            title = ' '.join(cand.split())
            break

    published, source = '', ''
    for o in ld:
        if isinstance(o.get('datePublished'), str) and o['datePublished'].strip():
            published, source = o['datePublished'].strip(), 'jsonld'
            break
    if not published:
        dd = [d for d in doc.xpath(DATE_META) if d and d.strip()]
        if dd:
            published, source = dd[0].strip(), 'meta'
    if not published:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', page)
        if m:
            published, source = m.group(1), 'inline_json'
    if not published:
        m = re.search(r'(?:입력|등록|승인|게재|기사입력)\s*[:：]?\s*(20\d{2}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2})', body)
        if m:
            published, source = m.group(1), 'body_text'
    if not published and find_date is not None:
        try:
            d = find_date(page, original_date=True, extensive_search=False, outputformat='%Y-%m-%d')
        except Exception:
            d = None
        if d:
            published, source = d, 'htmldate'

    return {'title': title, 'body': body, 'published_at': published, 'date_source': source, 'extractor': extractor,
            'xpath': cands.get('_xpath', '') if extractor.startswith('selector') else '',
            'candidates': {k: len(v) for k, v in cands.items() if not k.startswith('_')}}
