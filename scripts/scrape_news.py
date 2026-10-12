import urllib.request,urllib.parse,json,pathlib,re,concurrent.futures,hashlib,datetime
from lxml import html
ROOT=pathlib.Path(__file__).parent
OUT=ROOT/'raw_news';OUT.mkdir(exist_ok=True)
PATTERNS={
'NAION':r'NAION|비동맥.{0,15}(?:시신경|허혈)|허혈성.{0,8}시신경',
'GASTROPARESIS':r'위\s*마비|위장?\s*무력증|gastroparesis|위장?\s*운동.{0,4}마비',
'BOWEL_OBSTRUCTION':r'장\s*폐색|장\s*마비|ileus|bowel obstruction',
'PANCREATITIS':r'췌장염|pancreatitis',
'SUICIDALITY':r'자살|자해|suicid',
'THYROID_CANCER':r'갑상[선샘].{0,4}(?:암|종양)|thyroid cancer',
'GALLBLADDER':r'담석|담낭염|담낭.{0,5}질환|cholelithiasis|cholecystitis',
'GI_SYMPTOMS':r'메스꺼|메슥|오심|구역|구토|설사|변비|위장관.{0,5}부작용',
}
SELECTORS=['//*[@id="dic_area"]','//*[@id="harmonyContainer"]','//*[@id="article-view-content-div"]','//*[@id="newsct_article"]','//*[@id="articleBodyContents"]','//*[@id="articleBody"]','//*[@id="article_body"]','//*[@id="newsEndContents"]','//*[@id="newsContent"]','//*[@id="article_txt"]','//*[@id="newsView"]','//*[contains(@class,"article-body")]','//*[contains(@class,"article_body")]','//*[contains(@class,"news_body")]','//*[contains(@class,"article_view")]','//article']
def clean(node):
 node=html.fromstring(html.tostring(node))
 for e in node.xpath('.//script|.//style|.//nav|.//footer|.//header|.//aside|.//form|.//iframe|.//noscript'):e.drop_tree()
 for e in node.xpath('.//br'):e.tail='\n'+(e.tail or '')
 for e in node.xpath('.//p|.//div|.//section'):e.tail='\n'+(e.tail or '')
 return '\n'.join(' '.join(x.split()) for x in node.text_content().splitlines() if x.strip())
def one(r):
 out={**r,'article_id':'A'+hashlib.sha1(r['canonical_url'].encode()).hexdigest()[:12],'collected_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'crawl_status':'failed','body':'','title_verified':'','published_at':'','selector':''}
 try:
  u=r['url'];u='https:'+u[5:] if u.startswith('http:') else u
  req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0 (compatible; AcademicPilot/1.0)'})
  with urllib.request.urlopen(req,timeout=22) as resp:
   b=resp.read(4000000); charset=resp.headers.get_content_charset();out['resolved_url']=resp.url
  if not charset:
   m=re.search(br'charset\s*=\s*["\x27]?([\w-]+)',b[:12000],re.I);charset=m.group(1).decode() if m else 'utf-8'
  try:s=b.decode(charset,errors='replace')
  except LookupError:s=b.decode('utf-8',errors='replace')
  doc=html.fromstring(s)
  tt=doc.xpath('//meta[@property="og:title"]/@content|//title/text()');out['title_verified']=tt[0].strip() if tt else r['title']
  dd=doc.xpath('//meta[@property="article:published_time"]/@content|//meta[@name="date"]/@content|//meta[@name="publish-date"]/@content|//meta[@property="og:regDate"]/@content|//time/@datetime')
  if dd:out['published_at']=dd[0]
  if not out['published_at']:
   m=re.search(r'"datePublished"\s*:\s*"([^"]+)"',s)
   if m:out['published_at']=m.group(1)
  body=''
  for xp in SELECTORS:
   nodes=doc.xpath(xp)
   candidates=[clean(x) for x in nodes]
   candidates=[x for x in candidates if len(x)>350 and re.search(r'위고비|세마글루|Wegovy|semaglutide',x,re.I)]
   if candidates:body=max(candidates,key=len);out['selector']=xp;break
  if not body:
   nodes=doc.xpath('//body');body=clean(nodes[0]) if nodes else clean(doc);out['selector']='body_fallback'
  out['body']=body
  out['crawl_status']='body_extracted' if len(body)>350 and re.search(r'위고비|세마글루|Wegovy|semaglutide',body,re.I) else 'insufficient_text'
  if not out['published_at']:
   m=re.search(r'(?:입력|등록|승인|게재|기사입력)\s*[:：]?\s*(20\d{2}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2})',body)
   if m:out['published_at']=m.group(1)
  out['detected_groups']=[g for g,pat in PATTERNS.items() if re.search(pat,body,re.I)]
  out['has_wegovy']=bool(re.search('위고비|Wegovy',body,re.I))
  out['has_semaglutide']=bool(re.search('세마글루[타티]이드|세마글루티드|semaglutide',body,re.I))
  out['research_cue']=bool(re.search(r'연구팀|연구진|메타분석|코호트|학술지|[Jj][Aa][Mm][Aa]|무작위|임상시험|논문|[Nn]ature',body))
  out['body_sha256']=hashlib.sha256(re.sub(r'\s','',body).encode()).hexdigest()
  out['evidence']={}
  for g in out['detected_groups']:
   mm=re.search(PATTERNS[g],body,re.I);out['evidence'][g]=body[max(0,mm.start()-120):mm.end()+260]
 except Exception as e:out['error']=str(e)
 (OUT/(out['article_id']+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2))
 print(out['article_id'],out['crawl_status'],len(out['body']),r['canonical_url'],flush=True)
 return out
if __name__=='__main__':
 rows=json.loads((ROOT/'news_candidates.json').read_text())
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:results=list(ex.map(one,rows))
 (ROOT/'news_crawled.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print('DONE',len(results),sum(x['crawl_status']=='body_extracted' for x in results),flush=True)
