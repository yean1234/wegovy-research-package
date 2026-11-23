"""Round-3 human-validation sample (criteria v3, 2026-11-24).

What changed since round 2 (see the Notion page "판정 기준 v3"):
  - papers: the expanded shortlist from collect_papers_v2.py (paper_screening_v2.json), not the old 23;
    coders answer three factual questions and the site derives eligibility / role from them;
  - articles: one unit = one article. Coders see the whole extracted body with the lead marked, answer
    "is this adverse event the main topic" once per bundle whose term occurs in the article, and decide
    "research report or not" in two steps. The five-way trigger question is gone (only the binary value
    is used in the analysis, and most round-1 disagreement was between two non-research categories);
  - to cut the workload, OVERLAP of the items are coded by every coder (reliability sample, Lombard,
    Snyder-Duch & Bracken 2002) and the rest are split between SLOTS coders.

Article pool. `--pilot` (default) draws PILOT_N articles from bodies already in scripts/raw_news/ and gives
them to every coder: this is the calibration round on the new criteria. `--main` draws the main sample
from the labelled pool: every article the computer passes (topic fit AND research report) plus REJECT_N
seeded random rejects (to estimate what the computer misses), excluding the pilot articles.

Output: validation/sample_round3.json (not redistributed: it contains article bodies and abstracts).
"""
import glob, json, math, pathlib, random, re, sys

from label_articles import TOPIC, paragraphs

ROOT = pathlib.Path(__file__).parent
REPO = ROOT.parent
OUT = REPO / 'validation'
SEED = 20261124
SLOTS = 3
OVERLAP = 0.30
PILOT_N, PILOT_PASS = 30, 18
REJECT_N = 45
GROUP_KO = {'NAION': '비동맥염성 앞허혈시신경병증(NAION)', 'GASTROPARESIS': '위마비', 'PANCREATITIS': '췌장염', 'SUICIDALITY': '자살사고·자살행동'}


def assign(items, rng, key):
    """Per stratum: the first OVERLAP share goes to every coder (0), the rest are dealt to slots 1..SLOTS."""
    strata = {}
    for it in items:
        strata.setdefault(key(it), []).append(it)
    for _, group in sorted(strata.items()):
        group.sort(key=lambda x: x['id'])
        rng.shuffle(group)
        n_all = math.ceil(len(group) * OVERLAP)
        for i, it in enumerate(group):
            it['assign'] = 0 if i < n_all else (i - n_all) % SLOTS + 1


def lead_paragraphs(paras):
    """Number of leading paragraphs that make up the lead: first 3 paragraphs or first 4 sentences, whichever ends first."""
    seen = 0
    for i, p in enumerate(paras[:3], 1):
        seen += len([s for s in re.split(r'(?<=[.?!])\s+', p) if s.strip()])
        if seen >= 4:
            return i
    return min(3, len(paras)) or 1


def paper_items(rng):
    screening = json.loads((REPO / 'paper_screening_v2.json').read_text(encoding='utf-8'))
    internal = json.loads((ROOT / 'papers_v2_internal.json').read_text(encoding='utf-8'))
    items = []
    for x in screening:
        if not x['shortlist']:
            continue
        g = x['side_effect']
        items.append({'id': f"P3-{g}-{x['pmid']}", 'pmid': x['pmid'], 'group': g, 'group_ko': GROUP_KO[g], 'title': x['title'], 'journal': x['journal_title'],
                      'date': x['first_publication_date'], 'url': 'https://doi.org/' + x['doi'] if x['doi'] else f"https://pubmed.ncbi.nlm.nih.gov/{x['pmid']}/",
                      'pub_types': x['pub_types'], 'sections': internal[f"{g}:{x['pmid']}"]['sections'],
                      'rule': {k: x[k] for k in ('drug_in_title', 'drug_mentions_abstract', 'outcome_in_title', 'outcome_in_results', 'evidence_synthesis', 'retained_from_first_analysis')}})
    assign(items, rng, lambda it: it['group'])
    return items


def article_pool():
    labels = {x['article_id']: x for x in json.loads((ROOT / 'article_labels_internal.json').read_text(encoding='utf-8')) if not x['duplicate_of'] and x['exact_groups']}
    pool = []
    for f in sorted(glob.glob(str(ROOT / 'raw_news' / '*.json'))):
        r = json.loads(pathlib.Path(f).read_text(encoding='utf-8'))
        x = labels.get(r['article_id'])
        if not x or r.get('crawl_status') != 'body_extracted':
            continue
        paras = paragraphs(r['body'])
        bundles = [g for g in TOPIC if re.search(TOPIC[g], (r.get('title_verified') or '') + '\n' + r['body'], re.I)]
        if not bundles or len(paras) < 2:
            continue
        fit = {g: bool(x['bundle_fit'].get(g, {}).get('fit')) for g in bundles}
        pool.append({'id': 'A3-' + r['article_id'], 'article_id': r['article_id'], 'title': r.get('title_verified') or x['title'], 'url': r.get('resolved_url') or r['url'],
                     'date': x['published_date'] or '', 'paragraphs': paras, 'lead_n': lead_paragraphs(paras), 'bundles': [{'code': g, 'ko': GROUP_KO[g]} for g in bundles],
                     'rule': {'fit': fit, 'research': x['research_report']}, 'rule_pass': any(fit.values()) and x['research_report'] == 'yes'})
    return pool


def article_items(rng, mode, previous=()):
    pool = [a for a in article_pool() if a['id'] not in previous]
    passed = [a for a in pool if a['rule_pass']]
    rejects = [a for a in pool if not a['rule_pass']]
    rng.shuffle(passed)
    rng.shuffle(rejects)
    if mode == 'pilot':
        items = passed[:PILOT_PASS] + rejects[:PILOT_N - PILOT_PASS]
        for it in items:
            it['assign'], it['pilot'] = 0, True
    else:
        items = passed + rejects[:REJECT_N]
        assign(items, rng, lambda it: it['rule_pass'])
        for it in items:
            it['pilot'] = False
    rng.shuffle(items)     # coders must not be able to tell passes from rejects by position
    return items, {'pool': len(pool), 'pool_pass': len(passed), 'pool_reject': len(rejects), 'n': len(items), 'n_pass': sum(a['rule_pass'] for a in items)}


if __name__ == '__main__':
    mode = 'main' if '--main' in sys.argv else 'pilot'
    target = OUT / 'sample_round3.json'
    old = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    papers = paper_items(random.Random(SEED))
    pilot = [a for a in old.get('articles', []) if a.get('pilot')] if mode == 'main' else []
    arts, counts = article_items(random.Random(SEED + 1), mode, previous={a['id'] for a in pilot})
    meta = {'round': 3, 'criteria_version': 'v3 (2026-11-24)', 'seed': SEED, 'slots': SLOTS, 'overlap_share': OVERLAP, 'article_mode': mode,
            'papers': {'n': len(papers), 'per_group': {g: sum(p['group'] == g for p in papers) for g in GROUP_KO}, 'all_coders': sum(p['assign'] == 0 for p in papers)},
            'articles': {**counts, 'all_coders': sum(a['assign'] == 0 for a in arts), 'pilot_kept': len(pilot)}}
    OUT.mkdir(exist_ok=True)
    target.write_text(json.dumps({'meta': meta, 'papers': papers, 'articles': pilot + arts}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    per = {s: sum(p['assign'] in (0, s) for p in papers) for s in range(1, SLOTS + 1)}
    print('papers per coder slot', per, '| articles per coder slot', {s: sum(a['assign'] in (0, s) for a in pilot + arts) for s in range(1, SLOTS + 1)})
