"""Inject sample_round3.json into site_template_round3.html -> index_round3.html (round-3 verification page).

Usage: python build_site_round3.py [NOTION_URL]
NOTION_URL is the criteria page the guide tab links to.
"""
import json
import pathlib
import sys

H = pathlib.Path(__file__).parent
NOTION_URL = sys.argv[1] if len(sys.argv) > 1 else 'https://app.notion.com/p/3deed99f9ad5801ca63be6aa1d7a9746'
data = json.dumps(json.loads((H / 'sample_round3.json').read_text(encoding='utf-8')), ensure_ascii=False).replace('</', '<\\/')
page = (H / 'site_template_round3.html').read_text(encoding='utf-8').replace('/*DATA*/', data).replace('/*NOTION_URL*/', NOTION_URL)
(H / 'index_round3.html').write_text(page, encoding='utf-8')
print('index_round3.html', len(page) // 1024, 'KB')
