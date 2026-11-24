"""Human paper screening -> the final paper list, and a check of the two automatic content checks.

Usage: python summarize_paper_screening.py validation/validation_codes_round3.csv

Input: the CSV exported from the round-3 validation site (task 'P' rows: derived_eligible, derived_role, q_bg).
Final answer per (paper, bundle): the answer every coder gave, or the majority; a tie is left out of the
list and printed, so the team settles it and adds it by hand. A record seen by one coder takes that answer.

Outputs
  validation/final_papers.json       eligible papers: pmid, side_effect, role, background_sentences
                                     (-> translate_abstracts.py --include, analyze_rq.py)
  paper_screening_validation.json    committed: per bundle the counts of the flow diagram's last steps, and
                                     how the automatic priority compared with the human decision

Why the second file: collect_papers_v2.py does not let the computer exclude on content, because automatic
elimination is not yet proven (O'Mara-Eves et al. 2015) and records marked ineligible by a tool have to be
reported (PRISMA 2020 flow diagram). It only stratifies. With people screening both strata we can report
what share of the low-priority records were eligible after all, i.e. what an automatic cut would have lost.
"""
import collections, csv, json, math, pathlib, statistics, sys

ROOT = pathlib.Path(__file__).parent
REPO = ROOT.parent


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 3), round(min(1, c + h), 3)]


def read_codes(path):
    votes = collections.defaultdict(list)
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r.get('task') == 'P' and r.get('derived_eligible') in ('yes', 'no'):
                bg = r.get('q_bg', '')
                votes[(r['pmid_or_article_id'], r['group'])].append({'elig': r['derived_eligible'], 'role': r.get('derived_role', ''), 'bg': int(bg) if bg.isdigit() else None})
    return votes


def decide(vs):
    """-> (eligible 'yes'/'no'/None for a tie, role, background_sentences)."""
    c = collections.Counter(v['elig'] for v in vs)
    if c['yes'] == c['no']:
        return None, '', None
    elig = 'yes' if c['yes'] > c['no'] else 'no'
    if elig == 'no':
        return 'no', 'none', None
    roles = collections.Counter(v['role'] for v in vs if v['elig'] == 'yes')
    role = 'main' if roles['main'] > roles['background'] else ('background' if roles['background'] > roles['main'] else 'undecided')
    bgs = [v['bg'] for v in vs if v['elig'] == 'yes' and v['bg'] is not None]
    return 'yes', role, (int(statistics.median_low(bgs)) if bgs else None)


def summarize(votes, screening):
    by = {(x['pmid'], x['side_effect']): x for x in screening}
    final, ties, report = [], [], {}
    for (pmid, g), vs in sorted(votes.items()):
        elig, role, bg = decide(vs)
        x = by.get((pmid, g), {})
        rep = report.setdefault(g, {'screened': 0, 'eligible': 0, 'main': 0, 'background': 0, 'role_undecided': 0, 'not_eligible': 0, 'tied': 0,
                                    'by_priority': {'high': {'screened': 0, 'eligible': 0}, 'low': {'screened': 0, 'eligible': 0}}})
        rep['screened'] += 1
        if elig is None:
            rep['tied'] += 1
            ties.append((pmid, g))
            continue
        pr = rep['by_priority'].get(x.get('priority', ''), None)
        if pr is not None:
            pr['screened'] += 1
            pr['eligible'] += elig == 'yes'
        if elig == 'no':
            rep['not_eligible'] += 1
            continue
        rep['eligible'] += 1
        rep[{'main': 'main', 'background': 'background'}.get(role, 'role_undecided')] += 1
        final.append({'pmid': pmid, 'side_effect': g, 'role': role, 'background_sentences': bg, 'coders': len(vs),
                      'priority': x.get('priority', ''), 'retained_from_first_analysis': x.get('retained_from_first_analysis', False)})
    tot = {'high': [0, 0], 'low': [0, 0]}
    for rep in report.values():
        for p, v in rep['by_priority'].items():
            v['eligible_share'] = round(v['eligible'] / v['screened'], 3) if v['screened'] else None
            tot[p][0] += v['eligible']; tot[p][1] += v['screened']
    report['ALL'] = {'by_priority': {p: {'screened': n, 'eligible': k, 'eligible_share': round(k / n, 3) if n else None, 'ci95_wilson': wilson(k, n)} for p, (k, n) in tot.items()},
                     'reading': 'eligible share in "low" = what an automatic exclusion on the two content checks would have lost among the records people saw'}
    return final, ties, report


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('usage: python summarize_paper_screening.py <validation_codes_round3.csv>')
    screening = json.loads((REPO / 'paper_screening_v2.json').read_text(encoding='utf-8'))
    final, ties, report = summarize(read_codes(sys.argv[1]), screening)
    (REPO / 'validation').mkdir(exist_ok=True)
    (REPO / 'validation' / 'final_papers.json').write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding='utf-8')
    (REPO / 'paper_screening_validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    for g, v in report.items():
        print(g, json.dumps(v, ensure_ascii=False))
    print('eligible papers', len(final), '| main', sum(x['role'] == 'main' for x in final), '| ties to settle by hand', ties)
