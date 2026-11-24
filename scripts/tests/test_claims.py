"""scripts/claims.py + config/lexicon_ko.yaml 회귀 테스트 (네트워크 없음).

실행:  cd <repo> && python3 -m pytest scripts/tests/test_claims.py -q

선행 사전(TextMining-med-claim-trace)에서 확인된 결함 6가지가 다시 생기지 않는지 본다.
  1. 주장 필터가 OR 이었다            → 약물 AND 그 묶음의 부작용
  2. '부작용'·'발생'만으로 주장이 됐다  → ambiguous_weak 삭제
  3. 부정이 무시됐다                  → 절 끝 부정, 틀 단서 물려받기
  4. hedge/booster 가 겹쳤다          → 코드에서 booster 를 hedge 로 옮긴다
  5. 대상(population)이 거의 항상 잡혔다 → 한정 표현만
  6. '장기'(기간)와 장기(臟器)         → 기간 뜻이 분명한 형태만
아직 못 잡는 유형은 지우지 않고 xfail(strict)로 남겼다. 고쳐지면 XPASS 로 실패하므로 그때 표시를 뗀다.
"""
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import claims as C

REPO = pathlib.Path(__file__).resolve().parents[2]
LEX = C.load_lexicon()


def code(sentence, bundle=None, **kw):
    return C.code_sentence(sentence, bundle, LEX, **kw)


# ---------------------------------------------------------------- 사전 구조
def test_lexicon_structure():
    assert C.DEFAULT_LEXICON == REPO / "config" / "lexicon_ko.yaml"
    assert list(LEX.section("claim_strength")) == ["direct", "possible", "association", "none"]
    assert not LEX.has("claim_strength", "ambiguous_weak") and not LEX.has("claim_strength", "ambiguous")
    assert list(LEX.section("conditions")) == ["population", "dose", "duration", "design", "limitation"]
    assert set(LEX.section("extra_conditions")) == {"animal", "sample_size", "effect_size"}
    assert set(LEX.section("outcome_terms")) == set(C.BUNDLES)
    for key in ("drug_terms", "drug_terms_broad", "hedges", "boosters"):
        assert LEX.section(key)
    assert LEX.section("outcome_terms_broad", "NAION")


def test_every_lexicon_entry_compiles():
    def walk(node, keys=()):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, keys + (k,))
        elif isinstance(node, list) and all(isinstance(x, str) for x in node) and keys[0] != "macros":
            assert LEX.patterns(*keys), keys
    walk(LEX.data)
    for keys in (("modal_after",), ("indirect_question",), ("inquiry_after",), ("negation", "after_cue"),
                 ("negation", "before_cue"), ("negation", "clause_boundary"), ("booster_negation", "pattern")):
        assert LEX.regex(*keys)
    # 매크로가 다 풀렸는지: {RISK} 같은 이름이 정규식에 남아 있으면 안 된다
    for cat in C.STRENGTHS:
        for pat in LEX.patterns("claim_strength", cat):
            assert not re.search(r"\{[A-Z]+\}", pat.pattern), pat.pattern


def test_outcome_terms_match_label_articles_topic():
    """묶음 판정(label_articles.TOPIC)과 주장 필터가 같은 정규식을 쓴다."""
    import label_articles
    for bundle in C.BUNDLES:
        assert LEX.section("outcome_terms", bundle) == ["re:" + label_articles.TOPIC[bundle]]


