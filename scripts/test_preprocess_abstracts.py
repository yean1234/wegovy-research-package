# -*- coding: utf-8 -*-
"""Unit tests for scripts/preprocess_abstracts.py (no network; translate is mocked).

Run:  python3 -m unittest scripts.test_preprocess_abstracts      (from repo root)
      python3 -m unittest test_preprocess_abstracts              (from scripts/)
Fixtures are SYNTHETIC ("Drug X", "outcome Y") and do not imitate any real abstract.
"""
from __future__ import annotations

import json
import pathlib
import re
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
    "collapse_map": {"collapsed_to_group3": {"단정": "단정", "가능성": "가능성", "연관": "연관·무관", "무관": "연관·무관"},
                     "level_to_collapsed": {"6": "단정", "5": "가능성", "4": "가능성", "3": "연관", "2": "연관", "1": "무관", "0": None}},
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

    def test_inline_tags_do_not_insert_spaces(self):
        self.assertEqual(pa.clean_abstract("<i>Drug</i>-treated (<i>P</i>&lt;.001) et <i>al</i>.")["abstract_clean"],
                         "Drug-treated (P<.001) et al.")
        info = pa.clean_abstract("Patients on <i>semaglutide</i>-treated arms and GLP-1<sup>a</sup>, see Smith <i>et al</i>. Next.")
        self.assertIn("semaglutide-treated", info["abstract_clean"])
        self.assertIn("GLP-1a,", info["abstract_clean"])
        self.assertIn("et al. Next.", info["abstract_clean"])

    def test_entities_decoded_once(self):
        self.assertEqual(pa.clean_abstract("A &amp;lt; B")["abstract_clean"], "A &lt; B")

    def test_no_nfkc_in_preserved_text(self):
        self.assertIn("kg/m²", pa.clean_abstract("BMI 30 kg/m² and 10⁻³.")["abstract_clean"])

    def test_truncation_suspect_flag(self):
        info = pa.clean_abstract("n<a and x<five y and a longer tail of words here")
        self.assertTrue(info["clean_truncated_suspect"])
        self.assertFalse(pa.clean_abstract(STRUCTURED_HTML)["clean_truncated_suspect"])

    def test_labels_only_abstract_is_empty(self):
        info = pa.clean_abstract("<h4>Background</h4><h4>Results</h4><h4>Conclusions</h4>")
        self.assertTrue(info["structured"])
        self.assertTrue(info["abstract_empty"])
        self.assertFalse(pa.clean_abstract(STRUCTURED_HTML)["abstract_empty"])


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

    def test_ci_clause_boundary_named_rule(self):
        rows = pa.flag_boundaries(["Risk was higher (HR 2.05; 95% CI 1.20–3.40.", "Next sentence."])
        self.assertIn("prev_ends_CI_clause.", rows[1]["boundary_reason"])
        rows = pa.flag_boundaries(["Risk was higher 95% CI 1.20–3.40.", "Next sentence."])
        self.assertIn("prev_ends_CI_clause.", rows[1]["boundary_reason"])

    def test_abbreviations_are_single_tokens(self):
        self.assertNotIn("et al", pa.ABBREVIATIONS)
        self.assertIn("al", pa.ABBREVIATIONS)

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

    def test_strongest_statement_wins_over_no_relationship(self):
        # Sumner appendix: "stronger statements trumped weaker ones" -> no level-1 override (removed in v3)
        lex = pa.compile_lexicon({**TINY_LEXICON, "entries": TINY_LEXICON["entries"] + [
            {"cue": "no increase", "pattern": r"\bno\s+increase\b", "level": 1, "type": "no_relationship"}]})
        sc = pa.score_sentence("There was no increase in risk although Drug X causes outcome Q.", lex)
        self.assertEqual(sc["level"], 6)
        self.assertEqual(sc["base_level"], 6)
        self.assertIn("mixed_levels_review", sc["review_flags"])
        self.assertNotIn("no_relationship_overrides_level>=5", sc["review_flags"])

    def test_modifier_must_precede_causal_cue(self):
        # Sumner levels 4/5: causal statement "preceded by" the modal
        self.assertEqual(pa.score_sentence("Drug X causes outcome Y, which may resolve.", TINY_LEXICON)["level"], 6)
        self.assertEqual(pa.score_sentence("Drug X may cause outcome Y.", TINY_LEXICON)["level"], 4)

    def test_negation_window_stops_at_clause_boundary(self):
        sc = pa.score_sentence("Drug X, but not drug W, was associated with outcome Y.", TINY_LEXICON)
        self.assertEqual(sc["level"], 2)
        self.assertNotIn("negation_window_applied", sc["review_flags"])

    def test_negation_window_flagged_for_review(self):
        sc = pa.score_sentence("Drug X was not associated with outcome Y.", TINY_LEXICON)
        self.assertIn("negation_window_applied", sc["review_flags"])

    def test_evidence_flags_do_not_set_level(self):
        lex = pa.compile_lexicon({**TINY_LEXICON, "entries": TINY_LEXICON["entries"] + [
            {"cue": "HR", "pattern": r"\b(?-i:HR)\b", "level": 2, "type": "effect_measure"},
            {"cue": "risk of", "pattern": r"\brisk\s+of\b", "level": 2, "type": "risk_language", "requires_cooccurrence": True}]})
        sc = pa.score_sentence("We estimated the HR to assess the risk of outcome Y.", lex)
        self.assertEqual(sc["level"], 0)
        self.assertEqual([m["cue"] for m in sc["evidence_flags"]], ["HR"])
        self.assertEqual(sc["matched_cues"], [])
        sc = pa.score_sentence("Drug X is associated with a risk of outcome Y.", lex)
        self.assertEqual(sc["level"], 2)
        self.assertEqual([m["cue"] for m in sc["matched_cues"]], ["associated with", "risk of"])
        self.assertEqual(pa.score_sentence("The hr was long.", lex)["evidence_flags"], [])

    def test_unanchored_pattern_warns_and_strict_raises(self):
        bad = {**TINY_LEXICON, "entries": [{"cue": "cause", "pattern": "caus", "level": 6}]}
        lex = pa.compile_lexicon(bad)
        self.assertEqual(len(lex["warnings"]), 1)
        self.assertIn("caus", lex["warnings"][0])
        with self.assertRaises(ValueError):
            pa.compile_lexicon(bad, strict=True)
        ok = {**TINY_LEXICON, "modifiers": TINY_LEXICON["modifiers"] + [
            {"cue": "nt", "pattern": "n't\\b", "effect": "negation_to_1", "allow_unanchored": True}]}
        self.assertEqual(pa.compile_lexicon(ok)["warnings"], [])
        self.assertEqual(pa.compile_lexicon(TINY_LEXICON)["warnings"], [])

    def test_nfkc_view_for_matching(self):
        # full-width letters are folded by NFKC before matching (W5 p.29)
        self.assertEqual(pa.score_sentence("Drug X ｃａｕｓｅｓ outcome Y.", TINY_LEXICON)["level"], 6)

    def test_missing_lexicon_fails_loudly(self):
        with self.assertRaises(FileNotFoundError):
            pa.load_lexicon(pathlib.Path("/nonexistent/lexicon.json"))
        with self.assertRaises(FileNotFoundError):
            pa.load_section_labels(pathlib.Path("/nonexistent/labels.json"))


