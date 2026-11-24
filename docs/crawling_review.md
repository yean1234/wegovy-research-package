# 수집 코드 검토와 v2 변경 (2026-11-24)

대상은 main의 수집·본문 추출 스크립트 8개다(`collect_news.py`, `scrape_news.py`, `collect_windows.py`, `scrape_windows.py`, `extend_historical.py`, `rescrape_existing.py`, `merge_candidates.py`, `analyze_pilot.py`).

## 1. 검토 기준

노션 강의 노트에는 수집 단계가 "SNS나 크롤링을 통해 데이터를 구축"(텍스트 마이닝 5단계의 1단계)과 정형·반정형·비정형, HTML·XML 구분으로만 적혀 있다. 강의 슬라이드 원본은 확인하지 못했다. 그래서 아래 다섯 가지를 기준으로 삼았다.

1. 공식 경로(API)를 먼저 쓰는가
2. 사이트의 수집 규칙(robots.txt)과 요청 간격을 지키는가
3. 실패한 요청을 다시 시도하고, 실패 사유를 남기는가
4. 같은 입력으로 다시 돌렸을 때 같은 결과가 나오는가
5. 본문이 아닌 글자(메뉴, 관련 기사, 저작권 문구)가 섞이지 않는가

## 2. 기존 코드에서 유지한 것

| 항목 | 위치 | 유지한 이유 |
|---|---|---|
| API 우선, 상한에 걸릴 때만 웹 검색 보충 | `collect_windows.py` | 공식 경로를 먼저 쓰고, 보충한 이유를 기사마다 남긴다 |
| 수집 경로 기록 (`collection_paths`, `web_fallback_reason`) | 같은 파일 | 웹 검색으로만 찾은 기사를 민감도 분석에서 뺄 수 있다 |
| 기사 ID = 정규화한 URL의 해시 | `scrape_news.py` | 재수집해도 ID가 바뀌지 않는다. v2도 같은 방식을 쓴다 |
| 본문 7글자 조각 기반 유사 중복 탐지 | `analyze_pilot.py` | 전재·받아쓰기 기사를 한 번만 센다 |
| 검색 감사 파일 | `search_audit.json`, `window_search_log.json` | 어떤 검색을 했는지 추적할 수 있다 |

## 3. 문제와 v2에서 바꾼 것

| 문제 | 근거 | v2 |
|---|---|---|
| robots.txt를 확인하지 않는다 | `scrape_news.py`에 확인 코드가 없다 | `crawl_common.Robots`가 요청 전에 확인한다. 금지된 페이지는 받지 않고 `robots_disallowed`로 기록한다 |
| 같은 사이트에 6개 스레드가 간격 없이 요청한다 | `scrape_news.py` 67행. 메디칼타임즈 robots.txt는 `Crawl-delay: 10`을 요구한다 | 사이트별로 한 번에 한 요청, 최소 1초 간격. 사이트가 더 긴 간격을 요구하면 그 값(최대 10초)을 따른다 |
| 재시도가 없다 | 예외가 나면 바로 `failed` | 429·5xx·시간 초과는 간격을 늘려 가며 3회까지 다시 시도한다 |
| 선택자가 안 맞으면 페이지 전체 글자를 본문으로 쓴다 | `scrape_news.py` 47행 `body_fallback` | 선택자, trafilatura, JSON-LD 세 방법을 쓰고 어느 방법이 뽑았는지 기록한다. 페이지 전체는 `body_fallback_only`로 표시하고 본문으로 세지 않는다 |
| 글자 인코딩을 한 번만 추측한다 | 헤더·메타가 없으면 UTF-8로 읽고 깨진 글자를 그대로 둔다 | 헤더 → 메타 → UTF-8 → CP949 순으로 엄격하게 시도한다 |
| 받은 HTML을 저장하지 않는다 | 본문을 다시 뽑으려면 다시 요청해야 한다. 10/12와 10/29 사이에 추출 수가 330건에서 323건으로 바뀌었다 | 원본 HTML을 `scripts/raw_html/`에 저장한다(배포하지 않음) |
| 수집 날짜가 코드에 박혀 있다 | `collect_news.py`, `analyze_pilot.py`의 `2026-10-12` | 전체 기간 수집은 실행일을 끝 날짜로 쓴다 |
| 논문 11편의 공개일 주변만 수집한다 | `collect_windows.py` | `collect_fullperiod.py`가 2021-01-01부터 실행일까지 수집한다 |
| 테스트가 없다 | – | `scripts/tests/test_crawl.py`에 네트워크 없이 도는 테스트 10개 |

