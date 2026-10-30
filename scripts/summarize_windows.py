"""Per-paper counts for the 30/90/180-day windows (robustness of step 2) -> ../window_summary.json."""
import json,pathlib,collections
ROOT=pathlib.Path(__file__).parent;REPO=ROOT.parent
L=[x for x in json.loads((ROOT/'article_labels_internal.json').read_text(encoding='utf-8')) if not x['duplicate_of'] and x['exact_groups']]
papers=[p for p in json.loads((REPO/'paper_dates.json').read_text(encoding='utf-8')) if p['selection_role']=='main' and p['side_effect'] in ('NAION','GASTROPARESIS','PANCREATITIS','SUICIDALITY')]
per=[]
for p in papers:
 row={'pmid':p['pmid'],'group':p['side_effect'],'online_first_date':p['online_first_date'],'repo_indexed_date':p['repo_indexed_date']}
 for w in (30,90,180):
  inw=[x for x in L if x['windows'].get(p['pmid'],{}).get(f'in_{w}d')]
  row[f'{w}d']={'topic_articles_in_window':len(inw),'research_report_yes':sum(x['research_report']=='yes' for x in inw),
   'cited_this_paper':sum(p['pmid'] in x['cited_match_full'] for x in inw),'bundle_fit_yes':sum(x['bundle_fit'][p['side_effect']]['fit'] for x in inw)}
 per.append(row)
inw=[x for x in L if x['in_primary_window']]
summary={'primary_window_days':90,'sensitivity_days':[30,180],'unique_articles_with_priority_topic':len(L),
 'primary_window':{'articles':len(inw),'research_report_yes':sum(x['research_report']=='yes' for x in inw),
  'cited_paper':dict(collections.Counter(x['cited_paper'].split(':')[0] for x in inw if x['research_report']=='yes')),
  'collection_paths':dict(collections.Counter(p for x in inw for p in x['collection_paths']))},
 'auxiliary_not_research_triggered':sum(x['analysis_set']!='main_window' for x in L),
 'trigger_categories_all':dict(collections.Counter(x['trigger']['category'] for x in L)),'per_paper':per}
(REPO/'window_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=1),encoding='utf-8')
for r in per:print(r['pmid'],r['group'],r['online_first_date'],*[(w,r[f'{w}d']['topic_articles_in_window'],r[f'{w}d']['research_report_yes'],r[f'{w}d']['cited_this_paper']) for w in (30,90,180)])
