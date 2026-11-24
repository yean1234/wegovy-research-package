"""Verify scripts/nlm_section_labels.json against NLM: harvest AbstractText Label -> NlmCategory pairs
that NLM itself assigned in MEDLINE (PubMed E-utilities efetch XML). Usage: python3 scripts/verify_section_labels.py OUT.json"""
import json,urllib.request,urllib.parse,time,re,collections,xml.etree.ElementTree as ET,sys
E='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
def get(url):
    for i in range(4):
        try: return urllib.request.urlopen(url,timeout=90).read()
        except Exception as e: time.sleep(2**i)
    raise SystemExit('fail '+url)
queries=[  # journals/formats; years when NLM assigned categories broadly
 '"JAMA"[ta] AND 2014:2016[dp] AND hasstructuredabstract',
 '"JAMA Ophthalmol"[ta] AND 2014:2016[dp] AND hasstructuredabstract',
 '"JAMA Intern Med"[ta] AND 2014:2016[dp] AND hasstructuredabstract',
 '"BMJ"[ta] AND 2012:2016[dp] AND hasstructuredabstract',
 '"Lancet"[ta] AND 2012:2016[dp] AND hasstructuredabstract',
 '"Ann Intern Med"[ta] AND 2012:2016[dp] AND hasstructuredabstract',
 '"Diabetes Obes Metab"[ta] AND 2014:2016[dp] AND hasstructuredabstract',
 '"Cochrane Database Syst Rev"[ta] AND 2014:2016[dp] AND hasstructuredabstract',
 '"Ophthalmology"[ta] AND 2014:2016[dp] AND hasstructuredabstract',
 '"J Investig Med High Impact Case Rep"[ta] AND hasstructuredabstract',
 '"Cureus"[ta] AND hasstructuredabstract',
 '"Front Public Health"[ta] AND hasstructuredabstract',
 '"Diabetol Metab Syndr"[ta] AND hasstructuredabstract',
 '"Expert Opin Drug Saf"[ta] AND 2014:2018[dp] AND hasstructuredabstract',
 '"Nat Med"[ta] AND hasstructuredabstract',
 '"JAMA Netw Open"[ta] AND 2018:2019[dp] AND hasstructuredabstract',
 '"Diabetes Metab Syndr"[ta] AND hasstructuredabstract',
 '"Diabetol Int"[ta] AND hasstructuredabstract',
 '"Front Pharmacol"[ta] AND hasstructuredabstract',
 '"Int J Mol Sci"[ta] AND hasstructuredabstract',
 '"Am J Gastroenterol"[ta] AND 2014:2016[dp] AND hasstructuredabstract',
 '"J Clin Endocrinol Metab"[ta] AND 2014:2016[dp] AND hasstructuredabstract',
]
pairs=collections.defaultdict(collections.Counter); seen=0
for q in queries:
    r=json.loads(get(E+'esearch.fcgi?'+urllib.parse.urlencode({'db':'pubmed','term':q,'retmax':300,'retmode':'json','sort':'pub_date'})))
    ids=r['esearchresult']['idlist']; time.sleep(0.4)
    for i in range(0,len(ids),150):
        x=get(E+'efetch.fcgi?'+urllib.parse.urlencode({'db':'pubmed','id':','.join(ids[i:i+150]),'retmode':'xml'})); time.sleep(0.4)
        for a in ET.fromstring(x).iter('AbstractText'):
            L=a.get('Label')
            if L: pairs[re.sub(r'\s+',' ',L.upper().rstrip(':. '))][a.get('NlmCategory') or 'NONE']+=1
        seen+=len(ids[i:i+150])
    print(q[:45],len(ids),file=sys.stderr)
json.dump({k:dict(v) for k,v in pairs.items()},open(sys.argv[1] if len(sys.argv)>1 else 'nlm_label_pairs.json','w'),indent=0)
print('records',seen,'labels',len(pairs))
