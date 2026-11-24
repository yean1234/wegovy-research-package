# 영어 확신·완화 단서 사전(`scripts/certainty_lexicon_en.json`) 출처와 검증 상태 (v3, 2026-10-30)

Notion 계획 ⑥ "영어 원문 교차 확인"에 쓰는 사전이다. 영어 초록의 각 문장에 Sumner et al. (2014)의 인과 주장 강도 0–6을 매기고, 한국어 사전과 같은 단정/가능성/연관/무관으로 접어서 번역문의 한국어 라벨과 일치율을 낸다.

**v3에서 바뀐 근거.** v1·v2는 네트워크가 막혀 Sumner 척도와 예문을 기억에 의존했다(`unverified_from_memory`). v3에서는 Europe PMC로 다음을 직접 읽었다.

| 출처 | 확인한 것 | 사전의 표시 |
|---|---|---|
| Sumner P et al. *BMJ* 2014;349:g7015 (PMID 25498121, PMC4262123) 본문 Methods | 코딩 단위, 7점 척도와 단계별 예문 1개씩, "stronger statements trumped weaker ones" | `sources[sumner2014]`: `status: verified_source_text`, `citation_status: verified_europepmc_metadata_2026-10-30` |
| 같은 논문 web appendix ww1 (Europe PMC supplementaryFiles), pdftotext 72–108행 | **원래 코딩 매뉴얼**: 단계별 정의와 예문 표, 최강 진술 규칙, 별도의 "explicitly probabilistic" 이진 코드 | `sources[sumner2014_appendix]`: `verified_source_text` (인용문은 `verified_quotes`에 원문 그대로 저장) |
| Vincze V et al. *BMC Bioinformatics* 2008;9 Suppl 11:S9 (PMID 19025695, PMC2586758) 본문 | 논문 본문 예문에 표시된 hedge·negation 키워드, "punctuation marks or conjunctions function as scope boundary markers" | `sources[vincze2008]`: 인용한 단어만 `verified_source_text` |
| Adams RC et al. *J Exp Psychol Appl* 2017;23:1-14 (PMID 27808530) | **서지 메타데이터만** 확인. 본문은 접근 불가 | `citation_status`만 verified, 내용은 `unverified_from_memory`. v3에서는 이 출처에 기대는 항목이 없다 |
| Hyland 2005 *Metadiscourse* (단행본) | 접근 불가 | hedges/boosters 목록은 계속 `unverified_from_memory` |

`status` 값의 뜻(`provenance_policy.status_values`):

- `verified_source_text`: 원문에서 그 문구(또는 직접 굴절형)와 단계를 확인했다. 항목마다 `source_quote`에 원문 인용이 있다. 이 status는 **문구→단계 대응**에 대한 것이다. 정규식 형태(lookaround 제외 규칙, 목적어 명사 목록 등)가 단순 굴절형을 넘으면 `pattern_status: "project_operationalisation"`과 `pattern_note`로 따로 표시했다.
- `project_extension_of_verified_category`: 원문에 그 문구는 없다. 원문이 정의한 범주의 동의어나 파생형으로 프로젝트가 넣은 항목이다. `extends_category`/`extends_quote`에 어느 범주를 확장했는지 적었다. 이 항목들은 휴리스틱으로 보고해야 한다.
- `project_addition`: 확인된 범주의 확장으로도 정당화하기 어려운 프로젝트 항목.
- `unverified_from_memory`: 원문과 대조하지 못한 항목.
- `verified_lecture_pdf`: 수업 PDF(W5)에서 확인한 항목.

## 1. Sumner 2014 원문 (검증됨)

### 1.1 코딩 매뉴얼 (web appendix ww1) 원문

