#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""영어 초록 전처리 파이프라인 / English-abstract preprocessing pipeline.

Notion 계획 「영어 초록 전처리 제안」 ①–⑨ 를 아래 stage 로 구현한다. 각 stage 가 따르는
수업 자료(W3_2 Data Collection & Preprocessing, W5_1 Text Preprocessing 2; 페이지는
pdftotext 기준)와, 수업 기법으로 부족하여 다른 검증된 방법을 쓴 곳을 함께 적는다.

Stage → Notion ↔ lecture mapping
---------------------------------
 0 fetch     : Europe PMC REST (resultType=core) 로 초록 수집. W3 p.31 (requests 로 웹 수집)
               → 이 저장소 관례(collect_papers.py, make_validation_sample.py)대로 urllib 사용.
 1 clean     : Notion ①. <h4> 섹션 레이블을 먼저 보존한 뒤 BeautifulSoup.get_text() 로 태그 제거
               (W3 p.9-21 get_text), html.unescape 로 엔티티 복원, unicodedata.normalize('NFKC')
               (W5 p.29). 분석 텍스트는 casefold 하지 않음 (HR/CI/OR/NAION 약어 보존, Notion ⑦).
 2 sections  : Notion ②. scripts/nlm_section_labels.json (NLM 구조화 초록 범주) 로 keep/drop.
               비구조화 초록은 자동 분할하지 않고 needs_human_sectioning=true.
 3 sentences : Notion ③. nltk.sent_tokenize (Punkt; W3 p.33 punkt) + 약어 목록을 확장한
               PunktTokenizer 결과를 둘 다 보관, 다르면 boundary_check 플래그. 수업에는
               문장 분리 단원이 없어 NLTK Punkt (Kiss & Strunk 2006) 를 사용.
 4 translate : Notion ④. 문장 단위 EN→KO (Google Translate 웹 endpoint, 미문서화 → 휴리스틱 로그).
 5 cues      : Notion ⑥ (+⑤ 검수 sheet). scripts/certainty_lexicon_en.json (Sumner 2014 7단계)
               으로 문장 수준 산출. 부정 창(negation window)은 W5 p.30-33 '부정어 보존' 원칙을
               따르되 창 크기 자체는 프로젝트 휴리스틱(HEURISTICS_LOG 참조).
 6 tokens    : Notion ⑦⑧. (a) tokens_analysis: NFKC+casefold (W5 p.29) + W5 p.13-14 TOKEN_PATTERN
               (숫자·축약형 보존) 확장판; 불용어 제거·짧은 토큰 제거 없음 (W5 p.30-33).
               (b) tokens_tfidf: W3 p.44-48 수업 정제 re.sub(r'[^a-zA-Z\\s]',' ',lower()).split()
               — 글자만, TF-IDF 사본 전용. (c) stems: SnowballStemmer (W5 p.53-54 Porter 계열)
               을 tokens_tfidf 에만 적용, NER 먼저 (W5 p.61 'NER before stemming') 로 엔티티 보호.
 7 normalize : Notion ⑨. scripts/normalize_terms.normalize_text 로 용어 → entity_id.
 8 report    : abstracts/preprocessing_report.json + abstracts/HEURISTICS_LOG.md (한국어).

모든 stage 는 멱등(idempotent)이며 abstracts/ 아래에 디스크 캐시된다. 사용 예:
    python3 scripts/preprocess_abstracts.py                      # 모든 stage
    python3 scripts/preprocess_abstracts.py --stage clean --stage sentences
    python3 scripts/preprocess_abstracts.py --raw-dir /path/to/prefetched --out /tmp/x

Importable helpers: clean_abstract(html) -> dict, split_sections(clean, labels) -> dict,
split_sentences(text) -> list, translate_sentence(text) -> str, score_sentence(text, lexicon) -> dict,
tokenize_analysis(text) -> list, tokenize_tfidf(text) -> list.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import html
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_OUT = REPO / "abstracts"
CANDIDATES = REPO / "paper_candidates.json"
SECTION_LABELS_PATH = HERE / "nlm_section_labels.json"
LEXICON_PATH = HERE / "certainty_lexicon_en.json"

EPMC_HOST = "www.ebi.ac.uk"
EPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
TRANSLATE_HOST = "translate.googleapis.com"
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
TRANSLATE_TOOL = "Google Translate (translate.googleapis.com, client=gtx, undocumented web endpoint)"

STAGES = ["fetch", "clean", "sections", "sentences", "translate", "cues", "tokens", "normalize", "report"]

# ---------------------------------------------------------------------------
# Heuristic registry: every rule in this file that is NOT backed by a cited source is
# registered here and written to abstracts/HEURISTICS_LOG.md by the report stage.
# ---------------------------------------------------------------------------
HEURISTICS: list[dict[str, str]] = []


def _heuristic(what: str, where: str, why: str, verify: str) -> None:
    HEURISTICS.append({"what": what, "where": where, "why": why, "verify": verify})


# --- Notion ③ sentence splitting: abbreviation list ---------------------------------
# Project-documented list (HEURISTIC). Punkt (Kiss & Strunk 2006) learns abbreviations
# unsupervised; these are added because the Notion plan names them as mis-split risks.
ABBREVIATIONS = {"vs", "et al", "al", "e.g", "i.e", "dr", "fig", "no", "approx", "ca", "cf", "etc"}
# Unit abbreviations are NOT added by default: "… at 2.4 mg." is a common sentence end in
# dose statements (RQ2), and treating "mg." as an abbreviation merges two sentences.
ABBREVIATIONS_UNITS = {"mg", "kg"}
_heuristic(
    "Punkt 약어 목록 ABBREVIATIONS = {vs, et al, al, e.g, i.e, dr, fig, no, approx, ca, cf, etc}; "
    "단위 약어 {mg, kg} 는 --abbrev-units 로만 추가",
    "preprocess_abstracts.py ABBREVIATIONS / ABBREVIATIONS_UNITS, make_abbrev_tokenizer()",
    "Notion ③ 가 'vs.', 'et al.', 'e.g.' 등을 오분할 위험으로 지목. 'mg.' 는 용량 문장 끝에 흔해 "
    "기본 포함 시 두 문장이 합쳐지는 것을 픽스처에서 확인함.",
    "Punkt 가 학습한 abbrev_types 와 비교하고, 23편 초록의 boundary_check 행을 사람이 확인.",
)

