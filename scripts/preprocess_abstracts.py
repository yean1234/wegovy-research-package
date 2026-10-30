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
               (W3 p.9-21 get_text; bs4 가 HTML 엔티티도 복원). abstract_clean / analysis_text 는
               태그 제거·공백 축약만 하고 NFKC·casefold 를 적용하지 않는다 (Notion ⑦⑧: HR/CI/OR 약어와
               'kg/m²' 같은 단위 표기를 원문 그대로 보존). NFKC(W5 p.29)는 분석 뷰(tokenize_analysis,
               score_sentence, normalize_terms.normalize_view)에서만 적용한다.
 2 sections  : Notion ②. scripts/nlm_section_labels.json (NLM 구조화 초록 범주) 로 keep/drop.
               비구조화 초록은 자동 분할하지 않고 needs_human_sectioning=true.
               'clean' 을 실행하면 'sections' 가 자동으로 뒤따른다 (clean 출력 계약에 analysis_text 포함).
 3 sentences : Notion ③. nltk.sent_tokenize (Punkt; W3 p.33 punkt) + 약어 목록을 확장한
               PunktTokenizer 결과를 둘 다 보관, 다르면 boundary_check 플래그. 수업에는
               문장 분리 단원이 없어 NLTK Punkt 를 사용 (Kiss T, Strunk J. Unsupervised multilingual
               sentence boundary detection. Computational Linguistics 2006;32(4):485-525 —
               서지사항은 unverified_from_memory).
 4 translate : Notion ④. 문장 단위 EN→KO (Google Translate 웹 endpoint, 미문서화 → 휴리스틱 로그).
 5 cues      : Notion ⑥ (+⑤ 검수 sheet). scripts/certainty_lexicon_en.json (Sumner 2014 7단계)
               으로 문장 수준 산출. 부정 창(negation window)은 W5 p.30-33 '부정어 보존' 원칙을
               따르되 창 크기 자체는 프로젝트 휴리스틱(HEURISTICS_LOG 참조).
 6 tokens    : Notion ⑦⑧. (a) tokens_analysis: NFKC+casefold (W5 p.29) + W5 p.13-14 TOKEN_PATTERN
               (숫자·축약형 보존) 확장판; 불용어 제거·짧은 토큰 제거 없음 (W5 p.30-33).
               (b) tokens_tfidf: W3 p.44-45 수업 정제 re.sub(r'[^a-zA-Z\\s]',' ',lower()).split()
               — 글자만, TF-IDF 사본 전용. W3 p.47-48 (NLTK 불용어 + len>2) 은 기본 적용하지 않음
               (프로젝트 결정, HEURISTICS_LOG); --tfidf-w3-filter 로 켤 수 있다.
               (c) stems: SnowballStemmer (W5 p.55 'Modification of the Porter stemmer')
               을 tokens_tfidf 에만 적용, NER 먼저 (W5 p.61 'NER before stemming') 로 엔티티 보호.
 7 normalize : Notion ⑨. scripts/normalize_terms.normalize_text 로 용어 → entity_id.
               기본은 normalization.json 별칭만 사용; standard_terms.json 의 예상 표기
               (surface_forms_added, project_addition_unverified) 는 --candidate-surface-forms 로만 사용.
 8 agreement : Notion ⑥ 후반 '번역의 한국어 사전 라벨과 일치율 보고'. 저장소에 한국어 확신 사전이
               아직 없으므로, 한국어 라벨은 (a) --ko-labels JSON {sentence_id: 라벨} (향후 한국어 사전
               출력) 또는 (b) review_sheet.csv 의 ko_level_human 열(사람 라벨)에서 읽는다. 둘 다 없으면
               status=deferred 로 보고한다 (일치율 계산은 사람 라벨링 이후로 미룸). 일치율은 단순
               일치율 + Cohen's kappa (sklearn.metrics.cohen_kappa_score; 없으면 동일 공식 직접 계산).
 9 report    : abstracts/preprocessing_report.json + abstracts/HEURISTICS_LOG.md (한국어).

모든 stage 는 멱등(idempotent)이며 abstracts/ 아래에 디스크 캐시된다. 사용 예:
    python3 scripts/preprocess_abstracts.py                      # 모든 stage
    python3 scripts/preprocess_abstracts.py --stage clean --stage sentences   # sections 가 자동 삽입됨
    python3 scripts/preprocess_abstracts.py --raw-dir /path/to/prefetched --out /tmp/x

Importable helpers: clean_abstract(html) -> dict, split_sections(clean, labels) -> dict,
split_sentences(text) -> list, translate_sentence(text) -> str, score_sentence(text, lexicon) -> dict,
tokenize_analysis(text) -> list, tokenize_tfidf(text) -> list, agreement_stats(pairs) -> dict.
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

STAGES = ["fetch", "clean", "sections", "sentences", "translate", "cues", "tokens", "normalize", "agreement", "report"]
USER_AGENT = "wegovy-research-package/preprocess_abstracts (contact: see README_ko.md)"

# ---------------------------------------------------------------------------
# Heuristic registry: every rule in this file that is NOT backed by a cited source is
# registered here and written to abstracts/HEURISTICS_LOG.md by the report stage.
# ---------------------------------------------------------------------------
HEURISTICS: list[dict[str, str]] = []


def _heuristic(what: str, where: str, why: str, verify: str) -> None:
    HEURISTICS.append({"what": what, "where": where, "why": why, "verify": verify})


