"""Inject sample.json into site_template.html -> index.html (the published verification page)."""
import json,pathlib
H=pathlib.Path(__file__).parent
data=json.dumps(json.loads((H/'sample.json').read_text(encoding='utf-8')),ensure_ascii=False).replace('</','<\/')
(H/'index.html').write_text((H/'site_template.html').read_text(encoding='utf-8').replace('/*DATA*/',data),encoding='utf-8')
print('index.html',len(data)//1024,'KB data')
