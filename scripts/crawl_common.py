"""Shared HTTP layer for the news crawler (v2, 2026-11-24).

Why this file exists: the pilot scripts (collect_news.py, scrape_news.py) fetched pages with a bare
urllib call from 6 threads: no robots.txt check, no delay between requests to the same site, no retry,
and a single charset guess. Each of those is fixed here, in one place, so every script behaves the same.

  1. robots.txt   Robots.allowed(url) is checked before every publisher request (RFC 9309: a missing
                  robots.txt, i.e. 4xx, means "allowed"; an unreachable one, 5xx, means "disallowed").
  2. politeness   one request per host at a time, MIN_DELAY seconds apart, or the site's own
                  Crawl-delay if it is longer (capped at MAX_DELAY so one slow site cannot stall a run).
  3. retries      429 / 5xx / timeouts are retried with exponential backoff; Retry-After is honoured.
  4. charset      HTTP header -> <meta charset> -> strict UTF-8 -> CP949 (older Korean outlets).
  5. raw cache    the fetched HTML is kept (gzip) under scripts/raw_html/ so the body can be extracted
                  again later without a second request. raw_html/ is not redistributed.

Nothing here knows about Wegovy; the study-specific logic stays in the collect_* / scrape_* scripts.
"""
import gzip, hashlib, os, pathlib, re, threading, time, urllib.error, urllib.parse, urllib.request, urllib.robotparser

ROOT = pathlib.Path(__file__).parent
RAW_HTML = ROOT / 'raw_html'

# A generic research user agent. Set CRAWL_CONTACT (e.g. a team e-mail) to append contact details.
UA_TOKEN = 'AcademicResearchCrawler'
USER_AGENT = f'Mozilla/5.0 (compatible; {UA_TOKEN}/2.0' + (f'; {os.environ["CRAWL_CONTACT"]}' if os.environ.get('CRAWL_CONTACT') else '') + ')'
# Robots groups that address AI agents. When the crawl is run by an AI assistant (RESPECT_AI_RULES=1),
# a site that disallows any of these is skipped, even if the generic group allows the page.
AI_TOKENS = ('ClaudeBot', 'Claude-Web', 'anthropic-ai', 'GPTBot', 'CCBot')
RESPECT_AI_RULES = os.environ.get('RESPECT_AI_RULES') == '1'

MIN_DELAY = 1.0     # seconds between two requests to the same host
MAX_DELAY = 10.0    # upper bound applied to a site's Crawl-delay
TIMEOUT = 25
MAX_BYTES = 4_000_000
RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchResult:
    __slots__ = ('status', 'url', 'data', 'charset', 'error', 'attempts')

    def __init__(self, status=0, url='', data=b'', charset=None, error='', attempts=0):
        self.status, self.url, self.data, self.charset, self.error, self.attempts = status, url, data, charset, error, attempts

    @property
    def ok(self):
        return self.status == 200 and bool(self.data)


