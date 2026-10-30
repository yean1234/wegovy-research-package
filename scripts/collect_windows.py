"""Step 3-4: window-based news collection around each main paper's online-first date.

Windows: [online_first_date, online_first_date + COLLECT_DAYS] per main paper (paper_dates.json).
COLLECT_DAYS is the widest sensitivity window; narrower windows are subsets selected later.
Per group query (collect_news.GROUPS):
  1. Naver Search API, sort=date, pages of 100 until an item is older than the window start.
  2. If the API cannot reach the window start (start<=1000 cap) or fails (e.g. auth), the
     Naver web search with the window's date range fills that window via the scroll endpoint.
Every row records collection_path ('naver_api' / 'naver_web_daterange') and why the web path ran.
"""
import urllib.request,urllib.parse,json,pathlib,datetime,email.utils,re,sys,time
from lxml import html
from collect_news import GROUPS,canon,fetch
ROOT=pathlib.Path(__file__).parent;REPO=ROOT.parent
PRIORITY=['NAION','GASTROPARESIS','PANCREATITIS','SUICIDALITY']
COLLECT_DAYS=int(sys.argv[1]) if len(sys.argv)>1 else 183
def env():
 p=REPO/'.env'
 return {k.strip():v.strip().strip('"\'') for k,_,v in (l.partition('=') for l in p.read_text(encoding='utf-8-sig').splitlines()) if k.strip()} if p.exists() else {}
def windows():
 papers=json.loads((REPO/'paper_dates.json').read_text(encoding='utf-8'))
 out={}
 for p in papers:
  if p['selection_role']!='main' or p['side_effect'] not in PRIORITY:continue
  s=datetime.date.fromisoformat(p['online_first_date'])
  out.setdefault(p['side_effect'],[]).append((s,s+datetime.timedelta(days=COLLECT_DAYS),p['pmid']))
 merged={}
 for g,ws in out.items():  # union overlapping windows so each period is queried once
  ws.sort();cur=[]
  for s,e,pm in ws:
   if cur and s<=cur[-1][1]:cur[-1]=(cur[-1][0],max(cur[-1][1],e),cur[-1][2]+[pm])
   else:cur.append((s,e,[pm]))
  merged[g]=cur
 return merged
def api_window(q,start,end,keys):
 rows=[];reached=False
 for st in range(1,1001,100):
  # Search API moved to NAVER API HUB (Naver Cloud): new host/path, NCP gateway headers.
  u='https://naverapihub.apigw.ntruss.com/search/v1/news?'+urllib.parse.urlencode({'query':q,'display':100,'start':st,'sort':'date','format':'json'})
  req=urllib.request.Request(u,headers={'X-NCP-APIGW-API-KEY-ID':keys['NAVER_CLIENT_ID'],'X-NCP-APIGW-API-KEY':keys['NAVER_CLIENT_SECRET']})
  with urllib.request.urlopen(req,timeout=25) as r:items=json.load(r)['items']
  time.sleep(0.12)
  for it in items:
   d=email.utils.parsedate_to_datetime(it['pubDate']).date()
   if d<start:reached=True;break
   if d<=end:
    t=re.sub('<[^>]+>','',html.fromstring('<p>'+it['title']+'</p>').text_content())
    u0=it['originallink'] or it['link']
    rows.append({'url':u0,'canonical_url':canon(u0),'naver_link':it['link'],'title':t,'snippet':re.sub('<[^>]+>','',it['description']),'api_pubDate':it['pubDate']})
  if reached or len(items)<100:reached=True;break
 return rows,reached
def web_window(q,start,end):
 ds,de=start.strftime('%Y.%m.%d'),end.strftime('%Y.%m.%d')
 seen=set();rows=[];pages=0
 for st in range(1,4000,10):
  pars={'ssc':'tab.news.all','query':q,'sort':'0','pd':'3','ds':ds,'de':de,'nso':f'so:r,p:from{ds.replace(".","")}to{de.replace(".","")},a:all','start':st}
  u='https://s.search.naver.com/p/newssearch/3/api/tab/more?'+urllib.parse.urlencode(pars)
  d,_,_=fetch(u);j=json.loads(d);h=''.join(c.get('html','') for c in j.get('collection',[]));pages+=1
  new=0
  if h.strip():
   for a in html.fromstring(h).xpath('//a[@data-heatmap-target=".tit"]'):
    u0=a.get('href','')
    if not u0.startswith('http') or canon(u0) in seen:continue
    seen.add(canon(u0));new+=1
    c=a.getparent();sn=c.xpath('.//a[@data-heatmap-target=".body"]')
    rows.append({'url':u0,'canonical_url':canon(u0),'title':' '.join(a.text_content().replace('새 창 열림','').split()),'snippet':' '.join(sn[0].text_content().split()) if sn else '','search_url':u})
  time.sleep(0.4)
  if not new or not j.get('url'):break
 return rows,pages
if __name__=='__main__':
 keys=env();api_ok=bool(keys.get('NAVER_CLIENT_ID'))
 log=[];by={}
 def add(r,g,q,path,win,why=''):
  k=r['canonical_url']
  x=by.setdefault(k,{**r,'candidate_groups':[],'queries':[],'collection_paths':[],'query_windows':[]})
  for f,v in (('candidate_groups',g),('queries',q),('collection_paths',path),('query_windows',win)):
   if v not in x[f]:x[f].append(v)
  if why:x['web_fallback_reason']=why
 for g,ws in windows().items():
  for s,e,pmids in ws:
   win=f'{s}~{e}'
   for q in GROUPS[g]:
    why=''
    if api_ok:
     try:
      rows,reached=api_window(q,s,e,keys)
      for r in rows:add(r,g,q,'naver_api',win)
      log.append({'group':g,'query':q,'window':win,'pmids':pmids,'path':'naver_api','rows':len(rows),'reached_window_start':reached})
      print(g,q,win,'API',len(rows),'reached' if reached else 'CAP',flush=True)
      if reached:continue
      why='api_1000_cap_before_window_start'
     except urllib.error.HTTPError as ex:
      why=f'api_http_{ex.code}';api_ok=ex.code!=401  # stop retrying a rejected key
    else:why=why or 'api_key_unavailable_or_rejected'
    rows,pages=web_window(q,s,e)
    for r in rows:add(r,g,q,'naver_web_daterange',win,why)
    log.append({'group':g,'query':q,'window':win,'pmids':pmids,'path':'naver_web_daterange','reason':why,'rows':len(rows),'pages':pages})
    print(g,q,win,'WEB',len(rows),'pages',pages,why,flush=True)
 stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
 (ROOT/'window_search_log.json').write_text(json.dumps({'collect_days':COLLECT_DAYS,'run_at':stamp,'log':log},ensure_ascii=False,indent=2),encoding='utf-8')
 (ROOT/'window_candidates.json').write_text(json.dumps(list(by.values()),ensure_ascii=False,indent=2),encoding='utf-8')
 print('UNIQUE',len(by))