# ---------------------------------------------------------------- 주장 문장 필터 (결함 1·2)
@pytest.mark.parametrize("sentence,bundle", [
    ("부작용 사례가 보고됐다.", "PANCREATITIS"),                       # 약물도 부작용도 없음
    ("식약처가 위고비 부작용 발생 현황을 공개했다.", "PANCREATITIS"),    # 그 묶음의 부작용 단서 없음
    ("위고비 부작용 사례가 보고됐다.", "PANCREATITIS"),                 # '부작용'은 부작용 단서가 아니다
    ("췌장염은 췌장에 염증이 생기는 질환이다.", "PANCREATITIS"),         # 약물 없음
    ("위고비가 췌장염을 유발한다.", "NAION"),                          # 다른 묶음의 부작용
    ("GLP-1 비만약, 췌장염 위험 9배 높인다", "PANCREATITIS"),           # 일반어는 기본 필터에서 약물이 아니다
    ("이 약은 췌장염을 유발할 수 있다.", "PANCREATITIS"),               # 대용어는 풀지 않는다 (설계상 한계)
])
def test_not_a_claim_sentence(sentence, bundle):
    assert C.is_claim_sentence(sentence, bundle, LEX) is False
    r = code(sentence, bundle)
    assert r["is_claim"] is False and r["strength"] is None and r["cues"] == [] and r["negated"] is False


@pytest.mark.parametrize("sentence,bundle,kw", [
    ("위고비가 췌장염을 유발한다.", "PANCREATITIS", {}),
    ("위고비가 췌장염을 유발한다.", None, {}),                          # bundle=None: 4개 중 아무 부작용
    ("Wegovy는 pancreatitis 위험을 높일 수 있다.", "PANCREATITIS", {}),
    ("세마글루티드 사용자에서 위 무력증이 보고됐다.", "GASTROPARESIS", {}),
    ("오젬픽 복용 후 비동맥염성 전방 허혈성 시신경병증이 발생했다.", "NAION", {}),
    ("GLP-1 비만약, 췌장염 위험 9배 높인다", "PANCREATITIS", {"broad_drug": True}),
    ("위고비 맞으면 실명 위험 2배", "NAION", {"broad_outcome": True}),
])
def test_is_a_claim_sentence(sentence, bundle, kw):
    assert C.is_claim_sentence(sentence, bundle, LEX, **kw) is True
    assert code(sentence, bundle, **kw)["is_claim"] is True


def test_broad_terms_are_off_by_default():
    assert C.is_claim_sentence("위고비 맞으면 실명 위험 2배", "NAION", LEX) is False
    assert C.is_claim_sentence("위고비 맞으면 시신경 손상", "NAION", LEX) is False
    # 넓은 NAION 단서는 NAION 묶음에만 붙는다
    assert C.is_claim_sentence("위고비 맞으면 실명 위험 2배", "PANCREATITIS", LEX, broad_outcome=True) is False


def test_filter_parts_are_reported():
    r = code("췌장염은 췌장에 염증이 생기는 질환이다.", "PANCREATITIS")
    assert (r["has_drug"], r["has_outcome"], r["is_claim"]) == (False, True, False)
    r = code("위고비 부작용 사례가 보고됐다.", "PANCREATITIS")
    assert (r["has_drug"], r["has_outcome"], r["is_claim"]) == (True, False, False)
    r = code("위고비가 췌장염을 유발한다.", "PANCREATITIS")
    assert (r["has_drug"], r["has_outcome"], r["is_claim"]) == (True, True, True)


def test_unknown_bundle_is_an_error():
    with pytest.raises(ValueError):
        C.is_claim_sentence("위고비가 췌장염을 유발한다.", "HAIR_LOSS", LEX)


def test_claim_sentence_without_strength_cue_is_uncoded():
    """ambiguous_weak 삭제: 약물과 부작용이 함께 있어도 관계 표현이 없으면 강도를 주지 않는다."""
    r = code("세마글루타이드를 처방받은 환자 중 37명에게서 NAION이 발병했다.", "NAION")
    assert r["is_claim"] is True and r["strength"] is None
    r = code("위고비 사용량이 폭발적으로 증가했고 췌장염 환자도 있었다.", "PANCREATITIS")
    assert r["strength"] is None                       # '사용량이 증가했다'는 관계 표현이 아니다
    r = code("체중을 15% 줄이는 위고비가 췌장염 논란에 휩싸였다.", "PANCREATITIS")
    assert r["strength"] is None                       # '체중을 줄인다'는 방향 동사의 목적어가 위험이 아니다


