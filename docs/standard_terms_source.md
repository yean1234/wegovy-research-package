# 표준 용어 연결표(standard_terms.json)의 출처와 한계

관련 파일: `scripts/standard_terms.json`, `scripts/normalize_terms.py`, `normalization.json`
(`scripts/normalization.json`은 루트 파일과 동일함을 diff로 확인, 2026-10-30)

## 1. 목적 (Notion 계획 ⑨ 용어 통일)

번역문에 "비동맥염성 전방 허혈성 시신경병증", "세마글루타이드" 등으로 나오는 표현이 기사 표현과 달라도
같은 entity id(NAION, SEMAGLUTIDE …)로 묶기 위한 것이다. `normalization.json`은 수정·삭제하지 않고,
`standard_terms.json`이 entity id마다 표준 어휘 식별자와 추가 표면형을 **별도 필드**로 붙인다.

## 2. 사용한 표준 어휘

| 키 | 어휘 | 용도 |
|---|---|---|
| MESH | Medical Subject Headings (NLM) | 영어 개념 식별 |
| ICD10 | WHO ICD-10 (2019) | 질병 코드. ICD-10-CM 세부코드는 `cm_code`에 분리 |
| KCD8 | 한국표준질병·사인분류 8차 (통계청, 2021) | 한국어 질병 분류명 |
| INN / ATC | WHO 국제일반명 / ATC 분류 | 약물 성분·분류 |
| MFDS | 식약처 의약품통합정보시스템 허가 품목명 | 한국 시판명(위고비프리필드펜 등) |
| KMLE_or_KMA | 대한의사협회 의학용어집 6판 | 한국어 표준 용어 후보 |

## 3. 검증 상태 (중요)

- (최초 작성 시) 식별자 사이트 접속이 막혀 모든 식별자를 기억에서 적었다. **2026-10-30 네트워크 허용 후 MeSH 전부와 WHO ICD-10을 원 출처로 확인했다.** 결과는 아래 '검증 결과' 절과 각 항목의 `status`·`who_check` 필드를 본다.
- 여전히 미확인: PSEUDO_OBSTRUCTION·GASTROPARESIS의 ICD 배정(제목만 확인), ICD-10-CM 코드, KCD-8 한글 분류명 전부(koicd.kr 403),
  MFDS 품목명(오젬픽프리필드펜·리벨서스정·마운자로프리필드펜·삭센다펜주), 의학용어집 표기(`kma_term_candidate`), ATC 코드.
- `surface_forms_added`는 표준 용어집 근거가 없는 **프로젝트 추가 표기 변형**이다
  (`surface_forms_status: project_addition_unverified`). 기계번역에서 나올 법한 띄어쓰기·음역 변형을
  작성자가 예상해 넣었으므로 휴리스틱에 해당한다. 그래서 `normalize_terms.py`의 **기본 매칭표에서 제외**되며
  `normalize_text(text, include_candidate_forms=True)` / `preprocess_abstracts.py --candidate-surface-forms`로만
  켜진다(매칭의 `alias_source`로 구분). Notion ⑨가 명시한 두 표현("비동맥염성 전방 허혈성 시신경병증",
  "세마글루타이드")은 `normalization.json` 별칭에 이미 있어 기본 매칭된다. 실제 번역 결과를 받은 뒤
  관찰된 표기만 `normalization.json`으로 승격하고 나머지는 지우는 것이 좋다.
- preferred_label_ko는 `normalization.json`의 `label`(부작용) 또는 첫 한국어 별칭(약물)을 썼다.
  단, 세 그룹은 label을 **축약**했다(프로젝트 선택, `preferred_label_ko_note`에 기록): BOWEL_OBSTRUCTION
  '장폐색·장마비'→'장폐색', SUICIDALITY '자살사고·자살행동 관련 안전성'→'자살사고', GI_SYMPTOMS
  '흔한 위장관 증상(확장 후보)'→'위장관 증상'. 이것은 프로젝트 사전 결정이지 의학용어집 표준은 아니다.

## 4. 네트워크가 열리면 할 일

1. MeSH: `https://id.nlm.nih.gov/mesh/<UI>.json` 또는 MeSH Browser에서 디스크립터명·UI 대조.
   비워 둔 UI(Semaglutide 등)는 Browser 검색으로 채운다.
2. ICD-10: WHO 브라우저(`icd.who.int/browse10/2019/en#/<code>`)에서 코드·영문명 대조. ICD-10-CM 세부코드는
   CDC/CMS 표에서 따로 확인.
3. KCD-8: koicd.kr 검색으로 코드·한글명 대조.
4. MFDS: nedrug.mfds.go.kr 품목 검색으로 허가 품목명 대조.
5. 일치하면 `status`를 `verified`로 바꾸고 `note`에 확인일·URL을 적는다. 불일치하면 표준 값을 우선한다.

## 5. 매칭 규칙의 근거

- NFKC 정규화 + casefold + 공백 축약: W5 강의 p.29.
- 엔티티 인식을 어간추출 전에 수행, 엔티티명에 어간추출 적용 안 함: W5 강의 p.61 ("NER can be used before stemming to protect named entities", Boeing 예; 요약은 p.63; pdftotext 기준. v1이 인용한 p.58은 한국어 형태소분석 슬라이드였음).
- 영문 약어 단어 경계, 한국어 다단어 띄어쓰기 변형 허용, 원문 미수정: `normalization.json` text_rules 2·3.
- 긴 별칭 우선·비중첩(longest match first): 사전 기반 NER의 일반 관행이며 강의 자료에는 없는 프로젝트 선택이다.
- `expansion_only`·`do_not_merge`는 매칭에 쓰지 않는다(`normalization.json` rule: 검색 확장어는 동의어가 아님).

## 6. 오프셋 주의

`normalize_text()`의 start/end는 원문이 아니라 정규화 뷰(`normalize_view(text)`) 기준이다. NFKC 변환으로
문자 길이가 바뀔 수 있으므로 원문에 하이라이트하려면 뷰를 함께 저장하거나 원문 쪽에서 별칭을 다시 찾아야 한다.

## 검증 결과 (2026-10-30, 네트워크 허용 후)

- **MeSH**: 28개 디스크립터 이름·UI를 NLM `id.nlm.nih.gov/mesh/lookup`으로 전부 확인(불일치 0). 비어 있던 세마글루타이드(D000099194), GLP-1 수용체 작용제(D000097789), 티르제파타이드(D000098860) UI를 채움. 수질성 갑상선암(MTC)은 SPARQL로 확인한 보충개념 'Thyroid cancer, medullary'(C536914)로 교체(관련 디스크립터 'Carcinoma, Medullary' D018276).
- **WHO ICD-10 (2019)**: `icd.who.int/browse10`에서 코드·제목·포함어를 확인. NAION(H47.0 포함어 'Ischaemic optic neuropathy'), 자살사고(R45.8 포함어 'Suicidal ideation'), 췌장염(K85)은 포함어까지 확인. 위마비(K31.8)와 가성장폐색(K59.8)은 제목만 맞고 포함어에 없어 배정이 미확인이다. 담낭 'K80-K82'는 WHO 블록이 아니라 프로젝트 묶음이다.
- **미확인으로 남음**: ICD-10-CM 코드(미국 분류, 미대조), KCD-8(koicd.kr 접속 403), 식약처 제품명(nedrug 접속 불가), 대한의사협회 용어집 표기, ATC 코드, 기계번역 표면형 후보(`surface_forms_added`, 기본 매칭에서 제외).
