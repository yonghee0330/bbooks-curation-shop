#!/usr/bin/env python3
"""C.books 데이터 손보기 도구 — 사람이든 작은 모델이든 이 명령만 쓰면 파일 형식을 망가뜨리지 않는다.

  python3 tools/edit.py find 신의 일식            # 추천 항목·책 찾기 (항목 ID와 ISBN이 나옴)
  python3 tools/edit.py show emmaus/2025-05/신의일식-복있는사람-pick
  python3 tools/edit.py set  <항목ID> title "새 제목"     # title author publisher summary section field
  python3 tools/edit.py set  <항목ID> by "홍길동, 김철수"  # 추천자 (쉼표로 여러 명)
  python3 tools/edit.py isbn <항목ID> 9788932823447      # 알라딘 연결 바꾸기 (책 정보·표지 자동으로 받아 옴)
  python3 tools/edit.py isbn <항목ID> none               # '국내 책 없음'으로 표시 (다시 검색하지 않음)
  python3 tools/edit.py isbn <항목ID> auto               # 연결을 지우고 제목으로 다시 자동 검색
  python3 tools/edit.py search "고백록 아우구스티누스"     # 알라딘 검색 — ISBN 후보 고르기
  python3 tools/edit.py hide <항목ID>   /  unhide <항목ID>  # 사이트에서 숨기기 / 되돌리기
  python3 tools/edit.py cover <ISBN> https://…/cover.jpg  # 표지 이미지 주소로 바꾸기
  python3 tools/edit.py cover <ISBN> ~/Desktop/표지.jpg     # 내 컴퓨터 이미지로 바꾸기 (site/assets/covers/ 로 복사)
  python3 tools/edit.py cover <ISBN> reset                # 표지 보정 지우기 (알라딘 표지로)
  python3 tools/edit.py book <ISBN> title "표시할 제목"     # 책 자체 정보 보정 (title author publisher priceStandard)

항목ID = 매체/호/키  (find 결과 첫 칸을 그대로 복사)
고친 뒤: python3 build.py 로 확인 → tools/deploy.sh "메시지" 로 배포용 빌드·커밋 (푸시는 사용자 확인 후)
"""
import glob
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISSUES = os.path.join(ROOT, 'data', 'issues')
HOUSE = os.path.join(ROOT, 'data', 'house')
BOOKS = os.path.join(ROOT, 'data', 'cache', 'books')
OVR = os.path.join(ROOT, 'data', 'overrides.json')
TEXT_FIELDS = ('title', 'author', 'publisher', 'summary', 'section', 'field', 'translator')


def die(msg):
    print('✗ ' + msg)
    sys.exit(1)


def issue_files():
    for f in sorted(glob.glob(os.path.join(ISSUES, '*', '*.json'))):
        if not os.path.basename(f).startswith('_'):
            yield os.path.basename(os.path.dirname(f)), f
    for f in sorted(glob.glob(os.path.join(HOUSE, '*.json'))):
        if not os.path.basename(f).startswith('_'):
            yield 'house', f


def load(f):
    return json.load(open(f, encoding='utf-8'))


