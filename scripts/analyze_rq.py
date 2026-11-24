"""RQ1-RQ3 on the confirmed papers and articles (course methods only).

Inputs
  articles   --articles FILE : JSON list of {"article_id", "bundles": [...]} confirmed by the human validation.
             Without it the COMPUTER-passed set is used (topic fit AND research report in
             article_labels_internal.json); that run is a dry run, not a result.
             Bodies come from scripts/raw_news/<article_id>.json.
  abstracts  scripts/abstract_translations.json (translate_abstracts.py): Korean sentences of the analysis
             part of each abstract. Without it the abstract group is left out and the report says so.

Three groups are compared: abstract (translated), article body, article title. One Korean lexicon
(config/lexicon_ko.yaml via claims.py) is applied to all three in the same way.

RQ1 (bundles pooled)  share of claim sentences that are direct / possible / association / none, per group.
                      A claim sentence names the drug AND one of the four adverse events (claims.py).
                      Intervals: bootstrap over documents (2000 resamples), because sentences of one
                      document are not independent. Plus title vs body: log-odds words (Monroe et al. 2008)
                      and a Naive Bayes title/body sentence classifier, folds split by article.
RQ2 (per bundle)      share of documents in which each condition category (population, dose, duration,
                      design, limitation) occurs, per bundle and group, with document counts.
                      Plus words with the highest PMI with the drug name (exploratory).
RQ3 (bundles pooled)  article bodies -> TF-IDF -> K-means, k chosen by silhouette; cluster x bundle table;
                      lexicon numbers per cluster. The lexicon numbers and the bundle labels are NOT
                      clustering inputs. LDA topic words are given next to it for naming the clusters.
                      The clustering is run twice: on the full text, and with the adverse-event words removed,
                      because on the full text the clusters mostly reproduce the bundles (topic clusters).

Output: results/rq_results.json (numbers only, no article text) and, when matplotlib is installed,
results/rq1_strength.png and results/rq2_conditions.png.
"""
import argparse, collections, json, math, pathlib, random, re

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics import f1_score, silhouette_score
from sklearn.model_selection import GroupKFold
from sklearn.naive_bayes import MultinomialNB

import claims
from label_articles import paragraphs

ROOT = pathlib.Path(__file__).parent
REPO = ROOT.parent
SEED = 20261124
BUNDLES = ['NAION', 'PANCREATITIS', 'SUICIDALITY', 'GASTROPARESIS']
STRENGTHS = ['direct', 'possible', 'association', 'none']
CONDITIONS = ['population', 'dose', 'duration', 'design', 'limitation']
GROUPS = ['abstract', 'body', 'title']

try:
    from kiwipiepy import Kiwi
    _kiwi = Kiwi()

    def ko_tokens(text):
        out = []
        for t in _kiwi.tokenize(text):
            if t.tag in ('NNG', 'NNP', 'SL', 'XR', 'MAG'):
                out.append(t.form)
            elif t.tag[:2] in ('VV', 'VA'):
                out.append(t.form + '다')
        return [w for w in out if len(w) > 1 or w in ('수',)]
except ImportError:      # degraded mode: whitespace tokens
    def ko_tokens(text):
        return re.findall(r'[가-힣A-Za-z]{2,}', text)


