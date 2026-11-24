"""용어 통일(Notion 계획 ⑨): 사전 기반 엔티티 매칭 모듈.

normalization.json 의 별칭(drug_entities.aliases, side_effects.exact_aliases,
side_effects.subtypes) 으로 텍스트에서 엔티티 언급을 찾고, 각 매칭에 표준 어휘 식별자
(MeSH/ICD-10/KCD-8/INN/ATC/MFDS)를 덧붙인다. 원문은 수정하지 않는다.

standard_terms.json 의 surface_forms_added (기계번역에서 나올 법하다고 작성자가 *예상*한 표기,
status project_addition_unverified) 는 사용자 규칙(사전은 휴리스틱이면 안 됨)에 따라 기본 매칭표에
넣지 않는다. normalize_text(text, include_candidate_forms=True) 로만 켜지며, 그 매칭은
alias_source="standard_terms.json:surface_forms_added" 로 따로 표시되어 사람이 확인한 뒤
normalization.json 으로 승격하거나 지운다.

매칭 규칙 (standard_terms.json["matching_rule"]):
  * 정규화 뷰 = unicodedata.normalize('NFKC', text).casefold() + 연속 공백 1칸 축약
    (W5 강의 p.29 NFKC+casefold). start/end 오프셋은 이 정규화 뷰 기준이다.
  * 영숫자로 시작/끝나는 별칭은 단어 경계 요구, 한글 포함 다단어 별칭은 띄어쓰기 변형 허용
    (normalization.json text_rules 3).
  * 긴 별칭 우선, 비중첩(longest-match-first).
  * 어간추출 없음: 엔티티 인식은 어간추출 전에 수행 (W5 강의 p.61 'NER can be used before stemming').

expansion_only / do_not_merge 항목은 라벨 확정에 쓰지 않으므로 매칭 대상에서 제외한다.
GALLBLADDER, GI_SYMPTOMS 처럼 exact_aliases 가 빈 그룹은 하위유형으로만 매칭된다.
"""
from __future__ import annotations

import json
import pathlib
import re
import unicodedata
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent
NORMALIZATION_PATH = _HERE / "normalization.json"
STANDARD_TERMS_PATH = _HERE / "standard_terms.json"

NORMALIZATION: dict[str, Any] = json.loads(NORMALIZATION_PATH.read_text(encoding="utf-8"))
STANDARD_TERMS: dict[str, Any] = json.loads(STANDARD_TERMS_PATH.read_text(encoding="utf-8"))

_WS = re.compile(r"\s+")
_HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힯]")


