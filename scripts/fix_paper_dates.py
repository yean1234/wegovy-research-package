"""Step 1: re-fetch each paper's online-first date (Europe PMC + Crossref) and matching metadata.

The repo's indexed_first_publication_date is often the journal issue date, which lags the
online release (e.g. PMID 38958939: issue 2024-08-01, online 2024-07-03, news 2024-07-04).
Online-first date = earliest day-precision date among
  explicit e-publication dates: PubMed epubdate, Europe PMC electronicPublicationDate, Crossref published-online
  public-availability proxies: PubMed Entrez date (record creation), Crossref created (DOI registration)
excluding issue-date placeholders: a value that equals the print/issue date AND falls on the 1st of the
month (EPMC/PubMed fill missing e-dates this way, e.g. PMID 39163046 shows 2024-08-01 but was published
online 2024-08-20). Online-only journals legitimately have print date == e-date, so those are kept.
JAMA-network journals expose no e-date at all, so their online date comes from the proxies.
All raw candidates are kept so the choice is auditable.
"""
import urllib.request,urllib.parse,json,pathlib,datetime,time,re
ROOT=pathlib.Path(__file__).resolve().parent.parent
UA={'User-Agent':'AcademicPilot/1.0 (mailto:22400264@handong.ac.kr)'}
ONLINE_KEYS=('pubmed_epubdate','epmc_electronicPublicationDate','crossref_published-online','pubmed_entrez','crossref_created')
def get(url):
 for attempt in range(3):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=40) as r:return json.load(r)
  except Exception:
   if attempt==2:raise
   time.sleep(2)
def dparts(d):
 p=(d or {}).get('date-parts',[[None]])[0]
 if not p or p[0] is None:return None
 p=list(p)+[1]*(3-len(p))
 return '%04d-%02d-%02d'%tuple(p[:3]),len((d or {}).get('date-parts',[[]])[0])
def epmc(pmid):
 q=urllib.parse.urlencode({'query':f'EXT_ID:{pmid} AND SRC:MED','format':'json','resultType':'core'})
 r=get('https://www.ebi.ac.uk/europepmc/webservices/rest/search?'+q)['resultList']['result']
 return r[0] if r else {}
def pubmed(pmids):
 r=get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id='+','.join(pmids))['result']
 return {i:r[i] for i in r['uids']}
MON={m:i+1 for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}
def pmdate(s):
 m=re.match(r'(\d{4}) (\w{3}) (\d{1,2})$',s or '')
 return '%s-%02d-%02d'%(m.group(1),MON[m.group(2)],int(m.group(3))) if m else None
def crossref(doi):
 try:return get('https://api.crossref.org/works/'+urllib.parse.quote(doi))['message']
 except Exception as e:return {'error':str(e)}
if __name__=='__main__':
 papers=json.loads((ROOT/'paper_candidates.json').read_text(encoding='utf-8'))
 out=[];pm=pubmed([p['pmid'] for p in papers])
 for p in papers:
  e=epmc(p['pmid']);c=crossref(p['doi'])
  cands={}
  if e.get('electronicPublicationDate'):cands['epmc_electronicPublicationDate']=e['electronicPublicationDate']
  if e.get('firstPublicationDate'):cands['epmc_firstPublicationDate']=e['firstPublicationDate']
  ji=e.get('journalInfo',{})
  if ji.get('printPublicationDate'):cands['epmc_printPublicationDate']=ji['printPublicationDate']
  for f in ['published-online','published-print','issued','created']:
   v=dparts(c.get(f))
   if v:cands['crossref_'+f]=v[0]+('' if v[1]==3 else ' (partial:%d)'%v[1])
  r=pm.get(p['pmid'],{})
  if pmdate(r.get('epubdate')):cands['pubmed_epubdate']=pmdate(r['epubdate'])
  if pmdate(r.get('pubdate')):cands['pubmed_pubdate']=pmdate(r['pubdate'])
  for h in r.get('history',[]):
   if h['pubstatus']=='entrez':cands['pubmed_entrez']=h['date'][:10].replace('/','-')
  issue={cands.get('epmc_printPublicationDate'),cands.get('pubmed_pubdate'),(cands.get('crossref_published-print') or '')[:10]}
  online={k:v for k,v in cands.items() if k in ONLINE_KEYS and len(v)==10 and not (v in issue and v.endswith('-01'))}
  first=min(online.values()) if online else None
  source=sorted(k for k,v in online.items() if v==first)
  authors=[{'last':a.get('lastName',''),'full':a.get('fullName',''),'affiliation':'; '.join(x.get('affiliation','') for x in a.get('authorAffiliationDetailsList',{}).get('authorAffiliation',[]))} for a in e.get('authorList',{}).get('author',[])]
  out.append({**{k:p[k] for k in('side_effect','selection_role','pmid','doi','title')},
   'repo_indexed_date':p['indexed_first_publication_date'],'date_candidates':cands,'online_first_date':first,
   'online_first_source':source,
   'journal_title':ji.get('journal',{}).get('title') or (c.get('container-title') or [''])[0],
   'journal_iso':ji.get('journal',{}).get('isoabbreviation',''),'authors':authors,
   'fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
  print(p['pmid'],p['selection_role'],p['indexed_first_publication_date'],'->',first,cands,flush=True)
 (ROOT/'paper_dates.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