> 0. No relationship stated (but could have been): The study must have contained at least two variables (IV and DV, or pseudo IV and DV) between which a relationship could have been stated. If there were not two suitable variables, the code 'not applicable' was used.
> 1. Statement of NO relationship/cause: e.g. 'no difference'; 'persists without'; 'does not result in'; 'no significant extra risk'; 'added no benefit'.
> 2. Statement of correlation: Meaning remains if the variables in the statement are reversed; e.g. 'associated with'; 'related to'; 'varies with'; 'increases as'; 'decreases as'; 'have higher/lower rates of'; 'linear relationship';
> 3. Ambiguous statement of correlation/cause: Strictly does not state cause, but contains stronger implication of direct relationship than level 2; e.g. 'linked to'; 'predicts'; 'connected to'; 'more successful'; 'had difficulty';
> 4. Conditional cause: Causal statement (examples in level 6) preceded by conditional, such as 'might', 'could', 'may', 'appears'; or a statement that implies 'might cause', e.g. 'likely to be a critical event', 'demonstrates potential'.
> 5. Can cause: Causal statement (examples in level 6) preceded by 'can'. … Thus we grouped 'could' with 'might' in category 4.
> 6. Causal statement: Direct causal statement; e.g. 'enhances', 'increases' [as transitive verb - X increases Y], 'decreases', 'cuts', 'ameliorates'; 'influences'; 'prevents'; 'raises/reduces'; 'enables'; 'determines'; 'is vital for'; 'boosts/improves'; 'drives'; 'leads to'; 'transforms'; encourages' etc.
> Where statements of different levels were made within the analysed segments of text, stronger statements trumped weaker ones. Separately, we also coded whether or not the statement of relationship was explicitly probabilistic – for example, 'correlated with the risk of...' (correlational probabilistic); 'raises the chance of...' (causal probabilistic); Further probabilistic words/phrases included: 'likelihood'; 'makes more likely'; 'tendency'; 'rate'.

참고: 부록은 "the 6 levels of relationship statement"라고 쓰면서 0–6을 나열하고, 본문은 "seven point scale"이라고 쓴다.

### 1.2 본문 Methods 원문

> For press releases and news we used the title and first two sentences as their main statements … For journal articles we used the abstract and discussion. We used a seven point scale to rate increasing levels of determinism, where the presence of stronger statements trumped weaker ones: no statement …, explicit statement of no relation, correlational (for example, "drinking wine is associated with increased cancer rates"), ambiguous (for example, "drinking wine linked to cancer risk"), conditional causal (for example, "drinking wine might increase cancer risk"), can cause (for example, "drinking wine can increase cancer risk"), and unconditionally causal (for example, "drinking wine increases cancer risk").

부록도 같은 내용을 적는다: "the IV …, DV and stated relationship between them (if any) were extracted from the main claims … For the JA, main claims were defined within the abstract and discussion sections."

### 1.3 단위의 차이 (휴리스틱으로 명시)

Sumner 등은 **사람 코더**가 main claims에서 **IV–DV 쌍**과 그 관계 진술을 뽑아 코딩했다. 이 파이프라인은 IV–DV 쌍을 식별하지 않는다. 초록의 **문장마다 정규식**으로 단서를 찾아 같은 척도와 최강 진술 규칙을 적용한다. 이는 프로젝트 조작화다(사전 `unit_of_analysis`, HEURISTICS_LOG A7). level 0도 Sumner의 "No relationship stated (but could have been)"와 "not applicable"(두 변수 없음)을 구분하지 않는다.

## 2. 검증된 단서 대응표 (`status: verified_source_text`)