# --- Notion ③ boundary-check regexes (previous sentence end) ---------------------------
BOUNDARY_END_PATTERNS = [
    (re.compile(r"\bvs\.$"), "prev_ends_vs."),
    (re.compile(r"\bet al\.$"), "prev_ends_et_al."),
    (re.compile(r"\b(?:e\.g|i\.e)\.$"), "prev_ends_e.g./i.e."),
    (re.compile(r"\bP\s*[<>=]\s*\.$"), "prev_ends_P<."),
    (re.compile(r"\d\.$"), "prev_ends_digit."),
    (re.compile(r"\bCI\b[^.]*\.$"), "prev_ends_CI_clause."),
    (re.compile(r"\bNo\.$"), "prev_ends_No."),
    (re.compile(r"\bFig\.$"), "prev_ends_Fig."),
]
BOUNDARY_START_PATTERN = re.compile(r"^[a-z0-9]")
# an abbreviation with a trailing period INSIDE a sentence (= a boundary that was NOT split)
INTERNAL_ABBREV_PATTERN = re.compile(
    r"\b(?:vs|et al|e\.g|i\.e|Dr|Fig|No|approx|ca|cf|etc)\.(?!$)", re.IGNORECASE
)
# a period followed by whitespace and a capital/digit INSIDE a sentence = a boundary Punkt chose not
# to split (e.g. "... at 2.4 mg. No increase ..." — pretrained Punkt lists 'mg' as an abbreviation)
INTERNAL_UNSPLIT_PATTERN = re.compile(r"\.\s+[A-Z0-9]")
_heuristic(
    "문장 경계 점검 정규식 BOUNDARY_END_PATTERNS / BOUNDARY_START_PATTERN / INTERNAL_ABBREV_PATTERN / "
    "INTERNAL_UNSPLIT_PATTERN('. ' 뒤 대문자·숫자가 문장 안에 남아 있으면 플래그)",
    "preprocess_abstracts.py split_sentences(), flag_boundaries()",
    "Notion ③ 의 예시('vs.', 'et al.', '95% CI 1.2–3.4', 'P < .001', 'e.g.', 'i.e.', 'Dr.', 'Fig.', "
    "'No.', 'approx.')를 정규식으로 옮긴 것. 출처 없는 프로젝트 규칙이며 재현율을 보장하지 않음. "
    "추가로 사전학습 Punkt 가 'mg' 를 약어로 알고 있어 '... at 2.4 mg. No increase ...' 를 한 문장으로 합치는 것을 "
    "픽스처에서 확인했으므로, 문장 내부에 남은 '. + 대문자' 경계도 사람 확인 대상으로 플래그한다.",
    "boundary_check=true 문장을 전수 사람 검토; 놓친 오분할은 검수 sheet note 에 기록.",
)

# --- Notion ⑦⑧ tokenizer ---------------------------------------------------------------
# W5 p.13-14 TOKEN_PATTERN = [A-Za-z]+(?:'[A-Za-z]+)+ | [A-Za-z]+ | \d+(?:\.\d+)?   (verified lecture)
W5_TOKEN_PATTERN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)+|[A-Za-z]+|\d+(?:\.\d+)?")
# Extension (HEURISTIC): + percentages '95%' as one token, + hyphenated words 'non-arteritic',
# 'GLP-1' kept as one token; en-dash ranges '1.20–3.40' fall out as two numbers because '–'
# matches nothing. Applied after NFKC + casefold (W5 p.29), so [a-z] suffices.
TOKEN_PATTERN_ANALYSIS = re.compile(
    r"[a-z]+(?:'[a-z]+)+"            # contractions (W5 p.14 #1, p.32 option 1)
    r"|[a-z0-9]+(?:-[a-z0-9]+)+"     # hyphenated abbreviations / compounds (extension)
    r"|[a-z]+"                       # plain words (W5 p.14 #2)
    r"|\d+(?:\.\d+)?%"               # percentages (extension, Notion ⑧)
    r"|\d+(?:\.\d+)?"                # numbers incl. decimals (W5 p.14 #3)
    r"|\.\d+"                        # leading-dot decimals 'P < .001' (extension, JAMA style)
)
_heuristic(
    "TOKEN_PATTERN_ANALYSIS: W5 TOKEN_PATTERN 에 '\\d+(?:\\.\\d+)?%' (퍼센트), "
    "'[a-z0-9]+(?:-[a-z0-9]+)+' (하이픈 결합어: non-arteritic, glp-1), '\\.\\d+' (P < .001 의 '.001') 세 대안을 추가",
    "preprocess_abstracts.py TOKEN_PATTERN_ANALYSIS, tokenize_analysis()",
    "Notion ⑧ '숫자 보존'(2.4 mg, HR 2.05, 95% CI) 과 약어 보존을 위해. W5 p.14 는 세 대안만 제시하므로 "
    "확장은 프로젝트 결정.",
    "23편 초록에서 '%' 포함 토큰과 하이픈 토큰 빈도표를 뽑아 분할 오류가 없는지 확인.",
)
# W3 p.45 lecture cleaning (verified from lecture text): re.sub(r'[^a-zA-Z\s]', ' ', ...)
LECTURE_CLEAN_PATTERN = re.compile(r"[^a-zA-Z\s]")

_WS = re.compile(r"\s+")


def utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _require(path: pathlib.Path, what: str) -> Any:
    if not path.exists():
        raise FileNotFoundError(
            f"{what} not found: {path}\n"
            f"This pipeline refuses to run without it (no silent fallback). "
            f"Create it per the contract in preprocess_abstracts.py or point --out/--raw-dir correctly."
        )
    return _read_json(path)


