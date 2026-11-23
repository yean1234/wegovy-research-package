#!/usr/bin/env python3
"""주장 문장 필터 + 관계 표현 강도(4범주) + 조건 표현 + hedge/booster 규칙 코딩.

논문 초록(한국어 번역) / 기사 본문 / 기사 제목에 같은 사전(config/lexicon_ko.yaml)을 적용한다.
제목도 본문 문장과 똑같이 한 문장으로 `code_sentence`에 넣는다(필터 예외 없음).

    RQ1  code_sentence(...)['strength'] — 주장 문장(약물 AND 그 묶음의 부작용이 같은 문장)에만 값이 있다.
         direct(직접 인과) > possible(가능성) > association(연관) > none(무관)
    RQ2  code_document(...)['summary']['conditions_present'] — 대상·용량·기간·설계·한계

공개 API
    load_lexicon(path=None) -> Lexicon
    split_sentences(text) -> list[str]
    is_claim_sentence(sentence, bundle, lex) -> bool
    code_sentence(sentence, bundle, lex) -> dict
    code_document(text, bundle, lex) -> dict

CLI
    python scripts/claims.py "위고비가 췌장염을 유발할 수 있다." PANCREATITIS
    python scripts/claims.py "위고비 맞으면 실명할 수 있다" NAION --broad-outcome

필수 의존성은 표준 라이브러리와 PyYAML뿐이다. kiwipiepy 가 있으면 문장 분리에 쓰고, 없으면
(또는 환경변수 CLAIMS_NO_KIWI=1 이면) 정규식으로 나눈다.

규칙과 한계는 docs/lexicon_changes.md 에 있다. 이 모듈의 값은 사람 검증 전의 '자동 코딩'이다.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
DEFAULT_LEXICON = REPO / "config" / "lexicon_ko.yaml"

BUNDLES = ("NAION", "PANCREATITIS", "SUICIDALITY", "GASTROPARESIS")
STRENGTHS = ("direct", "possible", "association", "none")      # 강한 것부터
CONDITION_CATEGORIES = ("population", "dose", "duration", "design", "limitation")
_RANK = {name: len(STRENGTHS) - i for i, name in enumerate(STRENGTHS)}   # direct 4 … none 1
_TIE_ORDER = {"none": 0, "direct": 1, "possible": 2, "association": 3}    # 같은 구간이 겹칠 때


# ====================================================================== 사전
def _compile_entry(entry: str, macros: dict[str, str]) -> re.Pattern:
    entry = str(entry)
    if entry.startswith("re:"):
        return re.compile(_expand(entry[3:], macros), re.IGNORECASE)
    return re.compile(re.escape(entry), re.IGNORECASE)


def _expand(pattern: str, macros: dict[str, str]) -> str:
    """{이름}을 macros 값으로 바꾼다. {0,8} 같은 수량자는 이름이 아니므로 그대로 둔다."""
    for name, value in macros.items():
        pattern = pattern.replace("{" + name + "}", value)
    return pattern


class Lexicon:
    """YAML 사전을 정규식으로 컴파일해 들고 있는다."""

    def __init__(self, data: dict, path: Path | None = None) -> None:
        self.data = data or {}
        self.path = path
        self.macros = {str(k): str(v) for k, v in (self.data.get("macros") or {}).items()}
        for _ in range(5):                                    # 매크로 안의 매크로({Q} 안의 {CMP} 등)를 푼다
            self.macros = {k: _expand(v, self.macros) for k, v in self.macros.items()}
        self._compiled: dict[tuple, list[re.Pattern]] = {}

    def section(self, *keys):
        node = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                raise KeyError(keys)
            node = node[k]
        return node

    def has(self, *keys) -> bool:
        try:
            self.section(*keys)
            return True
        except KeyError:
            return False

    def patterns(self, *keys) -> list[re.Pattern]:
        """목록 항목(문자열 또는 're:')을 컴파일한 것."""
        if keys not in self._compiled:
            entries = self.section(*keys) if self.has(*keys) else []
            if isinstance(entries, str):
                entries = [entries]
            self._compiled[keys] = [_compile_entry(e, self.macros) for e in (entries or [])]
        return self._compiled[keys]

    def regex(self, *keys) -> re.Pattern:
        """정규식 문자열 하나로 된 항목(modal_after, negation.after_cue …)."""
        key = ("__regex__",) + keys
        if key not in self._compiled:
            self._compiled[key] = [re.compile(_expand(str(self.section(*keys)), self.macros), re.IGNORECASE)]
        return self._compiled[key][0]

    def find(self, text: str, *keys) -> list[dict]:
        """일치 구간 목록. 겹치면 긴 것 하나만 남긴다."""
        found = []
        for pat in self.patterns(*keys):
            for m in pat.finditer(text or ""):
                if m.group().strip():
                    found.append({"text": m.group(), "start": m.start(), "end": m.end()})
        return _dedupe(found)

    def any(self, text: str, *keys) -> bool:
        return any(p.search(text or "") for p in self.patterns(*keys))


def _dedupe(spans: list[dict]) -> list[dict]:
    """겹치는 일치 중 가장 긴 것을 남긴다(길이가 같으면 앞의 것, 그다음 none > direct > possible > association)."""
    order = sorted(spans, key=lambda c: (-(c["end"] - c["start"]), c["start"],
                                         _TIE_ORDER.get(c.get("category"), 9)))
    kept: list[dict] = []
    for c in order:
        if all(c["end"] <= k["start"] or c["start"] >= k["end"] for k in kept):
            kept.append(c)
    return sorted(kept, key=lambda c: c["start"])


@lru_cache(maxsize=8)
def _load_cached(path_str: str) -> Lexicon:
    path = Path(path_str)
    with open(path, encoding="utf-8") as f:
        return Lexicon(yaml.safe_load(f) or {}, path)


def load_lexicon(path: str | os.PathLike | None = None) -> Lexicon:
    """사전을 읽는다. 기본 경로는 레포의 config/lexicon_ko.yaml."""
    return _load_cached(str(Path(path).resolve() if path else DEFAULT_LEXICON))


# ====================================================================== 문장 분리
# (선행 프로젝트 src/medclaim/nlp/segment.py 의 문장 분리·잡음 문장 제거를 옮겼다)
NOISE_PATTERNS = [
    re.compile(r"^\(?[^()]{0,25}=\s*[^()]{0,15}\)?\s*$"),          # (서울=연합뉴스)
    re.compile(r"^\[?[^\]]{0,30}기자\]?$"),                          # [홍길동 기자]
    re.compile(r"(사진|그래픽|이미지|자료)\s*=\s*\S+"),               # 사진=게티이미지
    re.compile(r"게티이미지|이미지투데이|클립아트코리아|셔터스톡"),
    re.compile(r"무단\s*전재|재배포\s*금지|저작권자|Copyright|ⓒ|©"),
    re.compile(r"^[▶☞■◆●▲△※]"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),                          # 이메일
]
LEADING_BYLINE = re.compile(
    r"^\s*(\([^)]{1,30}=[^)]{1,20}\)\s*)?(\[[^\]]{1,40}\]\s*)?([가-힣]{2,4}\s*(기자|특파원|객원기자)\s*=\s*)?"
)
BOILERPLATE_SENTENCE = re.compile(
    r"Global Health Pick|독자 여러분께 .{0,40}제공합니다|^(Advertisement\s*)+$|구글에서 선호하는 매체|"
    r"재판매 및 DB\s*금지")
INNER_BYLINE = re.compile(r"[가-힣]{2,4}\s*(인턴\s*)?(기자|특파원)\s*=\s*")
_REGEX_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+(?=\S)")


def normalize_text(text: str) -> str:
    """HTML 엔티티 풀기 + NFKC 정규화(전각 문자·'㎎'·'…' 등을 풀어 쓴다) + 공백 정리.

    단서 위치(start/end)는 이 결과 기준이다."""
    text = unicodedata.normalize("NFKC", html.unescape(text or ""))
    text = text.replace("​", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


@lru_cache(maxsize=1)
def _get_kiwi():
    if os.environ.get("CLAIMS_NO_KIWI"):
        return None
    try:
        from kiwipiepy import Kiwi
    except Exception:                      # kiwipiepy 미설치·로딩 실패 → 정규식 분리
        return None
    try:
        return Kiwi()
    except Exception:
        return None


def is_noise_sentence(sentence: str) -> bool:
    """바이라인·사진 설명·저작권 고지 같은 기사 잡음 문장인가."""
    s = sentence.strip()
    if len(s) < 8:
        return True
    if BOILERPLATE_SENTENCE.search(s) and not INNER_BYLINE.search(s):
        return True
    if len(s) < 60 and any(p.search(s) for p in NOISE_PATTERNS):
        return True
    return False


def strip_leading_byline(sentence: str) -> str:
    m = INNER_BYLINE.search(sentence[:250])
    if m:
        sentence = sentence[m.end():]
    return LEADING_BYLINE.sub("", sentence, count=1).strip()


def split_sentences(text: str, drop_noise: bool = True, use_kiwi: bool | None = None) -> list[str]:
    """문단(줄) 단위로 나눈 뒤 문장으로 쪼갠다. drop_noise 이면 바이라인을 떼고 잡음 문장을 버린다.

    use_kiwi=None 이면 kiwipiepy 가 있을 때만 쓴다. False 면 정규식 분리를 강제한다.
    """
    text = normalize_text(text)
    if not text:
        return []
    kiwi = _get_kiwi() if use_kiwi in (None, True) else None
    out: list[str] = []
    for para in (p.strip() for p in text.split("\n")):
        if not para:
            continue
        if kiwi is not None:
            out.extend(s.text.strip() for s in kiwi.split_into_sents(para))
        else:
            out.extend(s.strip() for s in _REGEX_SENT_SPLIT.split(para))
    out = [s for s in out if s]
    if drop_noise:
        out = [strip_leading_byline(s) for s in out]
        out = [s for s in out if s and not is_noise_sentence(s)]
    return out


# ====================================================================== 주장 문장 필터
def _check_bundle(bundle: str | None) -> str | None:
    if bundle is None or bundle == "" or str(bundle).upper() in ("ANY", "ALL", "NONE"):
        return None
    b = str(bundle).upper()
    if b not in BUNDLES:
        raise ValueError(f"알 수 없는 묶음: {bundle!r} (가능한 값: {', '.join(BUNDLES)} 또는 None)")
    return b


def _has_drug(s: str, lex: Lexicon, broad: bool = False) -> bool:
    return lex.any(s, "drug_terms") or (broad and lex.any(s, "drug_terms_broad"))


def _has_outcome(s: str, bundle: str | None, lex: Lexicon, broad: bool = False) -> bool:
    for b in ([bundle] if bundle else BUNDLES):
        if lex.any(s, "outcome_terms", b):
            return True
        if broad and lex.has("outcome_terms_broad", b) and lex.any(s, "outcome_terms_broad", b):
            return True
    return False


def is_claim_sentence(sentence: str, bundle: str | None = None, lex: Lexicon | None = None, *,
                      broad_outcome: bool = False, broad_drug: bool = False) -> bool:
    """약물 단서 AND 그 묶음의 부작용 단서가 같은 문장에 있으면 True.

    bundle=None 이면 4개 묶음 중 아무 부작용이나 있으면 된다. 기본은 좁은 목록(drug_terms,
    outcome_terms)만 쓴다. broad_outcome/broad_drug 는 민감도 분석용이다.
    """
    lex = lex or load_lexicon()
    bundle = _check_bundle(bundle)
    s = normalize_text(sentence)
    return bool(_has_drug(s, lex, broad_drug) and _has_outcome(s, bundle, lex, broad_outcome))


# ====================================================================== 강도 코딩
def _search_any(patterns: list[re.Pattern], text: str) -> re.Match | None:
    for p in patterns:
        m = p.search(text)
        if m:
            return m
    return None


def _clause_bounds(cue: dict, boundaries: list[tuple[int, int]], n: int) -> tuple[int, int]:
    """단서가 든 절의 (시작, 끝). 단서 안에 든 경계(숫자 속 쉼표 등)는 무시한다."""
    start, end = 0, n
    for b_start, b_end in boundaries:
        if b_end <= cue["start"]:
            start = max(start, b_end)
        elif b_end > cue["end"]:
            end = min(end, max(b_start, cue["end"]))
            break
    return start, end


def _strength_cues(s: str, lex: Lexicon) -> list[dict]:
    """사전 일치 → 부정·간접 의문·탐구 서술·단정 유보·양태·틀 규칙을 적용한 단서 목록.

    각 단서: category(조정 뒤 범주. 간접 의문·탐구 서술이라 세지 않는 단서는 None), text, start, end,
             base(사전 범주), rule(적용된 규칙. 없으면 '').
    """
    raw = []
    for cat in STRENGTHS:
        for pat in lex.patterns("claim_strength", cat):
            for m in pat.finditer(s):
                if m.group().strip():
                    raw.append({"category": cat, "text": m.group(), "start": m.start(), "end": m.end()})
    cues = _dedupe(raw)
    if not cues:
        return []

    neg_after = lex.regex("negation", "after_cue")
    neg_before = lex.regex("negation", "before_cue")
    n_eojeol = int(lex.section("negation", "after_cue_eojeols")) if lex.has("negation", "after_cue_eojeols") else 1
    clause_final = lex.patterns("negation", "clause_final")
    non_assertion = lex.patterns("negation", "non_assertion")
    modal = lex.regex("modal_after")
    indirect = lex.regex("indirect_question")
    inquiry = lex.regex("inquiry_after") if lex.has("inquiry_after") else None
    frames = lex.patterns("frame_cues")
    boundaries = [(m.start(), m.end()) for m in lex.regex("negation", "clause_boundary").finditer(s)]
    near = re.compile(r"\S*(?:\s+\S+){0,%d}" % n_eojeol)      # 단서가 든 어절의 나머지 + 다음 어절 N개
    near1 = re.compile(r"\S*(?:\s+\S+)?")
    near2 = re.compile(r"\S*(?:\s+\S+){0,2}")

    for cue in cues:
        base = cue["category"]
        cue["base"], cue["rule"] = base, ""
        c_start, c_end = _clause_bounds(cue, boundaries, len(s))
        cue["_clause"] = (c_start, c_end)                     # (절 시작, 절 끝)
        scope = s[cue["end"]:c_end]                           # 단서 끝 ~ 절 끝
        unsure = _search_any(non_assertion, scope) is not None

        if base == "none":                                    # '연관성이 없다고 단정할 수 없다'
            if unsure:
                cue["category"], cue["rule"] = "possible", "non_assertion"
            continue

        last_eojeol = cue["text"].split()[-1] if cue["text"].split() else cue["text"]
        if indirect.search(last_eojeol + near1.match(scope).group()):
            # '높이는지 조사했다'는 주장이 아니다. '높이는지 불분명하다'는 불확실성 진술이므로 possible.
            cue["category"], cue["rule"] = ("possible" if unsure else None), "indirect_question"
            continue
        if inquiry is not None and inquiry.search(near2.match(scope).group()):
            cue["category"], cue["rule"] = None, "inquiry"   # '연관성을 분석했다'
            continue

        negated = bool(neg_after.search(near.match(scope).group())
                       or neg_before.search(s[c_start:cue["start"]])
                       or _search_any(clause_final, scope))
        if negated:
            if unsure:                                        # '유발하지 않는다고 단정할 수 없다'
                cue["category"], cue["rule"] = "possible", "negated+non_assertion"
            else:
                cue["category"], cue["rule"] = "none", "negated"
        elif base == "direct" and unsure:                     # '높인다고 단정할 수 없다'
            cue["category"], cue["rule"] = "possible", "non_assertion"
        elif base == "direct" and modal.search(scope):        # '유발할 수 있다'
            cue["category"], cue["rule"] = "possible", "modal"

    # 틀 단서('~것으로 나타났다', '~을 시사한다')는 같은 절의 앞선 명제가 none 이면 none 을 물려받는다.
    for cue in cues:
        if cue["rule"] or cue["category"] not in ("possible", "association"):
            continue
        if not any(p.search(cue["text"]) for p in frames):
            continue
        c_start = cue["_clause"][0]
        if any(o["category"] == "none" and o["start"] >= c_start and o["end"] <= cue["start"] for o in cues):
            cue["category"], cue["rule"] = "none", "inherited"

    # 논항 단서('위험 증가', '위험 2배')는 같은 절의 뒤따르는 서술어가 none 이면 none 을 물려받는다.
    arguments = lex.patterns("argument_cues")
    for cue in cues:
        if cue["rule"] or cue["category"] != "association":
            continue
        if not any(p.search(cue["text"]) for p in arguments):
            continue
        c_end = cue["_clause"][1]
        if any(o["category"] == "none" and o["start"] >= cue["end"] and o["end"] <= c_end
               and o["rule"] != "inherited" for o in cues):
            cue["category"], cue["rule"] = "none", "inherited"

    for cue in cues:
        del cue["_clause"]
    return cues


def find_hedges_boosters(sentence: str, lex: Lexicon | None = None) -> tuple[list[str], list[str]]:
    """(hedge 일치 목록, booster 일치 목록).

    booster 일치가 hedge 일치 구간과 겹치거나('입증되지 않았다'), 바로 뒤 window 글자(사전의
    booster_negation.window) 안에서 부정이 시작되면('확실하지 않다', '입증한 것은 아니다') booster 가
    아니라 hedge 로 센다. '불확실'·'불분명' 안의 '확실'·'분명'도
    booster 가 아니다.
    """
    lex = lex or load_lexicon()
    s = normalize_text(sentence)
    hedges = lex.find(s, "hedges")
    boosters = lex.find(s, "boosters")
    window = int(lex.section("booster_negation", "window")) if lex.has("booster_negation", "window") else 6
    neg = lex.regex("booster_negation", "pattern")
    kept = []
    for b in boosters:
        if any(h["start"] < b["end"] and b["start"] < h["end"] for h in hedges):
            continue                                          # 이미 hedge 로 세어져 있다
        if b["start"] > 0 and s[b["start"] - 1] == "불":       # 불확실·불분명·불명확
            hedges.append({"text": "불" + b["text"], "start": b["start"] - 1, "end": b["end"]})
            continue
        tail = re.split(r"[,.;!?]", s[b["end"]:b["end"] + window + 6])[0]
        m = neg.search(tail)
        if m and m.start() < window:                          # 부정이 window 글자 안에서 시작
            end = b["end"] + m.end()
            hedges.append({"text": s[b["start"]:end], "start": b["start"], "end": end})
            continue
        kept.append(b)
    hedges.sort(key=lambda h: h["start"])
    return [h["text"] for h in hedges], [b["text"] for b in kept]


def find_conditions(sentence: str, lex: Lexicon | None = None, include_extra: bool = False) -> dict[str, list[str]]:
    """조건 범주별 일치 문자열. 기본은 5범주, include_extra 이면 extra_conditions(동물·표본수·효과크기)도."""
    lex = lex or load_lexicon()
    s = normalize_text(sentence)
    out = {cat: [c["text"] for c in lex.find(s, "conditions", cat)] for cat in CONDITION_CATEGORIES}
    if include_extra and lex.has("extra_conditions"):
        for cat in lex.section("extra_conditions"):
            out[cat] = [c["text"] for c in lex.find(s, "extra_conditions", cat)]
    return out


def code_sentence(sentence: str, bundle: str | None = None, lex: Lexicon | None = None, *,
                  broad_outcome: bool = False, broad_drug: bool = False,
                  include_extra: bool = False) -> dict:
    """한 문장(또는 제목 하나)을 코딩한다.

    반환
      sentence    정규화한 문장 (단서의 start/end 는 이 문자열 기준)
      is_claim    약물 AND 그 묶음의 부작용이 같은 문장에 있는가 (= has_drug and has_outcome)
      has_drug, has_outcome   필터의 두 조건 각각 (broad_* 옵션을 반영한 값)
      strength    'direct' | 'possible' | 'association' | 'none' | None
                  is_claim 이 False 이거나, 주장 문장이지만 강도 단서가 없으면 None
      cues        [{'category','text','start','end','base','rule'}] — is_claim 이 False 면 빈 목록.
                  category 는 규칙 적용 뒤의 범주(간접 의문·탐구 서술이라 세지 않는 단서는 None),
                  base 는 사전 범주, rule 은 '' | 'negated' | 'non_assertion' | 'negated+non_assertion'
                  | 'modal' | 'indirect_question' | 'inquiry' | 'inherited'
      negated     부정 규칙이 단서를 none 으로 바꾼 적이 있는가 (사전의 none 항목에 바로 일치한 것은 False)
      question    물음표로 끝나는가 (표시만 한다. strength 는 그대로 계산)
      hedges, boosters   일치 문자열 목록 (is_claim 과 무관하게 계산)
      conditions  {범주: [일치 문자열]} (is_claim 과 무관하게 계산)
    """
    lex = lex or load_lexicon()
    bundle = _check_bundle(bundle)
    s = normalize_text(sentence)
    has_drug = bool(_has_drug(s, lex, broad_drug))
    has_outcome = bool(_has_outcome(s, bundle, lex, broad_outcome))
    is_claim = has_drug and has_outcome
    cues = _strength_cues(s, lex) if is_claim else []
    counted = [c["category"] for c in cues if c["category"]]
    strength = max(counted, key=_RANK.get) if counted else None
    hedges, boosters = find_hedges_boosters(s, lex)
    return {
        "sentence": s,
        "is_claim": is_claim,
        "has_drug": has_drug,
        "has_outcome": has_outcome,
        "strength": strength,
        "cues": cues,
        "negated": any(c["rule"] in ("negated", "inherited") for c in cues),
        "question": bool(re.search(r"\?[\"'”’」』)\]\s]*$", s)),
        "hedges": hedges,
        "boosters": boosters,
        "conditions": find_conditions(s, lex, include_extra),
    }


def code_document(text: str, bundle: str | None = None, lex: Lexicon | None = None, *,
                  broad_outcome: bool = False, broad_drug: bool = False,
                  include_extra: bool = False) -> dict:
    """문서(초록·기사 본문)를 문장으로 나눠 코딩하고 문서 요약을 붙인다.

    반환  {'sentences': [code_sentence 결과 …], 'summary': {…}}
    summary
      n_sentences, n_claim_sentences
      strength_counts            {'direct','possible','association','none'} 주장 문장 수
      n_uncoded_claim_sentences  주장 문장이지만 강도 단서가 없는 문장 수
      max_strength               문서에서 가장 강한 값 (없으면 None)
      conditions_present         {범주: bool} — 문서 어느 문장에든 있으면 True (주장 문장이 아니어도 센다)
      hedge_sentences, booster_sentences               hedge/booster 가 하나라도 있는 문장 수 (전체 문장)
      claim_hedge_sentences, claim_booster_sentences   위와 같되 주장 문장만
      question_claim_sentences   물음표로 끝나는 주장 문장 수
    """
    lex = lex or load_lexicon()
    rows = [code_sentence(s, bundle, lex, broad_outcome=broad_outcome, broad_drug=broad_drug,
                          include_extra=include_extra) for s in split_sentences(text)]
    claims = [r for r in rows if r["is_claim"]]
    counts = {k: sum(r["strength"] == k for r in claims) for k in STRENGTHS}
    present = [k for k in STRENGTHS if counts[k]]
    cond_keys = list(rows[0]["conditions"]) if rows else list(CONDITION_CATEGORIES)
    summary = {
        "n_sentences": len(rows),
        "n_claim_sentences": len(claims),
        "strength_counts": counts,
        "n_uncoded_claim_sentences": sum(r["strength"] is None for r in claims),
        "max_strength": present[0] if present else None,
        "conditions_present": {k: any(r["conditions"].get(k) for r in rows) for k in cond_keys},
        "hedge_sentences": sum(bool(r["hedges"]) for r in rows),
        "booster_sentences": sum(bool(r["boosters"]) for r in rows),
        "claim_hedge_sentences": sum(bool(r["hedges"]) for r in claims),
        "claim_booster_sentences": sum(bool(r["boosters"]) for r in claims),
        "question_claim_sentences": sum(r["question"] for r in claims),
    }
    return {"sentences": rows, "summary": summary}


# ====================================================================== CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="한 문장을 코딩해 JSON 으로 출력한다.")
    ap.add_argument("sentence", help="코딩할 문장 (또는 --doc 와 함께 여러 문장)")
    ap.add_argument("bundle", nargs="?", default=None,
                    help="묶음 코드: " + " | ".join(BUNDLES) + " (생략하면 4개 중 아무 부작용)")
    ap.add_argument("--broad-outcome", action="store_true", help="outcome_terms_broad 도 부작용 단서로 쓴다")
    ap.add_argument("--broad-drug", action="store_true", help="drug_terms_broad 도 약물 단서로 쓴다")
    ap.add_argument("--extra", action="store_true", help="extra_conditions(동물·표본수·효과크기)도 출력한다")
    ap.add_argument("--doc", action="store_true", help="문서로 보고 문장 분리 + 요약까지 출력한다")
    ap.add_argument("--lexicon", default=None, help="사전 경로 (기본: config/lexicon_ko.yaml)")
    args = ap.parse_args(argv)
    lex = load_lexicon(args.lexicon)
    kw = {"broad_outcome": args.broad_outcome, "broad_drug": args.broad_drug, "include_extra": args.extra}
    try:
        result = (code_document if args.doc else code_sentence)(args.sentence, args.bundle, lex, **kw)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