| 단계 | 사전 항목(cue) | 원문 인용(`source_quote`) | 정규식에 들어간 프로젝트 조작화 |
|---|---|---|---|
| 6 | 현재형 타동사 enhances, increases, decreases, cuts, ameliorates, influences, prevents, raises, reduces, enables, determines, boosts, improves, drives, transforms, encourages | 'enhances', 'increases' [as transitive verb - X increases Y], … 'encourages' | 앞에 한정사(the/an/a/no/any)가 없고, 뒤에 전치사·접속사·조동사가 오지 않을 때만 타동사로 본다('increases in'은 명사, 'increases as'는 2단계). 'raises the question/concern(s)'는 제외 |
| 6 | 조동사/'appears to' + 위 동사 원형 (may increase, can reduce …) | 4·5단계 정의 + 본문 "might increase cancer risk", "can increase cancer risk" | 조동사가 span에 포함되고, 그 조동사가 4/5로 낮춘다. 'to determine whether'처럼 맨 'to'+동사는 제외 |
| 6 | prevented/enabled/ameliorated/transformed/encouraged/boosted/influenced/drove/driven by | 같은 6단계 목록의 굴절형 | 형용사로 자주 쓰이는 enhanced/improved/determined, 'transforming growth factor', 'encouraging', 'log transformed'는 제외 |
| 6 | increase/reduce the risk (X increases/raises/reduces the risk/chance/rate of Y) | 'raises the chance of...' (causal probabilistic); 본문 "drinking wine increases cancer risk" | 과거형은 위험 명사 앞에 한정사가 있어야 동사로 본다('increased the risk' 6, 'increased risk' 2) |
| 6 | increased/reduced + 결과 명사 (Semaglutide reduced weight) | 'increases' [as transitive verb], 'decreases', 'cuts', 'raises/reduces', 'boosts' | 목적어 명사 목록(levels/symptoms/weight/events/mortality/glucose/pressure)과 앞 단어 제외 목록은 프로젝트 패턴. 형용사 오탐 위험이 남는다 |
| 6 | lead to; is vital for | 'leads to'; 'is vital for' | — |
| 4 | likely to be; demonstrates potential | 'likely to be a critical event', 'demonstrates potential' | 'more/less/most likely to be'는 제외. 'the incidence is likely to be underestimated'도 4가 된다(오탐 위험) |
| 3 | linked to; predicts; connected to; more successful; had difficulty | 'linked to'; 'predicts'; 'connected to'; 'more successful'; 'had difficulty' + 본문 "drinking wine linked to cancer risk" | 'predicted probability/values'는 제외 |
| 2 | associated with; related to; varies with; increases/decreases as; have higher/lower rates of; linear relationship; correlated with | 2단계 예문 + 'correlated with the risk of...' (correlational probabilistic) + 본문 "is associated with increased cancer rates" | 'as compared/as well' 제외, 'have' 생략 허용, 'linear association/trend' 추가 |
| 1 | no difference; persists without; does not result in; no significant extra risk; added no benefit | 1단계 예문 | 'no (statistically) significant difference' 같은 삽입어 허용 |
| 수식어 | may, might, could, appears → 4; can → 5 | 4·5단계 정의 | "preceded by"는 수식어가 그 6단계 단서보다 문장 안에서 앞에 있으면(거리 제한 없음) 적용(HEURISTICS_LOG A9) |
| 확률 코드 | risk (of), chance (of), likelihood, makes more likely, tendency, rate | 'correlated with the risk of...', 'raises the chance of...', 'likelihood', 'makes more likely', 'tendency', 'rate' | 'risk factor(s)' 제외. 문장 level ≥ 1일 때만 `explicitly_probabilistic = true` |
| 문장 규칙 | 최댓값 규칙 | "stronger statements trumped weaker ones" | — |

`scripts/test_preprocess_abstracts.py`의 `test_verified_quotes_are_verbatim_source_text`는 Sumner로 검증 표시한 모든 항목에 대해, `source_quote` 안의 '…'/"…" 문구가 출처의 `verified_quotes`(원문 발췌)에 **글자 그대로** 들어 있는지 검사한다. `test_sumner_appendix_examples`와 `test_sumner_article_examples`는 부록 예문과 본문 예문 다섯 개가 해당 단계로 매겨지는지 확인한다.

## 3. v2 대비 바뀐 것