# ===========================================================================
# Stage 0: fetch
# ===========================================================================
def epmc_url(pmid: str) -> str:
    q = urllib.parse.urlencode({"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "resultType": "core"})
    return EPMC_URL + "?" + q


def fetch_one(pmid: str, retries: int = 3, timeout: int = 40) -> dict[str, Any]:
    """GET Europe PMC core record; 3 retries like collect_papers.py."""
    url = epmc_url(pmid)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                data = json.load(r)
            return {"pmid": pmid, "url": url, "fetched_at": utcnow(), "response": data}
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries - 1:
                time.sleep(1.0)
    raise RuntimeError(f"fetch failed for pmid {pmid} after {retries} attempts: {last}")


def stage_fetch(ctx: "Ctx") -> int:
    raw_dir = ctx.out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    n_ok = n_cached = 0
    for p in ctx.papers:
        pmid = p["pmid"]
        dest = raw_dir / f"{pmid}.json"
        if dest.exists():
            n_cached += 1
            continue
        try:
            _write_json(dest, fetch_one(pmid))
            n_ok += 1
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            ctx.report["stages"]["fetch"] = {"status": "failed", "error": msg, "fetched": n_ok, "cached": n_cached}
            print(
                f"[fetch] FAILED for pmid {pmid}: {msg}\n"
                f"[fetch] network host that must be allowed: {EPMC_HOST} (HTTPS). "
                f"Other stages still run on whatever exists under {raw_dir} or --raw-dir.",
                file=sys.stderr,
            )
            return 2
    ctx.report["stages"]["fetch"] = {"status": "ok", "fetched": n_ok, "cached": n_cached}
    print(f"[fetch] fetched {n_ok}, cached {n_cached}")
    return 0


def load_raw_record(path: pathlib.Path) -> dict[str, Any]:
    """Accept (a) this pipeline's wrapper {pmid,url,fetched_at,response}, (b) a raw Europe PMC
    search response, or (c) a single Europe PMC result record."""
    d = _read_json(path)
    if isinstance(d, dict) and "response" in d:
        d = d["response"]
    if isinstance(d, dict) and "resultList" in d:
        res = d["resultList"].get("result", [])
        return res[0] if res else {}
    return d if isinstance(d, dict) else {}


# ===========================================================================
# Stage 1: clean (Notion ①)
# ===========================================================================
_H4 = re.compile(r"<h4[^>]*>(.*?)</h4>", re.IGNORECASE | re.DOTALL)


def strip_html(fragment: str) -> str:
    """BeautifulSoup.get_text (W3 p.9-21) + html.unescape + NFKC (W5 p.29) + whitespace collapse.
    No casefold: the analysis text keeps HR/CI/OR/NAION (Notion ⑦)."""
    from bs4 import BeautifulSoup  # lecture W3 dependency

    text = BeautifulSoup(fragment, "html.parser").get_text(" ")
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    return _WS.sub(" ", text).strip()


def normalize_label(label: str) -> str:
    """nlm_section_labels.json matching_rule: upper, strip trailing ':' '.', collapse whitespace."""
    s = strip_html(label).upper()
    s = re.sub(r"[:.\s]+$", "", s)
    return _WS.sub(" ", s).strip()


def clean_abstract(abstract_html: str) -> dict[str, Any]:
    """Notion ①: capture <h4> labels in order with their following text, then strip tags."""
    raw = abstract_html or ""
    sections: list[dict[str, Any]] = []
    matches = list(_H4.finditer(raw))
    structured = bool(matches)
    if structured:
        preamble = raw[: matches[0].start()]
        if strip_html(preamble):
            sections.append({"label_raw": "", "label_norm": "", "text": strip_html(preamble)})
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            sections.append({
                "label_raw": html.unescape(m.group(1)).strip(),
                "label_norm": normalize_label(m.group(1)),
                "text": strip_html(raw[m.end():end]),
            })
    clean = strip_html(raw)
    return {
        "abstract_raw_html": raw,
        "abstract_clean": clean,
        "structured": structured,
        "sections": sections,
    }


def stage_clean(ctx: "Ctx") -> int:
    n = 0
    for p in ctx.papers:
        pmid = p["pmid"]
        src = ctx.raw_dir / f"{pmid}.json"
        if not src.exists():
            ctx.flags(pmid)["raw_missing"] = True
            continue
        rec = load_raw_record(src)
        info = clean_abstract(rec.get("abstractText", ""))
        out = {"pmid": pmid, "title": p.get("title") or rec.get("title", ""), "side_effect": p.get("side_effect"),
               "selection_role": p.get("selection_role"), **info, "needs_human_sectioning": not info["structured"],
               "cleaned_at": utcnow()}
        _write_json(ctx.out / "clean" / f"{pmid}.json", out)
        f = ctx.flags(pmid)
        f["structured"] = info["structured"]
        f["abstract_empty"] = not info["abstract_clean"]
        n += 1
    ctx.report["stages"]["clean"] = {"status": "ok", "n": n}
    print(f"[clean] {n} abstracts")
    return 0


# ===========================================================================
# Stage 2: sections (Notion ②)
# ===========================================================================
def load_section_labels(path: pathlib.Path = SECTION_LABELS_PATH) -> dict[str, Any]:
    d = _require(path, "section label table (scripts/nlm_section_labels.json)")
    for k in ("categories", "labels"):
        if k not in d:
            raise ValueError(f"{path}: missing key '{k}' (contract violation)")
    return d


def classify_label(label_norm: str, table: dict[str, Any]) -> tuple[str, str]:
    """Return (category, action) where action in keep/drop/needs_human."""
    cats = table["categories"]
    entry = table["labels"].get(label_norm)
    if entry is None:
        return "UNKNOWN", cats.get("UNKNOWN", "needs_human")
    cat = entry.get("category", "UNKNOWN")
    override = entry.get("action")
    if override == "drop_non_content":
        return cat, "drop"
    if override == "keep_as_results":
        return cat, "keep"
    return cat, cats.get(cat, "needs_human")


def split_sections(clean: dict[str, Any], table: dict[str, Any]) -> dict[str, Any]:
    """Apply keep/drop; unstructured → whole text + needs_human_sectioning; UNKNOWN → keep text but flag."""
    needs_human = not clean["structured"]
    sections = []
    kept_parts = []
    for s in clean.get("sections", []):
        if s["label_norm"] == "":
            cat, action = "UNKNOWN", "needs_human"  # text before the first <h4>
        else:
            cat, action = classify_label(s["label_norm"], table)
        keep = action in ("keep", "needs_human")   # UNKNOWN: keep its text, flag for human (project decision)
        if action == "needs_human":
            needs_human = True
        sec = {**s, "category": cat, "keep": keep, "action": action}
        sections.append(sec)
        if keep and s["text"]:
            kept_parts.append(sec)
    if clean["structured"]:
        analysis_text = " ".join(x["text"] for x in kept_parts)
    else:
        analysis_text = clean["abstract_clean"]
    return {"sections": sections, "analysis_text": analysis_text, "needs_human_sectioning": needs_human,
            "kept_sections": [(x["label_norm"], x["category"], x["text"]) for x in kept_parts]}


_heuristic(
    "UNKNOWN 레이블 섹션(및 첫 <h4> 앞 텍스트)을 버리지 않고 분석 텍스트에 포함한 채 needs_human_sectioning=true 로 표시",
    "preprocess_abstracts.py split_sections()",
    "자동으로 버리면 결과·결론 문장을 잃을 수 있고, 자동으로 남기면 배경 문장이 섞일 수 있어 사람이 판단하도록 둠 "
    "(nlm_section_labels.json fallback 규칙 'never auto keep/drop' 과 일치).",
    "needs_human_sectioning=true 인 초록의 섹션을 사람이 keep/drop 결정 후 재실행.",
)


def stage_sections(ctx: "Ctx") -> int:
    table = load_section_labels(ctx.section_labels_path)
    n = 0
    for pmid, clean_path in ctx.iter_clean():
        clean = _read_json(clean_path)
        res = split_sections(clean, table)
        clean.update({"sections": res["sections"], "analysis_text": res["analysis_text"],
                      "needs_human_sectioning": res["needs_human_sectioning"],
                      "section_table_version": table.get("version")})
        _write_json(clean_path, clean)
        at = ctx.out / "analysis_text"
        at.mkdir(parents=True, exist_ok=True)
        (at / f"{pmid}.txt").write_text(res["analysis_text"] + "\n", encoding="utf-8")
        f = ctx.flags(pmid)
        f["needs_human_sectioning"] = res["needs_human_sectioning"]
        f["unknown_labels"] = sorted({s["label_norm"] for s in res["sections"] if s["action"] == "needs_human" and s["label_norm"]})
        n += 1
    ctx.report["stages"]["sections"] = {"status": "ok", "n": n}
    print(f"[sections] {n} abstracts")
    return 0


# ===========================================================================
# Stage 3: sentences (Notion ③)
# ===========================================================================
def make_abbrev_tokenizer(extra: set[str] | None = None):
    from nltk.tokenize.punkt import PunktTokenizer

    tok = PunktTokenizer("english")  # pretrained english Punkt parameters (punkt_tab)
    tok._params.abbrev_types.update(ABBREVIATIONS | (extra or set()))
    return tok


def split_sentences(text: str, extra_abbrev: set[str] | None = None) -> list[dict[str, Any]]:
    """Return abbreviation-aware sentences, each with default-punkt comparison and boundary flags."""
    import nltk

    default = [s.strip() for s in nltk.sent_tokenize(text) if s.strip()]
    tok = make_abbrev_tokenizer(extra_abbrev)
    aware = [s.strip() for s in tok.tokenize(text) if s.strip()]
    default_set = set(default)
    out = []
    for i, s in enumerate(aware):
        reasons: list[str] = []
        if s not in default_set:
            reasons.append("punkt_default_differs")
        m = INTERNAL_ABBREV_PATTERN.search(s)
        if m:
            reasons.append(f"contains_abbreviation:{m.group(0)}")
        m2 = INTERNAL_UNSPLIT_PATTERN.search(s)
        if m2:
            reasons.append(f"unsplit_period_before_capital:{s[max(0, m2.start() - 6):m2.end()].strip()}")
        if i > 0:
            prev = aware[i - 1]
            for pat, name in BOUNDARY_END_PATTERNS:
                if pat.search(prev):
                    reasons.append(name)
            if BOUNDARY_START_PATTERN.match(s):
                reasons.append("starts_lowercase_or_digit")
        out.append({"text_en": s, "boundary_check": bool(reasons), "boundary_reason": ";".join(reasons)})
    return out


def flag_boundaries(sentences: list[str]) -> list[dict[str, Any]]:
    """Apply only the regex boundary checks to an already-split list (used in tests)."""
    out = []
    for i, s in enumerate(sentences):
        reasons = []
        if i > 0:
            for pat, name in BOUNDARY_END_PATTERNS:
                if pat.search(sentences[i - 1]):
                    reasons.append(name)
            if BOUNDARY_START_PATTERN.match(s):
                reasons.append("starts_lowercase_or_digit")
        out.append({"text_en": s, "boundary_check": bool(reasons), "boundary_reason": ";".join(reasons)})
    return out


def sentences_for_abstract(clean: dict[str, Any], extra_abbrev: set[str] | None = None) -> list[dict[str, Any]]:
    pmid = clean["pmid"]
    units: list[tuple[str, str, str]]
    if clean["structured"]:
        units = [(s["label_norm"], s["category"], s["text"]) for s in clean["sections"] if s.get("keep") and s["text"]]
    else:
        units = [("", "UNSTRUCTURED", clean["analysis_text"])]
    rows = []
    idx = 0
    for label, cat, text in units:
        for s in split_sentences(text, extra_abbrev):
            rows.append({"sentence_id": f"{pmid}_s{idx:03d}", "section_label": label, "section_category": cat, **s})
            idx += 1
    return rows


def stage_sentences(ctx: "Ctx") -> int:
    n = n_flag = 0
    for pmid, clean_path in ctx.iter_clean():
        clean = _read_json(clean_path)
        if "analysis_text" not in clean:
            raise RuntimeError(f"{pmid}: run the 'sections' stage before 'sentences'")
        rows = sentences_for_abstract(clean, ctx.extra_abbrev)
        _write_json(ctx.out / "sentences" / f"{pmid}.json", {"pmid": pmid, "sentences": rows, "split_at": utcnow(),
                    "abbreviations": sorted(ABBREVIATIONS | ctx.extra_abbrev)})
        f = ctx.flags(pmid)
        f["n_sentences"] = len(rows)
        f["n_boundary_checks"] = sum(r["boundary_check"] for r in rows)
        n += len(rows)
        n_flag += f["n_boundary_checks"]
    ctx.report["stages"]["sentences"] = {"status": "ok", "n_sentences": n, "n_boundary_checks": n_flag}
    print(f"[sentences] {n} sentences, {n_flag} flagged for boundary check")
    return 0


# ===========================================================================
# Stage 4: translate (Notion ④)
# ===========================================================================
_heuristic(
    "번역 도구로 미문서화 Google Translate 웹 endpoint (translate_a/single, client=gtx) 사용",
    "preprocess_abstracts.py translate_sentence()",
    "컨테이너에서 접근 가능한 유일한 번역 경로. 공식 API 가 아니며 응답 형식·가용성이 바뀔 수 있음. "
    "도구명·endpoint·일시를 각 문장에 기록(Notion ④).",
    "가능하면 공식 Cloud Translation API 또는 DeepL API 로 재번역하고 tool 필드를 갱신; 검수 sheet(⑤)로 사람 대조.",
)


def translate_sentence(text: str, sl: str = "en", tl: str = "ko", retries: int = 3, timeout: int = 20) -> str:
    q = urllib.parse.urlencode({"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": text})
    url = TRANSLATE_URL + "?" + q
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (wegovy-research-package)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            return "".join(seg[0] for seg in data[0] if seg and seg[0])
        except urllib.error.URLError as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.0 + attempt)
        except Exception as e:  # noqa: BLE001
            last = e
            break
    raise RuntimeError(f"translate failed: {last}")


def stage_translate(ctx: "Ctx", translate=translate_sentence, sleep: float = 0.5) -> int:
    n_new = n_cached = 0
    unreachable: str | None = None
    for pmid, sent_path in ctx.iter_sentences():
        sents = _read_json(sent_path)["sentences"]
        dest = ctx.out / "translations" / f"{pmid}.json"
        tr = _read_json(dest) if dest.exists() else {"pmid": pmid, "sentences": []}
        done = {r["sentence_id"]: r for r in tr["sentences"] if r.get("text_ko")}
        rows = []
        for s in sents:
            sid = s["sentence_id"]
            if sid in done and done[sid]["text_en"] == s["text_en"]:
                rows.append(done[sid])
                n_cached += 1
                continue
            row = {"sentence_id": sid, "text_en": s["text_en"], "text_ko": None, "tool": TRANSLATE_TOOL,
                   "endpoint": TRANSLATE_URL, "translated_at": None, "error": None}
            if unreachable is None:
                try:
                    row["text_ko"] = translate(s["text_en"])
                    row["translated_at"] = utcnow()
                    n_new += 1
                    time.sleep(sleep)
                except Exception as e:  # noqa: BLE001
                    row["error"] = str(e)
                    unreachable = str(e)
            else:
                row["error"] = "skipped: endpoint unreachable earlier in this run"
            rows.append(row)
        tr["sentences"] = rows
        _write_json(dest, tr)
        ctx.flags(pmid)["n_translated"] = sum(1 for r in rows if r.get("text_ko"))
    status = {"status": "ok" if unreachable is None else "partial", "translated_new": n_new, "cached": n_cached,
              "tool": TRANSLATE_TOOL, "endpoint": TRANSLATE_URL}
    if unreachable:
        status["error"] = unreachable
        status["host_to_allow"] = TRANSLATE_HOST
        print(f"[translate] endpoint unreachable ({unreachable}); host to allow: {TRANSLATE_HOST}. Continuing.", file=sys.stderr)
    ctx.report["stages"]["translate"] = status
    print(f"[translate] new {n_new}, cached {n_cached}")
    return 0


# ===========================================================================
# Stage 5: cues (Notion ⑥) + review sheet (Notion ⑤)
# ===========================================================================
def load_lexicon(path: pathlib.Path = LEXICON_PATH) -> dict[str, Any]:
    d = _require(path, "English certainty lexicon (scripts/certainty_lexicon_en.json)")
    for k in ("entries", "modifiers", "levels"):
        if k not in d:
            raise ValueError(f"{path}: missing key '{k}' (contract violation)")
    return compile_lexicon(d)


def compile_lexicon(d: dict[str, Any]) -> dict[str, Any]:
    """Compile patterns case-insensitively. Cue lists (associational_cues, causal_cues,
    no_relationship_cues, ambiguous_cues) may hold entry dicts (contract) or cue-name strings
    that reference `entries` (current file); both are accepted and de-duplicated."""
    by_cue = {e["cue"]: e for e in d["entries"]}
    cues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(e: dict[str, Any]) -> None:
        key = (e["cue"], e["pattern"])
        if key in seen:
            return
        seen.add(key)
        cues.append({"cue": e["cue"], "level": int(e["level"]), "type": e.get("type"),
                     "regex": re.compile(e["pattern"], re.IGNORECASE)})

    for e in d["entries"]:
        add(e)
    for key in ("associational_cues", "causal_cues", "no_relationship_cues", "ambiguous_cues"):
        for item in d.get(key, []):
            if isinstance(item, dict) and "pattern" in item:
                add(item)
            elif isinstance(item, str) and item in by_cue:
                add(by_cue[item])
    mods = [{"cue": m["cue"], "effect": m["effect"], "regex": re.compile(m["pattern"], re.IGNORECASE)}
            for m in d["modifiers"]]
    hedges = [{"cue": h["cue"], "regex": re.compile(h["pattern"], re.IGNORECASE)} for h in d.get("hedges", [])]
    boosters = [{"cue": b["cue"], "regex": re.compile(b["pattern"], re.IGNORECASE)} for b in d.get("boosters", [])]
    levels = {str(k): v for k, v in d["levels"].items()}
    window = int(d.get("sentence_rule", {}).get("negation_window_tokens", 5))
    return {"cues": cues, "modifiers": mods, "hedges": hedges, "boosters": boosters, "levels": levels,
            "negation_window_tokens": window, "version": d.get("version")}


_heuristic(
    "부정 창(negation window): 부정 수식어가 인과/연관 단서보다 앞 N 토큰(기본 5, 사전의 sentence_rule.negation_window_tokens) 안에 있으면 level 1",
    "preprocess_abstracts.py score_sentence()",
    "Sumner 2014 는 문장 전체를 사람이 코딩하고, BioScope 류는 구문으로 부정 범위를 정함. 고정 창은 프로젝트 근사치. "
    "W5 p.30-33 '부정어(not/never/without) 보존' 원칙은 수업 출처.",
    "level 1 로 판정된 문장과 부정어가 있으나 level≥2 로 남은 문장을 검수 sheet 에서 사람이 확인; "
    "가능하면 NegEx(Chapman 2001) 같은 검증된 부정 탐지와 비교.",
)


def _token_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in W5_TOKEN_PATTERN.finditer(text)]