# ---------------------------------------------------------------- data
def load_documents(articles_file=None):
    """-> list of {'group', 'doc_id', 'bundles', 'sentences'}; meta dict."""
    docs, meta = [], {}
    labels = {x['article_id']: x for x in json.loads((ROOT / 'article_labels_internal.json').read_text(encoding='utf-8'))}
    if articles_file:
        wanted = {x['article_id']: x['bundles'] for x in json.loads(pathlib.Path(articles_file).read_text(encoding='utf-8'))}
        meta['article_set'] = 'human-confirmed list: ' + str(articles_file)
    else:
        wanted = {a: [g for g, v in x['bundle_fit'].items() if v['fit']] for a, x in labels.items()
                  if not x['duplicate_of'] and x['research_report'] == 'yes' and any(v['fit'] for v in x['bundle_fit'].values())}
        meta['article_set'] = 'DRY RUN: computer-passed articles, not human-confirmed'
    missing = 0
    for aid, bundles in sorted(wanted.items()):
        f = ROOT / 'raw_news' / f'{aid}.json'
        r = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
        if r.get('crawl_status') != 'body_extracted':
            missing += 1
            continue
        title = r.get('title_verified') or r.get('title') or ''
        body = '\n'.join(p for p in paragraphs(r['body']) if p.strip() != title.strip())
        docs.append({'group': 'body', 'doc_id': aid, 'bundles': bundles, 'sentences': claims.split_sentences(body), 'text': body})
        docs.append({'group': 'title', 'doc_id': aid, 'bundles': bundles, 'sentences': [title], 'text': title})
    meta['articles_wanted'], meta['articles_without_body'] = len(wanted), missing
    tr = ROOT / 'abstract_translations.json'
    if tr.exists():
        by = collections.defaultdict(list)
        data = json.loads(tr.read_text(encoding='utf-8'))
        final = REPO / 'validation' / 'final_papers.json'      # summarize_paper_screening.py
        bg = {x['pmid']: x.get('background_sentences') for x in json.loads(final.read_text(encoding='utf-8'))} if final.exists() else {}
        dropped = unmarked = 0
        for r in data['rows']:
            if r['section_category'] == 'unlabelled':
                n = bg.get(r['pmid'])
                if n is None:
                    unmarked += 1          # no human mark yet: the sentence is kept, and counted in the report
                elif r['position'] < n:
                    dropped += 1           # coders marked this opening sentence as background / objective
                    continue
            by[r['pmid']].append(r)
        meta['unstructured_abstract_sentences'] = {'dropped_as_background_by_coders': dropped, 'kept_without_a_human_mark': unmarked}
        for pmid, rows in sorted(by.items()):
            docs.append({'group': 'abstract', 'doc_id': pmid, 'bundles': rows[0]['side_effects'], 'sentences': [r['text_ko'] for r in rows], 'text': ' '.join(r['text_ko'] for r in rows)})
        meta['abstracts'] = f"{len(by)} papers, provider {data.get('provider')}"
    else:
        meta['abstracts'] = 'MISSING: run translate_abstracts.py; the abstract group is left out'
    return docs, meta


# ---------------------------------------------------------------- RQ1
def code_documents(docs, lex):
    for d in docs:
        coded = [claims.code_sentence(s, None, lex) for s in d['sentences']]
        d['coded'] = coded
        d['n_claims'] = sum(c['is_claim'] for c in coded)
        d['strength'] = collections.Counter(c['strength'] for c in coded if c['is_claim'] and c['strength'])
        d['uncoded_claims'] = sum(1 for c in coded if c['is_claim'] and not c['strength'])
        d['conditions'] = {k: any(c['conditions'].get(k) for c in coded) for k in CONDITIONS}
        d['hedge_sentences'] = sum(bool(c['hedges']) for c in coded)
        d['booster_sentences'] = sum(bool(c['boosters']) for c in coded)
    return docs


def code_broad(docs, lex):
    """Same coding with the broad term lists (drug class words such as '비만약', outcome words such as '실명').
    Titles rarely repeat the exact drug and diagnosis, so the narrow filter leaves few title sentences."""
    out = []
    for d in docs:
        coded = [claims.code_sentence(s, None, lex, broad_outcome=True, broad_drug=True) for s in d['sentences']]
        out.append({**d, 'coded': coded, 'n_claims': sum(c['is_claim'] for c in coded),
                    'strength': collections.Counter(c['strength'] for c in coded if c['is_claim'] and c['strength']),
                    'hedge_sentences': d['hedge_sentences'], 'booster_sentences': d['booster_sentences']})
    return out


def shares(ds):
    tot = sum(sum(d['strength'].values()) for d in ds)
    return {s: (sum(d['strength'][s] for d in ds) / tot if tot else float('nan')) for s in STRENGTHS}


def bootstrap(ds, fn, n=2000, seed=SEED):
    rng = random.Random(seed)
    vals = collections.defaultdict(list)
    for _ in range(n):
        res = fn([ds[rng.randrange(len(ds))] for _ in ds])
        for k, v in res.items():
            if not math.isnan(v):
                vals[k].append(v)
    return {k: [round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)] for k, v in vals.items() if v}


