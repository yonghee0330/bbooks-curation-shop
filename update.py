#!/usr/bin/env python3
"""주간 갱신 한 번에 — 수집 → 도서 정보 → 요약 대기 확인 → docs/ 빌드 → 보고서

  python3 update.py            # 전체
  python3 update.py --no-fetch # 도서 정보 조회 생략 (빠르게 확인만)

배포(push)는 하지 않는다. 보고서(data/raw/update-YYYY-MM-DD.md)를 보고 확인한 뒤
  git add -A && git commit -m "…" && git push
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def snapshot():
    s = {}
    for p in glob.glob(os.path.join(ROOT, 'data', 'issues', '*', '*.json')):
        if os.path.basename(p).startswith('_'):
            continue
        d = json.load(open(p, encoding='utf-8'))
        s[os.path.relpath(p, ROOT)] = {it['key'] for it in d.get('items', [])}
    return s


def run(*args):
    print('$', ' '.join(args), flush=True)
    r = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True)
    print(r.stdout[-4000:], r.stderr[-2000:], sep='\n', flush=True)
    return r.stdout


def main():
    before = snapshot()
    out_collect = run('collect.py')
    after = snapshot()
    new_issues = sorted(set(after) - set(before))
    new_items = sum(len(after[k] - before.get(k, set())) for k in after)
    out_fetch = '' if '--no-fetch' in sys.argv else run('fetch.py')
    out_pending = run('pending.py')
    out_build = run('build.py', '--pages')
    out_sync = run('sync_books.py', '--docs')  # 주문 금액 계산용 books 테이블 (Q.books Supabase)
    git = subprocess.run(['git', 'status', '--short'], cwd=ROOT, capture_output=True, text=True).stdout
    lines = [f'# 비북스 서가 주간 갱신 {date.today()}', '',
             f'- 새 호/묶음 {len(new_issues)}개, 새 추천 {new_items}편', *[f'  - {x}' for x in new_issues], '',
             '## 수집', '```', '\n'.join(x for x in out_collect.splitlines() if x.startswith(('■', '  +', '  ?', '   !'))), '```',
             '## 도서 정보', '```', '\n'.join(x for x in out_fetch.splitlines() if x.startswith(('■', '   ?'))), '```',
             '## 요약 대기', '```', out_pending.strip(), '```',
             '## 빌드', '```', out_build.strip().splitlines()[-1] if out_build.strip() else '(실패)', out_sync.strip(), '```',
             '## 바뀐 파일 (git)', '```', git.strip()[:3000], '```',
             '', '확인 후 배포: `git add -A && git commit -m "주간 갱신" && git push`']
    os.makedirs(os.path.join(ROOT, 'data', 'raw'), exist_ok=True)
    path = os.path.join(ROOT, 'data', 'raw', f'update-{date.today()}.md')
    open(path, 'w', encoding='utf-8').write('\n'.join(lines))
    print('■ 보고서:', os.path.relpath(path, ROOT))


if __name__ == '__main__':
    main()
