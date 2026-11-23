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


def test_screen_rules():
    # outcome only in the background of a structured abstract -> excluded
    assert cp.screen(rec('Semaglutide for weight management', STRUCT), 'PANCREATITIS')['exclude'] == 'outcome_not_reported'
    ok = cp.screen(rec('Semaglutide and acute pancreatitis: a cohort study', '<h4>Results</h4>Pancreatitis occurred in 12 semaglutide users.'), 'PANCREATITIS')
    assert ok['exclude'] == '' and ok['drug_in_title'] and ok['outcome_in_title']
    # narrative review / editorial -> not a study; systematic review stays
    assert cp.screen(rec('Semaglutide and pancreatitis', 'Pancreatitis with semaglutide is discussed.', ('Review',)), 'PANCREATITIS')['exclude'] == 'not_a_study'
    assert cp.screen(rec('Semaglutide and pancreatitis: a systematic review and meta-analysis', 'Pancreatitis risk with semaglutide was pooled.', ('Review',)), 'PANCREATITIS')['exclude'] == ''
    # class-level paper naming semaglutide once -> in passing
    cls = cp.screen(rec('GLP-1 receptor agonists and pancreatitis', '<h4>Methods</h4>Users of liraglutide, dulaglutide or semaglutide.<h4>Results</h4>Pancreatitis risk was not increased.'), 'PANCREATITIS')
    assert cls['exclude'] == 'semaglutide_in_passing'
    # gastric-emptying-only paper is not a gastroparesis paper
    assert cp.screen(rec('Semaglutide and gastric emptying before endoscopy', '<h4>Results</h4>Semaglutide users had delayed gastric emptying. Semaglutide was continued.'), 'GASTROPARESIS')['exclude'] == 'outcome_not_reported'


def test_run_keeps_previous_main_papers_and_caps(monkeypatch):
    monkeypatch.setattr(cp, 'CAP', 3)
    monkeypatch.setattr(cp, 'GROUPS', {'PANCREATITIS': cp.GROUPS['PANCREATITIS']})
    recs = [rec(f'Semaglutide and pancreatitis case {i}', 'A patient on semaglutide developed pancreatitis. Semaglutide was stopped.', pmid=str(100 + i)) for i in range(8)]
    summary, screening, internal = cp.run('2026-11-24', fetch=lambda q: (recs, len(recs)), log=lambda *a: None, keep={'105', '107'})
    short = {x['pmid'] for x in screening if x['shortlist']}
    assert len(short) == 3 and {'105', '107'} <= short
    assert summary['flow']['PANCREATITIS']['passed_auto_screen'] == 8 and 'PANCREATITIS:105' in internal
    again = {x['pmid'] for x in cp.run('2026-11-24', fetch=lambda q: (recs, len(recs)), log=lambda *a: None, keep={'105', '107'})[1] if x['shortlist']}
    assert again == short      # seeded: the same shortlist every run


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