def rq1(docs):
    out = {}
    for g in GROUPS:
        ds = [d for d in docs if d['group'] == g]
        if not ds:
            continue
        sh = shares(ds)
        out[g] = {'documents': len(ds), 'sentences': sum(len(d['sentences']) for d in ds), 'claim_sentences': sum(d['n_claims'] for d in ds),
                  'claim_sentences_with_strength_cue': sum(sum(d['strength'].values()) for d in ds),
                  'documents_with_a_claim_sentence': sum(d['n_claims'] > 0 for d in ds),
                  'share_of_coded_claim_sentences': {k: round(v, 3) for k, v in sh.items() if not math.isnan(v)},
                  'ci95_bootstrap_over_documents': bootstrap(ds, shares) if len(ds) >= 5 else {},
                  'documents_with_direct_claim': sum(d['strength']['direct'] > 0 for d in ds),
                  'sentences_with_hedge': sum(d['hedge_sentences'] for d in ds), 'sentences_with_booster': sum(d['booster_sentences'] for d in ds)}
    return out


def log_odds(tokens_a, tokens_b, prior=0.1, min_count=3, top=15):
    """Monroe, Colaresi & Quinn (2008) log-odds ratio with an informative Dirichlet prior; z-scores."""
    ca, cb = collections.Counter(tokens_a), collections.Counter(tokens_b)
    vocab = [w for w in set(ca) | set(cb) if ca[w] + cb[w] >= min_count]
    na, nb, a0 = sum(ca.values()), sum(cb.values()), 0.0
    pri = {w: prior * (ca[w] + cb[w]) for w in vocab}
    a0 = sum(pri.values())
    z = {}
    for w in vocab:
        la = math.log((ca[w] + pri[w]) / (na + a0 - ca[w] - pri[w]))
        lb = math.log((cb[w] + pri[w]) / (nb + a0 - cb[w] - pri[w]))
        z[w] = (la - lb) / math.sqrt(1 / (ca[w] + pri[w]) + 1 / (cb[w] + pri[w]))
    rank = sorted(z, key=z.get)
    return [(w, round(z[w], 2)) for w in rank[::-1][:top]], [(w, round(z[w], 2)) for w in rank[:top]]


def title_vs_body(docs, lex):
    titles = [d for d in docs if d['group'] == 'title']
    bodies = {d['doc_id']: d for d in docs if d['group'] == 'body'}
    if len(titles) < 10:
        return {'note': 'fewer than 10 articles'}
    tt = [w for d in titles for w in ko_tokens(d['text'])]
    bt = [w for d in bodies.values() for w in ko_tokens(d['text'])]
    top_title, top_body = log_odds(tt, bt)
    X, y, groups = [], [], []
    for d in titles:
        X.append(d['text']); y.append(1); groups.append(d['doc_id'])
        for s in bodies[d['doc_id']]['sentences']:
            X.append(s); y.append(0); groups.append(d['doc_id'])
    y = np.array(y)
    pred = np.zeros(len(y), dtype=int)
    for tr, te in GroupKFold(n_splits=5).split(X, y, groups):       # an article's title and sentences stay in one fold
        vec = TfidfVectorizer(tokenizer=ko_tokens, token_pattern=None, lowercase=False, min_df=2)
        m = MultinomialNB(alpha=0.5, fit_prior=False).fit(vec.fit_transform([X[i] for i in tr]), y[tr])
        pred[te] = m.predict(vec.transform([X[i] for i in te]))
    vec = TfidfVectorizer(tokenizer=ko_tokens, token_pattern=None, lowercase=False, min_df=2)
    m = MultinomialNB(alpha=0.5, fit_prior=False).fit(vec.fit_transform(X), y)
    diff = m.feature_log_prob_[1] - m.feature_log_prob_[0]
    names = vec.get_feature_names_out()
    nb_title = [names[i] for i in np.argsort(diff)[::-1][:20]]
    direct = [w for w in nb_title if any(c['category'] == 'direct' for c in claims.code_sentence('위고비 췌장염 ' + w, None, lex)['cues'])]
    return {'log_odds_title': top_title, 'log_odds_body': top_body,
            'naive_bayes': {'sentences': int(len(y)), 'titles': int(y.sum()), 'macro_f1': round(float(f1_score(y, pred, average='macro')), 3),
                            'title_recall': round(float(pred[y == 1].mean()), 3), 'baseline_all_body_macro_f1': round(float(f1_score(y, np.zeros_like(y), average='macro')), 3),
                            'top_title_words': nb_title, 'of_which_direct_causal_cues': direct}}


