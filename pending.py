#!/usr/bin/env python3
"""요약 대기 관리 — 비북스 요약(summary)이 비어 있는 추천을 모아 읽기 좋은 묶음으로 만들고, 써 둔 요약을 반영한다.

  python3 pending.py                   # 매체별 대기 수 + data/raw/pending/<매체>.md 묶음 생성 (원문 발췌 포함, 로컬 전용)
  python3 pending.py --limit 1500      # 묶음에 넣을 원문 글자 수 (기본 1800)
  python3 pending.py apply 파일.json    # {"매체/호/key": "요약", ...} 반영 (빈 summary 만 채움, --force 면 덮어씀)

요약 원칙 (사이트에 공개됨)
- 원문 문장을 옮기지 않고 비북스의 말로 1~2문장(60~120자). 무엇을 다룬 책인지 + 추천자가 왜 권하는지.
- 추천자 이름은 by 에 있으니 문장에 반복하지 않는다.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ISSUES = os.path.join(ROOT, 'data', 'issues')
RAW = os.path.join(ROOT, 'data', 'raw')


def issues():
    for m in sorted(os.listdir(ISSUES)):
        d = os.path.join(ISSUES, m)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith('.json') and not fn.startswith('_'):
                yield m, os.path.join(d, fn)


def raw_text(m, iid, key):
    for k in (key, 'essay'):
        p = os.path.join(RAW, m, iid, f'{k}.txt')
        if os.path.exists(p):
            return p, open(p, encoding='utf-8').read()
    return '', ''


def report(limit):
    os.makedirs(os.path.join(RAW, 'pending'), exist_ok=True)
    total = 0
    for m in sorted({m for m, _ in issues()}):
        out, n, waiting, shown = [], 0, [], set()
        for mm, path in issues():
            if mm != m:
                continue
            iss = json.load(open(path, encoding='utf-8'))
            if iss.get('status') == 'pending' and not iss.get('items'):
                waiting.append(f'{iss["id"]} ({iss["title"]}) → data/raw/{m}/{iss["id"]}.txt')
                continue
            for it in iss.get('items', []):
                if it.get('summary'):
                    continue
                n += 1
                rp, txt = raw_text(m, iss['id'], it['key'])
                if rp in shown:  # 한 글에 여러 책(에세이) → 원문은 처음 한 번만
                    txt = '(원문은 위 항목과 같음)'
                shown.add(rp)
                out.append(f'### {m}/{iss["id"]}/{it["key"]}\n'
                           f'《{it["title"]}》 {it.get("author", "")} / {it.get("publisher", "")} · {it.get("section", "")} · {", ".join(it.get("by", []))}'
                           f'{(" · 기사 제목: " + it["headline"]) if it.get("headline") else ""}\n\n{txt[:limit]}\n')
        if waiting:
            out.insert(0, '## 항목 정리 대기 호 (PDF 지면 → 항목 만들기)\n' + '\n'.join('- ' + w for w in waiting) + '\n')
        with open(os.path.join(RAW, 'pending', f'{m}.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(out))
        total += n
        print(f'  {m:<10} 요약 대기 {n:>4}편' + (f' · 정리 대기 호 {len(waiting)}개' if waiting else ''))
    print(f'■ 요약 대기 합계 {total}편 — 묶음: data/raw/pending/')


def apply(path, force=False):
    sums = json.load(open(path, encoding='utf-8'))
    done = 0
    for m, p in issues():
        iss = json.load(open(p, encoding='utf-8'))
        changed = False
        for it in iss.get('items', []):
            k = f'{m}/{iss["id"]}/{it["key"]}'
            v = sums.get(k)
            if isinstance(v, dict):  # {"s": 요약, "by": [추천자]} — 추천자도 바로잡을 때
                if v.get('by') is not None:
                    it['by'] = v['by']
                    changed = True
                v = v.get('s')
            if v and (force or not it.get('summary')):
                it['summary'] = v.strip()
                changed = True
                done += 1
        if changed:
            json.dump(iss, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'■ 요약 반영 {done}편 / 입력 {len(sums)}편')


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == 'apply':
        apply(sys.argv[2], '--force' in sys.argv)
    else:
        lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 1800
        report(lim)