1. **단계 수정 (원문과 달랐던 것)**: 'linked to' 2→**3**, 'predicts' (v2: level-2 project_addition 'predictor / predict') → **3**, 'connected to' 2→**3**, 동사 'influences' 3→**6**. 명사 'influence of/on'은 3으로 남기고 확장으로 표시했다. 'tied to'는 'linked to'의 동의어로 2→3(확장).
2. **추가한 검증 단서**: 6단계 동사 목록 전체(위 표), 'is vital for', 4단계 'likely to be'와 'demonstrates potential', 3단계 'more successful'과 'had difficulty', 2단계 'varies with', 'increases/decreases as', 'have higher/lower rates of', 'linear relationship', 'correlated with', 1단계 'persists without', 'does not result in', 'no significant extra risk', 'added no benefit', 수식어 'appears'.
3. **no-relationship 우선 규칙 삭제.** v2는 level-1 단서가 하나라도 있으면 문장을 1로 고정했다(`no_relationship_overrides_level>=5`, 옛 HEURISTICS_LOG A8). 이 규칙은 부록의 "stronger statements trumped weaker ones"와 모순되므로 지웠다. 이제 문장 단계는 단서별 유효 단계의 **최댓값**이다. 한 문장에 유효 level 1과 유효 level ≥ 2가 같이 있으면 `review_flag = mixed_levels_review`만 붙인다. 단계는 바꾸지 않는다. 예: "Semaglutide increased the risk of NAION but was not associated with gastroparesis." → v2는 1, v3는 6에 mixed_levels_review.
4. **부정 처리를 단서별로 바꿈.** (a) level-1 단서 span 안에 있는 level ≥ 2 단서('was not associated with' 안의 'associated with')는 같은 부정 진술이므로 1이다. (b) 그 밖의 level ≥ 2 단서는 앞 5토큰 안에 부정어가 있으면 1이다. 다만 둘 사이에 절 경계(', ; :' 뒤 공백, but/whereas/although/though/while/however)가 있으면 적용하지 않는다. 절 경계는 Vincze 2008 원문 "Generally, punctuation marks or conjunctions function as scope boundary markers in the corpus"의 확장이고, 경계 목록은 프로젝트 선택이다. v2에서 확인된 오류 "Semaglutide, but not liraglutide, was associated with NAION." → 1은 이제 2가 된다.
5. **'risk of'를 단계 단서에서 뺐다.** Sumner의 확률 단어는 단계가 아니라 별도 이진 코드("explicitly probabilistic")다. `probabilistic_cues`와 `probabilistic_rule`에 구현했고, `score_sentence()`가 `probabilistic_cues`와 `explicitly_probabilistic`을 돌려준다(`abstracts/cues/*.json`에 기록).
6. **기억에 의존한 출처 표기를 바로잡았다.** effect/impact/affect, due to, because of는 v1·v2에서 Sumner 3·6단계라고 적었지만 부록 목록에 없다. 해당 범주의 확장으로 바꿨다. 'cause', 'result in', 'induce', 'trigger' 등도 마찬가지다. Adams 2017로 출처를 적었던 linked/related/connected/tied to는 Sumner 부록(검증) 또는 확장으로 옮겼다.
7. **패턴 정리.** 'increase the risk'(6)는 과거형일 때 위험 명사 앞에 한정사를 요구한다. 그래서 "a substantially increased risk"는 6으로 잡히지 않는다. 결과 명사 패턴에서 형용사 'lower'를 뺐고('lower body weight was seen' 오탐 제거), 'included increased lipase levels' 같은 앞 단어 문맥은 제외했다. 'link(s)' 단독, 'drive' 원형(sex drive)은 더 이상 잡지 않는다.
8. **BioScope 단서 검증.** 9절 참조.

## 4. 검증된 범주의 프로젝트 확장 (`project_extension_of_verified_category`)

모두 휴리스틱으로 보고해야 한다. 항목마다 `extends_category`/`extends_quote`가 있다.

