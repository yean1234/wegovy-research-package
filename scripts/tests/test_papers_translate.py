"""Offline tests for collect_papers_v2.py and translate_abstracts.py (no network)."""
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import collect_papers_v2 as cp
import translate_abstracts as ta


def rec(title, abstract, types=('Journal Article',), pmid='1'):
    return {'pmid': pmid, 'title': title, 'abstractText': abstract, 'pubTypeList': {'pubType': list(types)}}


STRUCT = ('<h4>Background</h4>Pancreatitis has been reported with GLP-1 receptor agonists.'
          '<h4>Methods</h4>Adults were randomised to semaglutide or placebo.<h4>Results</h4>Weight fell by 14.9%.')


def test_sections_and_result_part():
    secs = cp.sections(STRUCT)
    assert [l for l, _ in secs] == ['Background', 'Methods', 'Results']
    assert 'Pancreatitis' not in cp.result_part(secs)
    plain = cp.sections('Semaglutide is widely used. We report a case of pancreatitis. The patient recovered.')
    assert plain[0][0] == '' and 'case of pancreatitis' in cp.result_part(plain)


def test_screen_only_publication_type_excludes_content_checks_set_priority():
    # outcome only in the background of a structured abstract -> stays in the pool, low priority
    bg = cp.screen(rec('Semaglutide for weight management', STRUCT), 'PANCREATITIS')
    assert bg['exclude'] == '' and bg['priority'] == 'low' and not bg['auto_outcome_reported']
    ok = cp.screen(rec('Semaglutide and acute pancreatitis: a cohort study', '<h4>Results</h4>Pancreatitis occurred in 12 semaglutide users.'), 'PANCREATITIS')
    assert ok['exclude'] == '' and ok['priority'] == 'high'
    # narrative review / editorial -> not a study (NLM publication type); systematic review and letter stay
    assert cp.screen(rec('Semaglutide and pancreatitis', 'Pancreatitis with semaglutide is discussed.', ('Review',)), 'PANCREATITIS')['exclude'] == 'not_a_study'
    assert cp.screen(rec('Semaglutide and pancreatitis', 'Pancreatitis with semaglutide.', ('Editorial',)), 'PANCREATITIS')['exclude'] == 'not_a_study'
    assert cp.screen(rec('Semaglutide and pancreatitis: a systematic review and meta-analysis', 'Pancreatitis risk with semaglutide was pooled.', ('Review',)), 'PANCREATITIS')['exclude'] == ''
    assert cp.screen(rec('Pancreatitis in semaglutide users', 'We found 9 pancreatitis cases among semaglutide users.', ('Letter',)), 'PANCREATITIS')['exclude'] == ''
    # a title that merely contains the word "review" is no longer a reason to exclude
    assert cp.screen(rec('Semaglutide and pancreatitis: a chart review of 300 patients', 'Pancreatitis occurred in 4 semaglutide users.'), 'PANCREATITIS')['exclude'] == ''
    # class-level paper naming semaglutide once -> low priority, not excluded
    cls = cp.screen(rec('GLP-1 receptor agonists and pancreatitis', '<h4>Methods</h4>Users of liraglutide, dulaglutide or semaglutide.<h4>Results</h4>Pancreatitis risk was not increased.'), 'PANCREATITIS')
    assert cls['exclude'] == '' and cls['priority'] == 'low' and not cls['auto_semaglutide_focus']
    # unstructured abstract: no guess about which sentence is background
    plain = cp.screen(rec('Semaglutide in obesity', 'Pancreatitis is a known concern. We treated 40 adults with semaglutide. Semaglutide reduced weight.'), 'PANCREATITIS')
    assert plain['auto_outcome_reported'] and plain['priority'] == 'high'


def _pool(n_high, n_low):
    rows = [{'pmid': str(100 + i), 'priority': 'high'} for i in range(n_high)] + [{'pmid': str(500 + i), 'priority': 'low'} for i in range(n_low)]
    return rows


def test_draw_census_stratified_and_certainty_stratum():
    import random
    short, how = cp.draw(_pool(10, 8), random.Random(1), set(), cap=25, high_n=20)
    assert how == 'census' and len(short) == 18
    pool = _pool(50, 9)
    short, how = cp.draw(pool, random.Random(1), {'105', '107'}, cap=25, high_n=20)
    assert how == 'stratified random sample' and len(short) == 25 and {'105', '107'} <= short
    assert sum(int(p) < 500 for p in short) == 20 and sum(int(p) >= 500 for p in short) == 5
    assert cp.draw(pool, random.Random(1), {'105', '107'}, cap=25, high_n=20)[0] == short       # seeded
    # a stratum that cannot fill its share passes the slots on
    short, _ = cp.draw(_pool(12, 40), random.Random(1), set(), cap=25, high_n=20)
    assert sum(int(p) < 500 for p in short) == 12 and len(short) == 25
    short, _ = cp.draw(_pool(40, 2), random.Random(1), set(), cap=25, high_n=20)
    assert sum(int(p) >= 500 for p in short) == 2 and len(short) == 25


