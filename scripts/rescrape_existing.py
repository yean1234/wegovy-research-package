"""Re-extract bodies of the 345 pilot URLs (raw_news/ is not distributed) with the unchanged scrape_news.one."""
import json,pathlib,concurrent.futures
from scrape_news import one,OUT
ROOT=pathlib.Path(__file__).parent
rows=[{'url':a['url'],'canonical_url':a['canonical_url'],'title':a['title_verified'],'candidate_groups':a['candidate_groups'],'queries':a['queries'],'search_source':'naver_public_search','collection_paths':['pilot_web_2026-10-12']} for a in json.loads((ROOT.parent/'article_candidates.json').read_text(encoding='utf-8'))]
todo=[r for r in rows if not (OUT/(__import__('hashlib').sha1(r['canonical_url'].encode()).hexdigest()[:12].join(['A','.json']))).exists()]
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:list(ex.map(one,todo))
