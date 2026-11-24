# 구조화 초록 섹션 레이블 매핑표의 출처와 한계

관련 파일: `scripts/nlm_section_labels.json`

## 1. NLM 구조화 초록 범주 체계

미국 국립의학도서관(NLM)은 MEDLINE/PubMed에 수록된 구조화 초록(structured abstract)의 섹션 제목을 다섯 가지 범주로 정규화한다.

- BACKGROUND
- OBJECTIVE
- METHODS
- RESULTS
- CONCLUSIONS

NLM은 실제 저널에서 쓰이는 수천 개의 섹션 제목(예: IMPORTANCE, DESIGN, SETTING, AND PARTICIPANTS, FINDINGS, INTERPRETATION)을 이 다섯 범주로 매핑한 목록을 공개·유지하며, PubMed XML의 `<AbstractText Label="..." NlmCategory="...">` 속성이 이 매핑의 결과다. 섹션 제목이 매핑표에 없으면 NlmCategory가 UNASSIGNED로 남는다. (이 문단 전체는 기억에 의존, 미확인 — §5 참조.)

## 2. 근거 문헌 (서지사항·URL 모두 기억에 의존, 미확인)

- Ripple AM, Mork JG, Knecht LS, Humphreys BL. A retrospective cohort study of structured abstracts in MEDLINE, 1992–2006. *J Med Libr Assoc*. 2011;99(2):160–163. doi:10.3163/1536-5050.99.2.009 (기억에 의존, 미확인)
- NLM, "Structured Abstracts in MEDLINE" (https://www.nlm.nih.gov/bsd/policy/structured_abstracts.html) 및 섹션 제목–범주 매핑 목록 (https://structuredabstracts.nlm.nih.gov/ — 기억에 의존, 미확인; 이 사이트는 폐쇄됐을 수 있어 URL 확인 필요)

## 3. keep / drop 결정의 출처

범주별 keep/drop은 NLM이 정한 것이 아니라 본 프로젝트의 결정이다.

- Notion 전처리 계획 ②: DESIGN·RESULTS·CONCLUSIONS 계열은 유지, IMPORTANCE·OBJECTIVE 계열은 제외
- `README_ko.md` §5: Background·Importance·Objectives 등 배경 섹션을 제외하고 Methods·Results·Conclusions 중심 분석 텍스트를 만든다

따라서 BACKGROUND, OBJECTIVE → drop / METHODS, RESULTS, CONCLUSIONS → keep / UNKNOWN → needs_human(자동 처리 금지)로 둔다. 비구조화 초록은 이 표를 적용하지 않고 `needs_human_sectioning`으로 표시한다(README_ko §5, Notion ②).

## 4. 매칭 규칙

레이블은 대문자 변환, 끝의 콜론·마침표 제거, 연속 공백 1칸으로 축약 후 표에서 정확히 일치하는 항목을 찾는다. 표에 없으면 UNKNOWN → needs_human. 일부 항목에는 `action` 필드가 있어 범주 기본값을 덮어쓴다(`drop_non_content`: 등록번호·그림초록 등 비본문, `keep_as_results`: 증례 경과 서술).

## 5. 검증 상태와 해야 할 일

- 이 환경에서는 NLM 사이트에 접근할 수 없어 매핑표를 원문과 대조하지 못했다. JSON의 `source.status`는 `unverified_from_memory`이며, 각 레이블의 `provenance`는 `nlm_list_unverified_from_memory`(NLM 표에 있다고 기억) 또는 `project_decision`(NLM 매핑이 없거나 불확실해 프로젝트가 정함) 둘 중 하나다. 현재 `nlm_list`(원문 확인 완료)로 표시된 항목은 없다.
- 2026-10-30.2 추가(기억 의존): CONTEXT→BACKGROUND, PATIENTS·MEASUREMENTS·MAIN OUTCOME MEASURE(S)·DESIGN AND SETTING→METHODS. 표에 없는 레이블은 `preprocessing_report.json`의 `unknown_section_labels`와 report stage 경고로 출력되므로, cues 통계를 쓰기 전에 사람이 표에 추가해야 한다.
- 특히 불확실한 항목: FUNDING, SIGNIFICANCE, DATA SYNTHESIS(RESULTS vs METHODS), OUTCOMES, DISCUSSION, LIMITATIONS, TRIAL REGISTRATION, CASE PRESENTATION 계열, KEY POINTS/HIGHLIGHTS/SUMMARY/LAY SUMMARY.
- 네트워크가 가능해지면 (1) NLM 매핑 목록을 내려받아 각 레이블의 범주를 대조하고, (2) 일치하는 항목의 provenance를 `nlm_list`로, `source.retrieved`를 실제 조회 날짜로 갱신하며, (3) 불일치 항목은 NLM 값을 우선하되 keep/drop 결정은 §3 규칙을 그대로 적용한다. 또는 PubMed E-utilities(efetch, retmode=xml)로 각 논문의 `NlmCategory` 속성을 직접 가져와 표 대신 사용하는 편이 더 정확하다.

## 검증 결과 (2026-10-30, 네트워크 허용 후)

NLM의 원 매핑 목록 파일은 보관 사이트(archive-it) 접근 제한으로 받지 못했다. 대신 **NLM이 MEDLINE 레코드에 실제로 부여한 범주**로 검증했다.

- 방법: PubMed E-utilities `efetch`로 구조화 초록 6,011건(연구 논문 23편의 학술지 + JAMA·BMJ·Lancet·Annals·Cochrane 등 22개 검색식)을 받아, 각 `AbstractText`의 `Label`과 NLM이 붙인 `NlmCategory`를 집계했다. 재현 스크립트: `scripts/verify_section_labels.py`.
- 결과: 사전의 76개 라벨 가운데 62개는 NLM 부여 범주로 확정(`provenance: nlm_assigned_in_medline`, 건수는 `evidence` 필드). 7개는 NLM 자료가 없어 기억 기반 미확인으로 남고, 7개는 프로젝트 결정이다.
- 바뀐 것 12개. 분석 텍스트가 실제로 달라지는 것은 두 개다.
  - `SIGNIFICANCE`: BACKGROUND(제외) → CONCLUSIONS(유지)
  - `SUMMARY`: 사람 판단 → CONCLUSIONS(유지)
  - 나머지(`IMPORTANCE`→OBJECTIVE, `BACKGROUND AND AIM(S)`→OBJECTIVE, `TRIAL/SYSTEMATIC REVIEW REGISTRATION`·`REGISTRATION`→BACKGROUND, `CASE PRESENTATION/REPORT/DESCRIPTION`→METHODS, `MAIN OUTCOMES`→RESULTS)는 유지·제외 결과가 같다.
- 연구 논문 23편의 PubMed XML에도 `NlmCategory`가 있는 경우(5편)는 모두 이 사전과 일치한다.
- 유지·제외 결정 자체(BACKGROUND·OBJECTIVE 제외, METHODS·RESULTS·CONCLUSIONS 유지)는 노션 계획 ②와 README §5의 프로젝트 결정이다.
