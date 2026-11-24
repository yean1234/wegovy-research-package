"""Paper group v2: search, automatic screening and the human-screening shortlist (2026-11-24).

Why: 11 main papers (2-3 per bundle) are too few to be called a group (professor's feedback, 2026-11-17).
Target: 10-20 papers per bundle after human screening, for the four priority bundles.

Inclusion rule (fixed before looking at the abstracts' wording about certainty):
  "the abstract names semaglutide and the study measured the bundle's adverse event as an outcome".
People decide that for every record they are shown; the computer never decides it. Sources for each step
are in docs/paper_selection_sources.md.

  1. Search (Europe PMC, MEDLINE records with an abstract, first published START..today):
       title/abstract contains semaglutide (or a brand name) AND a bundle term.
  2. Marked ineligible by automation, with a count (the box of that name in the PRISMA 2020 flow diagram):
       only records whose NLM publication type is not a study report: editorial, comment, news, erratum,
       retraction, or a review not indexed/titled as a systematic review or meta-analysis.
       Letters stay in (research letters report original data).
  3. Everything else is the screening pool. Two content checks are computed but exclude nothing
     (Cochrane Handbook 4.6.3: be over-inclusive at the title/abstract stage; O'Mara-Eves et al. 2015:
     automatic elimination is not yet proven, using text mining to prioritise is safe):
       auto_outcome_reported    the bundle term is in the title or outside the background sections
       auto_semaglutide_focus   semaglutide is in the title or named at least twice in the abstract
     priority = 'high' when both hold, else 'low'.
  4. Who people screen: every record of the pool when it has at most CAP records (census); otherwise a
     seeded stratified random sample, HIGH_N from the high stratum and CAP - HIGH_N from the low stratum.
     The main papers of the first analysis (paper_dates.json) are a certainty stratum inside 'high'.
     Because low-priority records are screened too, the human decisions show how often the two checks
     would have been wrong (summarize_paper_screening.py). CAP and HIGH_N are workload decisions of the
     team, not values from the literature; a systematic review would screen the whole pool.
  5. People answer factual questions per record on the validation site (eligibility, role, and for
     unstructured abstracts where the background sentences end).

Usage
  python collect_papers_v2.py                    search, screen, draw the shortlist (changes as Europe PMC grows)
  python collect_papers_v2.py --abstracts-only   fetch the abstracts of the committed list again, nothing else

Outputs
  paper_screening_v2.json      committed: ids, title, journal, dates, flags, shortlist (no abstracts)
  paper_flow_v2.json           committed: counts per step and bundle
  scripts/papers_v2_internal.json   NOT committed: the abstracts (publisher copyright), for the site and the analysis
"""
import datetime, json, pathlib, random, re, sys, time, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).parent
REPO = ROOT.parent
START = '2021-01-01'
SEED = 20261124
CAP = 25          # records per bundle that people screen (team workload decision, not from the literature)
HIGH_N = 20       # of which from the high-priority stratum; the remaining CAP - HIGH_N come from the low-priority stratum
DRUG_Q = 'semaglutide OR Wegovy OR Ozempic OR Rybelsus'
DRUG_RE = r'semaglutide|wegovy|ozempic|rybelsus'
GROUPS = {   # search terms (Europe PMC syntax) and the regex used on title/abstract
    'NAION': ('NAION OR "ischemic optic neuropathy" OR "ischaemic optic neuropathy"', r'NAION|isch(?:a)?emic optic neuropath'),
    # The bundle is gastroparesis itself (README §2: delayed gastric emptying is a mechanism/measurement, not a synonym),
    # matching the news-side pattern in label_articles.TOPIC, so "gastric emptying" is not a search term.
    'GASTROPARESIS': ('gastroparesis OR "gastric paralysis"', r'gastropare|gastric paralysis'),
    'PANCREATITIS': ('pancreatitis', r'pancreatitis'),
    'SUICIDALITY': ('suicid*', r'suicid'),
}
# NLM publication types that are not study reports. "Letter" is NOT here: research letters carry original data.
NOT_STUDY = {'editorial', 'comment', 'news', 'published erratum', 'retraction of publication', 'retracted publication',
             'expression of concern', 'biography', 'interview', 'patient education handout', 'video-audio media'}
SYNTH_RE = r'systematic review|meta-analys|metaanalys|pooled analysis|network meta'
RESULT_LABEL = r'^(results?|findings|conclusions?(?: and relevance)?|interpretation|discussion|main outcomes? and measures?|outcomes?)\b'
BACKGROUND_LABEL = r'^(background|importance|introduction|objectives?|aims?|purpose|context|rationale)\b'


