"""Inject sample_round2.json into site_template_round2.html -> index_round2.html (round-2 verification page)."""
import json,pathlib
H=pathlib.Path(__file__).parent
data=json.dumps(json.loads((H/'sample_round2.json').read_text(encoding='utf-8')),ensure_ascii=False).replace('</','<\\/')
(H/'index_round2.html').write_text((H/'site_template_round2.html').read_text(encoding='utf-8').replace('/*DATA*/',data),encoding='utf-8')
print('index_round2.html',len(data)//1024,'KB data')