class RealLexiconTests(unittest.TestCase):
    """Regression cases against the shipped scripts/certainty_lexicon_en.json."""

    @classmethod
    def setUpClass(cls):
        cls.lex = pa.load_lexicon(strict=True)  # every shipped pattern must be word-anchored

    def level(self, text):
        return pa.score_sentence(text, self.lex)["level"]

    def test_conjunction_or_and_hours_are_not_effect_measures(self):
        for s in ["Patients received 2 or 3 doses.", "Nausea lasted 24 hr after dosing.",
                  "Symptoms resolved in 1 or 2 patients within 24 hr.", "enrolled in 2019 or 2020"]:
            sc = pa.score_sentence(s, self.lex)
            self.assertEqual(sc["level"], 0, s)
            self.assertEqual(sc["evidence_flags"], [], s)

    def test_upper_case_abbreviations_are_evidence_flags(self):
        sc = pa.score_sentence("Risk was higher (HR 2.05; 95% CI 1.20–3.40; OR 2.0; P < .001).", self.lex)
        self.assertEqual(sc["level"], 0)
        self.assertEqual([m["cue"] for m in sc["evidence_flags"]],
                         ["hazard ratio / HR", "95% CI", "odds ratio / OR", "P value"])

    def test_increase_verb_only(self):
        self.assertEqual(self.level("An increase in weight was observed."), 0)
        self.assertEqual(self.level("The reduced events were noted."), 0)
        self.assertEqual(self.level("Semaglutide reduced weight."), 6)
        self.assertEqual(self.level("Semaglutide increases the risk of NAION."), 6)
        self.assertEqual(self.level("Semaglutide was associated with an increased risk of NAION."), 2)

    def test_methods_sentence_naming_statistics_is_level_0(self):
        sc = pa.score_sentence("We estimated hazard ratios using Cox models to assess the risk of NAION.", self.lex)
        self.assertEqual(sc["level"], 0)
        self.assertEqual([m["cue"] for m in sc["evidence_flags"]], ["hazard ratio / HR"])

    def test_requested_v3_corrections(self):
        self.assertEqual(self.level("Drug X is linked to outcome Y."), 3)
        self.assertEqual(self.level("Drug X predicts outcome Y."), 3)
        self.assertEqual(self.level("Drug X influences outcome Y."), 6)
        self.assertEqual(self.level("Drug X may increase outcome Y."), 4)
        self.assertEqual(self.level("Drug X can increase outcome Y."), 5)
        self.assertEqual(self.level("Drug X appears to increase outcome Y."), 4)
        self.assertEqual(self.level("No difference was observed."), 1)

    def test_seven_levels(self):
        self.assertEqual(self.level("Semaglutide causes NAION."), 6)
        self.assertEqual(self.level("Semaglutide can cause NAION."), 5)
        self.assertEqual(self.level("Semaglutide may cause NAION."), 4)
        self.assertEqual(self.level("The effect of semaglutide on NAION was studied."), 3)
        self.assertEqual(self.level("Semaglutide was associated with NAION."), 2)
        self.assertEqual(self.level("Semaglutide was not associated with NAION."), 1)
        self.assertEqual(self.level("Patients were enrolled from two centres."), 0)

    def test_data_driven_is_not_causal(self):
        self.assertEqual(self.level("A data-driven approach was used."), 0)

    def test_mixed_sentence_is_review_flagged(self):
        # v3: max level wins (Sumner appendix), the mixed sentence is only flagged
        sc = pa.score_sentence("Semaglutide increased the risk of NAION but was not associated with gastroparesis.", self.lex)
        self.assertEqual(sc["level"], 6)
        self.assertIn("mixed_levels_review", sc["review_flags"])
        sc = pa.score_sentence("X was not associated with Y but increases Z.", self.lex)
        self.assertEqual(sc["level"], 6)
        self.assertIn("mixed_levels_review", sc["review_flags"])

    def test_sumner_appendix_examples(self):
        # web appendix ww1 table of examples (verified_source_text)
        cases = {
            "X is linked to Y.": 3, "X predicts Y.": 3, "X is connected to Y.": 3,
            "X influences Y.": 6, "X enhances Y.": 6, "X prevents Y.": 6, "X leads to Y.": 6, "X is vital for Y.": 6,
            "X may increase Y.": 4, "X might increase Y.": 4, "X could increase Y.": 4, "X appears to increase Y.": 4,
            "X can increase Y.": 5,
            "X is associated with Y.": 2, "X is related to Y.": 2, "Y varies with X.": 2, "Y increases as X increases.": 2,
            "Users have higher rates of Y.": 2,
            "No difference was observed.": 1, "Y persists without X.": 1, "X does not result in Y.": 1,
            "There was no significant extra risk.": 1, "X added no benefit.": 1,
        }
        for text, lvl in cases.items():
            self.assertEqual(self.level(text), lvl, text)

    def test_sumner_article_examples(self):
        # BMJ 2014;349:g7015 Methods, one example per level (verified_source_text)
        self.assertEqual(self.level("Drinking wine is associated with increased cancer rates."), 2)
        self.assertEqual(self.level("Drinking wine linked to cancer risk."), 3)
        self.assertEqual(self.level("Drinking wine might increase cancer risk."), 4)
        self.assertEqual(self.level("Drinking wine can increase cancer risk."), 5)
        self.assertEqual(self.level("Drinking wine increases cancer risk."), 6)

    def test_contrastive_negation_is_not_level_1(self):
        # v2 known error fixed by the clause-boundary stop (Vincze 2008 scope boundary markers)
        self.assertEqual(self.level("Semaglutide, but not liraglutide, was associated with NAION."), 2)

    def test_explicitly_probabilistic_flag(self):
        sc = pa.score_sentence("Drug X was associated with a higher risk of outcome Y.", self.lex)
        self.assertEqual(sc["level"], 2)
        self.assertTrue(sc["explicitly_probabilistic"])
        self.assertIn("risk (of)", sc["probabilistic_cues"])
        sc = pa.score_sentence("Drug X raises the chance of outcome Y.", self.lex)
        self.assertEqual(sc["level"], 6)
        self.assertTrue(sc["explicitly_probabilistic"])
        # probabilistic word without a statement of relationship: listed, but flag stays False
        sc = pa.score_sentence("We assessed the risk of NAION.", self.lex)
        self.assertEqual(sc["level"], 0)
        self.assertEqual(sc["probabilistic_cues"], ["risk (of)"])
        self.assertFalse(sc["explicitly_probabilistic"])
        self.assertFalse(pa.score_sentence("Drug X is associated with outcome Y.", self.lex)["explicitly_probabilistic"])

    def test_hedge_question_is_not_causal(self):
        sc = pa.score_sentence("This raises the question of safety.", self.lex)
        self.assertEqual(sc["level"], 0)
        self.assertIn("raises the question of", sc["hedges"])

    def test_statuses_are_enumerated(self):
        d = json.loads(pa.LEXICON_PATH.read_text(encoding="utf-8"))
        allowed = set(d["provenance_policy"]["status_values"])
        for grp in ("entries", "modifiers", "hedges", "boosters", "probabilistic_cues"):
            for e in d[grp]:
                self.assertIn(e["status"], allowed, e["cue"])
                if e["status"] in ("project_addition", "project_extension_of_verified_category"):
                    self.assertEqual(e["source"], "project", e["cue"])
                if e["status"] == "project_extension_of_verified_category":
                    self.assertTrue(e.get("extends_category"), e["cue"])
                if e["status"] == "verified_source_text":
                    self.assertTrue(e.get("source_quote"), e["cue"])
                    self.assertIn(e["source"], {"sumner2014_appendix", "sumner2014", "vincze2008"}, e["cue"])
        self.assertNotIn("no_relationship_precedence", d["sentence_rule"]["status"])

    def test_verified_quotes_are_verbatim_source_text(self):
        # guard against labelling a cue verified when its phrase is not in the quoted source text: every
        # 'quoted' / “quoted” phrase in a Sumner-verified entry must occur verbatim in the source's verified_quotes
        d = json.loads(pa.LEXICON_PATH.read_text(encoding="utf-8"))
        excerpt = " ".join(q for src in d["sources"] if src["id"] in ("sumner2014", "sumner2014_appendix")
                           for q in src["verified_quotes"])
        for grp in ("entries", "modifiers", "probabilistic_cues"):
            for e in d[grp]:
                if e["status"] == "verified_source_text" and e["source"] == "sumner2014_appendix":
                    phrases = re.findall(r"'([^']+)'", e["source_quote"]) + re.findall(r"“([^”]+)”", e["source_quote"])
                    self.assertTrue(phrases, e["cue"])
                    for ph in phrases:
                        self.assertIn(ph, excerpt, e["cue"])


