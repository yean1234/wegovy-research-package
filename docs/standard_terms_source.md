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

- 작성 환경에서 meshb.nlm.nih.gov, id.nlm.nih.gov, icd.who.int, koicd.kr, nedrug.mfds.go.kr 접속이
  모두 차단되어(HTTP 000) **모든 식별자는 기억에서 적었고 `status: unverified_from_memory`다.**
  `verified`로 표시된 항목은 현재 하나도 없다.
- 특히 불확실한 항목: Semaglutide·GLP-1 RA·Tirzepatide의 MeSH UI(비워 둠), MTC의 MeSH 디스크립터,
  PSEUDO_OBSTRUCTION의 ICD 코드(K59.8), DIARRHEA의 ICD 코드(K59.1 vs A09 vs R19.7), KCD-8 한글 분류명 전부,
  MFDS 품목명(오젬픽프리필드펜·리벨서스정·마운자로프리필드펜·삭센다펜주), 의학용어집 표기(`kma_term_candidate`).
- `surface_forms_added`는 표준 용어집 근거가 없는 **프로젝트 추가 표기 변형**이다
  (`surface_forms_status: project_addition_unverified`). Notion ⑨에 적힌 두 표현과, 기계번역에서
  나올 법한 띄어쓰기·음역 변형을 작성자가 예상해 넣었으므로 휴리스틱에 해당한다. 실제 번역 결과를 받은 뒤
  관찰된 표기만 남기고 나머지는 지우는 것이 좋다.
- preferred_label_ko는 `normalization.json`의 `label`(부작용) 또는 첫 한국어 별칭(약물)을 그대로 썼다.
  이것은 프로젝트 사전 결정이지 의학용어집 표준은 아니다.

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
- 엔티티 인식을 어간추출 전에 수행, 엔티티명에 어간추출 적용 안 함: W5 강의 p.58.
- 영문 약어 단어 경계, 한국어 다단어 띄어쓰기 변형 허용, 원문 미수정: `normalization.json` text_rules 2·3.
- 긴 별칭 우선·비중첩(longest match first): 사전 기반 NER의 일반 관행이며 강의 자료에는 없는 프로젝트 선택이다.
- `expansion_only`·`do_not_merge`는 매칭에 쓰지 않는다(`normalization.json` rule: 검색 확장어는 동의어가 아님).

## 6. 오프셋 주의

`normalize_text()`의 start/end는 원문이 아니라 정규화 뷰(`normalize_view(text)`) 기준이다. NFKC 변환으로
문자 길이가 바뀔 수 있으므로 원문에 하이라이트하려면 뷰를 함께 저장하거나 원문 쪽에서 별칭을 다시 찾아야 한다.
