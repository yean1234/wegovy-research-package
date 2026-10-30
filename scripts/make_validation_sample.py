"""Draw the human-validation samples (validation 1 & 2) and pre-label the 23 papers.

Sample size (per task): Lacy & Riffe (1996) n = [(N-1)SE^2 + PQN] / [(N-1)SE^2 + PQ],
P = 0.90 assumed agreement, minimum acceptable 0.85, SE = (P-Pmin)/1.64 (95 % one-tailed),
then at least max(50, 10 % of N) (Lombard, Snyder-Duch & Bracken 2002). The 30-article size in the
original plan is kept only as the pilot (the first 30 items in the random order).
Coders never see the computer label (blind coding); items are shown in the random order drawn here.
Paper pre-labels: PICO eligibility (Cochrane Handbook ch.3, ch.19 allows outcome-restricted harms
questions) + role by OCEBM 2011 harms rows: semaglutide-specific primary study or its review = main;
GLP-1 class-level or mechanism-only = background (indirect PICO). Coders check all 23.
"""
import json,pathlib,random,math,re,urllib.request,urllib.parse
from label_articles import TOPIC,lead,paragraphs
ROOT=pathlib.Path(__file__).parent;REPO=ROOT.parent;OUT=REPO/'validation';OUT.mkdir(exist_ok=True)
SEED=20261029
GROUP_KO={'NAION':'비동맥염성 앞허혈시신경병증(NAION)','GASTROPARESIS':'위마비','PANCREATITIS':'췌장염','SUICIDALITY':'자살사고·자살행동'}
def lacy_riffe(N,P=0.90,Pmin=0.85,Z=1.64):
 se2=((P-Pmin)/Z)**2;pq=P*(1-P)
 n=math.ceil(((N-1)*se2+pq*N)/((N-1)*se2+pq))
 return min(N,max(n,50,math.ceil(0.1*N)))
def excerpt(body,group=None,limit=1400):
 paras=paragraphs(body);ld=lead(body);parts=[ld]
 if group:
  for p in paras:
   if re.search(TOPIC[group],p,re.I) and p not in ld:parts.append(p)
   if sum(map(len,parts))>limit:break
 return '\n\n'.join(parts)[:limit]
def epmc(pmid):
 q=urllib.parse.urlencode({'query':f'EXT_ID:{pmid} AND SRC:MED','format':'json','resultType':'core'})
 with urllib.request.urlopen('https://www.ebi.ac.uk/europepmc/webservices/rest/search?'+q,timeout=40) as r:
  res=json.load(r)['resultList']['result'];return res[0] if res else {}
O_EN={'NAION':r'NAION|optic neuropathy','GASTROPARESIS':r'gastroparesis|gastric emptying','BOWEL_OBSTRUCTION':r'obstruction|ileus','PANCREATITIS':r'pancreatitis',
 'SUICIDALITY':r'suicid','THYROID_CANCER':r'thyroid','GALLBLADDER':r'chole|gallbladder|biliary','GI_SYMPTOMS':r'gastrointestinal|nausea|vomit|diarrh|constipation'}
if __name__=='__main__':
 rng=random.Random(SEED)
 labels=[x for x in json.loads((ROOT/'article_labels_internal.json').read_text(encoding='utf-8')) if not x['duplicate_of'] and x['in_primary_window']]
 bodies={r['article_id']:r['body'] for r in json.loads((ROOT/'screening_internal.json').read_text(encoding='utf-8'))}
 papers=json.loads((REPO/'paper_dates.json').read_text(encoding='utf-8'))
 main=[p for p in papers if p['selection_role']=='main' and p['side_effect'] in TOPIC]
 # validation 1 (articles): one unit = (article, topic group) pair in the primary window
 pairs=[(x,g) for x in labels for g in x['exact_groups'] if any(w['in_90d'] for pm,w in x['windows'].items() if next(p for p in main if p['pmid']==pm)['side_effect']==g)]
 rng.shuffle(pairs);n1=lacy_riffe(len(pairs))
 v1=[{'id':f"T{i+1:03d}",'article_id':x['article_id'],'group':g,'group_ko':GROUP_KO[g],'title':x['title'],'url':x['url'],'date':x['published_date'],
  'excerpt':excerpt(bodies[x['article_id']],g),'rule':'yes' if x['bundle_fit'][g]['fit'] else 'no'} for i,(x,g) in enumerate(pairs[:n1])]
 # validation 2 (articles): one unit = article in the primary window
 arts=labels[:];rng.shuffle(arts);n2=lacy_riffe(len(arts))
 v2=[{'id':f"R{i+1:03d}",'article_id':x['article_id'],'title':x['title'],'url':x['url'],'date':x['published_date'],'groups_ko':[GROUP_KO[g] for g in x['exact_groups']],
  'excerpt':excerpt(bodies[x['article_id']]),'rule':x['research_report'],'rule_cited':x['cited_paper'],'rule_trigger':x['trigger']['category']} for i,x in enumerate(arts[:n2])]
 # validation 1 (papers): all 23, computer pre-label
 pv=[]
 for p in papers:
  e=epmc(p['pmid']);abs_=re.sub('<[^>]+>',' ',e.get('abstractText',''));ti=p['title']
  I=bool(re.search(r'semaglutide|wegovy|ozempic|rybelsus',ti+' '+abs_,re.I));O=bool(re.search(O_EN[p['side_effect']],ti+' '+abs_,re.I))
  types=[t for t in e.get('pubTypeList',{}).get('pubType',[])]
  role='main' if I and O and re.search(r'semaglutide|wegovy',ti,re.I) else 'background'
  pv.append({'id':'P'+p['pmid'],'pmid':p['pmid'],'group':p['side_effect'],'title':ti,'journal':p['journal_title'],'online_first_date':p['online_first_date'],
   'doi_url':'https://doi.org/'+p['doi'],'pub_types':types,'abstract':abs_.strip(),'rule_eligible':'yes' if I and O else 'no','rule_role':role,'repo_role':p['selection_role']})
 papers_list=[{'pmid':p['pmid'],'label':f"{p['authors'][0]['last']} et al., {p['journal_title']} ({p['online_first_date']})",'group':p['side_effect']} for p in main]
 meta={'seed':SEED,'primary_window_days':90,
  'v1_articles':{'population_N':len(pairs),'n':n1,'pilot_n':30},'v2':{'population_N':len(arts),'n':n2,'pilot_n':30},'papers_N':len(pv),
  'sample_size_rule':'Lacy & Riffe 1996 (P=.90, Pmin=.85, Z=1.64) with floor max(50, 10% of N) (Lombard et al. 2002)'}
 (OUT/'sample.json').write_text(json.dumps({'meta':meta,'main_papers':papers_list,'v1_articles':v1,'v1_papers':pv,'v2':v2},ensure_ascii=False,indent=1),encoding='utf-8')
 print(json.dumps(meta,ensure_ascii=False,indent=1))
 print('V1 rule yes',sum(x['rule']=='yes' for x in v1),'/',len(v1),'| V2 rule yes',sum(x['rule']=='yes' for x in v2),'/',len(v2))
 print('papers rule vs repo role',[(x['pmid'],x['repo_role'],x['rule_role'],x['rule_eligible']) for x in pv])