# ---------------------------------------------------------------- 강도 4범주
@pytest.mark.parametrize("sentence,bundle,expected", [
    ("위고비가 췌장염을 유발한다.", "PANCREATITIS", "direct"),
    ("위고비 맞으면 췌장염 위험 2배 이상 높아진다", "PANCREATITIS", "direct"),
    ("오젬픽은 NAION 발병의 상대적 위험을 2.19배 증가시키는 것으로 나타났다.", "NAION", "direct"),
    ("위고비가 췌장염을 유발할 수 있다.", "PANCREATITIS", "possible"),
    ("위고비는 췌장염을 유발하거나 악화시킬 수 있다.", "PANCREATITIS", "possible"),
    ("위고비 투여 후 췌장염이 발생할 수 있으므로 주의해야 한다.", "PANCREATITIS", "possible"),
    ("위고비가 자살 충동을 겪을 위험이 있다는 연구결과가 게재된 바 있다.", "SUICIDALITY", "possible"),
    ("위고비 췌장염 우려가 커지고 있다.", "PANCREATITIS", "possible"),
    ("세마글루타이드 사용은 NAION 위험 증가와 관련이 있었다.", "NAION", "association"),
    ("세마글루타이드는 위 마비 위험 증가와 연관되었다.", "GASTROPARESIS", "association"),
    ("세마글루타이드 사용자에서 NAION 위험이 4.28배 높았다.", "NAION", "association"),
    ("오젬픽 복용자, 위 마비 위험 3.67배 높았다", "GASTROPARESIS", "association"),
    ("위고비 사용자의 췌장염 위험은 대조군보다 높지 않았다.", "PANCREATITIS", "none"),
    ("오젬픽이나 위고비 복용이 자살 충동 증가와 관련이 없다는 연구결과가 나왔다.", "SUICIDALITY", "none"),
])
def test_strength_categories(sentence, bundle, expected):
    assert code(sentence, bundle)["strength"] == expected


@pytest.mark.parametrize("sentence,bundle,expected", [
    # 번역된 초록의 학술체
    ("이러한 결과는 세마글루타이드가 NAION의 위험을 증가시킬 수 있음을 시사한다.", "NAION", "possible"),
    ("세마글루타이드는 NAION 발생과 연관이 있는 것으로 보인다.", "NAION", "possible"),
    ("세마글루타이드는 NAION 발생과 연관이 있는 것으로 보였다.", "NAION", "possible"),
    ("세마글루타이드 투여군에서 위 마비 발생률이 더 높은 것으로 나타났다.", "GASTROPARESIS", "association"),
    ("세마글루타이드 투여군에서 위 마비가 더 자주 관찰되었다.", "GASTROPARESIS", "association"),
    ("세마글루타이드 투여군에서 위 마비가 더 자주 관찰됐다.", "GASTROPARESIS", "association"),
    ("세마글루타이드 사용은 췌장염과 관련이 있었다.", "PANCREATITIS", "association"),
    ("세마글루타이드 사용은 췌장염 위험 증가와 연관되었다.", "PANCREATITIS", "association"),
])
def test_academic_register_of_translated_abstracts(sentence, bundle, expected):
    assert code(sentence, bundle)["strength"] == expected


def test_strongest_cue_wins_after_negation():
    r = code("위고비는 췌장염 위험을 높이지만 자살 위험은 높이지 않는다.", None)
    assert r["strength"] == "direct" and r["negated"] is True     # 부정된 단서가 있어도 남은 direct 가 이긴다
    assert [c["category"] for c in r["cues"]] == ["direct", "none"]