def _token_index(spans: list[tuple[int, int]], char_pos: int) -> int:
    for i, (s, e) in enumerate(spans):
        if e > char_pos:
            return i
    return len(spans)


def score_sentence(text: str, lexicon: dict[str, Any]) -> dict[str, Any]:
    """Sumner-2014 style sentence level: max cue level, then modifiers (see lexicon sentence_rule)."""
    if "cues" not in lexicon:
        lexicon = compile_lexicon(lexicon)
    matches = []
    for c in lexicon["cues"]:
        for m in c["regex"].finditer(text):
            matches.append({"cue": c["cue"], "level": c["level"], "span": [m.start(), m.end()], "text": m.group(0)})
    matches.sort(key=lambda x: x["span"][0])
    base = max((m["level"] for m in matches), default=0)
    level = base
    applied: list[str] = []
    mod_hits = {}
    for mod in lexicon["modifiers"]:
        hits = [(m.start(), m.end()) for m in mod["regex"].finditer(text)]
        if hits:
            mod_hits[mod["cue"]] = (mod["effect"], hits)
    # explicit no-relationship cue (level 1 entry) wins over everything (lexicon sentence_rule step 5)
    if any(m["level"] == 1 for m in matches) and base >= 2:
        level = 1
        applied.append("no_relationship_cue")
    else:
        if level == 6 and any(eff == "level_5" for eff, _ in mod_hits.values()):
            level = 5
            applied.append("level_5")
        if level >= 5 and any(eff == "downgrade_to_4" for eff, _ in mod_hits.values()):
            level = 4
            applied.append("downgrade_to_4")
        if level >= 2:
            spans = _token_spans(text)
            win = lexicon["negation_window_tokens"]
            neg_positions = [h for eff, hs in mod_hits.values() if eff == "negation_to_1" for h in hs]
            for m in matches:
                if m["level"] < 2:
                    continue
                ci = _token_index(spans, m["span"][0])
                for ns, _ne in neg_positions:
                    ni = _token_index(spans, ns)
                    if 0 <= ci - ni <= win:
                        level = 1
                        applied.append(f"negation_to_1(window={win})")
                        break
                if level == 1:
                    break
    hedges = sorted({h["cue"] for h in lexicon["hedges"] if h["regex"].search(text)})
    boosters = sorted({b["cue"] for b in lexicon["boosters"] if b["regex"].search(text)})
    lv = lexicon["levels"].get(str(level), {})
    return {"base_level": base, "level": level, "collapsed_ko": lv.get("collapsed_ko"),
            "level_name_en": lv.get("name_en"), "matched_cues": matches,
            "modifiers": {k: v[0] for k, v in mod_hits.items()}, "applied": applied,
            "hedges": hedges, "boosters": boosters}


