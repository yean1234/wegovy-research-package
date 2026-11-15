"""Round-2 human-validation sample (after the judgement criteria were revised, 2026-11-16).

Why a new sample: round 1 (make_validation_sample.py, items T001-T081 / R001-R080) was discussed item by
item while the criteria were being revised, so re-coding the same items would not be independent.
Lombard, Snyder-Duch & Bracken (2002): when pilot reliability is inadequate, refine the instrument,
retrain, and assess reliability again on material the coders have not discussed.

How it is drawn: the SAME seeded permutations as round 1 are reproduced (seed 20261029) and continued
past the round-1 cut. Every article that appeared in round 1 (in either task) is skipped. Sample sizes
are unchanged (Lacy & Riffe 1996 with the Lombard floor). Article bodies are not stored in the repo, so
each candidate is fetched again with the scraper's selectors; a candidate whose body can no longer be
extracted is skipped and counted in meta.skipped_unfetchable. The computer labels are the ones stored in
article_labels_internal.json (computed on the 2026-10-29 bodies), not recomputed.

Changes to what coders answer (see the Notion page "새로운 판정 기준"):
- validation 2 no longer asks which paper was reported (dropped from the main validation);
- the 23 papers are coded again with eligibility and role asked as two separate questions.
Output: validation/sample_round2.json (not redistributed; contains excerpts).
"""
import json,pathlib,random,re,urllib.request,concurrent.futures
from lxml import html
from label_articles import TOPIC,paragraphs
from scrape_news import SELECTORS,clean
from make_validation_sample import lacy_riffe,excerpt,epmc,SEED,GROUP_KO,O_EN
ROOT=pathlib.Path(__file__).parent;REPO=ROOT.parent;OUT=REPO/'validation'
CACHE=ROOT/'round2_bodies.json'
WEGOVY=r'위고비|세마글루|Wegovy|semaglutide'
def fetch(url):
 try:
  u='https:'+url[5:] if url.startswith('http:') else url
  req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0 (compatible; AcademicPilot/1.0)'})
  with urllib.request.urlopen(req,timeout=22) as resp:b=resp.read(4000000);charset=resp.headers.get_content_charset()
  if not charset:
   m=re.search(br'charset\s*=\s*["\x27]?([\w-]+)',b[:12000],re.I);charset=m.group(1).decode() if m else 'utf-8'
  try:s=b.decode(charset,errors='replace')
  except LookupError:s=b.decode('utf-8',errors='replace')
  doc=html.fromstring(s)
  for xp in SELECTORS:
   cands=[x for x in (clean(n) for n in doc.xpath(xp)) if len(x)>350 and re.search(WEGOVY,x,re.I)]
   if cands:return max(cands,key=len)
  nodes=doc.xpath('//body');body=clean(nodes[0]) if nodes else ''  # same whole-page fallback as scrape_news.one
  if len(body)>350 and re.search(WEGOVY,body,re.I):return body
 except Exception:pass
 return ''
def excerpt2(body,group=None,floor=600,limit=1400):
 """Round-1 excerpt (lead + topic paragraphs); if that is shorter than `floor` (page-furniture lines can
 take up the lead after a whole-page fallback), keep adding the following paragraphs."""
 ex=excerpt(body,group,limit)
 if len(ex)>=floor:return ex
 parts=[ex]
 for p in paragraphs(body):
  if p in ex:continue
  parts.append(p)
  if sum(map(len,parts))>=floor:break
 return '\n\n'.join(parts)[:limit]
def bodies_for(arts):
 cache=json.loads(CACHE.read_text(encoding='utf-8')) if CACHE.exists() else {}
 todo=[x for x in arts if x['article_id'] not in cache]
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
  for x,b in zip(todo,ex.map(lambda x:fetch(x['url']),todo)):cache[x['article_id']]=b
 CACHE.write_text(json.dumps(cache,ensure_ascii=False),encoding='utf-8')
 return cache
def take(cands,n,key):
 """First n candidates (in permutation order) whose body can be fetched; fetch in chunks to limit requests."""
 got=[];skipped=0;i=0
 while len(got)<n and i<len(cands):
  chunk=cands[i:i+(n-len(got))+6];i+=len(chunk)
  cache=bodies_for([key(c) for c in chunk])
  for c in chunk:
   if len(got)==n:i-=len(chunk)-chunk.index(c);break
   if cache.get(key(c)['article_id']):got.append(c)
   else:skipped+=1
 return got,skipped,cache