def test_broad_outcome_possible():
    s = "위고비를 맞으면 실명할 수 있다는 연구 결과가 나왔다."
    assert code(s, "NAION")["is_claim"] is False                   # 좁은 목록에는 '실명'이 없다
    r = code(s, "NAION", broad_outcome=True)
    assert r["is_claim"] is True and r["strength"] == "possible"


def test_cue_fields_and_offsets():
    r = code("위고비가 췌장염을 유발할 수 있다.", "PANCREATITIS")
    (cue,) = r["cues"]
    assert set(cue) >= {"category", "text", "start", "end"}
    assert r["sentence"][cue["start"]:cue["end"]] == cue["text"]
    assert cue["base"] == "direct" and cue["category"] == "possible" and cue["rule"] == "modal"


# ---------------------------------------------------------------- 부정 (결함 3)
@pytest.mark.parametrize("sentence,bundle", [
    ("위고비가 췌장염을 유발한다는 근거는 없다.", "PANCREATITIS"),
    ("위고비가 췌장염 위험을 높이는 것으로 보이지는 않는다.", "PANCREATITIS"),
    ("세마글루타이드와 췌장염 사이에 유의한 연관성은 발견되지 않았다.", "PANCREATITIS"),
    ("세마글루타이드와 췌장염 사이의 연관성은 확인되지 않았다.", "PANCREATITIS"),
    ("위고비가 췌장염 위험을 높이는 것은 아니다.", "PANCREATITIS"),
    ("위고비는 췌장염을 유발하지 않는다.", "PANCREATITIS"),
    ("우려와 달리 세마글루타이드는 자살 위험을 높이지 않았다.", "SUICIDALITY"),
    ("자해나 자살 사고가 세마글루타이드 사용자에게서 증가했다는 결과는 나오지 않았다.", "SUICIDALITY"),
    ("세마글루타이드 사용은 자살 생각의 위험 증가와 연관되지 않았다.", "SUICIDALITY"),
    ("위고비가 자살 충동을 일으킨다는 오명을 벗게 됐다.", "SUICIDALITY"),
    ("위고비가 청소년의 자살 위험을 높이기는커녕 낮추는 것으로 나타났다는 주장은 과장이다.", "SUICIDALITY"),
])
def test_negated_claims_are_none(sentence, bundle):
    r = code(sentence, bundle)
    assert r["strength"] == "none", r["cues"]
    assert r["negated"] is True


def test_negated_proposition_inside_a_frame_is_none_not_possible():
    """'~지 않음을 시사한다': 시사한다(possible)가 감싼 명제가 부정이면 none."""
    r = code("세마글루타이드가 자살 사고의 위험을 증가시키지 않음을 시사한다.", "SUICIDALITY")
    assert r["strength"] == "none" and r["strength"] != "possible" and r["negated"] is True
    r = code("위고비가 췌장염과 무관한 것으로 나타났다.", "PANCREATITIS")
    assert r["strength"] == "none"                                 # '것으로 나타났다'(association)가 이기지 않는다
    r = code("세마글루타이드는 췌장염 위험 증가와 관련이 없는 것으로 보인다.", "PANCREATITIS")
    assert r["strength"] == "none"