def normalize_view(text: str) -> str:
    """NFKC + casefold + 공백 축약. 원문은 건드리지 않고 매칭용 뷰만 만든다."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()


def _alias_pattern(alias: str) -> re.Pattern[str]:
    a = normalize_view(alias)
    # 공백은 한글 별칭이면 0개 이상, 영문 별칭이면 정확히 1칸(뷰에서 이미 축약됨)
    if _HANGUL.search(a):
        body = r"\s*".join(re.escape(p) for p in a.split(" "))
    else:
        body = re.escape(a)
    if a and a[0].isascii() and a[0].isalnum():
        body = r"(?<![a-z0-9])" + body
    if a and a[-1].isascii() and a[-1].isalnum():
        body = body + r"(?![a-z0-9])"
    return re.compile(body)


def _vocab_links(entry: dict[str, Any]) -> dict[str, Any]:
    keys = ("preferred_label_en", "preferred_label_ko", "mesh", "icd10", "kcd8",
            "inn", "atc", "mfds_product_name_ko", "kma_term_candidate")
    return {k: entry[k] for k in keys if k in entry}


def _build_alias_table(include_candidate_forms: bool = False) -> list[dict[str, Any]]:
    """(별칭, entity_id, subtype, 출처, vocab_links) 목록. 긴 별칭 먼저.

    include_candidate_forms=False (기본): normalization.json 별칭만.
    True: standard_terms.json surface_forms_added (project_addition_unverified) 도 추가."""
    rows: list[dict[str, Any]] = []
    std = STANDARD_TERMS["entities"]
    cand = (lambda e: e.get("surface_forms_added", [])) if include_candidate_forms else (lambda e: [])

    def add(alias: str, eid: str, sub: str | None, source: str, links: dict[str, Any]) -> None:
        rows.append({"alias": alias, "entity_id": eid, "subtype": sub, "alias_source": source,
                     "vocab_links": links, "pattern": _alias_pattern(alias),
                     "norm_len": len(normalize_view(alias))})

    for ent in NORMALIZATION["drug_entities"]:
        eid = ent["id"]
        links = _vocab_links(std.get(eid, {}))
        for a in ent.get("aliases", []):
            add(a, eid, None, "normalization.json:aliases", links)
        for a in cand(std.get(eid, {})):
            add(a, eid, None, "standard_terms.json:surface_forms_added", links)

    for ent in NORMALIZATION["side_effects"]:
        eid = ent["id"]
        s_ent = std.get(eid, {})
        links = _vocab_links(s_ent)
        for a in ent.get("exact_aliases", []):
            add(a, eid, None, "normalization.json:exact_aliases", links)
        for a in cand(s_ent):
            add(a, eid, None, "standard_terms.json:surface_forms_added", links)
        for sub, aliases in ent.get("subtypes", {}).items():
            s_sub = s_ent.get("subtypes", {}).get(sub, {})
            sub_links = _vocab_links(s_sub) or links
            for a in aliases:
                add(a, eid, sub, "normalization.json:subtypes", sub_links)
            for a in cand(s_sub):
                add(a, eid, sub, "standard_terms.json:subtypes.surface_forms_added", sub_links)

    # 중복 별칭(같은 정규화 형태, 같은 엔티티/하위유형) 제거, normalization.json 출처 우선
    seen: set[tuple[str, str, str | None]] = set()
    uniq: list[dict[str, Any]] = []
    for r in rows:  # normalization.json 항목이 먼저 추가되므로 먼저 보존됨
        key = (normalize_view(r["alias"]), r["entity_id"], r["subtype"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    uniq.sort(key=lambda r: -r["norm_len"])
    return uniq


ALIAS_TABLE = _build_alias_table()                       # normalization.json only (default)
ALIAS_TABLE_WITH_CANDIDATES = _build_alias_table(True)   # + standard_terms.json surface_forms_added (opt-in)


def normalize_text(text: str, include_candidate_forms: bool = False) -> list[dict[str, Any]]:
    """텍스트에서 엔티티 언급을 찾는다.

    include_candidate_forms=True 이면 standard_terms.json 의 예상 표기(surface_forms_added)도
    매칭하며, 그 매칭은 alias_source 로 구분된다(사람 확인 대상).

    반환: [{entity_id, subtype, matched_alias, matched_text, start, end,
            alias_source, vocab_links}] (start/end 는 normalize_view(text) 기준,
            뷰 안에서 정렬·비중첩).
    """
    table = ALIAS_TABLE_WITH_CANDIDATES if include_candidate_forms else ALIAS_TABLE
    view = normalize_view(text)
    taken = [False] * len(view)
    out: list[dict[str, Any]] = []
    for row in table:  # longest first
        for m in row["pattern"].finditer(view):
            s, e = m.span()
            if e == s or any(taken[s:e]):
                continue
            for i in range(s, e):
                taken[i] = True
            out.append({
                "entity_id": row["entity_id"],
                "subtype": row["subtype"],
                "matched_alias": row["alias"],
                "matched_text": view[s:e],
                "start": s,
                "end": e,
                "alias_source": row["alias_source"],
                "vocab_links": row["vocab_links"],
            })
    out.sort(key=lambda d: d["start"])
    return out


def entity_summary(text: str, include_candidate_forms: bool = False) -> dict[str, Any]:
    """문서 단위 요약: 엔티티별 매칭 수와 표준 라벨."""
    matches = normalize_text(text, include_candidate_forms)
    agg: dict[str, dict[str, Any]] = {}
    for m in matches:
        key = m["entity_id"] if m["subtype"] is None else f'{m["entity_id"]}/{m["subtype"]}'
        d = agg.setdefault(key, {"count": 0, "aliases": [],
                                 "preferred_label_ko": m["vocab_links"].get("preferred_label_ko"),
                                 "preferred_label_en": m["vocab_links"].get("preferred_label_en")})
        d["count"] += 1
        if m["matched_alias"] not in d["aliases"]:
            d["aliases"].append(m["matched_alias"])
    return {"normalized_view": normalize_view(text), "entities": agg, "matches": matches}


if __name__ == "__main__":
    import sys

    demo = (
        "Semaglutide (Wegovy®) 2.4 mg was associated with an increased risk of "
        "nonarteritic anterior ischaemic optic neuropathy (NAION); HR 2.05. "
        "세마글루티드(위고비) 사용자에서 비동맥염성 전방 허혈성 시신경병증과 비동맥성전방허혈성시신경병증이 "
        "보고됐다. GLP-1 RA 계열인 리라글루타이드와 달리 자살 생각·자살 시도, 담석, 급성 췌장염, "
        "갑상선 수질암, 마비성 장폐색증, 메스꺼움·구토·변비도 언급됐다. Mounjaro is tirzepatide."
    )
    text = (sys.stdin.read() if not sys.stdin.isatty() else "").strip() or demo
    res = entity_summary(text, include_candidate_forms="--candidate-surface-forms" in sys.argv)
    print("normalized_view:", res["normalized_view"])
    print()
    for m in res["matches"]:
        sub = f"/{m['subtype']}" if m["subtype"] else ""
        mesh = m["vocab_links"].get("mesh", {})
        print(f"[{m['start']:4d}-{m['end']:4d}] {m['entity_id']}{sub:<20} "
              f"alias={m['matched_alias']!r:<45} mesh={mesh.get('descriptor')!r} "
              f"({mesh.get('status')}) src={m['alias_source']}")
    print()
    print(json.dumps(res["entities"], ensure_ascii=False, indent=1))