class Throttle:
    """Serialises requests per host and keeps them `delay` seconds apart."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self._clock, self._sleep = clock, sleep
        self._locks, self._last, self._guard = {}, {}, threading.Lock()

    def wait(self, host, delay=MIN_DELAY):
        with self._guard:
            lock = self._locks.setdefault(host, threading.Lock())
        with lock:
            gap = self._last.get(host, -1e9) + delay - self._clock()
            if gap > 0:
                self._sleep(gap)
            self._last[host] = self._clock()


THROTTLE = Throttle()


def _open(url, headers=None):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Language': 'ko,en;q=0.8', **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.url, r.read(MAX_BYTES), r.headers.get_content_charset(), r.headers


def fetch(url, delay=MIN_DELAY, retries=3, headers=None, opener=_open, throttle=None, sleep=time.sleep):
    """GET `url` politely. Never raises: failures come back as FetchResult(status, error)."""
    throttle = throttle or THROTTLE
    url = 'https:' + url[5:] if url.startswith('http:') else url
    host = urllib.parse.urlsplit(url).netloc.lower()
    last = FetchResult(url=url)
    for attempt in range(1, retries + 1):
        throttle.wait(host, delay)
        try:
            status, final, data, charset, _ = opener(url, headers)
            return FetchResult(status, final, data, charset, attempts=attempt)
        except urllib.error.HTTPError as e:
            last = FetchResult(e.code, url, error=f'http_{e.code}', attempts=attempt)
            if e.code not in RETRY_STATUS:
                return last
            wait = e.headers.get('Retry-After') if e.headers else None
            sleep(min(float(wait), 60) if wait and wait.isdigit() else 2 ** attempt)
        except Exception as e:  # timeout, DNS, TLS, connection reset
            last = FetchResult(0, url, error=f'{type(e).__name__}: {e}'[:200], attempts=attempt)
            sleep(2 ** attempt)
    return last


def decode(data, header_charset=None):
    """Bytes -> str. Returns (text, charset_used)."""
    tried = []
    m = re.search(br'<meta[^>]+charset\s*=\s*["\']?\s*([\w-]+)', data[:20000], re.I)
    for cs in (header_charset, m.group(1).decode('ascii', 'ignore') if m else None, 'utf-8', 'cp949'):
        if not cs or cs.lower() in tried:
            continue
        tried.append(cs.lower())
        try:
            return data.decode(cs), cs.lower()   # strict: a wrong guess must fail, not produce mojibake
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode(header_charset or 'utf-8', errors='replace'), (header_charset or 'utf-8').lower() + '+replace'


class Robots:
    """robots.txt cache, one entry per host."""

    def __init__(self, fetcher=fetch):
        self._fetch, self._cache, self._guard = fetcher, {}, threading.Lock()

    def _load(self, scheme, host):
        key = host
        with self._guard:
            if key in self._cache:
                return self._cache[key]
        r = self._fetch(f'{scheme}://{host}/robots.txt', retries=2)
        text, state = '', 'missing'
        if r.status == 200 and r.data:
            body, _ = decode(r.data, r.charset)
            # An HTML error or challenge page served with 200 is not a robots file.
            if not re.search(r'<\s*(html|!doctype)', body[:500], re.I):
                text, state = body, 'found'
        elif r.status >= 500 or r.status == 0:
            state = 'unreachable'
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(text.splitlines())
        entry = {'parser': rp, 'state': state, 'text': text}
        with self._guard:
            self._cache[key] = entry
        return entry

    def check(self, url):
        """-> dict(allowed, reason, crawl_delay, ai_blocked)."""
        p = urllib.parse.urlsplit(url)
        e = self._load(p.scheme or 'https', p.netloc.lower())
        if e['state'] == 'unreachable':
            return {'allowed': False, 'reason': 'robots_unreachable', 'crawl_delay': MIN_DELAY, 'ai_blocked': False}
        rp = e['parser']
        generic = rp.can_fetch(UA_TOKEN, url)
        ai_blocked = any(not rp.can_fetch(t, url) for t in AI_TOKENS) if e['state'] == 'found' else False
        delay = rp.crawl_delay(UA_TOKEN) or 0
        allowed = generic and not (RESPECT_AI_RULES and ai_blocked)
        reason = '' if allowed else ('robots_disallow' if not generic else 'robots_disallow_ai')
        return {'allowed': allowed, 'reason': reason, 'crawl_delay': min(max(float(delay), MIN_DELAY), MAX_DELAY), 'ai_blocked': ai_blocked}


ROBOTS = Robots()


def polite_get(url, robots=None, cache_key=None):
    """robots.txt check + throttled fetch + optional raw-HTML cache. -> (FetchResult, robots_info)."""
    robots = robots or ROBOTS
    info = robots.check(url)
    if not info['allowed']:
        return FetchResult(0, url, error=info['reason']), info
    if cache_key:
        cached = load_raw(cache_key)
        if cached is not None:
            return FetchResult(200, url, cached, None, attempts=0), info
    r = fetch(url, delay=info['crawl_delay'])
    if cache_key and r.ok:
        save_raw(cache_key, r.data)
    return r, info


def save_raw(key, data):
    RAW_HTML.mkdir(exist_ok=True)
    with gzip.open(RAW_HTML / f'{key}.html.gz', 'wb') as f:
        f.write(data)


def load_raw(key):
    p = RAW_HTML / f'{key}.html.gz'
    if not p.exists():
        return None
    with gzip.open(p, 'rb') as f:
        return f.read()


def article_id(canonical_url):
    """Same id scheme as scrape_news.py, so ids stay stable across pilot / window / full-period runs."""
    return 'A' + hashlib.sha1(canonical_url.encode()).hexdigest()[:12]