class AgreementTests(unittest.TestCase):
    def test_agreement_stats(self):
        pairs = [("단정", "단정"), ("가능성", "가능성"), ("연관", "무관"), ("무관", "무관")]
        st = pa.agreement_stats(pairs, {"단정": "단정", "가능성": "가능성", "연관": "연관·무관", "무관": "연관·무관"})
        self.assertEqual(st["n_pairs"], 4)
        self.assertAlmostEqual(st["simple_agreement"], 0.75)
        self.assertAlmostEqual(st["simple_agreement_group3"], 1.0)
        self.assertIsNotNone(st["cohen_kappa"])
        self.assertEqual(st["confusion"]["연관->무관"], 1)
        self.assertEqual(pa.agreement_stats([])["n_pairs"], 0)

    def test_kappa_formula(self):
        self.assertAlmostEqual(pa.cohen_kappa(["a", "b", "a"], ["a", "b", "b"]), 0.4)


class NormalizeTermsTests(unittest.TestCase):
    def test_candidate_surface_forms_are_opt_in(self):
        import normalize_terms as nt

        self.assertTrue(all(r["alias_source"].startswith("normalization.json") for r in nt.ALIAS_TABLE))
        self.assertTrue(any(r["alias_source"].startswith("standard_terms.json") for r in nt.ALIAS_TABLE_WITH_CANDIDATES))
        # Notion ⑨ example strings are normalization.json aliases -> matched by default
        ids = {m["entity_id"] for m in nt.normalize_text("비동맥염성 전방 허혈성 시신경병증과 세마글루타이드")}
        self.assertEqual(ids, {"NAION", "SEMAGLUTIDE"})
        # a predicted surface form is matched only on opt-in and is labelled by alias_source
        self.assertEqual(nt.normalize_text("자살 관념 보고"), [])
        m = nt.normalize_text("자살 관념 보고", include_candidate_forms=True)
        self.assertEqual([x["entity_id"] for x in m], ["SUICIDALITY"])
        self.assertEqual(m[0]["alias_source"], "standard_terms.json:surface_forms_added")


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

    def test_w3_filter_is_opt_in(self):
        toks = pa.tokenize_tfidf("No increase in HR was seen in the patients.")
        self.assertIn("no", toks)
        self.assertIn("hr", toks)
        filtered = pa.w3_filter_tokens(toks)
        self.assertNotIn("no", filtered)   # NLTK stopword (W3 p.47)
        self.assertNotIn("hr", filtered)   # len > 2 rule (W3 p.48)
        self.assertIn("increase", filtered)


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
        self.assertTrue(header.endswith("review_flag,ko_level_human,agree,note"))
        rep = json.loads((self.out / "preprocessing_report.json").read_text(encoding="utf-8"))
        self.assertTrue(rep["per_pmid"]["00000003"]["raw_missing"])
        self.assertFalse(rep["per_pmid"]["00000001"]["abstract_empty"])
        self.assertFalse(rep["per_pmid"]["00000001"]["analysis_text_empty"])
        self.assertEqual(rep["stages"]["agreement"]["status"], "deferred")  # no Korean labels yet
        self.assertIn("dictionary_status", rep)
        self.assertTrue((self.out / "HEURISTICS_LOG.md").exists())
        log = (self.out / "HEURISTICS_LOG.md").read_text(encoding="utf-8")
        self.assertIn("no_relationship", log)
        self.assertIn("certainty_lexicon_en.json", log)
        self.assertTrue((self.out / "tokens" / "00000002.json").exists())
        # idempotent: second run uses the translation cache and does not call translate again
        n_calls = len(calls)
        pa.run(["translate"], self.ctx, translate=fake_translate)
        self.assertEqual(len(calls), n_calls)

    def test_human_columns_survive_rerun_and_feed_agreement(self):
        pa.run(["clean", "sentences", "cues"], self.ctx, translate=lambda t: "x")
        path = self.out / "review_sheet.csv"
        import csv
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        target = next(r for r in rows if r["en_collapsed"])
        target["ko_level_human"] = target["en_collapsed"]
        target["note"] = "checked"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=pa.REVIEW_SHEET_COLS)
            w.writeheader()
            w.writerows(rows)
        pa.run(["cues", "agreement"], self.ctx, translate=lambda t: "x")
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            again = {r["sentence_id"]: r for r in csv.DictReader(f)}
        self.assertEqual(again[target["sentence_id"]]["note"], "checked")
        ag = self.ctx.report["stages"]["agreement"]
        self.assertEqual(ag["status"], "ok")
        self.assertEqual(ag["n_pairs"], 1)
        self.assertEqual(ag["simple_agreement"], 1.0)

    def test_agreement_from_ko_labels_file(self):
        pa.run(["clean", "sentences", "cues"], self.ctx, translate=lambda t: "x")
        cues = json.loads((self.out / "cues" / "00000002.json").read_text(encoding="utf-8"))["sentences"]
        labelled = [s for s in cues if s["collapsed_ko"]]
        ko = {s["sentence_id"]: ("무관" if s["collapsed_ko"] == "연관" else s["collapsed_ko"]) for s in labelled}
        kp = self.out / "ko.json"
        kp.write_text(json.dumps(ko, ensure_ascii=False), encoding="utf-8")
        self.ctx.ko_labels_path = kp
        pa.run(["agreement"], self.ctx)
        ag = self.ctx.report["stages"]["agreement"]
        self.assertEqual(ag["status"], "ok")
        self.assertEqual(ag["n_pairs"], len(ko))
        self.assertEqual(ag["simple_agreement_group3"], 1.0)

    def test_clean_then_sentences_inserts_sections(self):
        self.assertEqual(pa.resolve_stages(["clean", "sentences"]), ["clean", "sections", "sentences"])
        rc = pa.run(["clean", "sentences"], self.ctx)
        self.assertEqual(rc, 0)
        self.assertEqual(self.ctx.report["stages_run"], ["clean", "sections", "sentences"])
        self.assertGreater(self.ctx.per_pmid["00000001"]["n_sentences"], 0)
        # sentences without a prior sections enrichment fails with a message naming the fix
        for p in (self.out / "clean").glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            d.pop("analysis_text", None)
            p.write_text(json.dumps(d), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "sections"):
            pa.run(["sentences"], self.ctx)

    def test_labels_only_abstract_is_flagged(self):
        (self.raw / "00000003.json").write_text(json.dumps({"abstractText": "<h4>Background</h4><h4>Results</h4>"}), encoding="utf-8")
        pa.run(["clean", "sentences", "report"], self.ctx)
        f = self.ctx.report["per_pmid"]["00000003"]
        self.assertTrue(f["abstract_empty"])
        self.assertTrue(f["analysis_text_empty"])
        self.assertEqual(f["n_sentences"], 0)
        self.assertIn("00000003", self.ctx.report["stages"]["clean"]["empty"])

    def test_translate_failure_does_not_crash(self):
        def failing(text):
            raise RuntimeError("offline")

        rc = pa.run(["clean", "sections", "sentences", "translate", "cues", "report"], self.ctx, translate=failing)
        self.assertEqual(rc, 0)
        self.assertEqual(self.ctx.report["stages"]["translate"]["status"], "partial")
        tr = json.loads((self.out / "translations" / "00000001.json").read_text(encoding="utf-8"))
        self.assertTrue(all(r["text_ko"] is None for r in tr["sentences"]))

    def test_single_translate_failure_does_not_halt_corpus(self):
        calls = []

        def flaky(text):
            calls.append(text)
            if len(calls) == 1:
                raise ValueError("malformed response")
            return "번역"

        pa.run(["clean", "sentences", "translate"], self.ctx, translate=flaky)
        st = self.ctx.report["stages"]["translate"]
        self.assertEqual(st["status"], "partial")
        self.assertEqual(st["errors"], 1)
        self.assertGreater(st["translated_new"], 0)
        self.assertNotIn("error", st)  # endpoint was never declared unreachable


if __name__ == "__main__":
    unittest.main()
