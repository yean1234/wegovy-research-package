"""Lossless dictionary matching: outputs labels without rewriting raw text."""
import json,re,unicodedata,pathlib
CONFIG=json.loads((pathlib.Path(__file__).parent/'normalization.json').read_text())
def norm(text):
 return unicodedata.normalize('NFKC',text).lower().replace('®','').replace('™','')
def contains(text,term):
 t=norm(term);p=re.escape(t).replace(r'\ ',r'\s*')
 if t and t[0].isascii() and t[0].isalnum():p=r'(?<![a-z0-9])'+p
 if t and t[-1].isascii() and t[-1].isalnum():p+=r'(?![a-z0-9])'
 return bool(re.search(p,text))
def annotate(text):
 n=norm(text)
 drugs=[{'entity_id':e['id'],'entity_type':e['type'],'matched_aliases':[a for a in e['aliases'] if contains(n,a)]} for e in CONFIG['drug_entities']]
 drugs=[e for e in drugs if e['matched_aliases']]
 labels=[];expansions=[]
 for e in CONFIG['side_effects']:
  exact=[a for a in e.get('exact_aliases',[]) if contains(n,a)]
  sub={k:[a for a in aa if contains(n,a)] for k,aa in e.get('subtypes',{}).items()}
  sub={k:v for k,v in sub.items() if v}
  if exact or sub:labels.append({'side_effect':e['id'],'matched_aliases':exact,'subtypes':sub,'status':'dictionary_candidate_not_clinical_confirmation'})
  ex=[a for a in e.get('expansion_only',[]) if contains(n,a)]
  if ex:expansions.append({'side_effect':e['id'],'matched_search_expansions':ex,'requires_context':True})
 return {'drug_entities':drugs,'side_effect_candidates':labels,'expansion_matches':expansions}
if __name__=='__main__':
 import sys
 print(json.dumps(annotate(sys.stdin.read()),ensure_ascii=False,indent=2))
