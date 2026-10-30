"""Step 5a: extract bodies for window_candidates.json with the unchanged scrape_news.one (skips already-extracted ids)."""
import json,pathlib,hashlib,concurrent.futures
from scrape_news import one,OUT
ROOT=pathlib.Path(__file__).parent
rows=json.loads((ROOT/'window_candidates.json').read_text(encoding='utf-8'))
todo=[r for r in rows if not (OUT/('A'+hashlib.sha1(r['canonical_url'].encode()).hexdigest()[:12]+'.json')).exists()]
print('TODO',len(todo),'OF',len(rows),flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:list(ex.map(one,todo))