# --- Notion ③ sentence splitting: abbreviation list ---------------------------------
# Project-documented list (HEURISTIC). Punkt (Kiss & Strunk 2006, citation unverified_from_memory)
# learns abbreviations unsupervised; these are added because the Notion plan names them as
# mis-split risks. Punkt compares abbrev_types per token, so only single tokens ('al', not 'et al').
ABBREVIATIONS = {"vs", "al", "e.g", "i.e", "dr", "fig", "no", "approx", "ca", "cf", "etc"}
# Unit abbreviations are NOT added by default: "… at 2.4 mg." is a common sentence end in
# dose statements (RQ2), and treating "mg." as an abbreviation merges two sentences.
ABBREVIATIONS_UNITS = {"mg", "kg"}
_heuristic(
    "Punkt 약어 목록 ABBREVIATIONS = {vs, al, e.g, i.e, dr, fig, no, approx, ca, cf, etc} "
    "('et al.' 은 토큰 'al' 로 처리; Punkt abbrev_types 는 토큰 단위 비교); 단위 약어 {mg, kg} 는 --abbrev-units 로만 추가",
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
    # a CI clause usually contains decimals ('95% CI 1.20–3.40.'), so the clause must be allowed to
    # cross '.'; it is bounded by ';' or ')' instead.
    (re.compile(r"\bCI\b[^;)]*\.$"), "prev_ends_CI_clause."),
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
_heuristic(
    "TF-IDF 사본(tokens_tfidf)에 W3 p.44-45 (lower + 글자만 re.sub + split) 만 적용하고, "
    "W3 p.47-48 의 NLTK 불용어 + 사용자 불용어 + len(word)>2 필터는 기본 적용하지 않음 (--tfidf-w3-filter 로 선택)",
    "preprocess_abstracts.py tokenize_tfidf(), w3_filter_tokens(), stage_tokens()",
    "Notion ⑦ 은 분석 토큰에 대해서만 불용어·짧은 단어 제거를 금지하므로 TF-IDF 사본에 대한 생략은 프로젝트 결정. "
    "W3 p.48 자체가 len>2 를 'user-defined filtering rule' 이라 하고 의미 있는 짧은 단어가 지워질 수 있다고 경고함. "
    "사용자 불용어(W3 p.47 custom stopwords)는 코퍼스 특성에 따른 연구자 결정이라 어떤 목록도 추가하지 않음.",
    "--tfidf-w3-filter 로 두 사본을 만들어 TF-IDF 상위 어휘를 비교; 팀이 어느 쪽을 쓸지 결정 후 tokens_tfidf_rule 에 기록.",
)

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
            # explicit User-Agent like translate_sentence(): the proxy returned 403 to the default
            # Python-urllib agent there, and Europe PMC asks clients to identify themselves.
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
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
_H4_TAG = re.compile(r"</?h4[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")
# cleaned text shorter than this fraction of the tag-stripped raw text -> suspect html.parser
# truncation (a raw '<' followed by a letter is read as a tag start and the rest is dropped)
TRUNCATION_RATIO = 0.9


def strip_html(fragment: str) -> str:
    """BeautifulSoup.get_text() (W3 p.9-21; bs4 decodes HTML entities itself) + whitespace collapse.

    <h4> is the only block-level tag Europe PMC uses, so it is replaced by a space first to keep
    label/text separation; inline tags (<i>, <sup>, <sub>, <b>) are removed WITHOUT a separator so
    'semaglutide</i>-treated', '(<i>P</i>&lt;.001)', 'et <i>al</i>.' stay intact.
    No NFKC and no casefold here: abstract_clean / analysis_text keep 'kg/m²', 'HR', 'CI', 'NAION'
    (Notion ⑦⑧). NFKC (W5 p.29) is applied in the analysis views only."""
    from bs4 import BeautifulSoup  # lecture W3 dependency

    fragment = _H4_TAG.sub(" ", fragment)
    text = BeautifulSoup(fragment, "html.parser").get_text()
    return _WS.sub(" ", text).strip()


def truncation_suspect(raw: str, clean: str) -> bool:
    """True when the bs4 result is much shorter than a naive tag strip of the same raw text."""
    naive = _WS.sub(" ", html.unescape(_ANY_TAG.sub(" ", raw))).strip()
    return bool(naive) and len(clean) < TRUNCATION_RATIO * len(naive)


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
    # an abstract that holds only <h4> labels has no content: abstract_empty must say so
    content = " ".join(s["text"] for s in sections) if structured else clean
    return {
        "abstract_raw_html": raw,
        "abstract_clean": clean,
        "structured": structured,
        "sections": sections,
        "abstract_empty": not content.strip(),
        "clean_truncated_suspect": truncation_suspect(raw, clean),
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
        f["abstract_empty"] = info["abstract_empty"]
        f["clean_truncated_suspect"] = info["clean_truncated_suspect"]
        if info["abstract_empty"]:
            print(f"[clean] WARNING pmid {pmid}: abstract has no content text (abstract_empty=true)", file=sys.stderr)
        if info["clean_truncated_suspect"]:
            print(f"[clean] WARNING pmid {pmid}: cleaned text much shorter than raw (clean_truncated_suspect=true); "
                  f"check for a raw '<' in abstractText", file=sys.stderr)
        n += 1
    ctx.report["stages"]["clean"] = {"status": "ok", "n": n,
                                     "empty": sorted(p for p, f in ctx.per_pmid.items() if f.get("abstract_empty")),
                                     "truncation_suspects": sorted(p for p, f in ctx.per_pmid.items() if f.get("clean_truncated_suspect"))}
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
        f["analysis_text_empty"] = not res["analysis_text"].strip()
        if f["analysis_text_empty"]:
            print(f"[sections] WARNING pmid {pmid}: analysis_text is empty after keep/drop "
                  f"(structured={clean['structured']}, abstract_empty={clean.get('abstract_empty')})", file=sys.stderr)
        n += 1
    unknown_all = sorted({lab for f in ctx.per_pmid.values() for lab in f.get("unknown_labels", [])})
    ctx.report["stages"]["sections"] = {"status": "ok", "n": n, "unknown_labels": unknown_all,
                                        "analysis_text_empty": sorted(p for p, f in ctx.per_pmid.items() if f.get("analysis_text_empty"))}
    print(f"[sections] {n} abstracts")
    if unknown_all:
        print(f"[sections] UNKNOWN section labels (kept in analysis text, needs_human): {unknown_all}\n"
              f"[sections] -> add them to scripts/nlm_section_labels.json before trusting cue statistics", file=sys.stderr)
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
            raise RuntimeError(
                f"{pmid}: clean/{pmid}.json has no 'analysis_text' (written by the 'sections' stage). "
                f"Run `--stage sections --stage sentences` (or `--stage clean --stage sentences`, which "
                f"inserts 'sections' automatically)."
            )
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


MAX_CONSECUTIVE_TRANSLATE_FAILURES = 3


def stage_translate(ctx: "Ctx", translate=translate_sentence, sleep: float = 0.5,
                    max_consecutive_failures: int = MAX_CONSECUTIVE_TRANSLATE_FAILURES) -> int:
    """One malformed response must not halt the corpus: per-sentence errors are recorded and the
    endpoint is declared unreachable only after `max_consecutive_failures` failures in a row."""
    n_new = n_cached = n_err = 0
    unreachable: str | None = None
    consecutive = 0
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
                    consecutive = 0
                    time.sleep(sleep)
                except Exception as e:  # noqa: BLE001
                    row["error"] = str(e)
                    n_err += 1
                    consecutive += 1
                    if consecutive >= max_consecutive_failures:
                        unreachable = f"{consecutive} consecutive failures; last: {e}"
            else:
                row["error"] = "skipped: endpoint unreachable earlier in this run"
            rows.append(row)
        tr["sentences"] = rows
        _write_json(dest, tr)
        ctx.flags(pmid)["n_translated"] = sum(1 for r in rows if r.get("text_ko"))
        ctx.flags(pmid)["n_translate_errors"] = sum(1 for r in rows if r.get("error"))
    status = {"status": "ok" if (unreachable is None and n_err == 0) else "partial", "translated_new": n_new,
              "cached": n_cached, "errors": n_err, "tool": TRANSLATE_TOOL, "endpoint": TRANSLATE_URL}
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
def load_lexicon(path: pathlib.Path = LEXICON_PATH, strict: bool = False) -> dict[str, Any]:
    d = _require(path, "English certainty lexicon (scripts/certainty_lexicon_en.json)")
    for k in ("entries", "modifiers", "levels"):
        if k not in d:
            raise ValueError(f"{path}: missing key '{k}' (contract violation)")
    return compile_lexicon(d, strict=strict)


_ANCHOR_OK = ("\\b", "(?<!", "(?<=", "(?-i:")


def _top_level_alternatives(pattern: str) -> list[str]:
    """Split a regex on top-level '|' (ignoring '|' inside groups, classes and escapes)."""
    alts, depth, in_class, buf, i = [], 0, False, [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            buf.append(pattern[i:i + 2]); i += 2; continue
        if in_class:
            if ch == "]":
                in_class = False
        elif ch == "[":
            in_class = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            alts.append("".join(buf)); buf = []; i += 1; continue
        buf.append(ch); i += 1
    alts.append("".join(buf))
    return alts


def check_anchored(cue: str, pattern: str, allow_unanchored: bool = False) -> list[str]:
    """Return warnings for top-level alternatives that do not start with \\b, a lookbehind or (?-i:.
    A pattern without a word anchor matches inside words ('caus' in 'causeway')."""
    if allow_unanchored:
        return []
    bad = [a for a in _top_level_alternatives(pattern) if not a.startswith(_ANCHOR_OK)]
    return [f"lexicon pattern not word-anchored: cue={cue!r} alternative={a!r}" for a in bad]


# Clause boundaries that stop the negation window (BioScope, Vincze 2008: "punctuation marks or conjunctions
# function as scope boundary markers"; the specific list is a project choice). Overridden by the lexicon's
# sentence_rule.negation_scope_boundary_pattern.
NEGATION_SCOPE_BOUNDARY_DEFAULT = r"[,;:](?=\s|$)|\b(?:but|whereas|although|though|while|however)\b"


def compile_lexicon(d: dict[str, Any], strict: bool = False) -> dict[str, Any]:
    """Compile patterns with re.IGNORECASE; an entry may scope case-sensitive parts with (?-i:...)
    (used for the effect-measure abbreviations OR/HR/RR/IRR/CI). Cue lists (associational_cues,
    causal_cues, no_relationship_cues, ambiguous_cues) may hold entry dicts (contract) or cue-name
    strings that reference `entries` (current file); both are accepted and de-duplicated.
    Patterns whose top-level alternatives are not word-anchored produce warnings (raise if strict)
    unless the entry sets allow_unanchored=true."""
    by_cue = {e["cue"]: e for e in d["entries"]}
    cues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    warnings: list[str] = []
    flag_types = set(d.get("evidence_flag_types", ["effect_measure", "descriptive_frequency"]))

    def add(e: dict[str, Any]) -> None:
        key = (e["cue"], e["pattern"])
        if key in seen:
            return
        seen.add(key)
        warnings.extend(check_anchored(e["cue"], e["pattern"], e.get("allow_unanchored", False)))
        cues.append({"cue": e["cue"], "level": int(e["level"]), "type": e.get("type"),
                     "evidence_flag": e.get("type") in flag_types,
                     "requires_cooccurrence": bool(e.get("requires_cooccurrence", False)),
                     "regex": re.compile(e["pattern"], re.IGNORECASE)})

    for e in d["entries"]:
        add(e)
    for key in ("associational_cues", "causal_cues", "no_relationship_cues", "ambiguous_cues"):
        for item in d.get(key, []):
            if isinstance(item, dict) and "pattern" in item:
                add(item)
            elif isinstance(item, str) and item in by_cue:
                add(by_cue[item])

    def simple(items: list[dict[str, Any]], extra: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        out = []
        for it in items:
            warnings.extend(check_anchored(it["cue"], it["pattern"], it.get("allow_unanchored", False)))
            out.append({"cue": it["cue"], **{k: it[k] for k in extra}, "regex": re.compile(it["pattern"], re.IGNORECASE)})
        return out

    mods = simple(d["modifiers"], ("effect",))
    hedges = simple(d.get("hedges", []))
    boosters = simple(d.get("boosters", []))
    probabilistic = simple(d.get("probabilistic_cues", []))  # Sumner 'explicitly probabilistic' (separate binary code)
    if strict and warnings:
        raise ValueError("\n".join(warnings))
    levels = {str(k): v for k, v in d["levels"].items()}
    rule = d.get("sentence_rule", {})
    window = int(rule.get("negation_window_tokens", 5))
    boundary_pat = rule.get("negation_scope_boundary_pattern", NEGATION_SCOPE_BOUNDARY_DEFAULT)
    return {"cues": cues, "modifiers": mods, "hedges": hedges, "boosters": boosters, "probabilistic": probabilistic,
            "levels": levels, "negation_window_tokens": window,
            "negation_scope_boundary": re.compile(boundary_pat, re.IGNORECASE) if boundary_pat else None,
            "version": d.get("version"), "warnings": warnings,
            "collapse_map": d.get("collapse_map", {}), "evidence_flag_types": sorted(flag_types)}


_heuristic(
    "문장 단위 적용: Sumner 2014 척도(0-6)를 사람이 아닌 정규식으로, IV–DV 진술이 아닌 '문장' 단위로 적용",
    "preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json unit_of_analysis",
    "Sumner 2014 는 사람 코더가 main claims(보도자료·뉴스: 제목+첫 두 문장; 학술논문: abstract and discussion)에서 IV–DV 쌍과 "
    "관계 진술을 뽑아 코딩했다(web appendix ww1, 본문 Methods — 원문 확인). 이 파이프라인은 IV–DV 를 식별하지 않고 문장마다 단서를 찾아 "
    "'가장 강한 진술' 규칙(원문 확인)을 문장 안에서 적용한다. level 0 은 Sumner 의 'not applicable'(두 변수 없음)과 구분하지 않는다.",
    "검수 sheet 에서 사람이 문장별 IV–DV 진술과 단계를 코딩해 일치율(정밀도·재현율)을 보고.",
)
_heuristic(
    "부정 창(negation window): 부정어(no/not/neither/cannot; never/nor/n't)가 level≥2 단서보다 앞 N 토큰(기본 5, 사전의 "
    "sentence_rule.negation_window_tokens) 안에 있고 그 사이에 절 경계(', ; :' 뒤 공백, but/whereas/although/though/while/however)가 "
    "없으면 그 단서를 level 1 로 본다",
    "preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json sentence_rule.negation_scope_boundary_pattern",
    "Sumner 2014 는 진술 전체를 사람이 코딩하고, BioScope(Vincze 2008)는 부정 범위를 구문으로 정한다. 고정 창은 프로젝트 근사치. "
    "절 경계에서 창을 멈추는 것은 Vincze 2008 본문 'Generally, punctuation marks or conjunctions function as scope boundary markers "
    "in the corpus'(원문 확인)의 확장이며 경계 목록은 프로젝트 선택. v2 에서 확인된 오류 'Semaglutide, but not liraglutide, was "
    "associated with NAION.' → 1 은 쉼표 경계로 이제 2. 남은 위험: 경계 없이 대조 부정이 쓰인 문장, 쉼표로 끊긴 부정 범위.",
    "review_flag 'negation_window_applied' 문장을 전수 사람 검토; 가능하면 NegEx (Chapman WW et al. J Biomed Inform "
    "2001;34(5):301-310 — 서지사항 unverified_from_memory) 같은 검증된 부정 탐지와 비교.",
)
_heuristic(
    "수식어 위치 규칙: may/might/could/appears(→4), can(→5)이 level-6 단서 '앞'(같은 문장 어디든, 또는 단서 span 안)에 있으면 적용; "
    "possible/potential/likely/probably/putative/plausible, seem, hypothesis 류도 →4 (프로젝트 확장)",
    "preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json modifiers",
    "Sumner 부록: 'Causal statement (examples in level 6) preceded by conditional, such as might, could, may, appears' / 'preceded by can' "
    "(원문 확인). '앞에 있다'를 거리 제한 없이 문장 안 위치로만 판단하는 것과 형용사·부사형 hedge 를 같은 취급하는 것은 프로젝트 조작화.",
    "검수 sheet 에서 level 4/5 문장의 수식어가 실제로 그 인과 진술을 수식하는지 사람이 확인.",
)
_heuristic(
    "mixed_levels_review: 한 문장에 유효 level 1 단서와 유효 level≥2 단서가 함께 있으면 review_flag 만 붙인다(단계는 Sumner 대로 최댓값)",
    "preprocess_abstracts.py score_sentence()",
    "v2 의 'no_relationship 우선' 규칙(level-1 단서가 있으면 무조건 1; review_flag no_relationship_overrides_level>=5)은 Sumner 부록 "
    "'Where statements of different levels were made within the analysed segments of text, stronger statements trumped weaker ones' "
    "와 모순되어 v3 에서 삭제했다. Sumner 는 IV–DV 쌍별로 사람이 코딩했으므로 한 문장의 서로 다른 진술은 사람이 나눠 봐야 한다.",
    "mixed_levels_review 문장을 검수 sheet 에서 우선 검토하고 IV–DV 별 단계를 note 에 기록.",
)
_heuristic(
    "explicitly_probabilistic: probabilistic_cues(risk/chance/likelihood/makes more likely/tendency/rate + 프로젝트 확장 odds/hazard/"
    "probability/incidence/more·less likely)가 있고 문장 level≥1 일 때만 True",
    "preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json probabilistic_cues, probabilistic_rule",
    "Sumner 부록은 단계와 별도로 'whether or not the statement of relationship was explicitly probabilistic' 을 코딩했다(원문 확인). "
    "level≥1(관계 또는 무관계 진술이 있음)일 때만 세는 것과 'risk factor(s)' 제외는 프로젝트 조작화.",
    "검수 sheet 에서 explicitly_probabilistic 문장을 표본 검토.",
)
_heuristic(
    "효과 측정치·기술통계 단서(type effect_measure: HR/OR/RR/IRR/95% CI/P value; descriptive_frequency: prevalence/incidence of)는 "
    "문장 level 을 정하지 않고 evidence_flags 로만 기록 (v3: 'risk of' 는 level 단서에서 빠지고 Sumner 의 별도 코드 explicitly_probabilistic 으로 이동; "
    "requires_cooccurrence 기능은 코드에 남아 있으나 현재 사전에는 쓰는 항목이 없음)",
    "preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json evidence_flag_types, entries[*].requires_cooccurrence",
    "Sumner 2014 는 '관계 주장'을 코딩하는데, 통계량 이름만 나오는 METHODS 문장('We estimated hazard ratios using Cox models to "
    "assess the risk of NAION')이 level 2(연관)로 잡혀 연관 비율이 부풀려지는 것을 확인함. 이 항목들은 애초에 project_addition 이었음.",
    "검수 sheet 에서 evidence_flags 만 있는 문장(level 0)을 사람이 보고 관계 주장이 실제로 있는지 확인; "
    "있으면 누락 단서를 사전에 추가.",
)


def _token_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in W5_TOKEN_PATTERN.finditer(text)]


def _token_index(spans: list[tuple[int, int]], char_pos: int) -> int:
    for i, (s, e) in enumerate(spans):
        if e > char_pos:
            return i
    return len(spans)


def score_sentence(text: str, lexicon: dict[str, Any]) -> dict[str, Any]:
    """Sumner-2014 sentence level (lexicon sentence_rule, v3): per-cue effective level, then MAX.

    Matching runs on the NFKC view of the sentence (W5 p.29; spans refer to that view, which is
    identical to the source for ASCII text). Case is kept: patterns are IGNORECASE except the
    (?-i:...) groups for OR/HR/RR/IRR/CI. Contractions are matched as written (W5 p.32 option 1).

    Per cue (each hit in `matched_cues` gets `effective_level` and, if changed, `level_rule`):
      * a level>=2 cue whose span overlaps a level-1 cue is the same negated statement -> 1;
      * else a level>=2 cue starting within negation_window_tokens tokens after a negation modifier,
        with no clause boundary in between, -> 1 (PROJECT HEURISTIC; review_flag negation_window_applied);
      * else a level-6 cue preceded by may/might/could/appears (or a level-4 extension) -> 4, by can -> 5
        (Sumner appendix levels 4/5; 'preceded' = modifier starts before the cue ends).
    Sentence level = max effective level ('stronger statements trumped weaker ones', Sumner appendix).
    A sentence with both an effective level-1 cue and an effective level>=2 cue gets review_flag
    mixed_levels_review (no override). Entries of an evidence-flag type never set the level
    (`evidence_flags`); entries with requires_cooccurrence count only when another level>=2 cue matched.
    `explicitly_probabilistic` is Sumner's separate binary code: a probabilistic cue and level >= 1."""
    if "cues" not in lexicon:
        lexicon = compile_lexicon(lexicon)
    text = unicodedata.normalize("NFKC", text)
    matches, evidence_flags, deferred = [], [], []
    for c in lexicon["cues"]:
        for m in c["regex"].finditer(text):
            hit = {"cue": c["cue"], "level": c["level"], "span": [m.start(), m.end()], "text": m.group(0)}
            if c["evidence_flag"]:
                evidence_flags.append(hit)
            elif c["requires_cooccurrence"]:
                deferred.append(hit)
            else:
                matches.append(hit)
    if deferred and any(m["level"] >= 2 for m in matches):
        matches.extend(deferred)
    matches.sort(key=lambda x: x["span"][0])
    evidence_flags.sort(key=lambda x: x["span"][0])
    base = max((m["level"] for m in matches), default=0)
    mod_hits: dict[str, tuple[str, list[tuple[int, int]]]] = {}
    for mod in lexicon["modifiers"]:
        hits = [(m.start(), m.end()) for m in mod["regex"].finditer(text)]
        if hits:
            mod_hits[mod["cue"]] = (mod["effect"], hits)

    def starts(effect: str) -> list[tuple[int, int]]:
        return [h for eff, hs in mod_hits.values() if eff == effect for h in hs]

    neg_positions, to4, to5 = starts("negation_to_1"), starts("downgrade_to_4"), starts("level_5")
    level1_spans = [m["span"] for m in matches if m["level"] == 1]
    spans = _token_spans(text)
    win = lexicon.get("negation_window_tokens", 5)
    boundary = lexicon.get("negation_scope_boundary")
    review_flags: list[str] = []
    for m in matches:
        eff, rule = m["level"], None
        if m["level"] >= 2:
            if any(m["span"][0] < e and s < m["span"][1] for s, e in level1_spans):
                eff, rule = 1, "negated_inside_level1_cue"
            else:
                ci = _token_index(spans, m["span"][0])
                for ns, ne in neg_positions:
                    if 0 <= ci - _token_index(spans, ns) <= win and not (
                            boundary is not None and ne < m["span"][0] and boundary.search(text, ne, m["span"][0])):
                        eff, rule = 1, f"negation_to_1(window={win})"
                        break
        if eff == 6:
            if any(s < m["span"][1] for s, _ in to4):
                eff, rule = 4, "downgrade_to_4"
            elif any(s < m["span"][1] for s, _ in to5):
                eff, rule = 5, "level_5"
        m["effective_level"] = eff
        if rule:
            m["level_rule"] = rule
    level = max((m["effective_level"] for m in matches), default=0)
    applied = sorted({m["level_rule"] for m in matches if "level_rule" in m})
    if any(r.startswith("negation_to_1") for r in applied):
        review_flags.append("negation_window_applied")
    if any(m["effective_level"] == 1 for m in matches) and any(m["effective_level"] >= 2 for m in matches):
        review_flags.append("mixed_levels_review")
    if level >= 2 and neg_positions:
        review_flags.append("negation_present_but_level>=2")
    hedges = sorted({h["cue"] for h in lexicon["hedges"] if h["regex"].search(text)})
    boosters = sorted({b["cue"] for b in lexicon["boosters"] if b["regex"].search(text)})
    prob = sorted({p["cue"] for p in lexicon.get("probabilistic", []) if p["regex"].search(text)})
    lv = lexicon["levels"].get(str(level), {})
    return {"base_level": base, "level": level, "collapsed_ko": lv.get("collapsed_ko"),
            "level_name_en": lv.get("name_en"), "matched_cues": matches, "evidence_flags": evidence_flags,
            "modifiers": {k: v[0] for k, v in mod_hits.items()}, "applied": applied,
            "review_flags": review_flags, "hedges": hedges, "boosters": boosters,
            "probabilistic_cues": prob, "explicitly_probabilistic": bool(prob) and level >= 1}


REVIEW_SHEET_COLS = ["sentence_id", "pmid", "side_effect", "section", "text_en", "text_ko", "en_level", "en_collapsed",
                     "matched_cues", "explicitly_probabilistic", "probabilistic_cues", "evidence_flags", "hedges",
                     "boosters", "boundary_check", "review_flag", "ko_level_human", "agree", "note"]
HUMAN_COLS = ("ko_level_human", "agree", "note")  # filled by the team; preserved across reruns by sentence_id


def read_review_sheet(path: pathlib.Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return {r["sentence_id"]: r for r in csv.DictReader(f) if r.get("sentence_id")}


def stage_cues(ctx: "Ctx") -> int:
    lex = load_lexicon(ctx.lexicon_path, strict=ctx.strict)
    for w in lex["warnings"]:
        print(f"[cues] WARNING {w}", file=sys.stderr)
    n_cue = n = 0
    rows_csv = []
    previous = read_review_sheet(ctx.out / "review_sheet.csv")  # keep human columns on rerun
    for pmid, sent_path in ctx.iter_sentences():
        sents = _read_json(sent_path)["sentences"]
        tpath = ctx.out / "translations" / f"{pmid}.json"
        ko = {r["sentence_id"]: r.get("text_ko") for r in _read_json(tpath)["sentences"]} if tpath.exists() else {}
        side = ctx.paper_by_pmid.get(pmid, {}).get("side_effect", "")
        out = []
        for s in sents:
            sc = score_sentence(s["text_en"], lex)
            has_cue = bool(sc["matched_cues"] or sc["evidence_flags"] or sc["hedges"] or sc["boosters"])
            n_cue += has_cue
            n += 1
            out.append({"sentence_id": s["sentence_id"], "section_label": s["section_label"],
                        "section_category": s.get("section_category"), "text_en": s["text_en"], **sc})
            prev = previous.get(s["sentence_id"], {})
            rows_csv.append({
                "sentence_id": s["sentence_id"], "pmid": pmid, "side_effect": side, "section": s["section_label"],
                "text_en": s["text_en"], "text_ko": ko.get(s["sentence_id"]) or "",
                "en_level": sc["level"], "en_collapsed": sc["collapsed_ko"] or "",
                # raw level -> effective level after negation/modifier rules, e.g. "associated with(2->1)"
                "matched_cues": "; ".join(
                    f"{m['cue']}({m['level']})" if m.get("effective_level", m["level"]) == m["level"]
                    else f"{m['cue']}({m['level']}->{m['effective_level']})" for m in sc["matched_cues"]),
                "explicitly_probabilistic": sc.get("explicitly_probabilistic", ""),
                "probabilistic_cues": "; ".join(
                    (c if isinstance(c, str) else c.get("cue", "")) for c in sc.get("probabilistic_cues", [])),
                "evidence_flags": "; ".join(m["cue"] for m in sc["evidence_flags"]),
                "hedges": "; ".join(sc["hedges"]), "boosters": "; ".join(sc["boosters"]),
                "boundary_check": s["boundary_check"], "review_flag": "; ".join(sc["review_flags"]),
                **{c: prev.get(c, "") for c in HUMAN_COLS},
                "_has_cue": has_cue,
            })
        _write_json(ctx.out / "cues" / f"{pmid}.json", {"pmid": pmid, "lexicon_version": lex.get("version"),
                    "scored_at": utcnow(), "evidence_flag_types": lex["evidence_flag_types"], "sentences": out})
        ctx.flags(pmid)["n_cue_sentences"] = sum(1 for r in out if r["matched_cues"] or r["hedges"] or r["boosters"])
        ctx.flags(pmid)["n_review_flags"] = sum(1 for r in out if r["review_flags"])
    rows_csv.sort(key=lambda r: (not r["_has_cue"], r["sentence_id"]))
    with (ctx.out / "review_sheet.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_SHEET_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_csv)
    n_prev = sum(1 for r in rows_csv if any(r[c] for c in HUMAN_COLS))
    ctx.report["stages"]["cues"] = {"status": "ok", "n_sentences": n, "n_cue_sentences": n_cue,
                                    "n_review_flagged": sum(1 for r in rows_csv if r["review_flag"]),
                                    "human_columns_preserved": n_prev,
                                    "lexicon_version": lex.get("version"), "lexicon_warnings": lex["warnings"],
                                    "review_sheet_guidance": (
                                        "review_flag 열: mixed_levels_review (level 1 단서와 level≥2 단서가 한 문장에 함께 있음; 단계는 최댓값, IV–DV 별로 우선 검토), "
                                        "negation_window_applied (5토큰 창으로 무관 판정; 'X, but not Y, was associated' 류 대조 부정 오류 확인), "
                                        "negation_present_but_level>=2 (부정어가 있으나 창 밖). "
                                        "evidence_flags 만 있고 en_level=0 인 문장은 통계량만 언급한 문장으로 간주했으니 관계 주장이 있으면 note 에 기록.")}
    print(f"[cues] {n} sentences, {n_cue} with cues -> review_sheet.csv (human columns kept for {n_prev} rows)")
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
    Used ONLY for the TF-IDF copy (Notion ⑧). W3 p.47-48 (stopwords, len>2) is NOT applied here;
    see w3_filter_tokens()."""
    return LECTURE_CLEAN_PATTERN.sub(" ", text.lower()).split()


def w3_filter_tokens(tokens: list[str], custom_stopwords: set[str] | None = None) -> list[str]:
    """W3 p.47-48 (verified from lecture text): NLTK English stopwords (+ custom stopwords) and
    len(word) > 2. Opt-in via --tfidf-w3-filter; no project custom stopword list is defined."""
    from nltk.corpus import stopwords

    sw = set(stopwords.words("english")) | (custom_stopwords or set())
    return [w for w in tokens if w not in sw and len(w) > 2]


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
            if ctx.tfidf_w3_filter:
                tf = w3_filter_tokens(tf)
            rows.append({
                "sentence_id": s["sentence_id"],
                "tokens_analysis": tokenize_analysis(s["text_en"]),
                "tokens_tfidf": tf,
                "tokens_tfidf_label": "tfidf_copy_lecture_cleaning" + ("_w3_p47_48_filtered" if ctx.tfidf_w3_filter else ""),
                "stems_tfidf": stem_tokens(tf, protected),
                "protected_entity_tokens": sorted(protected),
            })
            n += 1
        tfidf_rule = "W3 p.44-45: lower(); re.sub(r'[^a-zA-Z\\s]',' '); split()  (letters only)"
        tfidf_rule += (" + W3 p.47-48: NLTK english stopwords, len(word) > 2 (--tfidf-w3-filter; no custom stopwords)"
                       if ctx.tfidf_w3_filter else
                       "; W3 p.47-48 stopwords/len>2 NOT applied (project decision, see HEURISTICS_LOG)")
        _write_json(ctx.out / "tokens" / f"{pmid}.json", {
            "pmid": pmid, "tokenized_at": utcnow(),
            "tokens_analysis_rule": "NFKC+casefold (W5 p.29) + TOKEN_PATTERN_ANALYSIS (W5 p.13-14 extended; see HEURISTICS_LOG); "
                                    "no stopwords, no length filter, numbers kept (Notion ⑦⑧, W5 p.30-33)",
            "tokens_tfidf_rule": tfidf_rule,
            "stems_rule": "nltk SnowballStemmer('english') on tokens_tfidf only (W5 p.55); entity tokens protected (W5 p.61 NER before stemming)",
            "normalize_terms_available": bool(nt), "normalize_terms_error": ctx.normalize_terms_error,
            "sentences": rows})
    ctx.report["stages"]["tokens"] = {"status": "ok", "n_sentences": n, "normalize_terms_available": bool(nt),
                                      "normalize_terms_error": ctx.normalize_terms_error,
                                      "tfidf_w3_filter": ctx.tfidf_w3_filter}
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
        _write_json(ctx.out / "entities" / f"{pmid}.json", {
            "pmid": pmid, "normalized_at": utcnow(),
            "alias_table": ("normalization.json + standard_terms.json surface_forms_added (candidate forms, "
                            "project_addition_unverified; --candidate-surface-forms)" if ctx.candidate_surface_forms
                            else "normalization.json aliases only (default)"),
            "sentences": rows})
    ctx.report["stages"]["normalize"] = {"status": "ok", "n_sentences": n,
                                         "candidate_surface_forms": ctx.candidate_surface_forms}
    print(f"[normalize] {n} sentences")
    return 0


# ===========================================================================
# Stage 7b: agreement (Notion ⑥, second half)
# ===========================================================================
def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa (Cohen J. Educ Psychol Meas 1960;20(1):37-46 — citation unverified_from_memory).
    Uses sklearn.metrics.cohen_kappa_score when available; otherwise the same formula."""
    if len(a) < 2:
        return None
    try:
        from sklearn.metrics import cohen_kappa_score

        return float(cohen_kappa_score(a, b))
    except ImportError:
        n = len(a)
        cats = sorted(set(a) | set(b))
        po = sum(x == y for x, y in zip(a, b)) / n
        pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
        return None if pe == 1 else (po - pe) / (1 - pe)


def agreement_stats(pairs: list[tuple[str, str]], collapse_to_group3: dict[str, str] | None = None) -> dict[str, Any]:
    """pairs = [(en_label, ko_label)] for sentences that have BOTH labels (level-0 / blank rows are
    excluded before calling). Returns simple agreement and kappa on the 4 categories and, if a
    collapse map is given, on the 3-group collapse (연관·무관 merged)."""
    out: dict[str, Any] = {"n_pairs": len(pairs)}
    if not pairs:
        return out
    a = [p[0] for p in pairs]
    b = [p[1] for p in pairs]
    out["simple_agreement"] = sum(x == y for x, y in pairs) / len(pairs)
    out["cohen_kappa"] = cohen_kappa(a, b)
    if collapse_to_group3:
        a3 = [collapse_to_group3.get(x, x) for x in a]
        b3 = [collapse_to_group3.get(x, x) for x in b]
        out["simple_agreement_group3"] = sum(x == y for x, y in zip(a3, b3)) / len(pairs)
        out["cohen_kappa_group3"] = cohen_kappa(a3, b3)
    conf: dict[str, int] = {}
    for x, y in pairs:
        conf[f"{x}->{y}"] = conf.get(f"{x}->{y}", 0) + 1
    out["confusion"] = dict(sorted(conf.items()))
    return out


def stage_agreement(ctx: "Ctx") -> int:
    """Compare en_collapsed (lexicon) with a Korean label per sentence_id. Korean labels come from
    --ko-labels (JSON {sentence_id: label}, e.g. a future Korean-lexicon run on text_ko) or, failing
    that, from review_sheet.csv ko_level_human. No Korean certainty lexicon exists in the repo yet,
    so without either input the stage reports status 'deferred' instead of inventing labels."""
    lex = load_lexicon(ctx.lexicon_path)
    collapse = lex["collapse_map"].get("collapsed_to_group3") or None
    valid = {v for v in lex["collapse_map"].get("level_to_collapsed", {}).values() if v}
    source: str
    ko: dict[str, str] = {}
    if ctx.ko_labels_path:
        ko = {k: str(v) for k, v in _require(ctx.ko_labels_path, "--ko-labels file").items() if v}
        source = f"--ko-labels {ctx.ko_labels_path}"
    else:
        sheet = read_review_sheet(ctx.out / "review_sheet.csv")
        ko = {sid: r["ko_level_human"].strip() for sid, r in sheet.items() if r.get("ko_level_human", "").strip()}
        source = "review_sheet.csv ko_level_human (human labels)"
    en: dict[str, str] = {}
    for pmid, _p in ctx.iter_sentences():
        cpath = ctx.out / "cues" / f"{pmid}.json"
        if cpath.exists():
            for s in _read_json(cpath)["sentences"]:
                if s.get("collapsed_ko"):
                    en[s["sentence_id"]] = s["collapsed_ko"]
    pairs = [(en[sid], ko[sid]) for sid in sorted(en) if sid in ko]
    unknown_ko = sorted({v for v in ko.values() if valid and v not in valid})
    if not ko:
        status = {"status": "deferred", "ko_label_source": None,
                  "note": ("Notion ⑥ 일치율: 한국어 라벨 입력이 없어 보류. 저장소에 한국어 확신 사전이 아직 없으므로 "
                           "review_sheet.csv 의 ko_level_human 을 채우거나 --ko-labels JSON 을 제공한 뒤 "
                           "--stage agreement 를 다시 실행."),
                  "n_en_labelled": len(en)}
    else:
        status = {"status": "ok", "ko_label_source": source, "n_en_labelled": len(en), "n_ko_labelled": len(ko),
                  "ko_labels_not_in_collapse_map": unknown_ko, **agreement_stats(pairs, collapse)}
    ctx.report["stages"]["agreement"] = status
    print(f"[agreement] {status['status']}: " + (f"{status['n_pairs']} pairs, agreement="
          f"{status.get('simple_agreement')}, kappa={status.get('cohen_kappa')}" if status["status"] == "ok" else status["note"]))
    return 0


# ===========================================================================
# Stage 8: report
# ===========================================================================
def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[str(it.get(key))] = out.get(str(it.get(key)), 0) + 1
    return dict(sorted(out.items()))


def lexicon_status_summary(path: pathlib.Path) -> dict[str, Any]:
    """Status fields of certainty_lexicon_en.json, so the log stays consistent with the JSON."""
    if not path.exists():
        return {"missing": str(path)}
    d = _read_json(path)
    groups = {k: d.get(k, []) for k in ("entries", "modifiers", "hedges", "boosters")}
    summary: dict[str, Any] = {"version": d.get("version"), "status_counts": {k: _count_by(v, "status") for k, v in groups.items()},
                               "sources": {s["id"]: s.get("status") for s in d.get("sources", [])},
                               "sentence_rule_status": d.get("sentence_rule", {}).get("status", {}),
                               "evidence_flag_types": d.get("evidence_flag_types"),
                               "collapse_map_status": d.get("collapse_map", {}).get("status")}
    groups["probabilistic_cues"] = d.get("probabilistic_cues", [])
    summary["status_counts"]["probabilistic_cues"] = _count_by(groups["probabilistic_cues"], "status")
    summary["project_addition_cues"] = {k: [e["cue"] for e in v if e.get("status") == "project_addition"] for k, v in groups.items()}
    summary["project_extension_cues"] = {k: [e["cue"] for e in v if e.get("status") == "project_extension_of_verified_category"]
                                         for k, v in groups.items()}
    summary["unit_of_analysis_status"] = d.get("unit_of_analysis", {}).get("status")
    summary["requires_cooccurrence"] = [e["cue"] for e in groups["entries"] if e.get("requires_cooccurrence")]
    summary["case_sensitive_groups"] = [e["cue"] for e in groups["entries"] if "(?-i:" in e.get("pattern", "")]
    return summary


def section_labels_status_summary(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"missing": str(path)}
    d = _read_json(path)
    labels = d.get("labels", {})
    return {"version": d.get("version"), "source_status": d.get("source", {}).get("status"),
            "provenance_counts": _count_by(list(labels.values()), "provenance"),
            "project_decision_labels": sorted(k for k, v in labels.items() if v.get("provenance") == "project_decision")}


def standard_terms_status_summary(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"missing": str(path)}
    d = _read_json(path)
    ents = d.get("entities", {})
    vocab_status: dict[str, int] = {}
    n_forms = 0
    for e in ents.values():
        for k in ("mesh", "icd10", "kcd8", "inn", "atc", "mfds_product_name_ko", "kma_term_candidate"):
            if isinstance(e.get(k), dict) and "status" in e[k]:
                vocab_status[e[k]["status"]] = vocab_status.get(e[k]["status"], 0) + 1
        n_forms += len(e.get("surface_forms_added", []))
        for s in e.get("subtypes", {}).values():
            n_forms += len(s.get("surface_forms_added", []))
    return {"version": d.get("version"), "identifier_status_counts": dict(sorted(vocab_status.items())),
            "n_surface_forms_added": n_forms,
            "surface_forms_status": "project_addition_unverified (opt-in via --candidate-surface-forms)"}


def write_heuristics_log(path: pathlib.Path, ctx: "Ctx") -> None:
    lines = ["# HEURISTICS_LOG — 전처리 파이프라인에서 출처로 뒷받침되지 않는 결정 목록", "",
             f"생성: {utcnow()} / scripts/preprocess_abstracts.py", "",
             "이 파일은 코드 안의 `_heuristic()` 등록(§A)과 사전 JSON 의 status 필드 요약(§B)으로 자동 생성된다. "
             "각 항목은 사람 검증 전까지 휴리스틱으로 보고해야 한다(사용자 규칙). 사전 항목별 근거와 검증 절차는 "
             "scripts/certainty_lexicon_en.json, scripts/nlm_section_labels.json, scripts/standard_terms.json, "
             "docs/*_source.md 참조.", "",
             "## A. 코드 안의 프로젝트 결정 (`_heuristic()` 등록)", ""]
    for i, h in enumerate(HEURISTICS, 1):
        lines += [f"### A{i}. {h['what']}", "", f"- **코드 위치**: {h['where']}", f"- **이유**: {h['why']}",
                  f"- **검증 방법**: {h['verify']}", ""]
    lines += ["## B. 사전 JSON 의 status 요약 (실행 시점의 파일 내용)", ""]
    for title, summ in (("certainty_lexicon_en.json", lexicon_status_summary(ctx.lexicon_path)),
                        ("nlm_section_labels.json", section_labels_status_summary(ctx.section_labels_path)),
                        ("standard_terms.json", standard_terms_status_summary(HERE / "standard_terms.json"))):
        lines += [f"### {title}", "", "```json", json.dumps(summ, ensure_ascii=False, indent=1), "```", ""]
    lines += ["## C. 보류·미구현 항목", "",
              "- Notion ⑥ 후반(번역의 한국어 사전 라벨과 일치율): 저장소에 한국어 확신 사전이 아직 없다. `agreement` stage 는 "
              "review_sheet.csv 의 ko_level_human(사람 라벨) 또는 --ko-labels JSON 이 있을 때만 일치율·kappa 를 계산하고, "
              "없으면 status=deferred 로 보고한다.",
              "- 절(clause)·IV–DV 단위 판정은 구현하지 않았다: 혼합 문장은 Sumner 의 최댓값 규칙으로 단계를 정하고 review_flag mixed_levels_review 로 사람 검토에 넘긴다 (A 항목 참조).",
              "- Europe PMC fetch 경로는 컨테이너에서 네트워크가 막혀 실제 pmid 로 검증하지 못했다 (User-Agent 헤더 추가만 함).", ""]
    tr = ctx.report["stages"].get("translate", {})
    ag = ctx.report["stages"].get("agreement", {})
    sec = ctx.report["stages"].get("sections", {})
    notes = []
    if tr.get("error"):
        notes.append(f"- 번역 endpoint 접근 실패: {tr['error']} (허용 필요 호스트: {TRANSLATE_HOST})")
    if ctx.normalize_terms_error:
        notes.append(f"- normalize_terms import 실패: {ctx.normalize_terms_error}")
    if ag.get("status") == "deferred":
        notes.append("- agreement stage: deferred (한국어 라벨 입력 없음)")
    if sec.get("unknown_labels"):
        notes.append(f"- UNKNOWN 섹션 레이블 (사람이 nlm_section_labels.json 에 추가해야 함): {sec['unknown_labels']}")
    for k in ("empty", "truncation_suspects"):
        if ctx.report["stages"].get("clean", {}).get(k):
            notes.append(f"- clean stage {k}: {ctx.report['stages']['clean'][k]}")
    if notes:
        lines += ["## D. 이번 실행 메모", "", *notes, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def stage_report(ctx: "Ctx") -> int:
    ctx.report["generated_at"] = utcnow()
    ctx.report["out_dir"] = str(ctx.out)
    ctx.report["raw_dir"] = str(ctx.raw_dir)
    ctx.report["n_papers"] = len(ctx.papers)
    ctx.report["per_pmid"] = ctx.per_pmid
    ctx.report["heuristics"] = HEURISTICS
    ctx.report["dictionary_status"] = {
        "certainty_lexicon_en.json": lexicon_status_summary(ctx.lexicon_path),
        "nlm_section_labels.json": section_labels_status_summary(ctx.section_labels_path),
        "standard_terms.json": standard_terms_status_summary(HERE / "standard_terms.json"),
    }
    unknown = ctx.report["stages"].get("sections", {}).get("unknown_labels") or sorted(
        {lab for f in ctx.per_pmid.values() for lab in f.get("unknown_labels", [])})
    ctx.report["unknown_section_labels"] = unknown
    _write_json(ctx.out / "preprocessing_report.json", ctx.report)
    write_heuristics_log(ctx.out / "HEURISTICS_LOG.md", ctx)
    print(f"[report] {ctx.out / 'preprocessing_report.json'} ; {ctx.out / 'HEURISTICS_LOG.md'}")
    if unknown:
        print(f"[report] !!! UNKNOWN section labels need a human decision before cue statistics are used: {unknown}",
              file=sys.stderr)
    return 0


# ===========================================================================
# Context / CLI
# ===========================================================================
class Ctx:
    def __init__(self, out: pathlib.Path, raw_dir: pathlib.Path | None, candidates: pathlib.Path,
                 section_labels_path: pathlib.Path = SECTION_LABELS_PATH, lexicon_path: pathlib.Path = LEXICON_PATH,
                 extra_abbrev: set[str] | None = None, papers: list[dict[str, Any]] | None = None,
                 strict: bool = False, tfidf_w3_filter: bool = False, candidate_surface_forms: bool = False,
                 ko_labels_path: pathlib.Path | None = None):
        self.out = out
        self.raw_dir = raw_dir or (out / "raw")
        self.section_labels_path = section_labels_path
        self.lexicon_path = lexicon_path
        self.extra_abbrev = extra_abbrev or set()
        self.strict = strict
        self.tfidf_w3_filter = tfidf_w3_filter
        self.candidate_surface_forms = candidate_surface_forms
        self.ko_labels_path = ko_labels_path
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

                include = self.candidate_surface_forms

                def _nt(text: str, _f=normalize_terms.normalize_text, _inc=include):
                    return _f(text, include_candidate_forms=_inc)

                self._nt = _nt
            except Exception as e:  # noqa: BLE001
                self.normalize_terms_error = f"{type(e).__name__}: {e}"
        return self._nt


def resolve_stages(stages: list[str]) -> list[str]:
    """'clean' rewrites clean/<pmid>.json without the sections enrichment, so whenever 'clean' runs,
    'sections' must run too (the clean-output contract includes analysis_text). Order follows STAGES."""
    wanted = set(stages)
    if "clean" in wanted:
        wanted.add("sections")
    return [s for s in STAGES if s in wanted]


def run(stages: list[str], ctx: Ctx, translate=translate_sentence) -> int:
    funcs = {"fetch": stage_fetch, "clean": stage_clean, "sections": stage_sections, "sentences": stage_sentences,
             "translate": lambda c: stage_translate(c, translate), "cues": stage_cues, "tokens": stage_tokens,
             "normalize": stage_normalize, "agreement": stage_agreement, "report": stage_report}
    resolved = resolve_stages(stages)
    added = [s for s in resolved if s not in stages]
    if added:
        print(f"[run] prerequisite stage(s) added automatically: {added}")
    ctx.report["stages_run"] = resolved
    rc = 0
    for st in resolved:
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
    ap.add_argument("--strict", action="store_true", help="fail on lexicon patterns that are not word-anchored")
    ap.add_argument("--tfidf-w3-filter", action="store_true",
                    help="also apply W3 p.47-48 (NLTK stopwords + len>2) to the TF-IDF copy (default: W3 p.44-45 only)")
    ap.add_argument("--candidate-surface-forms", action="store_true",
                    help="also match standard_terms.json surface_forms_added (project_addition_unverified) in the normalize stage")
    ap.add_argument("--ko-labels", type=pathlib.Path,
                    help="JSON {sentence_id: 단정|가능성|연관|무관} for the agreement stage (default: review_sheet.csv ko_level_human)")
    a = ap.parse_args(argv)
    stages = a.stage or list(STAGES)
    if a.raw_dir:
        stages = [s for s in stages if s != "fetch"]
    if a.no_translate:
        stages = [s for s in stages if s != "translate"]
    ctx = Ctx(a.out, a.raw_dir, a.candidates, a.section_labels, a.lexicon,
              ABBREVIATIONS_UNITS if a.abbrev_units else set(), strict=a.strict, tfidf_w3_filter=a.tfidf_w3_filter,
              candidate_surface_forms=a.candidate_surface_forms, ko_labels_path=a.ko_labels)
    a.out.mkdir(parents=True, exist_ok=True)
    return run(stages, ctx)


if __name__ == "__main__":
    sys.exit(main())
