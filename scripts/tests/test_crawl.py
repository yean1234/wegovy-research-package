"""Offline tests for the v2 crawler: no network. Run:  python -m pytest scripts/tests -q"""
import datetime, json, pathlib, sys, urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import crawl_common as cc
import extract_article as ea
from collect_news import canon

REPO = pathlib.Path(__file__).resolve().parents[2]

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta property="og:title" content="위고비, 시신경 질환 위험 연관성 관찰">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle","headline":"위고비 헤드라인","datePublished":"2024-07-04T09:10:00+09:00"}</script>
<title>사이트명 - 위고비</title></head><body>
<nav><a>정치</a><a>경제</a><a>로그인</a></nav>
<div id="article-view-content-div">
<p>미국 하버드대 연구팀이 비만 치료제 위고비(성분명 세마글루타이드)를 처방받은 환자에서 비동맥염성 앞허혈시신경병증 발생이 더 많았다는 관찰연구 결과를 국제학술지에 발표했다.</p>
<figure><img src="a.jpg"><figcaption>사진=게티이미지</figcaption></figure>
<p>연구팀은 2017년부터 2023년까지 신경안과 진료를 받은 환자 1만6827명의 기록을 분석했다. 그 결과 세마글루타이드 처방군에서 해당 질환의 위험비가 높게 나타났다고 밝혔다.</p>
<p>다만 연구팀은 이번 연구가 관찰연구여서 인과관계를 입증한 것은 아니며, 추가 연구가 필요하다고 설명했다. 전문가들은 환자가 임의로 약을 끊어서는 안 된다고 조언했다.</p>
<p>국내에서는 위고비가 2024년 10월 출시됐다. 식품의약품안전처는 허가 범위 안에서 의사의 처방에 따라 사용해야 한다고 당부했다. 이 약은 체질량지수 기준을 충족하는 성인 비만 환자에게 쓰인다.</p>
</div>
<aside><h3>많이 본 뉴스</h3><ul><li>연예인 A씨 근황</li><li>오늘의 날씨</li></ul></aside>
<footer>무단 전재 및 재배포 금지 ⓒ 사이트명</footer></body></html>"""


def test_extract_takes_article_not_page_furniture():
    r = ea.extract(PAGE, 'https://example.com/news/1')
    assert r['extractor'] in ('selector_id', 'trafilatura')
    assert '하버드대 연구팀' in r['body'] and '추가 연구가 필요' in r['body']
    for junk in ('많이 본 뉴스', '로그인', '무단 전재', '게티이미지'):
        assert junk not in r['body']
    assert r['title'] == '위고비, 시신경 질환 위험 연관성 관찰'          # og:title wins over <title>
    assert r['published_at'].startswith('2024-07-04') and r['date_source'] == 'jsonld'


def test_extract_falls_back_and_flags_when_no_article_container():
    page = '<html><body><div>' + '위고비 관련 안내문입니다. ' * 40 + '</div></body></html>'
    r = ea.extract(page)
    assert r['extractor'] in ('body_fallback', 'trafilatura')


def test_decode_handles_cp949_without_header():
    text = '<html><head></head><body>위고비 췌장염 연구 결과</body></html>'
    out, cs = cc.decode(text.encode('cp949'), None)
    assert '췌장염' in out and cs == 'cp949'
    out, cs = cc.decode(text.replace('<head>', '<head><meta charset="euc-kr">').encode('euc-kr'), None)
    assert '췌장염' in out and cs == 'euc-kr'
    assert cc.decode(text.encode('utf-8'), 'utf-8')[1] == 'utf-8'


def _robots(text, status=200):
    return cc.Robots(fetcher=lambda url, retries=2: cc.FetchResult(status, url, text.encode()))


def test_robots_rules_and_crawl_delay():
    rb = _robots('User-agent: *\nCrawl-delay: 10\nDisallow: /search/\n\nUser-agent: ClaudeBot\nDisallow: /\n')
    ok = rb.check('https://x.kr/news/1')
    assert ok['allowed'] and ok['crawl_delay'] == 10.0 and ok['ai_blocked']
    assert not rb.check('https://x.kr/search/?q=1')['allowed']
    assert _robots('User-agent: *\nCrawl-delay: 120\n').check('https://y.kr/a')['crawl_delay'] == cc.MAX_DELAY   # capped


def test_robots_missing_allows_unreachable_blocks_html_page_ignored():
    assert _robots('', 404).check('https://a.kr/n/1')['allowed']
    assert not _robots('', 503).check('https://b.kr/n/1')['allowed']
    assert _robots('<!DOCTYPE html><html><body>Just a moment...</body></html>').check('https://c.kr/n/1')['allowed']


def test_respect_ai_rules_flag(monkeypatch):
    monkeypatch.setattr(cc, 'RESPECT_AI_RULES', True)
    r = _robots('User-agent: anthropic-ai\nDisallow: /\n').check('https://d.kr/n/1')
    assert not r['allowed'] and r['reason'] == 'robots_disallow_ai'


def test_throttle_spaces_requests_per_host():
    now, slept = [0.0], []
    th = cc.Throttle(clock=lambda: now[0], sleep=lambda s: (slept.append(round(s, 3)), now.__setitem__(0, now[0] + s)))
    th.wait('a.kr', 1.0); th.wait('a.kr', 1.0); th.wait('b.kr', 1.0); th.wait('a.kr', 10.0)
    assert slept == [1.0, 10.0]          # second a.kr waits 1 s, b.kr does not wait, third a.kr waits its crawl-delay


def test_fetch_retries_then_succeeds_and_gives_up_on_404():
    calls = []
    def flaky(url, headers):
        calls.append(url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(url, 503, 'busy', {}, None)
        return 200, url, b'ok', 'utf-8', {}
    quiet = cc.Throttle(sleep=lambda s: None)
    r = cc.fetch('http://e.kr/1', opener=flaky, throttle=quiet, sleep=lambda s: None)
    assert r.ok and r.attempts == 3 and calls[0].startswith('https://')
    def gone(url, headers):
        raise urllib.error.HTTPError(url, 404, 'nf', {}, None)
    r = cc.fetch('https://e.kr/2', opener=gone, throttle=quiet, sleep=lambda s: None)
    assert r.status == 404 and r.attempts == 1


def test_article_ids_match_the_ids_already_in_the_repo():
    """The id is sha1(canonical_url of the search candidate): every labelled article must be reproducible from the candidate list."""
    cands = json.loads((REPO / 'scripts' / 'news_candidates_all.json').read_text(encoding='utf-8'))
    ids = {cc.article_id(c['canonical_url']) for c in cands}
    assert all(c['canonical_url'] == canon(c['url']) for c in cands[:300])
    labelled = json.loads((REPO / 'scripts' / 'article_labels_internal.json').read_text(encoding='utf-8'))
    missing = {r['article_id'] for r in labelled} - ids
    assert len(missing) <= 1          # A4aaa27697b28: labelled on 2026-10-29 but absent from the committed candidate list


def test_fullperiod_slices_and_api_cap_fallback():
    import collect_fullperiod as cf
    d = datetime.date
    sl = cf.slices(d(2021, 1, 1), d(2021, 12, 31))
    assert sl[0][0] == d(2021, 1, 1) and sl[-1][1] == d(2021, 12, 31)
    assert all(a[1] + datetime.timedelta(days=1) == b[0] for a, b in zip(sl, sl[1:]))
    row = lambda u, dt: {'url': u, 'canonical_url': u, 'title': 't', 'api_pubDate': dt}
    def api(q, s, e, keys):   # first query is capped at 2024-03-01, the others reach the start
        if q == cf.GROUPS['NAION'][0]:
            return [row('https://a/1', 'Fri, 01 Mar 2024 10:00:00 +0900')], False
        return [row('https://a/2', 'Mon, 04 Jan 2021 10:00:00 +0900')], True
    web_calls = []
    def web(q, s, e):
        web_calls.append((q, s, e))
        return [{'url': 'https://a/1', 'canonical_url': 'https://a/1', 'title': 't'}], 1
    rows, log = cf.collect(groups=['NAION'], end=d(2026, 11, 24), keys={'NAVER_CLIENT_ID': 'x'}, web_fallback=True, api=api, web=web, log=lambda *a: None)
    assert {q for q, _, _ in web_calls} == {cf.GROUPS['NAION'][0]}                 # only the capped query uses the web
    assert web_calls[0][1] == cf.START and web_calls[-1][2] == d(2024, 3, 1)       # and only for the part the API missed
    merged = next(r for r in rows if r['canonical_url'] == 'https://a/1')
    assert merged['collection_paths'] == ['naver_api', 'naver_web_daterange'] and merged['web_fallback_reason']
    rows2, _ = cf.collect(groups=['NAION'], end=d(2026, 11, 24), keys={'NAVER_CLIENT_ID': 'x'}, web_fallback=False, api=api, web=web, log=lambda *a: None)
    assert all(r['collection_paths'] == ['naver_api'] for r in rows2)