def test_run_reports_flow_and_never_excludes_on_content(monkeypatch):
    monkeypatch.setattr(cp, 'GROUPS', {'PANCREATITIS': cp.GROUPS['PANCREATITIS']})
    recs = [rec(f'Semaglutide and pancreatitis case {i}', 'A patient on semaglutide developed pancreatitis. Semaglutide was stopped.', pmid=str(100 + i)) for i in range(30)]
    recs += [rec('GLP-1 drugs and weight', 'Pancreatitis is known. Users of semaglutide lost weight.', pmid=str(500 + i)) for i in range(10)]
    recs += [rec('Semaglutide and pancreatitis', 'Pancreatitis with semaglutide is discussed.', ('Review',), pmid='900')]
    summary, screening, internal = cp.run('2026-11-24', fetch=lambda q: (recs, len(recs)), log=lambda *a: None, keep={'105'})
    f = summary['flow']['PANCREATITIS']
    assert f['marked_ineligible_by_automation'] == {'not_a_study_publication_type': 1} and f['screening_pool'] == 40
    assert f['strata']['high'] == {'in_pool': 30, 'drawn': 20, 'sampling_fraction': 0.667} and f['strata']['low']['drawn'] == 5
    short = {x['pmid'] for x in screening if x['shortlist']}
    assert '105' in short and '900' not in short and len(short) == 25 and 'PANCREATITIS:105' in internal


def test_summarize_paper_screening_majority_ties_and_priority_check():
    import summarize_paper_screening as sp
    v = lambda e, r='', bg=None: {'elig': e, 'role': r, 'bg': bg}
    votes = {('1', 'NAION'): [v('yes', 'main', 2), v('yes', 'main', 1), v('no')],        # majority eligible, median_low of bg
             ('2', 'NAION'): [v('no'), v('no'), v('yes', 'main')],
             ('3', 'NAION'): [v('yes', 'background'), v('no')],                            # tie -> left out
             ('4', 'NAION'): [v('yes', 'main', 0)],                                        # single coder
             ('5', 'NAION'): [v('yes', 'background')]}
    screening = [{'pmid': p, 'side_effect': 'NAION', 'priority': pr} for p, pr in (('1', 'high'), ('2', 'high'), ('3', 'low'), ('4', 'low'), ('5', 'low'))]
    final, ties, report = sp.summarize(votes, screening)
    assert [(x['pmid'], x['role'], x['background_sentences']) for x in final] == [('1', 'main', 1), ('4', 'main', 0), ('5', 'background', None)]
    assert ties == [('3', 'NAION')] and report['NAION']['tied'] == 1 and report['NAION']['eligible'] == 3
    assert report['NAION']['by_priority']['high'] == {'screened': 2, 'eligible': 1, 'eligible_share': 0.5}
    assert report['ALL']['by_priority']['low']['eligible'] == 2 and report['ALL']['by_priority']['low']['screened'] == 2


def test_split_sentences_handles_decimals_and_abbreviations():
    s = ta.split_sentences('The hazard ratio was 7.64 (95% CI, 2.21-26.36). Semaglutide vs. placebo showed no difference. Smith et al. reported 3 cases.')
    assert s == ['The hazard ratio was 7.64 (95% CI, 2.21-26.36).', 'Semaglutide vs. placebo showed no difference.', 'Smith et al. reported 3 cases.']


def test_analysis_sentences_drop_background_and_mark_unstructured():
    rows = ta.analysis_sentences({'pmid': '9', 'sections': cp.sections(STRUCT)})
    assert [r['section_label'] for r in rows] == ['Methods', 'Results'] and rows[0]['sentence_id'] == '9_s000'
    plain = ta.analysis_sentences({'pmid': '8', 'sections': [['', 'Background sentence. We report a case.']]})
    assert [r['section_category'] for r in plain] == ['unlabelled', 'unlabelled'] and plain[1]['position'] == 1


def test_translate_rows_uses_cache_and_records_provider():
    calls = []
    def fake(texts, keys):
        calls.append(list(texts))
        return ['KO:' + t for t in texts]
    rows = [{'text_en': 'A.'}, {'text_en': 'B.'}, {'text_en': 'A.'}]
    cache = {}
    out = ta.translate_rows(rows, 'deepl', {}, cache, translator=fake, today='2026-11-24', log=lambda *a: None)
    assert [r['text_ko'] for r in out] == ['KO:A.', 'KO:B.', 'KO:A.'] and calls == [['A.', 'B.']]
    assert out[0]['provider'] == 'deepl' and out[0]['translated_at'] == '2026-11-24'
    ta.translate_rows([{'text_en': 'A.'}, {'text_en': 'C.'}], 'deepl', {}, cache, translator=fake, log=lambda *a: None)
    assert calls[1] == ['C.']          # only the new sentence is sent
