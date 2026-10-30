# 영어 확신·완화 단서 사전(`scripts/certainty_lexicon_en.json`) 출처와 검증 계획 (2026-10-30)

Notion 계획 ⑥ "영어 원문 교차 확인"에 쓰는 사전이다. 영어 초록의 각 문장에 Sumner et al. (2014) 7단계 인과 주장 강도를 매기고, 이를 한국어 사전과 같은 단정/가능성/연관/무관으로 접어서 번역문의 한국어 라벨과 일치율을 낸다.

**작성 시점의 제약.** 컨테이너에서 Europe PMC, PubMed, Crossref, 출판사 사이트가 모두 차단되어 수업 PDF 두 편 외에는 어떤 출처도 원문 대조를 하지 못했다. 그래서 사전의 모든 학술 출처 항목은 `status: "unverified_from_memory"`이고, 출처 없이 이 프로젝트가 추가한 항목은 `status: "project_addition"`이다. 수업 PDF에서 직접 확인한 항목만 `verified_lecture_pdf`다. 네트워크가 열리면 아래 5절 목록대로 확인한 뒤 status를 바꿔야 한다.

## 1. 척도: Sumner et al. 2014 (BMJ 2014;349:g7015)

Sumner 등은 대학 보도자료와 뉴스의 과장을 재기 위해 "인과 주장 강도"를 7단계로 코딩했다. 기억하는 정의와 예문은 다음과 같다 (모두 미확인).

| 단계 | 영어 이름 | 기억하는 예문 | 접은 범주 |
|---|---|---|---|
| 6 | unconditional statement of causation | X causes Y / X increases the risk of Y / X leads to Y | 단정 |
| 5 | statement of "can" cause | X can cause Y | 가능성 |
| 4 | conditional statement of causation | X may/might/could cause Y | 가능성 |
| 3 | ambiguous statement of relationship | the effect/impact of X on Y, X affects/influences Y | 연관 |
| 2 | statement of correlation | X is associated/linked with Y, patients taking X had a higher risk of Y | 연관 |
| 1 | explicit statement of no relationship | X was not associated with Y, no increased risk | 무관 |
| 0 | no statement of relationship | (방법·표본·배경 문장) | 해당 없음 |

코딩 원칙으로 기억하는 것: 한 텍스트에 여러 주장이 있으면 **가장 강한 주장**으로 코딩한다. 이 원칙은 Notion 계획 v2 ⑤ "단서가 여럿이면 가장 강한 것으로"와 같다.

같은 연구진의 Adams et al. (2017, *J Exp Psychol Appl* 23(1):1-14)은 독자가 "associated with / linked to / related to"(상관), "might cause / can increase"(조건·can), "causes / increases / leads to"(직접 인과)를 어떻게 다르게 읽는지 실험했다. 사전의 associational/causal 예문은 이 자극 목록에서 가져온 것으로 기억한다 (미확인).

## 2. 완화·강조 어휘: Hyland 2005

Hyland, *Metadiscourse* (Continuum 2005) 부록의 hedges/boosters 목록을 썼다. hedges는 "명제를 단정적으로 제시하기를 유보하는 표현"(may, might, could, possible, likely, suggest, indicate, appear, seem, perhaps, probably, relatively, generally, mainly, largely, approximately, tend to, unclear, uncertain …), boosters는 "확신을 표시하는 표현"(clearly, demonstrate, establish, show, evident, definitely, certainly, undoubtedly, prove, find …)이다. 목록 전체가 기억에 의존하므로 모두 `unverified_from_memory`다.

Hyland 목록에 없는 생의학 초록 관용구(warrant further, further studies are needed, cannot be excluded, should be interpreted with caution, hypothesis-generating, preliminary, confounding 등)와 통계 확신어(robust, strongly, significant, consistent)는 `project_addition`이다. 생의학 hedge 단서(potential, putative, whether, hypothesis, speculate)와 부정 단서(lack of, absence of, fail to)는 BioScope 코퍼스 지침(Vincze et al. 2008, *BMC Bioinformatics* 9(S11):S9)에 있다고 기억하여 그 출처로 적었다 (미확인).

**hedges/boosters는 단계를 바꾸지 않는다.** 단계는 관계 단서(causal/associational/no-relationship)와 modifier(may/might/could/can/부정)로만 정한다. hedges/boosters는 문장별 개수로만 세고, Notion ⑤ 번역 검수 sheet에 해당 문장을 올리는 데 쓴다.

## 3. 4범주로 접기 (Notion 계획 v2)

한국어 사전은 Sumner 척도를 단정/가능성/연관·무관으로 접는다. 영어 쪽도 같은 매핑을 쓴다.

- 6 → **단정**
- 5, 4 → **가능성**
- 3, 2 → **연관**
- 1 → **무관** (보고 시 연관·무관을 한 묶음으로 합치는 경우 `collapsed_to_group3` 사용)
- 0 → 해당 없음 (일치율 계산에서 제외)

이 중 **5("can cause")를 가능성에 넣는 것**과 **3(ambiguous)을 연관에 넣는 것**은 프로젝트 결정이다. Sumner 논문은 접지 않으며, Adams 2017에서 독자들은 "can" 문장을 상관 문장보다 더 인과적으로 읽었다고 기억한다. 한국어 사전이 "~할 수 있다"를 가능성으로 두므로 영어도 맞췄다. 결과 보고 때 이 결정을 명시한다.