def save(f, doc):
    tmp = f + '.tmp'
    json.dump(doc, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.load(open(tmp, encoding='utf-8'))  # 깨진 JSON이면 여기서 멈춤
    os.replace(tmp, f)


def item_id(media, doc, it):
    return f"{media}/{doc.get('id') or os.path.basename(media)}/{it['key']}"


def locate(iid):
    parts = iid.split('/', 2)
    if len(parts) != 3:
        die('항목ID는 매체/호/키 형식입니다. find 로 먼저 찾으세요.')
    media, issue, key = parts
    f = os.path.join(HOUSE if media == 'house' else os.path.join(ISSUES, media), f'{issue}.json')
    if not os.path.exists(f):
        die(f'파일 없음: {os.path.relpath(f, ROOT)}')
    doc = load(f)
    for it in doc.get('items', []):
        if it.get('key') == key:
            return f, doc, it
    die(f'키를 찾지 못함: {key}  (find 로 정확한 항목ID를 확인하세요)')


def book(isbn):
    p = os.path.join(BOOKS, f'{isbn}.json')
    return load(p) if os.path.exists(p) else None


def norm(s):
    return ''.join(ch for ch in (s or '').lower() if ch.isalnum())


def cmd_find(q):
    nq = norm(q)
    n = 0
    for media, f in issue_files():
        doc = load(f)
        for it in doc.get('items', []):
            hay = norm(it.get('title')) + norm(it.get('author')) + norm(it.get('key'))
            if nq and (nq in hay or q.strip() == (it.get('isbn13') or '')):
                b = book(it.get('isbn13')) if it.get('isbn13') not in (None, 'none') else None
                print(f"{item_id(media, doc, it)}\n   {it.get('title')} / {it.get('author', '')} · ISBN {it.get('isbn13') or '(미연결)'}"
                      f"{' · 숨김' if it.get('hidden') else ''}{(' → 알라딘: ' + b['title'][:40] + ' / ' + b.get('publisher', '')) if b else ''}")
                n += 1
    print(f'— {n}건')


def cmd_show(iid):
    f, doc, it = locate(iid)
    print(os.path.relpath(f, ROOT))
    print(json.dumps(it, ensure_ascii=False, indent=1))
    if it.get('isbn13') not in (None, 'none'):
        b = book(it['isbn13'])
        print('알라딘:', (b['title'] + ' / ' + b.get('author', '') + ' / ' + b.get('publisher', '')) if b else '(캐시 없음 — isbn 명령으로 다시 받아 오세요)')
        ov = (load(OVR) if os.path.exists(OVR) else {}).get(it['isbn13'])
        if ov:
            print('보정:', ov)


def cmd_set(iid, field, value):
    if field == 'by':
        f, doc, it = locate(iid)
        it['by'] = [x.strip() for x in value.split(',') if x.strip()]
    elif field in TEXT_FIELDS:
        f, doc, it = locate(iid)
        it[field] = value
    else:
        die(f'바꿀 수 있는 칸: {", ".join(TEXT_FIELDS)}, by  (ISBN은 isbn 명령)')
    save(f, doc)
    print(f'✓ {field} = {value}')


def fetch_one(it):
    sys.argv = [sys.argv[0]]
    sys.path.insert(0, ROOT)
    import fetch
    try:
        return fetch.fetch_book(it)
    finally:
        json.dump(fetch.MATCH, open(fetch.MATCH_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)


def cmd_isbn(iid, value):
    f, doc, it = locate(iid)
    v = value.strip().replace('-', '')
    if v == 'none':
        it['isbn13'] = 'none'
    elif value.startswith('custom-'):  # data/custom_books.json 에 등록한 책
        it['isbn13'] = value.strip()
    elif v == 'auto':
        it.pop('isbn13', None)
        got = fetch_one(it)
        if not got:
            save(f, doc)
            die('자동 검색으로 찾지 못했어요. search 로 후보를 보고 isbn <항목ID> <ISBN> 으로 지정하세요.')
        it['isbn13'] = got
    else:
        if not (v.isdigit() and len(v) in (10, 13)):
            die('ISBN은 숫자 13자리(또는 10자리)입니다.')
        it['isbn13'] = v
        if not fetch_one(it):
            die('알라딘에서 이 ISBN을 조회하지 못했어요. 번호를 다시 확인하세요. (파일은 바꾸지 않았습니다)')
    save(f, doc)
    b = book(it['isbn13']) if it['isbn13'] != 'none' else None
    print(f"✓ isbn13 = {it['isbn13']}" + (f"  ({b['title'][:50]} / {b.get('publisher', '')})" if b else ''))


def cmd_search(q):
    sys.argv = [sys.argv[0]]
    sys.path.insert(0, ROOT)
    import fetch
    res = fetch.api('ItemSearch', Query=q, QueryType='Keyword', SearchTarget='Book', MaxResults=10, Sort='Accuracy')
    for it in res.get('item') or []:
        print(f"{it.get('isbn13')}  {it['title'][:60]}\n               {it.get('author', '')[:40]} / {it.get('publisher')} / {it.get('pubDate')} / 정가 {it.get('priceStandard')}")


def cmd_hide(iid, on):
    f, doc, it = locate(iid)
    if on:
        it['hidden'] = True
    else:
        it.pop('hidden', None)
    save(f, doc)
    print('✓ 숨김' if on else '✓ 다시 보이기')


def ovr_load():
    return load(OVR) if os.path.exists(OVR) else {'_note': ''}


def cmd_cover(isbn, src):
    ov = ovr_load()
    if src == 'reset':
        (ov.get(isbn) or {}).pop('cover', None)
        if isbn in ov and not ov[isbn]:
            ov.pop(isbn)
        save(OVR, ov)
        print('✓ 표지 보정 지움 (알라딘 표지 사용)')
        return
    if src.startswith('http://') or src.startswith('https://'):
        val = src
    else:
        p = os.path.expanduser(src)
        if not os.path.exists(p):
            die(f'파일 없음: {p}')
        ext = os.path.splitext(p)[1].lower() or '.jpg'
        if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
            die('jpg · png · webp 이미지만 가능합니다.')
        dst_dir = os.path.join(ROOT, 'site', 'assets', 'covers')
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copyfile(p, os.path.join(dst_dir, isbn + ext))
        val = f'covers/{isbn}{ext}'
    ov.setdefault(isbn, {})['cover'] = val
    save(OVR, ov)
    if not book(isbn):
        print('! 주의: 이 ISBN의 책 정보가 아직 없어요. 항목에 isbn 을 먼저 연결해야 표지가 보입니다.')
    print(f'✓ 표지 = {val}')


def cmd_book(isbn, field, value):
    if field not in ('title', 'author', 'publisher', 'priceStandard'):
        die('book 으로 바꿀 수 있는 칸: title author publisher priceStandard')
    ov = ovr_load()
    ov.setdefault(isbn, {})[field] = int(value) if field == 'priceStandard' else value
    save(OVR, ov)
    print(f'✓ {isbn} {field} = {value}')


def main():
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return
    c, rest = a[0], a[1:]
    need = {'find': 1, 'show': 1, 'set': 3, 'isbn': 2, 'search': 1, 'hide': 1, 'unhide': 1, 'cover': 2, 'book': 3}
    if c not in need:
        die(f'알 수 없는 명령: {c}  (python3 tools/edit.py help)')
    if len(rest) < need[c]:
        die(f'{c} 명령에 필요한 값이 모자랍니다. python3 tools/edit.py help')
    if c in ('find', 'search'):
        rest = [' '.join(rest)]
    if c in ('set', 'book') and len(rest) > 3:
        rest = rest[:2] + [' '.join(rest[2:])]
    {'find': cmd_find, 'show': cmd_show, 'set': cmd_set, 'isbn': cmd_isbn, 'search': cmd_search,
     'hide': lambda i: cmd_hide(i, True), 'unhide': lambda i: cmd_hide(i, False),
     'cover': cmd_cover, 'book': cmd_book}[c](*rest)


if __name__ == '__main__':
    main()
