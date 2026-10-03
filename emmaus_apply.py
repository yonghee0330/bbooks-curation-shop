#!/usr/bin/env python3
"""data/raw/emmaus-curated/<호>.json (손으로 정리한 항목) → data/issues/emmaus/<호>.json
항목: [제목, 저자, 출판사, 코너, 분야, [추천자], 쪽, 요약]"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect
ROOT = os.path.dirname(os.path.abspath(__file__))
for iid in sys.argv[1:]:
    cur = json.load(open(os.path.join(ROOT, 'data', 'raw', 'emmaus-curated', f'{iid}.json'), encoding='utf-8'))
    iss = collect.load_issue('emmaus', iid)
    old = {it['key']: it for it in iss.get('items', [])}
    items = []
    for t, a, p, sec, field, by, page, s in cur['items']:
        key = collect.item_key(t, p) + '-' + sec
        it = {'key': key, 'title': t, 'author': a, 'publisher': p, 'section': sec, 'by': by, 'page': page, 'summary': s}
        if field:
            it['field'] = field
        if old.get(key, {}).get('isbn13'):
            it['isbn13'] = old[key]['isbn13']
        items.append(it)
    iss['items'] = items
    iss['status'] = 'done'
    for k in ('no', 'coverage', 'theme'):
        if cur.get(k):
            iss[k] = cur[k]
    y, m = iid.split('-')
    iss['title'] = f'엠마오 {y}년 {int(m)}월호' if not cur.get('title') else cur['title']
    iss['_curated'] = True
    collect.save_issue(iss)
    print(iid, len(items))
