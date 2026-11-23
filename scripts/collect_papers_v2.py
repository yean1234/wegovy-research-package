"""Paper group v2: search, automatic screening and the human-screening shortlist (2026-11-24).

Why: 11 main papers (2-3 per bundle) are too few to be called a group (professor's feedback, 2026-11-17).
Target: 10-20 papers per bundle after human screening, for the four priority bundles.

Inclusion rule (fixed before looking at the abstracts' wording about certainty):
  "the abstract names semaglutide and the study measured the bundle's adverse event as an outcome".
The computer can only approximate that rule, so it works in two steps and a person confirms every paper.

  1. Search (Europe PMC, MEDLINE records with an abstract, first published START..today):
       title/abstract contains semaglutide (or a brand name) AND a bundle term.
  2. Automatic exclusion, each with a count (flow diagram, paper_flow_v2.json):
       a. publication type is not a study: editorial, comment, letter, news, erratum, retraction,
          or a review that is not a systematic review / meta-analysis        -> 'not_a_study'
       b. the bundle term is absent from the title AND absent from the results/conclusion part
          of the abstract (it is only background)                              -> 'outcome_not_reported'
       c. semaglutide is absent from the title AND named fewer than twice in the abstract
          (a class-level paper that mentions it in passing)                    -> 'semaglutide_in_passing'
  3. Shortlist for human screening: every remaining paper, or, when a bundle has more than CAP, the main
     papers of the first analysis (paper_dates.json, already human-checked) plus a seeded random sample
     of the rest up to CAP (so the new choices do not depend on what the abstracts say).
     People then answer three factual questions per paper on the validation site (eligibility and role).

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
CAP = 25
DRUG_Q = 'semaglutide OR Wegovy OR Ozempic OR Rybelsus'
DRUG_RE = r'semaglutide|wegovy|ozempic|rybelsus'
GROUPS = {   # search terms (Europe PMC syntax) and the regex used on title/abstract
    'NAION': ('NAION OR "ischemic optic neuropathy" OR "ischaemic optic neuropathy"', r'NAION|isch(?:a)?emic optic neuropath'),
    # The search also retrieves "gastric emptying" papers so the flow diagram shows how many there are, but the bundle is
    # gastroparesis itself (README §2: delayed gastric emptying is a mechanism/measurement, not a synonym), matching the
    # news-side pattern in label_articles.TOPIC. Emptying-only papers leave at step 2b.
    'GASTROPARESIS': ('gastroparesis OR "gastric paralysis" OR "gastric emptying"', r'gastropare|gastric paralysis'),
    'PANCREATITIS': ('pancreatitis', r'pancreatitis'),
    'SUICIDALITY': ('suicid*', r'suicid'),
}
NOT_STUDY = {'editorial', 'comment', 'letter', 'news', 'published erratum', 'retraction of publication', 'retracted publication',
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
    """Text where outcomes are reported. Structured: every section that is not background/objective.
    Unstructured: everything after the first sentence (the first sentence is normally the background)."""
    if len(secs) > 1 or secs[0][0]:
        keep = [t for lab, t in secs if lab and not re.match(BACKGROUND_LABEL, lab, re.I)]
        return ' '.join(keep)
    sents = re.split(r'(?<=[.!?])\s+(?=[A-Z])', secs[0][1])
    return ' '.join(sents[1:]) if len(sents) > 1 else secs[0][1]


def screen(rec, group):
    """-> dict of flags + 'exclude' ('' when the paper stays in)."""
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
    if set(types) & NOT_STUDY or ('review' in types and not synth) or (re.search(r'\breview\b', title, re.I) and not synth and 'case' not in title.lower()):
        f['exclude'] = 'not_a_study'
    elif not (f['outcome_in_title'] or f['outcome_in_results']):
        f['exclude'] = 'outcome_not_reported'
    elif not f['drug_in_title'] and f['drug_mentions_abstract'] < 2:
        f['exclude'] = 'semaglutide_in_passing'
    else:
        f['exclude'] = ''
    return f


def previous_main():
    return {p['pmid'] for p in json.loads((REPO / 'paper_dates.json').read_text(encoding='utf-8')) if p['selection_role'] == 'main' and p['side_effect'] in GROUPS}


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
        kept = sorted([x for x in rows if not x['exclude']], key=lambda x: x['pmid'])
        rng.shuffle(kept)
        retained = [x for x in kept if x['pmid'] in keep]
        short = {x['pmid'] for x in (retained + [x for x in kept if x['pmid'] not in keep])[:CAP]}
        for x in rows:
            x['shortlist'] = x['pmid'] in short
            x['retained_from_first_analysis'] = x['pmid'] in keep
        flow[g] = {'query': q, 'identified': hits, 'with_pmid_and_abstract': len(rows),
                   'excluded': {k: sum(x['exclude'] == k for x in rows) for k in ('not_a_study', 'outcome_not_reported', 'semaglutide_in_passing')},
                   'passed_auto_screen': len(kept), 'shortlist_for_human_screening': len(short), 'of_which_retained_from_first_analysis': len(retained), 'cap': CAP}
        screening += rows
        log(g, flow[g]['identified'], '->', len(rows), flow[g]['excluded'], '->', len(kept), '-> shortlist', len(short))
    meta = {'run_date': today, 'period_start': START, 'seed': SEED, 'source': 'Europe PMC REST search (SRC:MED, HAS_ABSTRACT:y)',
            'rule': 'abstract names semaglutide and reports the bundle adverse event as an outcome; see module docstring'}
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