def test_cannot_conclude_is_possible_not_none():
    """'단정할 수 없다'는 none 이 아니라 possible 로 정했다.

    이유: 이 표현은 관계를 부정하지 않는다. '확정할 수 없다'고 판단을 미룰 뿐이어서, '관계 없음을
    명시'(none)로 세면 무관하다는 주장을 한 것처럼 부풀려진다. 관계가 열려 있다는 불확실성 진술이므로
    possible 로 두고, negated 는 False 로 둔다(부정 규칙이 none 으로 바꾼 것이 아니다). 같은 이유로
    '입증되지 않았다', '불분명하다'도 possible 이다. 반대로 결과가 없었다는 보고('발견되지 않았다',
    '확인되지 않았다', '근거는 없다')는 none 이다. 기준을 바꾸려면 사전의 negation.non_assertion 항목을
    negation.clause_final 로 옮기면 된다.
    """
    r = code("위고비가 췌장염 위험을 높인다고 단정할 수 없다.", "PANCREATITIS")
    assert r["strength"] == "possible" and r["negated"] is False
    assert r["cues"][0]["rule"] == "non_assertion"
    assert r["hedges"]                                             # hedge 로도 잡힌다
    # 선행 사전에서는 direct(단정)였다
    assert r["strength"] != "direct"
    # 부정 + 단정 유보: '유발하지 않는다고 단정할 수 없다' → 관계가 있을 수 있다
    assert code("위고비가 췌장염을 유발하지 않는다고 단정할 수 없다.", "PANCREATITIS")["strength"] == "possible"
    assert code("위고비와 자살 생각 사이의 인과관계는 입증되지 않았다.", "SUICIDALITY")["strength"] == "possible"


def test_negation_scope_stops_at_clause_boundary():
    r = code("위고비는 췌장염을 유발하지만, 자살과의 연관성은 발견되지 않았다.", None)
    assert [c["category"] for c in r["cues"]] == ["direct", "none"]
    # '때문에 ... 않는'의 부정은 '때문'의 것이 아니고, '위험 때문'은 약물이 원인이라는 말도 아니다
    r = code("췌장염 위험 때문에 위고비를 처방하지 않는 의사도 있다.", "PANCREATITIS")
    assert r["strength"] is None


def test_indirect_question_and_inquiry_are_not_claims():
    """초록의 목적 문장('~는지 평가하였다', '연관성을 분석했다')은 주장 문장이어도 강도를 주지 않는다."""
    r = code("연구팀은 세마글루타이드가 NAION 위험을 증가시키는지 평가하였다.", "NAION")
    assert r["is_claim"] is True and r["strength"] is None
    assert r["cues"][0]["rule"] == "indirect_question" and r["cues"][0]["category"] is None
    r = code("본 연구는 세마글루타이드와 NAION의 연관성을 평가하였다.", "NAION")
    assert r["strength"] is None and r["cues"][0]["rule"] == "inquiry"
    # 간접 의문 + 불확실: 불확실성 진술이므로 possible
    assert code("위고비가 췌장염을 유발하는지는 아직 불분명하다.", "PANCREATITIS")["strength"] == "possible"


def test_question_is_flagged_but_strength_is_kept():
    r = code("위고비, 췌장염 유발?", "PANCREATITIS")
    assert r["question"] is True and r["strength"] == "direct"
    assert code("위고비가 췌장염을 유발한다.", "PANCREATITIS")["question"] is False
    assert code('"위고비, 췌장염 유발?"', "PANCREATITIS")["question"] is True


@pytest.mark.xfail(strict=True, reason="이중 부정('~지 않는 것은 아니다')은 처리하지 않는다: none 으로 나온다")
def test_double_negation_known_limit():
    assert code("위고비가 췌장염 위험을 높이지 않는 것은 아니다.", "PANCREATITIS")["strength"] != "none"


@pytest.mark.xfail(strict=True, reason="단서의 주어가 약물인지 확인하지 않는다: 질환이 주어인 인과 동사도 잡힌다")
def test_causal_verb_about_the_disease_known_limit():
    r = code("세마글루타이드 사용자에게 나타난 NAION은 영구적인 시력 상실을 초래할 수 있다.", "NAION")
    assert r["strength"] is None


@pytest.mark.xfail(strict=True, reason="단서가 그 묶음의 부작용에 대한 말인지 확인하지 않는다: 다른 결과(저혈당)의 위험 서술도 잡힌다")
def test_cue_about_another_outcome_known_limit():
    r = code("세마글루타이드는 저혈당 위험이 낮고 췌장염 사례도 드물다.", "PANCREATITIS")
    assert r["strength"] is None


