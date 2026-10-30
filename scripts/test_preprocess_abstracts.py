# -*- coding: utf-8 -*-
"""Unit tests for scripts/preprocess_abstracts.py (no network; translate is mocked).

Run:  python3 -m unittest scripts.test_preprocess_abstracts      (from repo root)
      python3 -m unittest test_preprocess_abstracts              (from scripts/)
Fixtures are SYNTHETIC ("Drug X", "outcome Y") and do not imitate any real abstract.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import preprocess_abstracts as pa  # noqa: E402

STRUCTURED_HTML = (
    "<h4>Importance</h4>Drug X is used widely.<h4>Objective</h4>To test."
    "<h4>Design, Setting, and Participants</h4>Cohort of 100 patients vs. controls, e.g. adults."
    "<h4>Results</h4>Risk was higher (HR 2.05; 95% CI 1.20&#8211;3.40; P &lt; .001) at 2.4 mg. "
    "No increase was seen in group B.<h4>Conclusions and Relevance</h4>Drug X may cause outcome Y; "
    "further studies are needed."
)
UNSTRUCTURED_HTML = (
    "Drug X was given to 50 volunteers. Drug X was not associated with outcome Y "
    "(OR 1.01; 95% CI 0.80&#8211;1.30). <i>Drug X</i> causes outcome Z in mice."
)

# Tiny inline table/lexicon (synthetic; the real files are scripts/nlm_section_labels.json and
# scripts/certainty_lexicon_en.json).
SECTION_TABLE = {
    "categories": {"BACKGROUND": "drop", "OBJECTIVE": "drop", "METHODS": "keep", "RESULTS": "keep",
                   "CONCLUSIONS": "keep", "UNKNOWN": "needs_human"},
    "labels": {
        "IMPORTANCE": {"category": "BACKGROUND"}, "OBJECTIVE": {"category": "OBJECTIVE"},
        "DESIGN, SETTING, AND PARTICIPANTS": {"category": "METHODS"}, "RESULTS": {"category": "RESULTS"},
        "CONCLUSIONS AND RELEVANCE": {"category": "CONCLUSIONS"},
        "TRIAL REGISTRATION": {"category": "UNKNOWN", "action": "drop_non_content"},
    },
}
TINY_LEXICON = {
    "entries": [
        {"cue": "cause", "pattern": r"\bcaus(?:e|es|ed|ing)\b", "level": 6},
        {"cue": "associated with", "pattern": r"\bassociated\s+with\b", "level": 2},
    ],
    "modifiers": [
        {"cue": "may", "pattern": r"\bmay\b", "effect": "downgrade_to_4"},
        {"cue": "can", "pattern": r"\bcan\b", "effect": "level_5"},
        {"cue": "negation", "pattern": r"\b(?:not|no|never)\b", "effect": "negation_to_1"},
    ],
    "hedges": [{"cue": "suggest", "pattern": r"\bsuggest(?:s|ed)?\b"}],
    "boosters": [{"cue": "clearly", "pattern": r"\bclearly\b"}],
    "sentence_rule": {"negation_window_tokens": 5},
    "levels": {"6": {"collapsed_ko": "단정"}, "5": {"collapsed_ko": "가능성"}, "4": {"collapsed_ko": "가능성"},
               "3": {"collapsed_ko": "연관"}, "2": {"collapsed_ko": "연관"}, "1": {"collapsed_ko": "무관"},
               "0": {"collapsed_ko": None}},
}


class CleanTests(unittest.TestCase):
    def test_tags_entities_removed_and_labels_captured(self):
        info = pa.clean_abstract(STRUCTURED_HTML)
        self.assertTrue(info["structured"])
        self.assertNotIn("<h4>", info["abstract_clean"])
        self.assertNotIn("</", info["abstract_clean"])
        self.assertNotIn("&lt;", info["abstract_clean"])
        self.assertIn("P < .001", info["abstract_clean"])
        self.assertIn("1.20–3.40", info["abstract_clean"])  # entity &#8211; -> en dash
        self.assertEqual([s["label_norm"] for s in info["sections"]],
                         ["IMPORTANCE", "OBJECTIVE", "DESIGN, SETTING, AND PARTICIPANTS", "RESULTS",
                          "CONCLUSIONS AND RELEVANCE"])
        self.assertEqual(info["sections"][1]["text"], "To test.")

    def test_unstructured(self):
        info = pa.clean_abstract(UNSTRUCTURED_HTML)
        self.assertFalse(info["structured"])
        self.assertEqual(info["sections"], [])
        self.assertNotIn("<i>", info["abstract_clean"])

    def test_case_preserved_in_analysis_text(self):
        self.assertIn("HR 2.05", pa.clean_abstract(STRUCTURED_HTML)["abstract_clean"])

    def test_normalize_label(self):
        self.assertEqual(pa.normalize_label("Results:"), "RESULTS")
        self.assertEqual(pa.normalize_label("Conclusions   and  Relevance."), "CONCLUSIONS AND RELEVANCE")


class SectionTests(unittest.TestCase):
    def test_keep_drop(self):
        clean = pa.clean_abstract(STRUCTURED_HTML)
        res = pa.split_sections(clean, SECTION_TABLE)
        kept = [s["label_norm"] for s in res["sections"] if s["keep"]]
        dropped = [s["label_norm"] for s in res["sections"] if not s["keep"]]
        self.assertEqual(dropped, ["IMPORTANCE", "OBJECTIVE"])
        self.assertEqual(kept, ["DESIGN, SETTING, AND PARTICIPANTS", "RESULTS", "CONCLUSIONS AND RELEVANCE"])
        self.assertFalse(res["needs_human_sectioning"])
        self.assertNotIn("used widely", res["analysis_text"])
        self.assertTrue(res["analysis_text"].startswith("Cohort of 100"))

    def test_unstructured_needs_human(self):
        res = pa.split_sections(pa.clean_abstract(UNSTRUCTURED_HTML), SECTION_TABLE)
        self.assertTrue(res["needs_human_sectioning"])
        self.assertIn("50 volunteers", res["analysis_text"])

    def test_unknown_label_flags_and_keeps(self):
        res = pa.split_sections(pa.clean_abstract("<h4>Weird Heading</h4>Kept text.<h4>Results</h4>R."), SECTION_TABLE)
        self.assertTrue(res["needs_human_sectioning"])
        self.assertEqual(res["sections"][0]["category"], "UNKNOWN")
        self.assertIn("Kept text.", res["analysis_text"])

    def test_action_override_drop(self):
        self.assertEqual(pa.classify_label("TRIAL REGISTRATION", SECTION_TABLE), ("UNKNOWN", "drop"))


class SentenceTests(unittest.TestCase):
    def test_abbreviations_not_split_and_flagged(self):
        text = "Cohort of 100 patients vs. controls, e.g. adults. Risk was higher at 2.4 mg."
        rows = pa.split_sentences(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["text_en"], "Cohort of 100 patients vs. controls, e.g. adults.")
        self.assertTrue(rows[0]["boundary_check"])
        self.assertIn("contains_abbreviation", rows[0]["boundary_reason"])

    def test_regex_boundary_flags(self):
        rows = pa.flag_boundaries(["Treated with 2.4 mg vs.", "placebo.", "Shown in Fig.", "2 below.", "Normal sentence."])
        self.assertTrue(rows[1]["boundary_check"])
        self.assertIn("prev_ends_vs.", rows[1]["boundary_reason"])
        self.assertIn("starts_lowercase_or_digit", rows[1]["boundary_reason"])
        self.assertIn("prev_ends_Fig.", rows[3]["boundary_reason"])
        self.assertFalse(rows[4]["boundary_check"])

    def test_sentence_ids_sequential(self):
        clean = pa.clean_abstract(STRUCTURED_HTML)
        clean.update(pa.split_sections(clean, SECTION_TABLE))
        clean["pmid"] = "00000001"
        rows = pa.sentences_for_abstract(clean)
        self.assertEqual([r["sentence_id"] for r in rows], [f"00000001_s{i:03d}" for i in range(len(rows))])
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(rows[0]["section_category"], "METHODS")
        self.assertEqual(rows[-1]["section_category"], "CONCLUSIONS")
        # pretrained Punkt knows 'mg' as an abbreviation and merges "... 2.4 mg. No increase ..." into one
        # sentence; the pipeline must flag that unsplit boundary for human check
        merged = [r for r in rows if "No increase" in r["text_en"]]
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["boundary_check"])
        self.assertIn("unsplit_period_before_capital", merged[0]["boundary_reason"])


class ScoreTests(unittest.TestCase):
    def test_levels(self):
        lex = pa.compile_lexicon(TINY_LEXICON)
        self.assertEqual(pa.score_sentence("Drug X may cause outcome Y.", lex)["level"], 4)
        self.assertEqual(pa.score_sentence("Drug X causes outcome Y.", lex)["level"], 6)
        self.assertEqual(pa.score_sentence("Drug X can cause outcome Y.", lex)["level"], 5)
        self.assertEqual(pa.score_sentence("Drug X is associated with outcome Y.", lex)["level"], 2)
        self.assertEqual(pa.score_sentence("Drug X was not associated with outcome Y.", lex)["level"], 1)
        self.assertEqual(pa.score_sentence("Patients were enrolled.", lex)["level"], 0)

    def test_collapsed_and_hedges(self):
        sc = pa.score_sentence("Results suggest Drug X causes outcome Y.", TINY_LEXICON)
        self.assertEqual(sc["collapsed_ko"], "단정")
        self.assertEqual(sc["hedges"], ["suggest"])
        self.assertEqual(sc["matched_cues"][0]["span"], [23, 29])
        self.assertEqual(sc["matched_cues"][0]["text"], "causes")

    def test_negation_outside_window_does_not_apply(self):
        lex = pa.compile_lexicon({**TINY_LEXICON, "sentence_rule": {"negation_window_tokens": 2}})
        sc = pa.score_sentence("No data on dose were available, but Drug X was associated with outcome Y.", lex)
        self.assertEqual(sc["level"], 2)

    def test_cue_lists_as_strings_resolved(self):
        lex = pa.compile_lexicon({**TINY_LEXICON, "causal_cues": ["cause"], "associational_cues": ["associated with"]})
        self.assertEqual(len(lex["cues"]), 2)  # de-duplicated

    def test_missing_lexicon_fails_loudly(self):
        with self.assertRaises(FileNotFoundError):
            pa.load_lexicon(pathlib.Path("/nonexistent/lexicon.json"))
        with self.assertRaises(FileNotFoundError):
            pa.load_section_labels(pathlib.Path("/nonexistent/labels.json"))


class TokenTests(unittest.TestCase):
    def test_tokens_analysis_keeps_numbers_negation_abbrev(self):
        toks = pa.tokenize_analysis("Risk was higher (HR 2.05; 95% CI 1.20–3.40; P < .001) at 2.4 mg. No, it may not.")
        for t in ["2.4", "2.05", "95%", "1.20", "3.40", "ci", "hr", "no", "not", "may", "p"]:
            self.assertIn(t, toks, t)
        self.assertNotIn("1.20–3.40", toks)

    def test_tokens_analysis_contractions_hyphens(self):
        toks = pa.tokenize_analysis("It isn't a non-arteritic GLP-1 effect.")
        self.assertIn("isn't", toks)
        self.assertIn("non-arteritic", toks)
        self.assertIn("glp-1", toks)

    def test_tokens_tfidf_letters_only(self):
        toks = pa.tokenize_tfidf("Risk was higher (HR 2.05; 95% CI 1.20–3.40) at 2.4 mg.")
        self.assertTrue(all(t.isalpha() for t in toks))
        self.assertEqual(toks[:3], ["risk", "was", "higher"])

    def test_stems_protect_entities(self):
        stems = pa.stem_tokens(["patients", "boeing", "semaglutide"], protected={"semaglutide"})
        self.assertEqual(stems, ["patient", "boe", "semaglutide"])


class PipelineTests(unittest.TestCase):
    """End-to-end on synthetic Europe PMC-shaped JSON; translate is mocked (no network)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.raw = root / "raw"
        self.raw.mkdir()
        self.out = root / "out"
        self.papers = [
            {"pmid": "00000001", "side_effect": "TEST_A", "selection_role": "main", "title": "Synthetic structured"},
            {"pmid": "00000002", "side_effect": "TEST_B", "selection_role": "main", "title": "Synthetic unstructured"},
            {"pmid": "00000003", "side_effect": "TEST_C", "selection_role": "main", "title": "Missing raw"},
        ]
        for pmid, html_ in [("00000001", STRUCTURED_HTML), ("00000002", UNSTRUCTURED_HTML)]:
            (self.raw / f"{pmid}.json").write_text(json.dumps({
                "pmid": pmid, "url": "fixture", "fetched_at": "2026-01-01T00:00:00+00:00",
                "response": {"resultList": {"result": [{"id": pmid, "abstractText": html_, "title": "t"}]}}}),
                encoding="utf-8")
        (root / "labels.json").write_text(json.dumps(SECTION_TABLE), encoding="utf-8")
        (root / "lex.json").write_text(json.dumps(TINY_LEXICON), encoding="utf-8")
        self.ctx = pa.Ctx(self.out, self.raw, root / "none.json", root / "labels.json", root / "lex.json",
                          papers=self.papers)

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_stages_run_offline(self):
        calls = []

        def fake_translate(text):
            calls.append(text)
            return "번역:" + text[:10]

        rc = pa.run([s for s in pa.STAGES if s != "fetch"], self.ctx, translate=fake_translate)
        self.assertEqual(rc, 0)
        self.assertTrue(calls)
        clean = json.loads((self.out / "clean" / "00000001.json").read_text(encoding="utf-8"))
        self.assertFalse(clean["needs_human_sectioning"])
        self.assertTrue(json.loads((self.out / "clean" / "00000002.json").read_text(encoding="utf-8"))["needs_human_sectioning"])
        tr = json.loads((self.out / "translations" / "00000001.json").read_text(encoding="utf-8"))
        self.assertTrue(all(r["text_ko"] for r in tr["sentences"]))
        self.assertEqual(tr["sentences"][0]["tool"], pa.TRANSLATE_TOOL)
        sheet = (self.out / "review_sheet.csv").read_bytes()
        self.assertTrue(sheet.startswith(b"\xef\xbb\xbf"))  # UTF-8 BOM for Excel
        header = sheet.decode("utf-8-sig").splitlines()[0]
        self.assertTrue(header.startswith("sentence_id,pmid,side_effect,section,text_en,text_ko,en_level,en_collapsed"))
        self.assertTrue(header.endswith("ko_level_human,agree,note"))
        rep = json.loads((self.out / "preprocessing_report.json").read_text(encoding="utf-8"))
        self.assertTrue(rep["per_pmid"]["00000003"]["raw_missing"])
        self.assertEqual(rep["per_pmid"]["00000001"]["n_sentences"], rep["per_pmid"]["00000001"]["n_sentences"])
        self.assertTrue((self.out / "HEURISTICS_LOG.md").exists())
        self.assertTrue((self.out / "tokens" / "00000002.json").exists())
        # idempotent: second run uses the translation cache and does not call translate again
        n_calls = len(calls)
        pa.run(["translate"], self.ctx, translate=fake_translate)
        self.assertEqual(len(calls), n_calls)

    def test_translate_failure_does_not_crash(self):
        def failing(text):
            raise RuntimeError("offline")

        rc = pa.run(["clean", "sections", "sentences", "translate", "cues", "report"], self.ctx, translate=failing)
        self.assertEqual(rc, 0)
        self.assertEqual(self.ctx.report["stages"]["translate"]["status"], "partial")
        tr = json.loads((self.out / "translations" / "00000001.json").read_text(encoding="utf-8"))
        self.assertTrue(all(r["text_ko"] is None for r in tr["sentences"]))


if __name__ == "__main__":
    unittest.main()