- **6 (Direct causal statement)**: cause(부록에서 4/5단계를 'Can cause' / 'may cause'로 설명할 때 쓰는 인과 동사. 명사 'causes of'도 잡힘), result in('does not result in'의 긍정형), induce('semaglutide-induced' 형용사도 잡힘), trigger, lower(동사; 'reduces' 동의어), elevate the risk, produce, responsible for, due to, because of, attributable to, contribute to, promote('encourages' 동의어), protect against('prevents' 동의어).
- **3 (Ambiguous)**: linked with / link between, connection between/with, tied to, predictor/predictive, effect of, affect, impact, influence(명사) of/on, role of / play a role, implicated in. 'affect'는 부록이 'influences'를 6에 두므로 6일 수도 있다. v2처럼 3으로 두고 검토 대상으로 남긴다.
- **2 (Correlation)**: association(명사), relation/relationship with/between, correlation/correlate, increased/higher/greater/elevated/lower/reduced risk·rate·incidence(행위자 없는 비교; 본문 예 "associated with increased cancer rates"처럼 사이에 단어 하나 허용), more/less likely.
- **1 (NO relationship)**: no association, not associated / was not associated(검증된 2·3단계 단서의 부정), no increased risk('no significant extra risk'의 동의어), did not increase/cause 등 부정된 인과 동사('does not result in'과 같은 구조), no evidence of, not significant(통계적 null; 최댓값 규칙에서는 다른 단서가 없을 때만 단계를 정한다), without + 관계 명사('persists without'; BioScope 'without'도 원문 확인), lack/absence of, fail to show(BioScope 논문 본문에는 없음).
- **4 수식어**: seem(s)('appears' 동의어), possible/potential/likely/probably/putative/plausible('likely to be a critical event', 'demonstrates potential'의 확장), 가설 표현(hypothesis/speculative/unconfirmed/not established).
- **확률 코드**: more/less likely, odds/hazard/probability/incidence.
- **부정어**: never/nor/n't(Vincze 본문에 없음. 'never'는 W5 p.30-31에서 확인).

## 5. 프로젝트 추가 (`project_addition`)

- `adverse event / side effect`(3): 약물 귀속을 암시하는 약물감시 명사다. Sumner의 관계 "진술"은 아니다. 이 항목 하나로 기술적 문장 다수가 3이 되므로 우선 검토한다.
- 효과 측정치·기술통계 evidence flag(HR, OR, RR, IRR, 95% CI, P value, prevalence/incidence of): 단계에 반영하지 않는다.
- `CI includes 1 / null`(1): 언어 진술이 아니라 통계 추론이다.
- hedges/boosters의 생의학 관용구(warrant further, further studies are needed, should be interpreted with caution, preliminary, confounding, robust, significant 등).
- 문장 단위 적용(1.3절), 부정 5토큰 창, mixed_levels_review 플래그, explicitly_probabilistic의 level ≥ 1 조건, 대소문자 구분 약어 그룹.

## 6. 문장 규칙 (`sentence_rule`)