if __name__=='__main__':
 rng=random.Random(SEED)
 labels=[x for x in json.loads((ROOT/'article_labels_internal.json').read_text(encoding='utf-8')) if not x['duplicate_of'] and x['in_primary_window']]
 papers=json.loads((REPO/'paper_dates.json').read_text(encoding='utf-8'))
 main=[p for p in papers if p['selection_role']=='main' and p['side_effect'] in TOPIC]
 pairs=[(x,g) for x in labels for g in x['exact_groups'] if any(w['in_90d'] for pm,w in x['windows'].items() if next(p for p in main if p['pmid']==pm)['side_effect']==g)]
 rng.shuffle(pairs);n1=lacy_riffe(len(pairs))
 arts=labels[:];rng.shuffle(arts);n2=lacy_riffe(len(arts))
 round1={x['article_id'] for x,g in pairs[:n1]}|{x['article_id'] for x in arts[:n2]}
 p2,skip1,cache=take([p for p in pairs[n1:] if p[0]['article_id'] not in round1],n1,lambda p:p[0])
 a2,skip2,cache=take([x for x in arts[n2:] if x['article_id'] not in round1],n2,lambda x:x)
 v1=[{'id':f"T2{i+1:03d}",'article_id':x['article_id'],'group':g,'group_ko':GROUP_KO[g],'title':x['title'],'url':x['url'],'date':x['published_date'],
  'excerpt':excerpt2(cache[x['article_id']],g),'rule':'yes' if x['bundle_fit'][g]['fit'] else 'no'} for i,(x,g) in enumerate(p2)]
 v2=[{'id':f"R2{i+1:03d}",'article_id':x['article_id'],'title':x['title'],'url':x['url'],'date':x['published_date'],'groups_ko':[GROUP_KO[g] for g in x['exact_groups']],
  'excerpt':excerpt2(cache[x['article_id']]),'rule':x['research_report'],'rule_trigger':x['trigger']['category']} for i,x in enumerate(a2)]
 pv=[]
 for p in papers:
  e=epmc(p['pmid']);abs_=re.sub('<[^>]+>',' ',e.get('abstractText',''));ti=p['title']
  I=bool(re.search(r'semaglutide|wegovy|ozempic|rybelsus',ti+' '+abs_,re.I));O=bool(re.search(O_EN[p['side_effect']],ti+' '+abs_,re.I))
  role='main' if I and O and re.search(r'semaglutide|wegovy',ti,re.I) else 'background'
  pv.append({'id':'P2'+p['pmid'],'pmid':p['pmid'],'group':p['side_effect'],'title':ti,'journal':p['journal_title'],'online_first_date':p['online_first_date'],
   'doi_url':'https://doi.org/'+p['doi'],'pub_types':e.get('pubTypeList',{}).get('pubType',[]),'abstract':abs_.strip(),'rule_eligible':'yes' if I and O else 'no','rule_role':role,'repo_role':p['selection_role']})
 meta={'round':2,'seed':SEED,'primary_window_days':90,'criteria_version':'v2 (2026-11-16)',
  'v1_articles':{'population_N':len(pairs),'n':len(v1),'round1_n':n1,'skipped_unfetchable':skip1},
  'v2':{'population_N':len(arts),'n':len(v2),'round1_n':n2,'skipped_unfetchable':skip2},'papers_N':len(pv),
  'excluded_round1_articles':len(round1),
  'sample_size_rule':'Lacy & Riffe 1996 (P=.90, Pmin=.85, Z=1.64) with floor max(50, 10% of N) (Lombard et al. 2002)'}
 (OUT/'sample_round2.json').write_text(json.dumps({'meta':meta,'v1_articles':v1,'v1_papers':pv,'v2':v2},ensure_ascii=False,indent=1),encoding='utf-8')
 print(json.dumps(meta,ensure_ascii=False,indent=1))
 print('V1 rule yes',sum(x['rule']=='yes' for x in v1),'/',len(v1),'| V2 rule yes',sum(x['rule']=='yes' for x in v2),'/',len(v2))
