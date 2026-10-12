import urllib.request,urllib.parse,json,pathlib,re,concurrent.futures,time,datetime
from lxml import html
ROOT=pathlib.Path(__file__).parent
GROUPS={
 'NAION':['위고비 NAION','위고비 실명','세마글루타이드 시신경'],
 'GASTROPARESIS':['위고비 위마비','위고비 위 무력증','세마글루타이드 위마비'],
 'BOWEL_OBSTRUCTION':['위고비 장폐색','위고비 장 폐색','세마글루타이드 장폐색'],
 'PANCREATITIS':['위고비 췌장염','세마글루타이드 췌장염','세마글루티드 췌장염'],
 'SUICIDALITY':['위고비 자살','위고비 자살 충동','세마글루타이드 자살'],
 'THYROID_CANCER':['위고비 갑상선암','위고비 갑상샘암','세마글루타이드 갑상선암'],
 'GALLBLADDER':['위고비 담석','위고비 담낭염','세마글루타이드 담낭'],
 'GI_SYMPTOMS':['위고비 구토 연구','위고비 메스꺼움 연구','위고비 위장관 부작용 연구'],
}
def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; AcademicPilot/1.0)'})
 with urllib.request.urlopen(req,timeout=25) as r:return r.read(),r.headers.get_content_charset(),r.url
def canon(url):
 p=urllib.parse.urlsplit(url)
 pars=[(k,v) for k,v in urllib.parse.parse_qsl(p.query) if k.lower() not in {'outurl','utm_source','utm_medium','utm_campaign','ref','from','fbclid'}]
 return urllib.parse.urlunsplit(('https',p.netloc.lower(),p.path,urllib.parse.urlencode(pars),''))
def search(task):
 group,q,start,*period=task
 ds,de=period if period else ('2021.01.01','2026.10.12')
 pars={'where':'news','query':q,'sort':'0','pd':'3','ds':ds,'de':de,'nso':'so:r,p:from'+ds.replace('.','')+'to'+de.replace('.','')+',a:all','start':start}
 url='https://search.naver.com/search.naver?'+urllib.parse.urlencode(pars)
 try:
  data,charset,_=fetch(url); tree=html.fromstring(data.decode(charset or 'utf-8',errors='replace'))
  rows=[]
  for a in tree.xpath('//a[@data-heatmap-target=".tit"]'):
   u=a.get('href','');title=' '.join(a.text_content().replace('새 창 열림','').split())
   if not u.startswith('http'):continue
   container=a.getparent();snips=container.xpath('.//a[@data-heatmap-target=".body"]')
   snippet=' '.join(snips[0].text_content().replace('새 창 열림','').split()) if snips else ''
   rows.append({'group':group,'search_query':q,'start':start,'url':u,'canonical_url':canon(u),'title':title,'snippet':snippet,'search_source':'naver_public_search','search_url':url})
  print(group,q,start,len(rows),flush=True)
  return {'group':group,'query':q,'start':start,'search_url':url,'rows':rows,'error':None}
 except Exception as e:return {'group':group,'query':q,'start':start,'search_url':url,'rows':[],'error':str(e)}
if __name__=='__main__':
 tasks=[(g,q,start) for g,qs in GROUPS.items() for q in qs for start in [1,11]]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:results=list(ex.map(search,tasks))
 (ROOT/'news_search_log.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 by_url={}
 for entry in results:
  for r in entry['rows']:
   key=r['canonical_url']
   if key not in by_url:by_url[key]={**r,'candidate_groups':[],'queries':[]}
   if r['group'] not in by_url[key]['candidate_groups']:by_url[key]['candidate_groups'].append(r['group'])
   if r['search_query'] not in by_url[key]['queries']:by_url[key]['queries'].append(r['search_query'])
 rows=list(by_url.values())
 (ROOT/'news_candidates.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 print('UNIQUE_CANDIDATE_URLS',len(rows),flush=True)
