"""Steps 3 + 6 + 7: period assignment, bundle fit (validation 1) and research-report flag (validation 2).

Every rule and its source (details and full citations: docs/criteria_sources.md):
- Window: [t0, t0+90d], t0 = online-first date (paper_dates.json). 90 d = EurekAlert! timeliness rule
  ("first made available after peer review" + 90 days); news half-life 22 d (Fang & Costas 2020).
  Sensitivity windows 30 d and 180 d. Articles outside every window are kept as the auxiliary set.
- Bundle fit (KFF 2001 inclusion rule): >=100 words AND (topic term in headline/lead OR >=1/3 of the
  story about the topic). Korean words are counted as eojeol (space-separated units).
- Lead = first 3 paragraphs or first 4 sentences, whichever comes first (Pew/PEJ coding unit; borrowed).
- Cited paper (Altmetric text mining): journal AND author/institution AND date (article date inside the
  paper's window). Institution in place of author is the team's extension. One of journal/team -> uncertain.
- Research trigger (Pew/PEJ 'Story Trigger' = what made it news): research cue in headline+lead and no
  judicial/agency/company cue there -> research. Both in lead -> Pew 50% rule (borrowed): research if
  >=50% of paragraphs carry a research cue. Research only outside the lead -> background mention.
"""
import json,pathlib,re,datetime,collections,sys
ROOT=pathlib.Path(__file__).parent;REPO=ROOT.parent
PRIMARY=90;SENS=(30,180)
TOPIC={  # identical to analyze_pilot.PATTERNS
'NAION':r'NAION|비동맥.{0,18}(?:시신경|허혈)|허혈성.{0,8}시신경',
'GASTROPARESIS':r'위\s*마비|위장?\s*무력증|gastroparesis',
'PANCREATITIS':r'췌장염|pancreatitis',
'SUICIDALITY':r'자살|자해|suicid',
}
JOURNAL_WORD=r'학술지|저널|의학지|협회지|Journal|JAMA|자마|Lancet|란셋|NEJM|BMJ|네이처|Nature|Cureus|큐레우스|Ophthalmology'
RESEARCH_CUE=rf'(?:{JOURNAL_WORD})|연구\s*(?:팀|진)|논문|연구\s*결과|(?:이번|최근|새로운?)\s*연구|연구에\s*따르면'
NON_RESEARCH={  # Pew/PEJ trigger categories needed here (Judicial Action; Govt. Agency Action; Newsmaker Action non-govt)
'judicial_action':r'소송|고발|고소|수사|검찰|집단\s*소송|원고|피고|법원|판결|배심|재판(?!매)|다지역\s*소송|MDL|로펌|변호사',
'govt_agency_action':r'FDA(?!\s*부작용\s*보고|\s*\(?FAERS)|식품의약국|EMA|유럽\s*의약품청|PRAC|식약처|식품의약품안전처|보건\s*당국|규제\s*당국|허가\s*사항|경고\s*문구|라벨',
'newsmaker_action_nongovt':r'주가|실적|매출|출시|품절|공급\s*(?:부족|차질)|가격\s*(?:인하|인상)',
}
def date_of(s):
 m=re.search(r'(20\d{2})[-.]\s*(\d{1,2})[-.]\s*(\d{1,2})',s or '')
 try:return datetime.date(*map(int,m.groups())) if m else None
 except ValueError:return None
CAPTION=r'사진\s*[=:]|/\s*사진|\[사진|ⓒ|©|재판매|DB\s*금지|무단\s*전재|캡처|게티이미지|뉴스레터|구독'
def paragraphs(body):
 # Article-text paragraphs only: contains a sentence ending and is not a photo caption / nav / byline block.
 paras=[p.strip() for p in body.split('\n') if re.search(r'[다요][.!?]|[.!?]["”\']?$',p.strip()) and not re.search(CAPTION,p)]
 return paras or [p.strip() for p in body.split('\n') if p.strip()]  # no sentence-like line: keep raw lines
def lead(body):
 paras=paragraphs(body);three='\n'.join(paras[:3])
 sents=re.split(r'(?<=[.?!])\s+',' '.join(paras));four=''
 for s in sents[:4]:four+=s+' '
 return three if len(three)<=len(four) else four
