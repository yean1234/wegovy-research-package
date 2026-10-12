from collect_news import *
qs={g:items[0] for g,items in GROUPS.items() if g!='GI_SYMPTOMS'}
tasks=[(g,q,1,start,end) for g,q in qs.items() for start,end in [('2023.01.01','2024.12.31'),('2025.01.01','2025.12.31')]]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:results=list(ex.map(search,tasks))
(ROOT/'historical_search_log.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
old=json.loads((ROOT/'news_candidates.json').read_text());by_url={x['canonical_url']:x for x in old}
new=[]
for entry in results:
 for r in entry['rows']:
  key=r['canonical_url']
  if key not in by_url:
   by_url[key]={**r,'candidate_groups':[],'queries':[]};new.append(by_url[key])
  if r['group'] not in by_url[key]['candidate_groups']:by_url[key]['candidate_groups'].append(r['group'])
  if r['search_query'] not in by_url[key]['queries']:by_url[key]['queries'].append(r['search_query'])
(ROOT/'news_candidates_all.json').write_text(json.dumps(list(by_url.values()),ensure_ascii=False,indent=2))
(ROOT/'historical_new.json').write_text(json.dumps(new,ensure_ascii=False,indent=2))
print('NEW',len(new),'TOTAL',len(by_url),flush=True)
from scrape_news import one
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:list(ex.map(one,new))
