import urllib.request,urllib.parse,json,pathlib,concurrent.futures
ROOT=pathlib.Path(__file__).parent
Q={
'NAION':'semaglutide AND TITLE:(NAION OR "optic neuropathy")',
'GASTROPARESIS':'semaglutide AND TITLE:(gastroparesis OR "gastric emptying" OR "Gastrointestinal Adverse Events")',
'BOWEL_OBSTRUCTION':'semaglutide AND TITLE:("bowel obstruction" OR "intestinal obstruction" OR ileus OR "Gastrointestinal Adverse Events")',
'PANCREATITIS':'semaglutide AND TITLE:pancreatitis',
'SUICIDALITY':'semaglutide AND TITLE:("suicidal ideation" OR "psychiatric safety" OR "suicidal and self-injurious")',
'THYROID_CANCER':'semaglutide AND TITLE:("thyroid" OR "cancer")',
'GALLBLADDER':'semaglutide AND TITLE:(gallbladder OR cholelithiasis OR cholecystitis OR biliary)',
'GI_SYMPTOMS':'semaglutide AND TITLE:("Gastrointestinal tolerability" OR "Gastrointestinal adverse events")',
}
def run(p):
 k,q=p;q+=' AND FIRST_PDATE:[2021-01-01 TO 2025-12-31] AND SRC:MED'
 u='https://www.ebi.ac.uk/europepmc/webservices/rest/search?'+urllib.parse.urlencode({'query':q,'format':'json','resultType':'core','pageSize':100})
 try:
  with urllib.request.urlopen(u,timeout=35) as r:d=json.load(r)
  (ROOT/f'target_papers_{k}.json').write_text(json.dumps({'query':q,'url':u,'data':d},ensure_ascii=False,indent=2))
  print(k,d['hitCount'],flush=True)
 except Exception as e:print(k,str(e),flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:list(ex.map(run,Q.items()))