def epmc(query, page_size=100, sleep=0.3):
    """All results of a Europe PMC query (cursorMark paging)."""
    out, cursor = [], '*'
    while True:
        url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urllib.parse.urlencode(
            {'query': query, 'format': 'json', 'resultType': 'core', 'pageSize': page_size, 'cursorMark': cursor})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = json.load(r)
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        rows = data.get('resultList', {}).get('result', [])
        out += rows
        nxt = data.get('nextCursorMark')
        if not rows or not nxt or nxt == cursor:
            return out, data.get('hitCount', len(out))
        cursor = nxt
        time.sleep(sleep)


def sections(abstract_html):
    """[(label, text)] from Europe PMC abstract markup (<h4>Label</h4>text). Unstructured -> [('', text)]."""
    parts = re.split(r'<h4>\s*(.*?)\s*</h4>', abstract_html or '')
    strip = lambda s: ' '.join(re.sub(r'<[^>]+>', ' ', s).split())
    if len(parts) == 1:
        return [('', strip(parts[0]))]
    out = [('', strip(parts[0]))] if strip(parts[0]) else []
    return out + [(strip(parts[i]).rstrip(':.'), strip(parts[i + 1])) for i in range(1, len(parts) - 1, 2)]


def result_part(secs):
    """Text where outcomes are reported. Structured: every section that is not background/objective (the
    authors' own labels). Unstructured: the whole abstract, because sentence roles cannot be told by
    position; people mark the background sentences of unstructured abstracts on the validation site."""
    if len(secs) > 1 or secs[0][0]:
        keep = [t for lab, t in secs if lab and not re.match(BACKGROUND_LABEL, lab, re.I)]
        return ' '.join(keep)
    return secs[0][1]


def screen(rec, group):
    """-> dict of flags, 'exclude' ('' when the record stays in the pool) and 'priority' ('high' / 'low').

    Only the publication type removes a record. The two content checks are predictions used to stratify
    the sample; a 'low' record can still be drawn and is judged by people like any other."""
    title = rec.get('title') or ''
    secs = sections(rec.get('abstractText'))
    abstract = ' '.join(t for _, t in secs)
    types = [t.lower() for t in rec.get('pubTypeList', {}).get('pubType', [])]
    pat = GROUPS[group][1]
    synth = bool(re.search(SYNTH_RE, title, re.I)) or any(t in ('systematic review', 'meta-analysis') for t in types)
    f = {
        'structured_abstract': len(secs) > 1 or bool(secs[0][0]),
        'drug_in_title': bool(re.search(DRUG_RE, title, re.I)),
        'drug_mentions_abstract': len(re.findall(DRUG_RE, abstract, re.I)),
        'outcome_in_title': bool(re.search(pat, title, re.I)),
        'outcome_in_results': bool(re.search(pat, result_part(secs), re.I)),
        'evidence_synthesis': synth,
        'pub_types': rec.get('pubTypeList', {}).get('pubType', []),
    }
    f['exclude'] = 'not_a_study' if (set(types) & NOT_STUDY or ('review' in types and not synth)) else ''
    f['auto_outcome_reported'] = f['outcome_in_title'] or f['outcome_in_results']
    f['auto_semaglutide_focus'] = f['drug_in_title'] or f['drug_mentions_abstract'] >= 2
    f['priority'] = 'high' if f['auto_outcome_reported'] and f['auto_semaglutide_focus'] else 'low'
    return f


def previous_main():
    return {p['pmid'] for p in json.loads((REPO / 'paper_dates.json').read_text(encoding='utf-8')) if p['selection_role'] == 'main' and p['side_effect'] in GROUPS}


def draw(pool, rng, keep, cap=None, high_n=None):
    """Which records of one bundle people screen. -> (set of pmids, description of the draw).

    pool <= cap: all of them (census). Otherwise a stratified random sample: high_n from the high-priority
    stratum (the first-analysis main papers first, as a certainty stratum) and cap - high_n from the
    low-priority stratum; slots a stratum cannot fill go to the other one."""
    cap = CAP if cap is None else cap
    high_n = HIGH_N if high_n is None else high_n
    pool = sorted(pool, key=lambda x: x['pmid'])
    rng.shuffle(pool)
    if len(pool) <= cap:
        return {x['pmid'] for x in pool}, 'census'
    high = [x for x in pool if x['priority'] == 'high']
    low = [x for x in pool if x['priority'] == 'low']
    high = [x for x in high if x['pmid'] in keep] + [x for x in high if x['pmid'] not in keep]
    n_high = min(len(high), max(high_n, cap - len(low)))
    n_low = min(len(low), cap - n_high)
    return {x['pmid'] for x in high[:n_high] + low[:n_low]}, 'stratified random sample'


