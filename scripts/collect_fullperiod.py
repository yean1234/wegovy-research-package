"""Full-period news collection for the four priority bundles (replaces the per-paper windows).

Why: the paper group grows from 11 to 40-80 papers, so the union of the per-paper 90-day windows covers
almost the whole period anyway, and the article-paper link is reported as a limitation (professor's
feedback, 2026-11-17). Articles are therefore collected over one period, START..today, and the 90-day
window survives only as a sensitivity analysis (label_articles.py still computes it).

Path per query (collect_news.GROUPS, unchanged):
  1. Naver Search API, sort=date, up to the API's 1000-result limit   -> collection_path 'naver_api'
     (official route; the key is read from .env, see README §8-9).
  2. Only when the API hits the 1000 limit before START, and only with --web-fallback: the part of the
     period the API could not reach is cut into QUARTER-length slices and each slice is queried on the
     Naver web search with that date range                             -> 'naver_web_daterange'
     The web search is not an official interface; rows that came only from it are marked so a
     sensitivity analysis can drop them.
Without an API key the script stops, unless --web-only is given (pilot behaviour, not recommended).

Output: scripts/news_candidates_fullperiod.json (same row layout as window_candidates.json) and
scripts/fullperiod_search_log.json (every query, slice, path, row count, and whether START was reached).
"""
import datetime, email.utils, json, pathlib, sys

from collect_news import GROUPS
from collect_windows import PRIORITY, api_window, env, web_window

ROOT = pathlib.Path(__file__).parent
START = datetime.date(2021, 1, 1)     # same start as the pilot (README §3)
SLICE_DAYS = 92


def slices(start, end, days=SLICE_DAYS):
    """[start, end] cut into consecutive closed intervals of at most `days` days."""
    out, s = [], start
    while s <= end:
        e = min(s + datetime.timedelta(days=days - 1), end)
        out.append((s, e))
        s = e + datetime.timedelta(days=1)
    return out


def oldest_api_date(rows):
    ds = [email.utils.parsedate_to_datetime(r['api_pubDate']).date() for r in rows if r.get('api_pubDate')]
    return min(ds) if ds else None


def collect(groups=PRIORITY, start=START, end=None, keys=None, web_fallback=False, web_only=False, api=api_window, web=web_window, log=print):
    end = end or datetime.date.today()
    keys = keys or {}
    by, journal = {}, []

    def add(r, g, q, path, win, why=''):
        x = by.setdefault(r['canonical_url'], {**r, 'candidate_groups': [], 'queries': [], 'collection_paths': [], 'query_windows': []})
        for f, v in (('candidate_groups', g), ('queries', q), ('collection_paths', path), ('query_windows', win)):
            if v not in x[f]:
                x[f].append(v)
        if why:
            x['web_fallback_reason'] = why

    for g in groups:
        for q in GROUPS[g]:
            uncovered_until = end      # the web path has to cover start..uncovered_until
            why = 'web_only_requested'
            if not web_only:
                rows, reached = api(q, start, end, keys)
                for r in rows:
                    add(r, g, q, 'naver_api', f'{start}~{end}')
                oldest = oldest_api_date(rows)
                journal.append({'group': g, 'query': q, 'window': f'{start}~{end}', 'path': 'naver_api', 'rows': len(rows),
                                'reached_period_start': reached, 'oldest_api_date': str(oldest) if oldest else None})
                log(g, q, 'API', len(rows), 'reached start' if reached else f'CAP (oldest {oldest})')
                if reached:
                    continue
                why = 'api_1000_cap_before_period_start'
                uncovered_until = oldest or end
                if not web_fallback:
                    continue
            for s, e in slices(start, uncovered_until):
                rows, pages = web(q, s, e)
                for r in rows:
                    add(r, g, q, 'naver_web_daterange', f'{s}~{e}', why)
                journal.append({'group': g, 'query': q, 'window': f'{s}~{e}', 'path': 'naver_web_daterange', 'reason': why, 'rows': len(rows), 'pages': pages})
                log(g, q, f'{s}~{e}', 'WEB', len(rows), 'pages', pages)
    return list(by.values()), journal


if __name__ == '__main__':
    args = set(sys.argv[1:])
    keys = env()
    if not keys.get('NAVER_CLIENT_ID') and '--web-only' not in args:
        sys.exit('NAVER_CLIENT_ID / NAVER_CLIENT_SECRET not found in .env. Add the key (README §8-9), or pass --web-only.')
    rows, journal = collect(keys=keys, web_fallback='--web-fallback' in args, web_only='--web-only' in args)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (ROOT / 'fullperiod_search_log.json').write_text(json.dumps({'period_start': str(START), 'run_at': stamp, 'args': sorted(args), 'log': journal}, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'news_candidates_fullperiod.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    capped = [j for j in journal if j['path'] == 'naver_api' and not j['reached_period_start']]
    print('UNIQUE', len(rows), '| queries capped by the API:', len(capped))
    for j in capped:
        print('  capped:', j['group'], j['query'], 'oldest reachable date', j['oldest_api_date'])