# ---------------------------------------------------------------- RQ2
def rq2(docs):
    table = {}
    for b in BUNDLES:
        for g in GROUPS:
            ds = [d for d in docs if d['group'] == g and b in d['bundles']]
            if ds:
                table[f'{b}|{g}'] = {'documents': len(ds), **{c: round(sum(d['conditions'][c] for d in ds) / len(ds), 3) for c in CONDITIONS}}
    diff = {}
    for b in BUNDLES:
        if f'{b}|body' in table and f'{b}|title' in table:
            diff[b] = {c: round(table[f'{b}|body'][c] - table[f'{b}|title'][c], 3) for c in CONDITIONS}
    return {'share_of_documents_with_condition': table, 'body_minus_title': diff}


def drug_pmi(docs, lex, top=12, min_count=3):
    out = {}
    for g in GROUPS:
        sents = [s for d in docs if d['group'] == g for s in d['sentences']]
        if len(sents) < 30:
            continue
        n, with_drug, word, joint = 0, 0, collections.Counter(), collections.Counter()
        for s in sents:
            ws = set(ko_tokens(s))
            has = claims.code_sentence(s, None, lex).get('has_drug')
            if has is None:
                has = bool(re.search(r'위고비|세마글루|오젬픽|리벨서스|wegovy|semaglutide', s, re.I))
            n += 1; with_drug += has
            for w in ws:
                word[w] += 1
                if has:
                    joint[w] += 1
        if not with_drug:
            continue
        pmi = {w: math.log2((joint[w] / n) / ((with_drug / n) * (word[w] / n))) for w in joint if joint[w] >= min_count and not re.search(r'위고비|세마글루|오젬픽', w)}
        out[g] = {'sentences': n, 'sentences_with_drug': int(with_drug), 'top_pmi_words': [(w, round(v, 2), joint[w]) for w, v in sorted(pmi.items(), key=lambda x: -x[1])[:top]]}
    return out


# ---------------------------------------------------------------- RQ3
TOPIC_WORDS = (r'NAION|비동맥\S*|허혈\S*|시신경\S*|실명|시력|안과\S*|녹내장|Ophthalmology|췌장\S*|급성|자살\S*|자해|충동|정신\S*|우울\S*'
               r'|위\s*마비|위장?\s*무력증|무력증|위장\S*|장폐색|gastroparesis|pancreatitis|suicid\w*')