def run(today=None, fetch=epmc, log=print, keep=None):
    today = today or datetime.date.today().isoformat()
    rng = random.Random(SEED)
    keep = previous_main() if keep is None else keep
    screening, internal, flow = [], {}, {}
    for g, (terms, _) in GROUPS.items():
        q = f'TITLE_ABS:({DRUG_Q}) AND TITLE_ABS:({terms}) AND FIRST_PDATE:[{START} TO {today}] AND SRC:MED AND HAS_ABSTRACT:y'
        recs, hits = fetch(q)
        rows = []
        for r in recs:
            if not r.get('pmid') or not r.get('abstractText'):
                continue
            f = screen(r, g)
            rows.append({'pmid': r['pmid'], 'side_effect': g, 'title': (r.get('title') or '').rstrip('.'), 'journal_title': r.get('journalInfo', {}).get('journal', {}).get('title', ''),
                         'doi': r.get('doi', ''), 'first_publication_date': r.get('firstPublicationDate', ''), 'electronic_publication_date': r.get('electronicPublicationDate', ''),
                         'first_author': (r.get('authorList', {}).get('author') or [{}])[0].get('lastName', ''), **f})
            internal[f"{g}:{r['pmid']}"] = {'pmid': r['pmid'], 'side_effect': g, 'sections': sections(r['abstractText'])}
        pool = [x for x in rows if not x['exclude']]
        short, how = draw(pool, rng, keep)
        for x in rows:
            x['shortlist'] = x['pmid'] in short
            x['retained_from_first_analysis'] = x['pmid'] in keep
        strata = {}
        for p in ('high', 'low'):
            n_pool, n_drawn = sum(x['priority'] == p for x in pool), sum(x['priority'] == p and x['shortlist'] for x in pool)
            strata[p] = {'in_pool': n_pool, 'drawn': n_drawn, 'sampling_fraction': round(n_drawn / n_pool, 3) if n_pool else None}
        flow[g] = {'query': q, 'identified': hits, 'with_pmid_and_abstract': len(rows),
                   'marked_ineligible_by_automation': {'not_a_study_publication_type': sum(x['exclude'] == 'not_a_study' for x in rows)},
                   'screening_pool': len(pool), 'draw': how, 'strata': strata, 'screened_by_people': len(short),
                   'of_which_retained_from_first_analysis': sum(x['shortlist'] and x['retained_from_first_analysis'] for x in rows), 'cap': CAP}
        screening += rows
        log(g, 'identified', hits, '| not a study', flow[g]['marked_ineligible_by_automation']['not_a_study_publication_type'], '| pool', len(pool), strata, '|', how, len(short))
    meta = {'run_date': today, 'period_start': START, 'seed': SEED, 'source': 'Europe PMC REST search (SRC:MED, HAS_ABSTRACT:y)',
            'rule': 'abstract names semaglutide and reports the bundle adverse event as an outcome; see module docstring and docs/paper_selection_sources.md'}
    return {'meta': meta, 'flow': flow}, screening, internal


def abstracts_only(fetch=epmc):
    """Rebuild scripts/papers_v2_internal.json for the papers already listed in paper_screening_v2.json,
    without searching or sampling again (Europe PMC grows, so a new search would change the shortlist)."""
    screening = json.loads((REPO / 'paper_screening_v2.json').read_text(encoding='utf-8'))
    pmids = sorted({x['pmid'] for x in screening})
    found = {}
    for i in range(0, len(pmids), 40):
        recs, _ = fetch('SRC:MED AND EXT_ID:(' + ' OR '.join(pmids[i:i + 40]) + ')')
        found.update({r['pmid']: r for r in recs if r.get('pmid')})
    internal = {f"{x['side_effect']}:{x['pmid']}": {'pmid': x['pmid'], 'side_effect': x['side_effect'], 'sections': sections(found[x['pmid']].get('abstractText'))}
                for x in screening if x['pmid'] in found}
    (ROOT / 'papers_v2_internal.json').write_text(json.dumps(internal, ensure_ascii=False, indent=1), encoding='utf-8')
    print('abstracts', len(internal), 'of', len(screening), 'screened records')


if __name__ == '__main__':
    if '--abstracts-only' in sys.argv:
        abstracts_only()
        sys.exit()
    summary, screening, internal = run(sys.argv[1] if len(sys.argv) > 1 else None)
    (REPO / 'paper_flow_v2.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    (REPO / 'paper_screening_v2.json').write_text(json.dumps(screening, ensure_ascii=False, indent=1), encoding='utf-8')
    (ROOT / 'papers_v2_internal.json').write_text(json.dumps(internal, ensure_ascii=False, indent=1), encoding='utf-8')
    old = previous_main()
    by = {x['pmid']: x for x in screening}
    print('previous 11 main papers:', {pm: ('shortlist' if by[pm]['shortlist'] else (by[pm]['exclude'] or 'passed, not sampled')) if pm in by else 'not found by search' for pm in sorted(old)})