웹 검색 보충은 공식 인터페이스가 아니다. v2에서는 `--web-fallback`을 줄 때만 쓰고, API가 닿지 못한 구간만 분기 단위로 조회한다.

## 4. 추가한 기법

| 기법 | 쓰는 곳 | 출처 |
|---|---|---|
| trafilatura: 사이트별 규칙 없이 본문 영역을 찾는 휴리스틱 추출 | `extract_article.py` | Barbaresi (2021), ACL-IJCNLP System Demonstrations, 122–131 |
| schema.org JSON-LD: 페이지에 들어 있는 기사 메타데이터(발행일, 제목, 본문) | 같은 파일 | – |
| htmldate: 메타 태그가 없을 때 발행일 추정 | 같은 파일 | trafilatura와 함께 설치된다 |
| robots.txt 해석 규칙 (없으면 허용, 접속 불가면 금지) | `crawl_common.py` | RFC 9309 |

Bevendorff 외(2023, SIGIR)는 추출기 14개를 데이터셋 8개로 비교했다. 이후 문헌은 휴리스틱 방식 가운데 Trafilatura와 Readability가 좋았다고 요약하는데, 논문의 표를 직접 확인하지는 못했고 그 데이터셋에 한국어 뉴스는 없다. 그래서 아래처럼 우리 기사로 직접 비교했다.

## 5. 실제로 돌려 본 결과

기존 후보 가운데 158건(자동 선별 통과 98건과 탈락 표본 60건)을 v2로 다시 받았다. AI 도구가 실행했으므로 `RESPECT_AI_RULES=1`을 켰다.

| 결과 | 건수 |
|---|---:|
| 본문 추출 | 89 |
| robots.txt가 AI 크롤러를 금지 | 45 |
| robots.txt가 일반 크롤러도 금지 | 7 |
| robots.txt에 접속 불가 | 7 |
| 요청 실패 (시간 초과, 403 등) | 8 |
| 페이지 전체 글자만 얻음 | 2 |

- 추출한 89건 가운데 16건은 선택자 목록으로는 본문을 찾지 못했고 trafilatura만 찾았다. 기존 코드였다면 이 16건은 페이지 전체 글자가 본문으로 들어갔다.
- 두 방법이 모두 본문을 찾은 72건에서 길이 비율의 중앙값은 1.0이다. trafilatura가 15% 넘게 짧은 경우가 13건, 긴 경우는 0건이다.
- 발행일 출처는 JSON-LD 62건, 메타 태그 20건, htmldate 6건, 없음 1건이다.
- AI 크롤러 금지 45건은 팀 PC에서 사람이 실행하면 받을 수 있다(`RESPECT_AI_RULES`를 켜지 않은 기본값).

## 6. 실행 순서 (팀 PC)

```
python scripts/collect_fullperiod.py            # 네이버 API 키 필요 (.env)
python scripts/scrape_articles.py               # 본문 추출
python scripts/merge_candidates.py
python scripts/analyze_pilot.py
python scripts/label_articles.py
python scripts/make_validation_sample_round3.py --main
python validation/build_site_round3.py <노션 기준 페이지 주소>
```

## 7. 확인하지 못한 것

- 네이버 검색 API 경로는 키가 없어 이 환경에서 실행하지 못했다. `collect_fullperiod.py`는 10월 29일에 실제로 돌았던 `collect_windows.api_window`를 그대로 불러 쓰고, 상한에 걸렸을 때의 흐름은 가짜 응답으로 테스트했다.
- `search.naver.com`의 robots.txt는 이 환경에서 빈 응답이 와서 내용을 확인하지 못했다.
- 추출 품질을 사람이 문장 단위로 대조하지는 않았다. 위 비교는 길이와 방법별 성공 여부만 본 것이다.