# ---------------------------------------------------------------- hedge / booster (결함 4)
@pytest.mark.parametrize("text", ["확실하지 않다", "분명하지 않다", "아직 불확실하다", "입증되지 않았다",
                                  "아직 불분명하다", "확실치 않다", "인과관계를 입증한 것은 아니다"])
def test_negated_booster_is_a_hedge(text):
    hedges, boosters = C.find_hedges_boosters(text, LEX)
    assert boosters == [] and len(hedges) >= 1
    r = code(text)
    assert r["boosters"] == [] and len(r["hedges"]) >= 1          # code_sentence 도 같은 값을 준다


def test_plain_booster_is_counted_once():
    hedges, boosters = C.find_hedges_boosters("인과관계가 입증됐다", LEX)
    assert boosters == ["입증"] and hedges == []
    assert C.find_hedges_boosters("위고비(성분명 세마글루타이드)를 맞았다", LEX) == ([], [])   # '성분명'의 '분명'


def test_hedges_and_boosters_are_computed_for_non_claim_sentences():
    r = code("아직 확실하지 않지만 효과가 있을 수 있다.", "PANCREATITIS")
    assert r["is_claim"] is False and r["boosters"] == [] and len(r["hedges"]) >= 2


# ---------------------------------------------------------------- 조건 5범주 (결함 5·6)
def cond(text):
    return {k: v for k, v in C.find_conditions(text, LEX).items() if v}


def test_population_needs_a_qualifier():
    assert "population" not in cond("위고비는 비만 환자의 체중 감량에 쓰인다.")
    assert "population" not in cond("과체중 성인 참가자와 당뇨 환자 대상자를 모집했다.")
    assert "population" not in cond("2세대 비만약이 나왔다.")
    assert "population" not in cond("제2형 당뇨병 치료제 오젬픽")           # 약의 적응증 소개
    assert "population" in cond("65세 이상 고령 환자에서 위험이 컸다.")
    assert "population" in cond("제2형 당뇨병 환자에서만 위험이 높았다.")
    assert "population" in cond("당뇨병이 없는 비만 환자를 대상으로 했다.")
    assert "population" in cond("임신부와 청소년은 제외했다.")


def test_duration_does_not_match_organ():
    assert "duration" not in cond("장기 손상 위험")
    assert "duration" not in cond("주요 장기에 미치는 영향")
    assert "duration" in cond("장기 복용 시")
    assert "duration" in cond("장기간 추적했다")


def test_dose_duration_design_limitation():
    c = cond("2.4mg을 68주간 투여")
    assert "dose" in c and "duration" in c
    c = cond("관찰연구여서 인과관계를 입증한 것은 아니다")
    assert "design" in c and "limitation" in c
    # '관찰연구'의 '관찰'은 연관 단서('관찰됐다')가 아니다
    assert code("위고비와 췌장염에 대한 관찰연구가 발표됐다.", "PANCREATITIS")["strength"] is None


def test_default_conditions_are_five_and_extras_are_opt_in():
    r = code("환자 1만7000명을 분석한 결과 위험비(HR)는 4.28배였다.")
    assert list(r["conditions"]) == list(C.CONDITION_CATEGORIES)
    extra = C.find_conditions("환자 1만7000명을 분석한 결과 위험비(HR)는 4.28배였다.", LEX, include_extra=True)
    assert extra["sample_size"] and extra["effect_size"] and extra["animal"] == []