1. 모든 `entries`를 문장의 NFKC 뷰(W5 p.29)에 `re.IGNORECASE`로 적용한다. OR/HR/RR/IRR/CI는 `(?-i:...)`로 대소문자를 구분한다. 축약형은 보존한다(W5 p.32 Option 1). evidence-flag 유형은 단계를 정하지 않는다.
2. 단서별 유효 단계를 정한다. (a) level-1 단서 span과 겹치는 level ≥ 2 단서는 1이다. (b) 부정어(no/not/neither/cannot는 Vincze 검증, never/nor/n't는 확장) 뒤 5토큰 안에 있고 절 경계가 없는 level ≥ 2 단서는 1이다 [휴리스틱, `negation_window_applied`]. (c) 6단계 단서 앞에 may/might/could/appears(또는 확장 4단계 수식어)가 있으면 4, 'can'이 있으면 5다.
3. 문장 단계는 유효 단계의 **최댓값**이다(Sumner, 검증).
4. 유효 1과 유효 ≥ 2가 같이 있으면 `mixed_levels_review`를 붙인다(단계는 그대로).
5. 단서가 없으면 0이다. `collapsed_ko = collapse_map[level]`.
6. 확률 단어가 있고 level ≥ 1이면 `explicitly_probabilistic = true`다.
7. hedges/boosters는 단계를 바꾸지 않고 개수와 목록만 기록한다.

부정어 보존 근거(W5 p.30-33 "keep negations not/never/without", "stopword를 제거할 때도 not, no, never 같은 negation은 keep list에 넣어서 보존")는 수업 PDF에서 확인했다(`verified_lecture_pdf`). 그래서 단서 매칭 전에는 불용어와 짧은 단어를 지우지 않는다.

## 7. 4범주로 접기 (프로젝트 결정, Notion 계획 v2)

6 → 단정, 5·4 → 가능성, 3·2 → 연관, 1 → 무관(`collapsed_to_group3`에서는 연관·무관), 0 → 해당 없음. **5("Can cause")를 가능성에 넣는 것**과 **3(ambiguous)을 연관에 넣는 것**은 프로젝트 결정이다. Sumner는 접지 않는다. 부록은 "'Can cause' is more deterministic than 'may cause' because it denotes ability"라고 쓰므로, 5와 4를 합치면 Sumner가 구분한 차이가 사라진다. 결과 보고 때 이 결정을 명시한다.

## 8. 실제 데이터 결과 (23편, 226문장, 2026-10-30 재실행)

| en_level | v2 | v3 |
|---|---|---|
| 0 | 156 | 155 |
| 1 | 15 | 13 |
| 2 | 24 | 27 |
| 3 | 13 | 14 |
| 4 | 1 | 1 |
| 6 | 17 | 16 |

| en_collapsed | v2 | v3 |
|---|---|---|
| (없음, level 0) | 156 | 155 |
| 연관 | 37 | 41 |
| 단정 | 17 | 16 |
| 무관 | 15 | 13 |
| 가능성 | 1 | 1 |

바뀐 문장:

- 39226070_s012: 1→2, mixed. "did not increase the risk … and was associated with a small … reduction"
- 39332263_s003: 1→2, mixed. "lower recurrence rates … though not statistically significant"
- 39332263_s002: 0→2. "lower recurrence rates of AP"
- 38673931_s007: 6→3. "included increased lipase levels"의 형용사 오탐 제거

review_flag는 negation_window_applied 9, negation_present_but_level>=2 3, mixed_levels_review 2이고, explicitly_probabilistic 문장은 37개다. 부록 6단계 목록의 새 동사들(influences, enhances, predicts 등)은 이 코퍼스에 거의 나오지 않아서 분포 변화가 작다.

주의: `review_sheet.csv`의 `matched_cues` 열은 원래 단계(`cue(level)`)를 보여 준다. 부정 처리 후의 유효 단계(`effective_level`, `level_rule`)와 `explicitly_probabilistic`은 `abstracts/cues/*.json`에만 있다.

## 9. BioScope (Vincze 2008) 본문 대조 결과

**논문 본문에서 키워드로 표시된 것** (`verified_source_text`, `source_quote` 있음):

- hedge: may, might, likely, possible, probably, suggest(s), indicate, seem(s), appear. appear는 raising verb 목록 "seem, appear, be expected, be likely"에 있고, 논문은 'appear'가 hedge가 아닌 예도 든다. 그 밖에 be expected, cannot be (completely) excluded, raises the question of.
- negation: no, not, without, neither, cannot ("cannot, which is a negative keyword on its own").
- 범위 규칙: "Generally, punctuation marks or conjunctions function as scope boundary markers in the corpus."

**논문 본문에 단서로 나오지 않는 것** (계속 `unverified_from_memory` 또는 확장): potential, putative, whether, hypothesis, speculate(논문에서 'speculative'는 범주 이름으로만 쓰인다), lack, absence, fail to. 논문은 "A comprehensive list of speculative and negative keywords is also available on the corpus homepage"라고 쓴다. 이 홈페이지 목록은 확인하지 못했다. 'or'와 'either … or'도 BioScope hedge 키워드지만, 논문에 따르면 과학 초록에서 'or'가 hedge인 경우는 8.85%뿐이어서 사전에 넣지 않았다.

## 10. 아직 검증되지 않은 것

1. **Hyland 2005 hedges/boosters 목록 전체**(Vincze로 확인한 9개 hedge 단어를 빼고): hedges 54개, boosters 38개가 `unverified_from_memory`다. 단행본이라 접근할 수 없었다. 대체 확인처는 Hyland 1998 *Hedging in Scientific Research Articles*와 Hyland 2005 *Discourse Studies* 7(2):173-192 표다.
2. **Adams 2017 자극 문구**: 서지만 확인했고 본문은 확인하지 못했다. v3 사전에는 이 출처에 기대는 항목이 없다.
3. **BioScope 홈페이지 키워드 목록**과 Farkas et al. CoNLL-2010: potential, putative, whether, hypothesis, speculate, lack, absence, fail to.
4. **프로젝트 확장(4절)과 프로젝트 추가(5절) 전체**: 출처가 직접 뒷받침하지 않는다. 번역 검수 sheet에서 사람이 정밀도와 재현율로 확인해야 한다. 특히 다음은 오탐 위험이 크므로 우선 검토한다: adverse event/side effect(3), cause의 명사 용법, induce의 형용사 용법('drug-induced'), due to/because of, not significant(1), 결과 명사 패턴의 형용사 문맥, likely to be(4), 'rate'/'risk'의 확률 플래그.
5. **조작화 휴리스틱**: 문장 단위 적용(A7), 부정 5토큰 창과 절 경계 목록(A8), 수식어 위치 규칙(A9), mixed_levels_review(A10), explicitly_probabilistic의 level ≥ 1 조건(A11), evidence flag(A12). HEURISTICS_LOG.md에 등록되어 있다.
6. **4범주 접기**(7절): 프로젝트 결정이다.

## 11. 파일 구조

- `sources`: 출처마다 `status`(내용 검증 상태), `citation_status`(서지 확인), `verified_quotes`(원문 발췌).
- `unit_of_analysis`: Sumner의 코딩 단위와 이 프로젝트의 문장 단위 조작화.
- `levels`: 0–6 단계의 원문 이름(`name_en`, `name_article`)과 정의 인용.
- `entries`: 관계 단서. `level`, `type`, `source`, `status`, 그리고 `source_quote` 또는 `extends_category`/`extends_quote`, 선택적으로 `pattern_status`/`pattern_note`.
- `modifiers`: may/might/could/appears(→4), can(→5), 확장 수식어(→4), 부정어 두 묶음(검증/확장).
- `probabilistic_cues`, `probabilistic_rule`: Sumner의 별도 이진 코드.
- `hedges`, `boosters`: 단계와 무관하게 개수만 센다.
- `sentence_rule`: 6절 규칙과 단계별 status, `negation_window_tokens: 5`, `negation_scope_boundary_pattern`.
- 편의 목록: `causal_cues`, `conditional_cues`, `ambiguous_cues`, `associational_cues`, `no_relationship_cues`(cue 이름만).

검증 스크립트 `scripts/test_preprocess_abstracts.py`는 실제 사전을 `strict=True`로 로드해 모든 패턴이 단어 경계로 시작하는지 확인한다. 이어서 부록과 본문 예문, v3 수정 사항('X is linked to Y' → 3, 'X predicts Y' → 3, 'X influences Y' → 6, 'X may/can/appears to increase Y' → 4/5/4, 'No difference was observed.' → 1, 혼합 문장 → 6과 mixed_levels_review, 'risk of' → explicitly_probabilistic), status 열거값, 검증 인용의 원문 일치를 점검한다.
