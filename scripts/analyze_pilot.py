import pathlib,json,re,hashlib,collections,csv,difflib,datetime
from normalize_entities import annotate
ROOT=pathlib.Path(__file__).parent
GROUPS=['NAION','GASTROPARESIS','BOWEL_OBSTRUCTION','PANCREATITIS','SUICIDALITY','THYROID_CANCER','GALLBLADDER','GI_SYMPTOMS']
PATTERNS={
'NAION':r'NAION|비동맥.{0,18}(?:시신경|허혈)|허혈성.{0,8}시신경',
'GASTROPARESIS':r'위\s*마비|위장?\s*무력증|gastroparesis',
'BOWEL_OBSTRUCTION':r'장\s*폐[색쇄]|장\s*마비|ileus|bowel obstruction',
'PANCREATITIS':r'췌장염|pancreatitis',
'SUICIDALITY':r'자살|자해|suicid',
'THYROID_CANCER':r'갑상[선샘].{0,4}(?:암|종양)|thyroid cancer',
'GALLBLADDER':r'담석|담낭염|담낭.{0,5}질환|cholelithiasis|cholecystitis',
'GI_SYMPTOMS':r'메스꺼|메슥|오심|구역|구토|설사|변비|위장관.{0,5}부작용',
}
merged=json.loads((ROOT/'news_candidates_all.json').read_text()) if (ROOT/'news_candidates_all.json').exists() else json.loads((ROOT/'news_candidates.json').read_text())
metadata={x['canonical_url']:x for x in merged}
rows=[]
for p in sorted((ROOT/'raw_news').glob('*.json')):
 r=json.loads(p.read_text());md=metadata.get(r['canonical_url'],{})
 r['candidate_groups']=md.get('candidate_groups',r['candidate_groups']);r['queries']=md.get('queries',r['queries'])
 r['body_chars']=len(r['body']);r['entity_annotation']=annotate(r['body'])
 r['exact_groups']=[g for g,pat in PATTERNS.items() if re.search(pat,r['body'],re.I)]
 date=re.search(r'20\d{2}[-.]\s*\d{1,2}[-.]\s*\d{1,2}',r.get('published_at',''))
 try:
  parts=re.findall(r'\d+',date.group()) if date else []
  day=datetime.date(*map(int,parts))
  r['date_verified']=datetime.date(2021,1,1)<=day<=datetime.date(2026,10,12)
 except (ValueError,TypeError):r['date_verified']=False
 r['specific_body_selector']=bool(r.get('selector') and r['selector']!='body_fallback')
 r['research_context_groups']=[]
 for g in r['exact_groups']:
  for m in re.finditer(PATTERNS[g],r['body'],re.I):
   ctx=r['body'][max(0,m.start()-450):m.end()+450]
   if re.search(r'연구팀|연구진|메타분석|코호트|학술지|[Jj][Aa][Mm][Aa]|임상시험|논문|[Nn]ature|분석 결과|연구 결과',ctx):
    r['research_context_groups'].append(g);break
 r['provisional_groups']=r['research_context_groups'] if r['crawl_status']=='body_extracted' and r['body_chars']>=700 and r.get('has_wegovy') and r['specific_body_selector'] and r['date_verified'] else []
 r['duplicate_of']=''
 rows.append(r)
def normbody(s):
 s=re.sub(r'\s+',' ',s)
 return re.sub('[^가-힣a-zA-Z0-9]','',s).lower()
sets={}
keepers=[]
for r in sorted(rows,key=lambda x:(not x['specific_body_selector'],not x['date_verified'],x['article_id'])):
 if r['crawl_status']!='body_extracted':continue
 s=normbody(r['body']); ss={s[i:i+7] for i in range(max(0,len(s)-6))};sets[r['article_id']]=ss
 for prev in keepers:
  tt=sets[prev['article_id']]
  if not tt or not ss or min(len(ss),len(tt))/max(len(ss),len(tt))<0.7:continue
  score=len(ss&tt)/len(ss|tt)
  if score>=0.82:r['duplicate_of']=prev['article_id'];break
 if not r['duplicate_of']:keepers.append(r)
stats=[]
for g in GROUPS:
 queried=[r for r in merged if g in r['candidate_groups']]
 body=[r for r in rows if g in r['candidate_groups'] and r['crawl_status']=='body_extracted']
 exact=[r for r in rows if g in r['exact_groups'] and r['crawl_status']=='body_extracted' and not r['duplicate_of']]
 prelim=[r for r in rows if g in r['provisional_groups'] and not r['duplicate_of']]
 stats.append({'group':g,'search_unique_urls':len(queried),'queried_urls_body_extracted':len(body),'union_exact_topic_dedup':len(exact),'strict_provisional_research_candidates':len(prelim)})
(ROOT/'screening_internal.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
(ROOT/'pilot_stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
print('TOTAL',len(merged),'CRAWLED',len(rows),'STATUS',dict(collections.Counter(x['crawl_status'] for x in rows)),'NEAR_DUPLICATES',sum(bool(x['duplicate_of']) for x in rows))
for x in stats:print(x)
with (ROOT/'review_queue.txt').open('w') as f:
 for g in GROUPS:
  f.write('\n### '+g+'\n')
  for r in rows:
   if g not in r['provisional_groups'] or r['duplicate_of']:continue
   f.write(r['article_id']+' | '+r['title_verified']+' | '+r['published_at']+'\n')
   # Context used to flag relevance (internal only)
   for m in re.finditer(PATTERNS[g],r['body'],re.I):
    ctx=r['body'][max(0,m.start()-180):m.end()+240]
    if re.search(r'연구|분석|논문|학술|JAMA',ctx,re.I):f.write(ctx.replace('\n',' ')+'\n');break
