"""사이트 카탈로그(dist 또는 docs 의 data/catalog.json) → Supabase books 테이블 동기화

비밀 키는 .secrets/supabase.json 에만 둠 (git 제외):
  {"url": "https://<ref>.supabase.co", "service_role": "<service_role key>"}
사용: python3 sync_books.py [--docs]
주문 금액은 DB 의 books.price_standard 와 settings 로 계산되므로, 새 책이 사이트에 올라가기 전에 꼭 동기화할 것.
"""
import json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    sec_path = os.path.join(ROOT, '.secrets', 'supabase.json')
    if not os.path.exists(sec_path):
        print('· .secrets/supabase.json 없음 — books 동기화 건너뜀'); return
    sec = json.load(open(sec_path))
    src = os.path.join(ROOT, 'docs' if '--docs' in sys.argv else 'dist', 'data', 'catalog.json')
    cat = json.load(open(src, encoding='utf-8'))
    rows = [{'isbn13': b['isbn13'], 'title': b['title'], 'author': b.get('author'), 'publisher': b.get('publisher'),
             'price_standard': int(b.get('priceStandard') or 0), 'cover': b.get('cover'),
             'source': (b.get('recs') or [''])[0], 'active': True}
            for b in cat.values() if b.get('priceStandard')]
    hdr = {'apikey': sec['service_role'], 'Authorization': 'Bearer ' + sec['service_role'],
           'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates,return=minimal'}
    for i in range(0, len(rows), 200):
        req = urllib.request.Request(sec['url'] + '/rest/v1/books?on_conflict=isbn13', data=json.dumps(rows[i:i + 200]).encode(),
                                     headers=hdr, method='POST')
        urllib.request.urlopen(req, timeout=60).read()
    # 사이트에서 빠진 책은 판매 중지
    # (전체 ISBN을 URL에 넣으면 길이 초과 400 → DB의 활성 목록을 받아 차집합만 끔)
    keep = {r['isbn13'] for r in rows}
    live, off = set(), 0
    while True:  # Supabase 는 한 번에 1000행까지만 돌려줌
        req = urllib.request.Request(sec['url'] + f'/rest/v1/books?select=isbn13&active=eq.true&order=isbn13&limit=1000&offset={off}', headers=hdr)
        page = json.load(urllib.request.urlopen(req, timeout=60))
        live |= {r['isbn13'] for r in page}
        if len(page) < 1000:
            break
        off += 1000
    gone = sorted(live - keep)
    for i in range(0, len(gone), 100):
        req = urllib.request.Request(sec['url'] + '/rest/v1/books?isbn13=in.(' + ','.join(gone[i:i + 100]) + ')',
                                     data=b'{"active":false}', headers=hdr, method='PATCH')
        urllib.request.urlopen(req, timeout=60).read()
    print(f'■ books 동기화: {len(rows)}권')


if __name__ == '__main__':
    main()
