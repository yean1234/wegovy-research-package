# HEURISTICS_LOG — 전처리 파이프라인에서 출처로 뒷받침되지 않는 결정 목록

생성: 2026-10-30T12:14:14+00:00 / scripts/preprocess_abstracts.py

이 파일은 코드 안의 `_heuristic()` 등록(§A)과 사전 JSON 의 status 필드 요약(§B)으로 자동 생성된다. 각 항목은 사람 검증 전까지 휴리스틱으로 보고해야 한다(사용자 규칙). 사전 항목별 근거와 검증 절차는 scripts/certainty_lexicon_en.json, scripts/nlm_section_labels.json, scripts/standard_terms.json, docs/*_source.md 참조.

## A. 코드 안의 프로젝트 결정 (`_heuristic()` 등록)

### A1. Punkt 약어 목록 ABBREVIATIONS = {vs, al, e.g, i.e, dr, fig, no, approx, ca, cf, etc} ('et al.' 은 토큰 'al' 로 처리; Punkt abbrev_types 는 토큰 단위 비교); 단위 약어 {mg, kg} 는 --abbrev-units 로만 추가

- **코드 위치**: preprocess_abstracts.py ABBREVIATIONS / ABBREVIATIONS_UNITS, make_abbrev_tokenizer()
- **이유**: Notion ③ 가 'vs.', 'et al.', 'e.g.' 등을 오분할 위험으로 지목. 'mg.' 는 용량 문장 끝에 흔해 기본 포함 시 두 문장이 합쳐지는 것을 픽스처에서 확인함.
- **검증 방법**: Punkt 가 학습한 abbrev_types 와 비교하고, 23편 초록의 boundary_check 행을 사람이 확인.

### A2. 문장 경계 점검 정규식 BOUNDARY_END_PATTERNS / BOUNDARY_START_PATTERN / INTERNAL_ABBREV_PATTERN / INTERNAL_UNSPLIT_PATTERN('. ' 뒤 대문자·숫자가 문장 안에 남아 있으면 플래그)

- **코드 위치**: preprocess_abstracts.py split_sentences(), flag_boundaries()
- **이유**: Notion ③ 의 예시('vs.', 'et al.', '95% CI 1.2–3.4', 'P < .001', 'e.g.', 'i.e.', 'Dr.', 'Fig.', 'No.', 'approx.')를 정규식으로 옮긴 것. 출처 없는 프로젝트 규칙이며 재현율을 보장하지 않음. 추가로 사전학습 Punkt 가 'mg' 를 약어로 알고 있어 '... at 2.4 mg. No increase ...' 를 한 문장으로 합치는 것을 픽스처에서 확인했으므로, 문장 내부에 남은 '. + 대문자' 경계도 사람 확인 대상으로 플래그한다.
- **검증 방법**: boundary_check=true 문장을 전수 사람 검토; 놓친 오분할은 검수 sheet note 에 기록.

### A3. TOKEN_PATTERN_ANALYSIS: W5 TOKEN_PATTERN 에 '\d+(?:\.\d+)?%' (퍼센트), '[a-z0-9]+(?:-[a-z0-9]+)+' (하이픈 결합어: non-arteritic, glp-1), '\.\d+' (P < .001 의 '.001') 세 대안을 추가

- **코드 위치**: preprocess_abstracts.py TOKEN_PATTERN_ANALYSIS, tokenize_analysis()
- **이유**: Notion ⑧ '숫자 보존'(2.4 mg, HR 2.05, 95% CI) 과 약어 보존을 위해. W5 p.14 는 세 대안만 제시하므로 확장은 프로젝트 결정.
- **검증 방법**: 23편 초록에서 '%' 포함 토큰과 하이픈 토큰 빈도표를 뽑아 분할 오류가 없는지 확인.

### A4. TF-IDF 사본(tokens_tfidf)에 W3 p.44-45 (lower + 글자만 re.sub + split) 만 적용하고, W3 p.47-48 의 NLTK 불용어 + 사용자 불용어 + len(word)>2 필터는 기본 적용하지 않음 (--tfidf-w3-filter 로 선택)

- **코드 위치**: preprocess_abstracts.py tokenize_tfidf(), w3_filter_tokens(), stage_tokens()
- **이유**: Notion ⑦ 은 분석 토큰에 대해서만 불용어·짧은 단어 제거를 금지하므로 TF-IDF 사본에 대한 생략은 프로젝트 결정. W3 p.48 자체가 len>2 를 'user-defined filtering rule' 이라 하고 의미 있는 짧은 단어가 지워질 수 있다고 경고함. 사용자 불용어(W3 p.47 custom stopwords)는 코퍼스 특성에 따른 연구자 결정이라 어떤 목록도 추가하지 않음.
- **검증 방법**: --tfidf-w3-filter 로 두 사본을 만들어 TF-IDF 상위 어휘를 비교; 팀이 어느 쪽을 쓸지 결정 후 tokens_tfidf_rule 에 기록.

### A5. UNKNOWN 레이블 섹션(및 첫 <h4> 앞 텍스트)을 버리지 않고 분석 텍스트에 포함한 채 needs_human_sectioning=true 로 표시

- **코드 위치**: preprocess_abstracts.py split_sections()
- **이유**: 자동으로 버리면 결과·결론 문장을 잃을 수 있고, 자동으로 남기면 배경 문장이 섞일 수 있어 사람이 판단하도록 둠 (nlm_section_labels.json fallback 규칙 'never auto keep/drop' 과 일치).
- **검증 방법**: needs_human_sectioning=true 인 초록의 섹션을 사람이 keep/drop 결정 후 재실행.

### A6. 번역 도구로 미문서화 Google Translate 웹 endpoint (translate_a/single, client=gtx) 사용

- **코드 위치**: preprocess_abstracts.py translate_sentence()
- **이유**: 컨테이너에서 접근 가능한 유일한 번역 경로. 공식 API 가 아니며 응답 형식·가용성이 바뀔 수 있음. 도구명·endpoint·일시를 각 문장에 기록(Notion ④).
- **검증 방법**: 가능하면 공식 Cloud Translation API 또는 DeepL API 로 재번역하고 tool 필드를 갱신; 검수 sheet(⑤)로 사람 대조.

### A7. 문장 단위 적용: Sumner 2014 척도(0-6)를 사람이 아닌 정규식으로, IV–DV 진술이 아닌 '문장' 단위로 적용

- **코드 위치**: preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json unit_of_analysis
- **이유**: Sumner 2014 는 사람 코더가 main claims(보도자료·뉴스: 제목+첫 두 문장; 학술논문: abstract and discussion)에서 IV–DV 쌍과 관계 진술을 뽑아 코딩했다(web appendix ww1, 본문 Methods — 원문 확인). 이 파이프라인은 IV–DV 를 식별하지 않고 문장마다 단서를 찾아 '가장 강한 진술' 규칙(원문 확인)을 문장 안에서 적용한다. level 0 은 Sumner 의 'not applicable'(두 변수 없음)과 구분하지 않는다.
- **검증 방법**: 검수 sheet 에서 사람이 문장별 IV–DV 진술과 단계를 코딩해 일치율(정밀도·재현율)을 보고.

### A8. 부정 창(negation window): 부정어(no/not/neither/cannot; never/nor/n't)가 level≥2 단서보다 앞 N 토큰(기본 5, 사전의 sentence_rule.negation_window_tokens) 안에 있고 그 사이에 절 경계(', ; :' 뒤 공백, but/whereas/although/though/while/however)가 없으면 그 단서를 level 1 로 본다

- **코드 위치**: preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json sentence_rule.negation_scope_boundary_pattern
- **이유**: Sumner 2014 는 진술 전체를 사람이 코딩하고, BioScope(Vincze 2008)는 부정 범위를 구문으로 정한다. 고정 창은 프로젝트 근사치. 절 경계에서 창을 멈추는 것은 Vincze 2008 본문 'Generally, punctuation marks or conjunctions function as scope boundary markers in the corpus'(원문 확인)의 확장이며 경계 목록은 프로젝트 선택. v2 에서 확인된 오류 'Semaglutide, but not liraglutide, was associated with NAION.' → 1 은 쉼표 경계로 이제 2. 남은 위험: 경계 없이 대조 부정이 쓰인 문장, 쉼표로 끊긴 부정 범위.
- **검증 방법**: review_flag 'negation_window_applied' 문장을 전수 사람 검토; 가능하면 NegEx (Chapman WW et al. J Biomed Inform 2001;34(5):301-310 — 서지사항 unverified_from_memory) 같은 검증된 부정 탐지와 비교.

### A9. 수식어 위치 규칙: may/might/could/appears(→4), can(→5)이 level-6 단서 '앞'(같은 문장 어디든, 또는 단서 span 안)에 있으면 적용; possible/potential/likely/probably/putative/plausible, seem, hypothesis 류도 →4 (프로젝트 확장)

- **코드 위치**: preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json modifiers
- **이유**: Sumner 부록: 'Causal statement (examples in level 6) preceded by conditional, such as might, could, may, appears' / 'preceded by can' (원문 확인). '앞에 있다'를 거리 제한 없이 문장 안 위치로만 판단하는 것과 형용사·부사형 hedge 를 같은 취급하는 것은 프로젝트 조작화.
- **검증 방법**: 검수 sheet 에서 level 4/5 문장의 수식어가 실제로 그 인과 진술을 수식하는지 사람이 확인.

### A10. mixed_levels_review: 한 문장에 유효 level 1 단서와 유효 level≥2 단서가 함께 있으면 review_flag 만 붙인다(단계는 Sumner 대로 최댓값)

- **코드 위치**: preprocess_abstracts.py score_sentence()
- **이유**: v2 의 'no_relationship 우선' 규칙(level-1 단서가 있으면 무조건 1; review_flag no_relationship_overrides_level>=5)은 Sumner 부록 'Where statements of different levels were made within the analysed segments of text, stronger statements trumped weaker ones' 와 모순되어 v3 에서 삭제했다. Sumner 는 IV–DV 쌍별로 사람이 코딩했으므로 한 문장의 서로 다른 진술은 사람이 나눠 봐야 한다.
- **검증 방법**: mixed_levels_review 문장을 검수 sheet 에서 우선 검토하고 IV–DV 별 단계를 note 에 기록.

### A11. explicitly_probabilistic: probabilistic_cues(risk/chance/likelihood/makes more likely/tendency/rate + 프로젝트 확장 odds/hazard/probability/incidence/more·less likely)가 있고 문장 level≥1 일 때만 True

- **코드 위치**: preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json probabilistic_cues, probabilistic_rule
- **이유**: Sumner 부록은 단계와 별도로 'whether or not the statement of relationship was explicitly probabilistic' 을 코딩했다(원문 확인). level≥1(관계 또는 무관계 진술이 있음)일 때만 세는 것과 'risk factor(s)' 제외는 프로젝트 조작화.
- **검증 방법**: 검수 sheet 에서 explicitly_probabilistic 문장을 표본 검토.

### A12. 효과 측정치·기술통계 단서(type effect_measure: HR/OR/RR/IRR/95% CI/P value; descriptive_frequency: prevalence/incidence of)는 문장 level 을 정하지 않고 evidence_flags 로만 기록 (v3: 'risk of' 는 level 단서에서 빠지고 Sumner 의 별도 코드 explicitly_probabilistic 으로 이동; requires_cooccurrence 기능은 코드에 남아 있으나 현재 사전에는 쓰는 항목이 없음)

- **코드 위치**: preprocess_abstracts.py score_sentence(); certainty_lexicon_en.json evidence_flag_types, entries[*].requires_cooccurrence
- **이유**: Sumner 2014 는 '관계 주장'을 코딩하는데, 통계량 이름만 나오는 METHODS 문장('We estimated hazard ratios using Cox models to assess the risk of NAION')이 level 2(연관)로 잡혀 연관 비율이 부풀려지는 것을 확인함. 이 항목들은 애초에 project_addition 이었음.
- **검증 방법**: 검수 sheet 에서 evidence_flags 만 있는 문장(level 0)을 사람이 보고 관계 주장이 실제로 있는지 확인; 있으면 누락 단서를 사전에 추가.

## B. 사전 JSON 의 status 요약 (실행 시점의 파일 내용)

### certainty_lexicon_en.json

```json
{
 "version": "2026-10-30-v3",
 "status_counts": {
  "entries": {
   "project_addition": 9,
   "project_extension_of_verified_category": 39,
   "verified_source_text": 26
  },
  "modifiers": {
   "project_extension_of_verified_category": 4,
   "verified_source_text": 6
  },
  "hedges": {
   "project_addition": 11,
   "project_extension_of_verified_category": 1,
   "unverified_from_memory": 54,
   "verified_source_text": 12
  },
  "boosters": {
   "project_addition": 9,
   "unverified_from_memory": 38
  },
  "probabilistic_cues": {
   "project_extension_of_verified_category": 2,
   "verified_source_text": 6
  }
 },
 "sources": {
  "sumner2014": "verified_source_text",
  "sumner2014_appendix": "verified_source_text",
  "adams2017": "unverified_from_memory",
  "vincze2008": "verified_source_text",
  "hyland2005": "unverified_from_memory",
  "w5_lecture": "verified_lecture_pdf",
  "notion_plan_v2": "project_document"
 },
 "sentence_rule_status": {
  "highest_claim_rule": "verified_source_text — sumner2014_appendix: 'Where statements of different levels were made within the analysed segments of text, stronger statements trumped weaker ones.'; article: 'the presence of stronger statements trumped weaker ones'",
  "modal_modifiers": "verified_source_text — sumner2014_appendix levels 4/5 (may/might/could/appears -> 4; can -> 5)",
  "modifier_position_rule": "project_operationalisation — 'preceded by' is implemented as: the modifier starts before the end of the level-6 cue anywhere in the same sentence (no window, no clause check). HEURISTIC.",
  "negated_causal_verb_is_level_1": "verified_source_text for 'does not result in' (appendix level-1 example); other negated verbs are project_extension_of_verified_category",
  "overlap_negation": "project_operationalisation — a level>=2 cue inside a level-1 cue span is the same statement, not a second claim",
  "negation_window_tokens": "project_addition — PROJECT HEURISTIC (Sumner coded whole statements by hand; BioScope resolves negation scope syntactically). Report it and check with human validation.",
  "negation_scope_boundary": "project_extension_of_verified_category — vincze2008: 'Generally, punctuation marks or conjunctions function as scope boundary markers in the corpus'. The specific boundary list (', ; :' followed by space; but/whereas/although/though/while/however) is a project choice.",
  "mixed_levels_review": "project_addition — review flag only (does not change the level)",
  "sentence_as_unit": "project_addition — HEURISTIC: see unit_of_analysis (Sumner coded main-claim IV–DV statements, not sentences)",
  "explicitly_probabilistic": "verified_source_text (separate binary code) + project gating (level >= 1)",
  "hedge_booster_counts": "hyland2005 lists unverified_from_memory, except hedges verified in vincze2008 (see hedges[*].status)",
  "evidence_flags_not_levels": "project_addition — effect_measure / descriptive_frequency entries are evidence flags, not levels",
  "case_sensitive_abbreviations": "project_addition — (?-i:OR|HR|RR|IRR|CI) groups",
  "removed_in_v3": "no_relationship_precedence (v2: any level-1 cue forced the sentence to 1, overriding the strongest-claim rule; flag no_relationship_overrides_level>=5). Removed because the appendix says stronger statements trump weaker ones."
 },
 "evidence_flag_types": [
  "effect_measure",
  "descriptive_frequency"
 ],
 "collapse_map_status": "project_document; level 5 -> 가능성 and level 3 -> 연관 are project decisions (see docs/certainty_lexicon_source.md)",
 "project_addition_cues": {
  "entries": [
   "adverse event / side effect (noun, attribution implied)",
   "hazard ratio / HR",
   "odds ratio / OR",
   "relative risk / RR",
   "incidence rate ratio / IRR",
   "95% CI",
   "P value",
   "prevalence / incidence of (descriptive)",
   "CI includes 1 / null"
  ],
  "modifiers": [],
  "hedges": [
   "warrant further",
   "further research / studies are needed",
   "should be interpreted with caution",
   "hypothesis-generating",
   "limited evidence / limitations",
   "preliminary",
   "exploratory",
   "inconclusive",
   "unknown / not known / remains to be",
   "not causal / causality not established",
   "residual confounding / confounding"
  ],
  "boosters": [
   "robust",
   "strongly / strong",
   "significant / significantly (statistical)",
   "consistent / consistently",
   "substantial / substantially",
   "markedly / marked",
   "conclude / conclusion",
   "well-established / well established",
   "evidence (noun, positive)"
  ],
  "probabilistic_cues": []
 },
 "project_extension_cues": {
  "entries": [
   "cause",
   "result in",
   "induce",
   "trigger",
   "lower (verb) + outcome noun",
   "elevate (verb) the risk",
   "produce",
   "responsible for",
   "due to",
   "because of",
   "attributable to",
   "contribute to",
   "promote",
   "protect against",
   "linked with / link between (noun)",
   "connection between / with",
   "tied to",
   "predictor / predictive of",
   "effect of",
   "affect",
   "impact",
   "influence (noun) of / on",
   "role of / play a role",
   "implicated in",
   "association (noun)",
   "relation / relationship with / between",
   "correlation / correlate",
   "increased / higher / greater / elevated risk (adjectival, no agent)",
   "more likely / less likely",
   "no association",
   "not associated / not linked / not related",
   "was not associated",
   "no increased risk",
   "did not increase / did not cause (negated causal verb)",
   "no evidence of",
   "not significant / non-significant",
   "without (negation)",
   "lack of / absence of (association)",
   "fail to / failed to (show)"
  ],
  "modifiers": [
   "seem / seems",
   "possible / potential / likely / probably / putative / plausible (before causal cue)",
   "hypothetical / unconfirmed framing",
   "negation (never / nor / n't)"
  ],
  "hedges": [
   "cannot be ruled out"
  ],
  "boosters": [],
  "probabilistic_cues": [
   "more / less likely",
   "odds / hazard / probability / incidence"
  ]
 },
 "unit_of_analysis_status": "project_addition (HEURISTIC; registered in HEURISTICS_LOG)",
 "requires_cooccurrence": [],
 "case_sensitive_groups": [
  "hazard ratio / HR",
  "odds ratio / OR",
  "relative risk / RR",
  "incidence rate ratio / IRR",
  "95% CI"
 ]
}
```

### nlm_section_labels.json

```json
{
 "version": "2026-10-30.4",
 "source_status": "unverified_from_memory",
 "provenance_counts": {
  "nlm_assigned_in_medline": 62,
  "nlm_list_unverified_from_memory": 7,
  "project_decision": 7
 },
 "project_decision_labels": [
  "FINANCIAL DISCLOSURE(S)",
  "FINANCIAL DISCLOSURES",
  "GRAPHICAL ABSTRACT",
  "HIGHLIGHTS",
  "KEY POINTS",
  "LAY SUMMARY",
  "PROSPERO REGISTRATION"
 ]
}
```

### standard_terms.json

```json
{
 "version": "2026-10-30-standard-terms-v1",
 "identifier_status_counts": {
  "code_title_verified_mapping_unverified": 1,
  "not_applicable": 22,
  "project_grouping_of_verified_categories": 1,
  "unverified_from_memory": 34,
  "verified_nlm_mesh_lookup_2026-10-30": 16,
  "verified_who_icd10_2019_inclusion_term": 3,
  "verified_who_icd10_2019_title": 3
 },
 "n_surface_forms_added": 163,
 "surface_forms_status": "project_addition_unverified (opt-in via --candidate-surface-forms)"
}
```

## C. 보류·미구현 항목

- Notion ⑥ 후반(번역의 한국어 사전 라벨과 일치율): 저장소에 한국어 확신 사전이 아직 없다. `agreement` stage 는 review_sheet.csv 의 ko_level_human(사람 라벨) 또는 --ko-labels JSON 이 있을 때만 일치율·kappa 를 계산하고, 없으면 status=deferred 로 보고한다.
- 절(clause)·IV–DV 단위 판정은 구현하지 않았다: 혼합 문장은 Sumner 의 최댓값 규칙으로 단계를 정하고 review_flag mixed_levels_review 로 사람 검토에 넘긴다 (A 항목 참조).
- Europe PMC fetch 경로는 컨테이너에서 네트워크가 막혀 실제 pmid 로 검증하지 못했다 (User-Agent 헤더 추가만 함).

## D. 이번 실행 메모

- agreement stage: deferred (한국어 라벨 입력 없음)