## 4. 문장 규칙과 그 안의 휴리스틱

1. 모든 `entries` 패턴을 `re.IGNORECASE`로 문장(NFKC+casefold, 숫자 보존, 축약형 정규화 후)에 적용한다.
2. 매칭된 항목 중 가장 높은 단계를 기본 단계로 한다 (Sumner "가장 강한 주장"; Notion v2 ⑤).
3. "associated with (an) increased risk"는 2여야 한다. 6단계 "increase the risk" 패턴이 관사·전치사 뒤의 분사형(an/the/with/of increased risk)을 lookbehind로 제외해서 처리한다. **lookbehind 목록은 프로젝트 패턴**이다.
4. 기본 단계가 6이고 `can`이 있으면 5. 기본 단계가 5 이상이고 may/might/could가 있으면 4 (Sumner 4·5단계 정의). 형용사·부사형 hedge(possible, potential, likely 등)를 may/might와 같이 취급하는 것은 **프로젝트 확장(휴리스틱)**이다.
5. no_relationship 패턴이 하나라도 맞으면 1. 그 외에 부정어(not/no/never/cannot/n't)가 관계 단서 **앞 5토큰 안**에 있으면 1. 이 **5토큰 창은 프로젝트 휴리스틱**이다. Sumner는 사람이 전체 진술을 읽고 코딩했고, BioScope는 부정의 범위를 구문으로 정한다. 창 크기는 사람 검증 결과로 조정한다.
6. 매칭이 없으면 0.
7. 부정어를 보존하는 근거는 수업 자료다 (W5 p.30-31 "keep negations not/never/without — they flip meaning", p.32-33 "do not blindly remove short tokens", 축약형 정규화 isn't → is not, "stopword를 제거할 때도 not, no, never 같은 negation은 keep list에 넣어서 보존"). 이 부분은 PDF 텍스트로 직접 확인했다. 따라서 Notion ⑦대로 단서 매칭 전에는 불용어 제거와 짧은 단어 제거를 하지 않는다 (NLTK stopwords에 no/not/can이 들어 있고, len>2 필터가 no/HR/CI/OR를 지운다).

## 5. 네트워크가 열리면 확인할 것 (순서대로)

1. **BMJ 2014;349:g7015 web appendix (supplementary coding scheme).** 7단계의 정확한 이름·정의와 단계별 예문 표. 특히 (a) effect/impact/affect/influence가 3단계인지, (b) due to / because of / prevent가 6단계인지, (c) "increases risk"(6) 대 "increased risk"(2) 구분이 실제로 있는지, (d) "가장 강한 주장" 코딩 원칙의 원문 표현. 확인 후 해당 항목의 `status`를 `verified`로 바꾸고 `note`에 부록의 표·행 번호를 적는다.
2. **Adams et al. 2017 Table 1 / 보충 자극 목록.** associated with, linked to, related to, connected to, tied to 등이 실제 자극인지. 아니면 출처를 sumner2014로 옮기거나 project_addition으로 바꾼다.
3. **Hyland 2005 부록.** hedges/boosters 목록 각 항목을 하나씩 대조한다. 없는 단어(예: confirm, potential)는 `project_addition`으로 바꾼다. Hyland 1998 *Hedging in Scientific Research Articles* 또는 Hyland 2005 *Discourse Studies* 7(2):173-192 표도 같은 목록이므로 대체 확인처로 쓸 수 있다.
4. **BioScope 지침(Vincze 2008 보충 파일) 및 CoNLL-2010 shared task(Farkas 2010).** potential, putative, whether, hypothesis, lack of, absence of, fail to가 지침의 단서 예시인지.
5. **프로젝트 추가 항목(`project_addition`) 전체.** 출처를 찾지 못하면 그대로 휴리스틱으로 보고하고, 사람 검증(번역 검수 sheet)에서 정밀도·재현율로 확인한다. 특히 다음은 오탐 가능성이 커서 우선 검토한다: `significant`(booster), `evidence`(booster), `adverse event / side effect`(3단계), `prevalence / incidence of`(2단계), `not significant`(1단계), `produce`(6단계), `limited / limitations`(hedge), `confounding`(hedge).

## 6. 파일 구조 요약

- `sources`: 출처 6개. 각 항목에 `status`와 `verify_against`.
- `levels`, `collapse_map`: 척도와 접기.
- `entries`: 관계 단서 (causal 6, ambiguous 3, associational 2, no_relationship 1). 각 항목에 `pattern`(Python 정규식, `\b` 경계), `level`, `source`, `status`, `note`.
- `modifiers`: may/might/could(→4), can(→5), 형용사형 hedge(→4, 휴리스틱), 부정(→1), 가설 표현(→4, 휴리스틱).
- `hedges`, `boosters`: 단계와 무관한 완화·강조 어휘. 개수만 센다.
- `sentence_rule`: 위 4절 규칙과 각 단계의 status, `negation_window_tokens: 5`.
- 편의 목록: `causal_cues`, `ambiguous_cues`, `associational_cues`, `no_relationship_cues` (cue 이름만).

검증 스크립트: 사전을 로드하고 모든 패턴을 `re.compile(p, re.IGNORECASE)`로 컴파일하며, 7단계 각각에 해당하는 예문 11개로 문장 규칙을 점검했다 (2026-10-30, 184개 패턴 모두 컴파일됨).
