import urllib.request, urllib.parse, json, time, pathlib, concurrent.futures, re
ROOT=pathlib.Path(__file__).parent
ROOT.mkdir(exist_ok=True)
GROUPS={
 'NAION':'NAION OR "nonarteritic anterior ischemic optic neuropathy" OR "non-arteritic anterior ischaemic optic neuropathy"',
 'GASTROPARESIS':'gastroparesis OR "gastric paralysis" OR "delayed gastric emptying"',
 'BOWEL_OBSTRUCTION':'"bowel obstruction" OR "intestinal obstruction" OR ileus',
 'PANCREATITIS':'pancreatitis',
 'SUICIDALITY':'"suicidal ideation" OR suicidality OR "suicide attempt"',
 'THYROID_CANCER':'"thyroid cancer" OR "thyroid carcinoma" OR "C-cell tumor"',
 'GALLBLADDER':'cholelithiasis OR cholecystitis OR "gallbladder disease"',
 'GI_SYMPTOMS':'"gastrointestinal tolerability" OR nausea OR vomiting OR diarrhea OR constipation',
}
def collect(item):
 key,term=item
 query=f'(TITLE_ABS:semaglutide OR TITLE_ABS:Wegovy) AND ({term}) AND FIRST_PDATE:[2021-01-01 TO 2026-10-12]'
 url='https://www.ebi.ac.uk/europepmc/webservices/rest/search?'+urllib.parse.urlencode({'query':query,'format':'json','resultType':'core','pageSize':100})
 for attempt in range(3):
  try:
   with urllib.request.urlopen(url,timeout=45) as r: data=json.load(r)
   (ROOT/f'papers_{key}.json').write_text(json.dumps({'query':query,'url':url,'data':data},ensure_ascii=False,indent=2))
   records=data.get('resultList',{}).get('result',[])
   print(key, 'raw_hits',data.get('hitCount'), 'downloaded',len(records),'abstracts',sum(bool(x.get('abstractText')) for x in records),flush=True)
   return
  except Exception as e:
   if attempt==2: print(key,'ERROR',str(e),flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:list(ex.map(collect,GROUPS.items()))