def stage_cues(ctx: "Ctx") -> int:
    lex = load_lexicon(ctx.lexicon_path)
    n_cue = n = 0
    rows_csv = []
    for pmid, sent_path in ctx.iter_sentences():
        sents = _read_json(sent_path)["sentences"]
        tpath = ctx.out / "translations" / f"{pmid}.json"
        ko = {r["sentence_id"]: r.get("text_ko") for r in _read_json(tpath)["sentences"]} if tpath.exists() else {}
        side = ctx.paper_by_pmid.get(pmid, {}).get("side_effect", "")
        out = []
        for s in sents:
            sc = score_sentence(s["text_en"], lex)
            has_cue = bool(sc["matched_cues"] or sc["hedges"] or sc["boosters"])
            n_cue += has_cue
            n += 1
            out.append({"sentence_id": s["sentence_id"], "section_label": s["section_label"], "text_en": s["text_en"], **sc})
            rows_csv.append({
                "sentence_id": s["sentence_id"], "pmid": pmid, "side_effect": side, "section": s["section_label"],
                "text_en": s["text_en"], "text_ko": ko.get(s["sentence_id"]) or "",
                "en_level": sc["level"], "en_collapsed": sc["collapsed_ko"] or "",
                "matched_cues": "; ".join(f"{m['cue']}({m['level']})" for m in sc["matched_cues"]),
                "hedges": "; ".join(sc["hedges"]), "boosters": "; ".join(sc["boosters"]),
                "boundary_check": s["boundary_check"], "ko_level_human": "", "agree": "", "note": "",
                "_has_cue": has_cue,
            })
        _write_json(ctx.out / "cues" / f"{pmid}.json", {"pmid": pmid, "lexicon_version": lex.get("version"),
                    "scored_at": utcnow(), "sentences": out})
        ctx.flags(pmid)["n_cue_sentences"] = sum(1 for r in out if r["matched_cues"] or r["hedges"] or r["boosters"])
    rows_csv.sort(key=lambda r: (not r["_has_cue"], r["sentence_id"]))
    cols = ["sentence_id", "pmid", "side_effect", "section", "text_en", "text_ko", "en_level", "en_collapsed",
            "matched_cues", "hedges", "boosters", "boundary_check", "ko_level_human", "agree", "note"]
    with (ctx.out / "review_sheet.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_csv)
    ctx.report["stages"]["cues"] = {"status": "ok", "n_sentences": n, "n_cue_sentences": n_cue,
                                    "lexicon_version": lex.get("version")}
    print(f"[cues] {n} sentences, {n_cue} with cues -> review_sheet.csv")
    return 0


# ===========================================================================
# Stage 6: tokens (Notion ⑦⑧)
# ===========================================================================
def tokenize_analysis(text: str) -> list[str]:
    """NFKC + casefold (W5 p.29) then TOKEN_PATTERN_ANALYSIS. No stopword removal, no length
    filter, numbers kept (Notion ⑦⑧; W5 p.30-32: keep not/never/without, do not blindly drop short tokens)."""
    return TOKEN_PATTERN_ANALYSIS.findall(unicodedata.normalize("NFKC", text).casefold())


def tokenize_tfidf(text: str) -> list[str]:
    """W3 p.44-45 lecture cleaning: lower() -> re.sub(r'[^a-zA-Z\\s]', ' ') -> split(). Letters only.
    Used ONLY for the TF-IDF copy (Notion ⑧)."""
    return LECTURE_CLEAN_PATTERN.sub(" ", text.lower()).split()


def _entity_tokens(text: str, normalize_text) -> set[str]:
    """Tokens (lecture cleaning) covered by entity mentions -> protected from stemming (W5 p.61)."""
    protected: set[str] = set()
    for ent in normalize_text(text):
        protected.update(tokenize_tfidf(ent.get("matched_text") or ent.get("matched_alias") or ""))
    return protected


def stem_tokens(tokens: list[str], protected: set[str] | None = None) -> list[str]:
    from nltk.stem import SnowballStemmer

    st = SnowballStemmer("english")
    protected = protected or set()
    return [t if t in protected else st.stem(t) for t in tokens]


def stage_tokens(ctx: "Ctx") -> int:
    nt = ctx.normalize_terms()
    n = 0
    for pmid, sent_path in ctx.iter_sentences():
        sents = _read_json(sent_path)["sentences"]
        rows = []
        for s in sents:
            protected = _entity_tokens(s["text_en"], nt) if nt else set()
            tf = tokenize_tfidf(s["text_en"])
            rows.append({
                "sentence_id": s["sentence_id"],
                "tokens_analysis": tokenize_analysis(s["text_en"]),
                "tokens_tfidf": tf,
                "tokens_tfidf_label": "tfidf_copy_lecture_cleaning",
                "stems_tfidf": stem_tokens(tf, protected),
                "protected_entity_tokens": sorted(protected),
            })
            n += 1
        _write_json(ctx.out / "tokens" / f"{pmid}.json", {
            "pmid": pmid, "tokenized_at": utcnow(),
            "tokens_analysis_rule": "NFKC+casefold (W5 p.29) + TOKEN_PATTERN_ANALYSIS (W5 p.13-14 extended; see HEURISTICS_LOG); "
                                    "no stopwords, no length filter, numbers kept (Notion ⑦⑧, W5 p.30-33)",
            "tokens_tfidf_rule": "W3 p.44-45: lower(); re.sub(r'[^a-zA-Z\\s]',' '); split()  (letters only)",
            "stems_rule": "nltk SnowballStemmer('english') on tokens_tfidf only (W5 p.53-54); entity tokens protected (W5 p.61 NER before stemming)",
            "normalize_terms_available": bool(nt), "normalize_terms_error": ctx.normalize_terms_error,
            "sentences": rows})
    ctx.report["stages"]["tokens"] = {"status": "ok", "n_sentences": n, "normalize_terms_available": bool(nt),
                                      "normalize_terms_error": ctx.normalize_terms_error}
    print(f"[tokens] {n} sentences")
    return 0


# ===========================================================================
# Stage 7: normalize (Notion ⑨)
# ===========================================================================
def stage_normalize(ctx: "Ctx") -> int:
    nt = ctx.normalize_terms()
    if not nt:
        ctx.report["stages"]["normalize"] = {"status": "skipped", "error": ctx.normalize_terms_error}
        print(f"[normalize] skipped: {ctx.normalize_terms_error}", file=sys.stderr)
        return 0
    n = 0
    for pmid, sent_path in ctx.iter_sentences():
        sents = _read_json(sent_path)["sentences"]
        tpath = ctx.out / "translations" / f"{pmid}.json"
        ko = {r["sentence_id"]: r.get("text_ko") for r in _read_json(tpath)["sentences"]} if tpath.exists() else {}
        rows = []
        for s in sents:
            def slim(ents):
                return [{"entity_id": e["entity_id"], "matched_alias": e["matched_alias"],
                         "matched_text": e.get("matched_text"), "start": e["start"], "end": e["end"]} for e in ents]
            row = {"sentence_id": s["sentence_id"], "entities_en": slim(nt(s["text_en"]))}
            k = ko.get(s["sentence_id"])
            row["entities_ko"] = slim(nt(k)) if k else None
            rows.append(row)
            n += 1
        _write_json(ctx.out / "entities" / f"{pmid}.json", {"pmid": pmid, "normalized_at": utcnow(), "sentences": rows})
    ctx.report["stages"]["normalize"] = {"status": "ok", "n_sentences": n}
    print(f"[normalize] {n} sentences")
    return 0


# ===========================================================================
# Stage 8: report
# ===========================================================================
def write_heuristics_log(path: pathlib.Path, ctx: "Ctx") -> None:
    lines = ["# HEURISTICS_LOG — 전처리 파이프라인에서 출처로 뒷받침되지 않는 결정 목록", "",
             f"생성: {utcnow()} / scripts/preprocess_abstracts.py", "",
             "이 파일은 코드 안의 `_heuristic()` 등록으로 자동 생성된다. 각 항목은 사람 검증 전까지 "
             "휴리스틱으로 보고해야 한다(사용자 규칙). 사전 자체의 unverified_from_memory 항목은 "
             "scripts/certainty_lexicon_en.json, scripts/nlm_section_labels.json, docs/*_source.md 참조.", ""]
    for i, h in enumerate(HEURISTICS, 1):
        lines += [f"## {i}. {h['what']}", "", f"- **코드 위치**: {h['where']}", f"- **이유**: {h['why']}",
                  f"- **검증 방법**: {h['verify']}", ""]
    tr = ctx.report["stages"].get("translate", {})
    if tr.get("error"):
        lines += ["## 실행 메모", "", f"- 번역 endpoint 접근 실패: {tr['error']} (허용 필요 호스트: {TRANSLATE_HOST})", ""]
    if ctx.normalize_terms_error:
        lines += [f"- normalize_terms import 실패: {ctx.normalize_terms_error}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def stage_report(ctx: "Ctx") -> int:
    ctx.report["generated_at"] = utcnow()
    ctx.report["out_dir"] = str(ctx.out)
    ctx.report["raw_dir"] = str(ctx.raw_dir)
    ctx.report["n_papers"] = len(ctx.papers)
    ctx.report["per_pmid"] = ctx.per_pmid
    ctx.report["heuristics"] = HEURISTICS
    _write_json(ctx.out / "preprocessing_report.json", ctx.report)
    write_heuristics_log(ctx.out / "HEURISTICS_LOG.md", ctx)
    print(f"[report] {ctx.out / 'preprocessing_report.json'} ; {ctx.out / 'HEURISTICS_LOG.md'}")
    return 0


# ===========================================================================
# Context / CLI
# ===========================================================================
class Ctx:
    def __init__(self, out: pathlib.Path, raw_dir: pathlib.Path | None, candidates: pathlib.Path,
                 section_labels_path: pathlib.Path = SECTION_LABELS_PATH, lexicon_path: pathlib.Path = LEXICON_PATH,
                 extra_abbrev: set[str] | None = None, papers: list[dict[str, Any]] | None = None):
        self.out = out
        self.raw_dir = raw_dir or (out / "raw")
        self.section_labels_path = section_labels_path
        self.lexicon_path = lexicon_path
        self.extra_abbrev = extra_abbrev or set()
        self.papers = papers if papers is not None else _require(candidates, "paper_candidates.json")
        self.paper_by_pmid = {p["pmid"]: p for p in self.papers}
        self.report: dict[str, Any] = {"stages": {}}
        self.per_pmid: dict[str, dict[str, Any]] = {}
        self._nt = None
        self.normalize_terms_error: str | None = None
        self._nt_tried = False

    def flags(self, pmid: str) -> dict[str, Any]:
        return self.per_pmid.setdefault(pmid, {})

    def iter_clean(self):
        for p in self.papers:
            path = self.out / "clean" / f"{p['pmid']}.json"
            if path.exists():
                yield p["pmid"], path

    def iter_sentences(self):
        for p in self.papers:
            path = self.out / "sentences" / f"{p['pmid']}.json"
            if path.exists():
                yield p["pmid"], path

    def normalize_terms(self):
        if not self._nt_tried:
            self._nt_tried = True
            try:
                if str(HERE) not in sys.path:
                    sys.path.insert(0, str(HERE))
                import normalize_terms  # lazy import (contract)

                self._nt = normalize_terms.normalize_text
            except Exception as e:  # noqa: BLE001
                self.normalize_terms_error = f"{type(e).__name__}: {e}"
        return self._nt


def run(stages: list[str], ctx: Ctx, translate=translate_sentence) -> int:
    funcs = {"fetch": stage_fetch, "clean": stage_clean, "sections": stage_sections, "sentences": stage_sentences,
             "translate": lambda c: stage_translate(c, translate), "cues": stage_cues, "tokens": stage_tokens,
             "normalize": stage_normalize, "report": stage_report}
    rc = 0
    for st in STAGES:
        if st not in stages:
            continue
        code = funcs[st](ctx)
        rc = rc or code
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stage", action="append", choices=STAGES, help="stage(s) to run; default: all")
    ap.add_argument("--raw-dir", type=pathlib.Path, help="directory of pre-fetched Europe PMC JSON (<pmid>.json); skips fetch")
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help="output root (default: abstracts/)")
    ap.add_argument("--candidates", type=pathlib.Path, default=CANDIDATES)
    ap.add_argument("--section-labels", type=pathlib.Path, default=SECTION_LABELS_PATH)
    ap.add_argument("--lexicon", type=pathlib.Path, default=LEXICON_PATH)
    ap.add_argument("--abbrev-units", action="store_true", help="also treat mg/kg as abbreviations (see HEURISTICS_LOG)")
    ap.add_argument("--no-translate", action="store_true", help="skip the translate stage")
    a = ap.parse_args(argv)
    stages = a.stage or list(STAGES)
    if a.raw_dir:
        stages = [s for s in stages if s != "fetch"]
    if a.no_translate:
        stages = [s for s in stages if s != "translate"]
    ctx = Ctx(a.out, a.raw_dir, a.candidates, a.section_labels, a.lexicon,
              ABBREVIATIONS_UNITS if a.abbrev_units else set())
    a.out.mkdir(parents=True, exist_ok=True)
    return run(stages, ctx)


if __name__ == "__main__":
    sys.exit(main())
