"""Article screening: rule filter vs Naive Bayes vs logistic regression, scored against human codes.

Question: can a classifier learned from the human validation codes screen articles better than the
hand-written rules in label_articles.py? Two binary targets are compared separately:
  research   "is this a research report?"            one unit per article
  topic      "is this adverse event the main topic?"  one unit per (article, bundle)

Gold standard: the majority answer of the coders for each unit (ties are dropped), read from the CSV
files exported by the validation sites (round 1/2: human_v / human_trig; round 3: derived_topic /
derived_research). Give one or more files:
    python compare_classifiers.py validation/validation_codes.csv validation/validation_codes_round3.csv

Text: title + body from scripts/raw_news/<article_id>.json (for topic: title, lead and the paragraphs that
mention the bundle term). Tokens: Kiwi morphemes when kiwipiepy is installed, else character 2-3-grams.
Features: TF-IDF fitted inside each training fold (no leakage from the test fold).
Evaluation: repeated stratified 5-fold cross-validation; the rule filter is scored on the same units.
Reported per method: precision, recall, F1 for "yes". For the two classifiers also the precision reached
when the decision threshold is lowered until recall >= RECALL_TARGET, because people check every article
the screen lets through, so a missed article costs more than an extra one.

The numbers are only as good as the human codes: with about 80 coded units per target the intervals are
wide. Output: classifier_comparison.json (no article text).
"""
import collections, csv, json, pathlib, re, sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import make_pipeline

from label_articles import TOPIC, paragraphs

ROOT = pathlib.Path(__file__).parent
REPO = ROOT.parent
SEED = 20261124
RECALL_TARGET = 0.90

try:
    from kiwipiepy import Kiwi
    _kiwi = Kiwi()

    def tokens(text):
        return [t.form for t in _kiwi.tokenize(text) if t.tag[0] in 'NVMS' or t.tag in ('XR',)]
    VEC = dict(tokenizer=tokens, token_pattern=None, lowercase=False, min_df=2, sublinear_tf=True)
except ImportError:
    VEC = dict(analyzer='char_wb', ngram_range=(2, 3), min_df=2, sublinear_tf=True)