def rq3(docs, mask_topic=False):
    bodies = [d for d in docs if d['group'] == 'body']
    if len(bodies) < 20:
        return {'note': 'fewer than 20 article bodies'}
    texts = [re.sub(TOPIC_WORDS, ' ', d['text'], flags=re.I) if mask_topic else d['text'] for d in bodies]
    vec = TfidfVectorizer(tokenizer=ko_tokens, token_pattern=None, lowercase=False, min_df=3, max_df=0.8, sublinear_tf=True)
    X = vec.fit_transform(texts)
    sil = {}
    for k in range(2, min(8, len(bodies) // 5) + 1):
        lab = KMeans(n_clusters=k, n_init=20, random_state=SEED).fit_predict(X)
        sil[k] = round(float(silhouette_score(X, lab)), 4)
    k = max(sil, key=sil.get)
    km = KMeans(n_clusters=k, n_init=20, random_state=SEED).fit(X)
    names = vec.get_feature_names_out()
    clusters = []
    for c in range(k):
        ds = [d for d, l in zip(bodies, km.labels_) if l == c]
        sh = shares(ds)
        clusters.append({'cluster': c, 'articles': len(ds), 'top_terms': [names[i] for i in np.argsort(km.cluster_centers_[c])[::-1][:12]],
                         'by_bundle': {b: sum(b in d['bundles'] for d in ds) for b in BUNDLES},
                         'share_of_coded_claim_sentences': {s: round(v, 3) for s, v in sh.items() if not math.isnan(v)},
                         'share_of_articles_with_condition': {cnd: round(sum(d['conditions'][cnd] for d in ds) / len(ds), 3) for cnd in CONDITIONS}})
    largest = [max(c['by_bundle'].values()) / max(1, sum(c['by_bundle'].values())) for c in clusters]
    cv = CountVectorizer(tokenizer=ko_tokens, token_pattern=None, lowercase=False, min_df=3, max_df=0.8)
    C = cv.fit_transform(texts)
    lda = LatentDirichletAllocation(n_components=k, random_state=SEED, max_iter=50).fit(C)
    vocab = cv.get_feature_names_out()
    return {'adverse_event_words_removed': mask_topic, 'articles': len(bodies), 'silhouette_by_k': sil, 'chosen_k': k, 'clusters': clusters,
            'largest_bundle_share_per_cluster': [round(x, 2) for x in largest],
            'reading_note': 'a cluster whose largest bundle share is near 1.0 is a topic cluster (one adverse event), not a way of reporting',
            'lda_topics': [[vocab[i] for i in np.argsort(t)[::-1][:10]] for t in lda.components_]}


def figures(res, out):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    made = []
    gs = [g for g in GROUPS if g in res['rq1']]
    fig, ax = plt.subplots(figsize=(6, 3.4))
    bottom = np.zeros(len(gs))
    for s in STRENGTHS:
        v = np.array([res['rq1'][g]['share_of_coded_claim_sentences'].get(s, 0) for g in gs])
        ax.bar(gs, v, bottom=bottom, label=s)
        bottom += v
    ax.set_ylabel('share of coded claim sentences'); ax.legend(frameon=False, fontsize=8); fig.tight_layout()
    fig.savefig(out / 'rq1_strength.png', dpi=160); plt.close(fig); made.append('rq1_strength.png')
    keys = list(res['rq2']['share_of_documents_with_condition'])
    if keys:
        M = np.array([[res['rq2']['share_of_documents_with_condition'][k][c] for c in CONDITIONS] for k in keys])
        fig, ax = plt.subplots(figsize=(6, 0.42 * len(keys) + 1.2))
        im = ax.imshow(M, vmin=0, vmax=1, cmap='Blues', aspect='auto')
        ax.set_xticks(range(len(CONDITIONS)), CONDITIONS); ax.set_yticks(range(len(keys)), [f"{k} (n={res['rq2']['share_of_documents_with_condition'][k]['documents']})" for k in keys], fontsize=8)
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                ax.text(j, i, f'{M[i, j]:.2f}', ha='center', va='center', fontsize=7, color='white' if M[i, j] > 0.6 else 'black')
        fig.colorbar(im, fraction=0.03); fig.tight_layout()
        fig.savefig(out / 'rq2_conditions.png', dpi=160); plt.close(fig); made.append('rq2_conditions.png')
    return made


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--articles')
    a = ap.parse_args(argv)
    lex = claims.load_lexicon()
    docs, meta = load_documents(a.articles)
    docs = code_documents(docs, lex)
    res = {'meta': {**meta, 'seed': SEED, 'documents': dict(collections.Counter(d['group'] for d in docs))},
           'rq1': rq1(docs), 'rq1_broad_terms_sensitivity': rq1(code_broad(docs, lex)), 'rq1_title_vs_body': title_vs_body(docs, lex), 'rq2': rq2(docs), 'rq2_drug_pmi': drug_pmi(docs, lex), 'rq3': rq3(docs),
           'rq3_adverse_event_words_removed': rq3(docs, mask_topic=True)}
    out = REPO / 'results'
    out.mkdir(exist_ok=True)
    res['meta']['figures'] = figures(res, out)
    (out / 'rq_results.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(res['meta'], ensure_ascii=False, indent=1))
    for g, v in res['rq1'].items():
        print(g, 'docs', v['documents'], 'claim sentences', v['claim_sentences'], v['share_of_coded_claim_sentences'])
    return res


if __name__ == '__main__':
    main()
