"""Step 5b: merge pilot (345) + window (new) candidates into news_candidates_all.json, the input analyze_pilot.py reads."""
import json,pathlib
ROOT=pathlib.Path(__file__).parent
by={}
for a in json.loads((ROOT.parent/'article_candidates.json').read_text(encoding='utf-8')):
 by[a['canonical_url']]={'url':a['url'],'canonical_url':a['canonical_url'],'title':a['title_verified'],'candidate_groups':list(a['candidate_groups']),'queries':list(a['queries']),'collection_paths':['pilot_web_2026-10-12'],'query_windows':[]}
for r in json.loads((ROOT/'window_candidates.json').read_text(encoding='utf-8')):
 x=by.setdefault(r['canonical_url'],{**r,'candidate_groups':[],'queries':[],'collection_paths':[],'query_windows':[]})
 for f in ('candidate_groups','queries','collection_paths','query_windows'):
  for v in r[f]:
   if v not in x[f]:x[f].append(v)
 if r.get('web_fallback_reason'):x['web_fallback_reason']=r['web_fallback_reason']
(ROOT/'news_candidates_all.json').write_text(json.dumps(list(by.values()),ensure_ascii=False,indent=2),encoding='utf-8')
print('MERGED',len(by))