def label(r,papers,aliases):
 body=r['body'];title=r.get('title_verified') or r.get('title','')
 d=date_of(r.get('published_at',''));paras=paragraphs(body);hl=title+'\n'+lead(body)
 out={'article_id':r['article_id'],'title':title,'url':r.get('resolved_url') or r['url'],'published_date':d.isoformat() if d else None,
  'collection_paths':r.get('collection_paths',[]),'crawl_status':r['crawl_status'],'duplicate_of':r.get('duplicate_of',''),
  'eojeol':len(body.split()),'exact_groups':[g for g in r.get('exact_groups',[]) if g in TOPIC]}
 # bundle fit (KFF 2001)
 fit={}
 for g in out['exact_groups']:
  share=sum(bool(re.search(TOPIC[g],p,re.I)) for p in paras)/max(1,len(paras))
  inlead=bool(re.search(TOPIC[g],hl,re.I))
  fit[g]={'in_headline_or_lead':inlead,'paragraph_share':round(share,3),'fit':out['eojeol']>=100 and (inlead or share>=1/3)}
 out['bundle_fit']=fit
 # windows
 win={}
 for p in papers:
  if p['side_effect'] not in out['exact_groups'] or not d:continue
  days=(d-datetime.date.fromisoformat(p['online_first_date'])).days
  win[p['pmid']]={'days_from_online':days,**{f'in_{w}d':0<=days<=w for w in (SENS[0],PRIMARY,SENS[1])}}
 out['windows']=win
 out['in_primary_window']=any(v[f'in_{PRIMARY}d'] for v in win.values())
 # cited paper (Altmetric: journal + author/institution + date)
 full,partial=[],[]
 for p in papers:
  a=aliases[p['pmid']];j=bool(re.search(a['journal'],body+title,re.I));t=bool(re.search(a['team'],body+title,re.I))
  days=(d-datetime.date.fromisoformat(p['online_first_date'])).days if d else None
  dated=days is not None and 0<=days<=PRIMARY
  if j and t and dated:full.append(p['pmid'])
  elif (j or t) and dated:partial.append({'pmid':p['pmid'],'journal':j,'team':t})
 out['cited_match_full']=full;out['cited_match_partial']=partial
 # trigger (Pew/PEJ)
 lead_research=bool(re.search(RESEARCH_CUE,hl,re.I))
 lead_other=[k for k,pat in NON_RESEARCH.items() if re.search(pat,hl,re.I)]
 rshare=sum(bool(re.search(RESEARCH_CUE,p,re.I)) for p in paras)/max(1,len(paras))
 if lead_research and not lead_other:trig='research_report_released'
 elif lead_research:trig='research_report_released' if rshare>=0.5 else lead_other[0]
 elif lead_other:trig=lead_other[0]
 else:trig='other_or_enterprise'
 out['trigger']={'category':trig,'lead_research_cue':lead_research,'lead_other_cues':lead_other,'research_paragraph_share':round(rshare,3),
  'research_mentioned_outside_lead':(not lead_research) and rshare>0}
 out['research_report']='yes' if trig=='research_report_released' else 'no'
 if out['research_report']=='yes':
  out['cited_paper']=','.join(full) if full else ('uncertain:'+','.join(x['pmid'] for x in partial) if partial else 'OTHER_STUDY')
 else:out['cited_paper']=''
 out['multi_study']=len(full)>1  # Haneef et al. 2015 exclude stories reporting >=2 studies
 out['analysis_set']='main_window' if out['in_primary_window'] and out['research_report']=='yes' else 'auxiliary_not_research_triggered'
 return out
if __name__=='__main__':
 papers=[p for p in json.loads((REPO/'paper_dates.json').read_text(encoding='utf-8')) if p['selection_role']=='main' and p['side_effect'] in TOPIC]
 aliases=json.loads((ROOT/'paper_aliases.json').read_text(encoding='utf-8'))
 rows=json.loads((ROOT/'screening_internal.json').read_text(encoding='utf-8'))
 # analyze_pilot (unchanged) keeps the raw_news copy of collection_paths, i.e. the path of the first scrape;
 # the merged candidate file holds every path that found the URL.
 merged={x['canonical_url']:x for x in json.loads((ROOT/'news_candidates_all.json').read_text(encoding='utf-8'))}
 for r in rows:r['collection_paths']=merged.get(r['canonical_url'],{}).get('collection_paths',r.get('collection_paths',[]))
 labels=[label(r,papers,aliases) for r in rows if r['crawl_status']=='body_extracted']
 (ROOT/'article_labels_internal.json').write_text(json.dumps(labels,ensure_ascii=False,indent=1),encoding='utf-8')
 live=[x for x in labels if not x['duplicate_of'] and x['exact_groups']]
 print('ARTICLES with priority topic',len(live))
 for w in (SENS[0],PRIMARY,SENS[1]):
  inw=[x for x in live if any(v[f'in_{w}d'] for v in x['windows'].values())]
  print(f'window {w}d: in-window',len(inw),'research yes',sum(x['research_report']=='yes' for x in inw),
   'cited main paper',sum(bool(x['cited_match_full']) for x in inw))
 c=collections.Counter(x['trigger']['category'] for x in live);print('TRIGGERS',dict(c))
 c=collections.Counter(p for x in live for p in x['cited_match_full']);print('CITED',dict(c))