def read_codes(paths):
    """-> {'research': {article_id: [yes/no,...]}, 'topic': {(article_id, group): [yes/no,...]}}"""
    votes = {'research': collections.defaultdict(list), 'topic': collections.defaultdict(list)}
    for p in paths:
        with open(p, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                aid = r.get('pmid_or_article_id') or r.get('article_or_pmid') or r.get('article_id') or ''
                task = r.get('task', '')
                if not aid.startswith('A'):
                    continue
                if task == 'A':                                  # round 3
                    if r.get('derived_research') in ('yes', 'no'):
                        votes['research'][(aid, r.get('coder'))] = r['derived_research']
                    if r.get('derived_topic') in ('yes', 'no'):
                        votes['topic'][(aid, r['group'])].append(r['derived_topic'])
                elif task == 'T' and r.get('human_v') in ('yes', 'no'):       # rounds 1-2, topic
                    votes['topic'][(aid, r['group'])].append(r['human_v'])
                elif task == 'R' and r.get('human_trig') and r['human_trig'] != 'unsure':   # rounds 1-2, trigger
                    votes['research'][(aid, r.get('coder'))] = 'yes' if r['human_trig'] == 'research' else 'no'
    per_article = collections.defaultdict(list)
    for (aid, _), v in votes['research'].items():   # one research vote per coder and article
        per_article[aid].append(v)
    votes['research'] = per_article
    return votes


def majority(vs):
    c = collections.Counter(vs)
    return None if c['yes'] == c['no'] else ('yes' if c['yes'] > c['no'] else 'no')


def load_bodies():
    out = {}
    for f in (ROOT / 'raw_news').glob('*.json'):
        r = json.loads(f.read_text(encoding='utf-8'))
        if r.get('crawl_status') == 'body_extracted':
            out[r['article_id']] = (r.get('title_verified') or r.get('title') or '', r['body'])
    internal = ROOT / 'screening_internal.json'
    if internal.exists():
        for r in json.loads(internal.read_text(encoding='utf-8')):
            if r.get('crawl_status') == 'body_extracted':
                out.setdefault(r['article_id'], (r.get('title_verified') or '', r['body']))
    return out


def topic_text(title, body, group):
    paras = paragraphs(body)
    hit = [p for p in paras[3:] if re.search(TOPIC[group], p, re.I)]
    return '\n'.join([title] + paras[:3] + hit)


def prf(y, pred):
    p, r, f, _ = precision_recall_fscore_support(y, pred, average='binary', pos_label=1, zero_division=0)
    return {'precision': round(float(p), 3), 'recall': round(float(r), 3), 'f1': round(float(f), 3)}


def evaluate(texts, y, rule, repeats=5):
    y = np.array(y)
    out = {'n': int(len(y)), 'n_yes': int(y.sum()), 'rule': prf(y, np.array(rule))}
    models = {'naive_bayes': lambda: make_pipeline(TfidfVectorizer(**VEC), MultinomialNB(alpha=0.5)),
              'logistic_regression': lambda: make_pipeline(TfidfVectorizer(**VEC), LogisticRegression(C=4.0, class_weight='balanced', max_iter=2000))}
    if min(y.sum(), len(y) - y.sum()) < 5:
        out['note'] = 'fewer than 5 units in one class: cross-validation skipped'
        return out
    cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=repeats, random_state=SEED)
    for name, make in models.items():
        prob = np.zeros((repeats, len(y)))
        for k, (tr, te) in enumerate(cv.split(texts, y)):
            m = make().fit([texts[i] for i in tr], y[tr])
            prob[k // 5, te] = m.predict_proba([texts[i] for i in te])[:, 1]
        p = prob.mean(axis=0)                      # out-of-fold probability, averaged over the repeats
        res = prf(y, (p >= 0.5).astype(int))
        thresholds = sorted(set(np.round(p, 4)), reverse=True)
        chosen = next((t for t in thresholds if prf(y, (p >= t).astype(int))['recall'] >= RECALL_TARGET), min(thresholds))
        res['recall_first'] = {'threshold': float(chosen), **prf(y, (p >= chosen).astype(int)), 'passed_to_humans': int((p >= chosen).sum())}
        out[name] = res
    return out


def main(paths, write=True):
    votes = read_codes(paths)
    bodies = load_bodies()
    labels = {x['article_id']: x for x in json.loads((ROOT / 'article_labels_internal.json').read_text(encoding='utf-8'))}
    report = {'codes': [str(p) for p in paths], 'seed': SEED, 'recall_target': RECALL_TARGET, 'tokens': 'kiwi' if 'tokenizer' in VEC else 'char 2-3-grams'}

    X, y, rule, skipped = [], [], [], 0
    for aid, vs in sorted(votes['research'].items()):
        m = majority(vs)
        if m is None or aid not in bodies or aid not in labels:
            skipped += 1
            continue
        X.append(bodies[aid][0] + '\n' + bodies[aid][1]); y.append(int(m == 'yes')); rule.append(int(labels[aid]['research_report'] == 'yes'))
    report['research'] = {**(evaluate(X, y, rule) if y else {'n': 0}), 'units_without_text_or_majority': skipped}

    X, y, rule, skipped = [], [], [], 0
    for (aid, g), vs in sorted(votes['topic'].items()):
        m = majority(vs)
        if m is None or aid not in bodies or aid not in labels or g not in TOPIC:
            skipped += 1
            continue
        X.append(topic_text(*bodies[aid], g)); y.append(int(m == 'yes')); rule.append(int(bool(labels[aid]['bundle_fit'].get(g, {}).get('fit'))))
    report['topic'] = {**(evaluate(X, y, rule) if y else {'n': 0}), 'units_without_text_or_majority': skipped}

    if write:
        (REPO / 'classifier_comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    for target in ('research', 'topic'):
        r = report[target]
        print(f"\n{target}: n={r.get('n')} yes={r.get('n_yes')} (skipped {r['units_without_text_or_majority']})")
        for k in ('rule', 'naive_bayes', 'logistic_regression'):
            if k in r:
                extra = f" | recall-first: P {r[k]['recall_first']['precision']} R {r[k]['recall_first']['recall']} -> {r[k]['recall_first']['passed_to_humans']} to humans" if 'recall_first' in r[k] else ''
                print(f"  {k:20s} P {r[k]['precision']}  R {r[k]['recall']}  F1 {r[k]['f1']}{extra}")
        if 'note' in r:
            print('  ', r['note'])
    return report


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('usage: python compare_classifiers.py <validation_codes.csv> [more.csv ...]')
    main([pathlib.Path(p) for p in sys.argv[1:]])