# ---------------------------------------------------------------- 문장 분리 / 문서
DOC = """(서울=연합뉴스) 홍길동 기자 = 위고비(성분명 세마글루타이드)가 췌장염을 유발할 수 있다는 연구 결과가 나왔다. 연구팀은 2.4mg을 68주간 투여한 65세 이상 환자를 추적 관찰했다.
다만 이번 연구는 관찰연구여서 인과관계를 입증한 것은 아니다. 세마글루타이드와 췌장염 사이에 유의한 연관성은 발견되지 않았다는 반론도 있다.
사진=게티이미지
무단 전재 및 재배포 금지"""
DOC_SENTENCES = [
    "위고비(성분명 세마글루타이드)가 췌장염을 유발할 수 있다는 연구 결과가 나왔다.",
    "연구팀은 2.4mg을 68주간 투여한 65세 이상 환자를 추적 관찰했다.",
    "다만 이번 연구는 관찰연구여서 인과관계를 입증한 것은 아니다.",
    "세마글루타이드와 췌장염 사이에 유의한 연관성은 발견되지 않았다는 반론도 있다.",
]


@pytest.mark.parametrize("use_kiwi", [None, False])            # kiwipiepy 가 있으면 kiwi, 없으면 정규식
def test_split_sentences_drops_byline_and_noise(use_kiwi):
    assert C.split_sentences(DOC, use_kiwi=use_kiwi) == DOC_SENTENCES
    assert C.split_sentences("", use_kiwi=use_kiwi) == []


def test_split_sentences_can_keep_noise():
    kept = C.split_sentences(DOC, drop_noise=False, use_kiwi=False)
    assert any("게티이미지" in s for s in kept) and len(kept) > len(DOC_SENTENCES)


def test_code_document_summary():
    r = C.code_document(DOC, "PANCREATITIS", LEX)
    assert [s["sentence"] for s in r["sentences"]] == DOC_SENTENCES
    assert [s["strength"] for s in r["sentences"]] == ["possible", None, None, "none"]
    assert r["summary"] == {
        "n_sentences": 4,
        "n_claim_sentences": 2,
        "strength_counts": {"direct": 0, "possible": 1, "association": 0, "none": 1},
        "n_uncoded_claim_sentences": 0,
        "max_strength": "possible",
        "conditions_present": {"population": True, "dose": True, "duration": True, "design": True,
                               "limitation": True},
        "hedge_sentences": 2,              # '유발할 수 있다', '입증한 것은 아니다'
        "booster_sentences": 0,            # '입증'은 부정되어 hedge 로 갔다
        "claim_hedge_sentences": 1,
        "claim_booster_sentences": 0,
        "question_claim_sentences": 0,
    }
    # 묶음이 다르면 주장 문장이 없다
    other = C.code_document(DOC, "NAION", LEX)["summary"]
    assert other["n_claim_sentences"] == 0 and other["max_strength"] is None
    assert other["conditions_present"]["dose"] is True          # 조건은 주장 문장이 아니어도 센다


def test_code_document_empty_text():
    s = C.code_document("", "NAION", LEX)["summary"]
    assert s["n_sentences"] == 0 and s["strength_counts"] == dict.fromkeys(C.STRENGTHS, 0)
    assert s["conditions_present"] == dict.fromkeys(C.CONDITION_CATEGORIES, False)


def test_html_entities_and_fullwidth_are_normalized():
    r = code("&#39;위고비&#39; 췌장염 유발？", "PANCREATITIS")
    assert r["sentence"] == "'위고비' 췌장염 유발?" and r["question"] is True and r["strength"] == "direct"


# ---------------------------------------------------------------- CLI
def test_cli_prints_json():
    env = dict(os.environ, CLAIMS_NO_KIWI="1", PYTHONIOENCODING="utf-8")
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "claims.py"),
                          "위고비가 췌장염을 유발할 수 있다.", "PANCREATITIS"],
                         capture_output=True, text=True, encoding="utf-8", env=env, check=True)
    r = json.loads(out.stdout)
    assert r["is_claim"] is True and r["strength"] == "possible" and r["hedges"] == ["수 있"]
    bad = subprocess.run([sys.executable, str(REPO / "scripts" / "claims.py"), "문장", "NOPE"],
                         capture_output=True, text=True, encoding="utf-8", env=env)
    assert bad.returncode == 2
