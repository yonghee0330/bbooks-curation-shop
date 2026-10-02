#!/usr/bin/env python3
"""책 정보 수집 — data/sources/*.json 의 책마다

  1) 알라딘 Open API(ItemSearch → ItemLookUp)로 ISBN·표지·정가·분류·쪽수
  2) 알라딘 상품 페이지 소개 블록(getContents Introduce)으로 책소개·목차·출판사 서평
  (예스24 검색은 스크립트 접근 시 메인으로 돌려보내 오매칭 위험 → 쓰지 않음. 목차가 없으면 비워 둠)

결과는 data/cache/books/<isbn13>.json, 표지는 data/cache/covers/<isbn13>.jpg 에 저장.
이미 있는 캐시는 건너뜀(--refresh 로 다시 받기). 사이트 간 간격 3초 이상(알라딘 robots Crawl-delay 3).

  python3 fetch.py                 # 모든 소스
  python3 fetch.py emmaus-28       # 특정 소스만
  python3 fetch.py --refresh       # 캐시 무시
  python3 fetch.py --reparse       # 받아 둔 html로 소개·목차만 다시 파싱
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'data', 'sources')
BOOKS = os.path.join(ROOT, 'data', 'cache', 'books')
COVERS = os.path.join(ROOT, 'data', 'cache', 'covers')
RAW = os.path.join(ROOT, 'data', 'cache', 'raw')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36'
REFRESH = '--refresh' in sys.argv
REPARSE = '--reparse' in sys.argv  # 네트워크 없이 raw 캐시로 소개·목차만 다시 파싱


def ttb_key():
    p = os.path.join(ROOT, '..', 'bbooks-curation', 'config.json')
    key = os.environ.get('ALADIN_TTB_KEY')
    if not key and os.path.exists(p):
        key = json.load(open(p, encoding='utf-8')).get('aladin_ttb_key')
    if not key:
        sys.exit('알라딘 TTB 키가 없습니다 (ALADIN_TTB_KEY 환경변수 또는 bbooks-curation/config.json)')
    return key


KEY = ttb_key()
_last = {}


def get(url, referer=None, host_gap=3.0):
    host = urllib.parse.urlparse(url).netloc
    wait = host_gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9',
                                               **({'Referer': referer} if referer else {})})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                body = r.read()
            _last[host] = time.time()
            for enc in ('utf-8', 'cp949'):
                try:
                    return body.decode(enc)
                except UnicodeDecodeError:
                    pass
            return body.decode('utf-8', 'ignore')
        except Exception as e:  # noqa: BLE001
            _last[host] = time.time()
            if attempt == 2:
                print('   ! 실패', url[:90], e)
                return ''
            time.sleep(4 * (attempt + 1))


def api(op, **params):
    q = {'ttbkey': KEY, 'output': 'js', 'Version': '20131101', **params}
    txt = get(f'https://www.aladin.co.kr/ttb/api/{op}.aspx?' + urllib.parse.urlencode(q), host_gap=1.0)
    try:
        return json.loads(txt)
    except ValueError:
        # 알라딘 js 출력은 가끔 제어문자/역슬래시가 섞여 있음
        return json.loads(re.sub(r'[\x00-\x1f]', ' ', txt).replace("\\'", "'"))


def norm(s):
    return re.sub(r'[\s·・,.\-()（）\[\]:;!?「」『』《》<>]', '', (s or '')).lower()


def find_item(book):
    """제목(+출판사)으로 검색해 가장 잘 맞는 상품 하나."""
    if book.get('isbn13'):
        return book['isbn13']
    res = api('ItemSearch', Query=book.get('search') or book['title'], QueryType='Keyword',
              SearchTarget='Book', MaxResults=20, Sort='Accuracy')
    items = res.get('item') or []
    want_t, want_p = norm(book['title']), norm(book.get('publisher'))
    best, best_score = None, -1
    for it in items:
        t, p = norm(it.get('title')), norm(it.get('publisher'))
        score = 0
        if want_p and want_p in p or (p and p in want_p and want_p):
            score += 5
        head = want_t[:8]
        if head and head in t:
            score += 4
        if t.startswith(want_t[:4]):
            score += 1
        if it.get('mallType') == 'BOOK':
            score += 1
        score += min(int(it.get('salesPoint') or 0), 50000) / 50000  # 같은 점수면 많이 팔린 판
        if score > best_score:
            best, best_score = it, score
    if not best or best_score < 4:
        print(f'   ? 확실한 일치 없음: {book["title"]} → 후보', [(i["title"][:30], i["publisher"]) for i in items[:5]])
        return best.get('isbn13') if best and best_score >= 4 else None
    return best.get('isbn13') or best.get('isbn')


def clean_html(fragment):
    t = re.sub(r'(?is)<(script|style).*?</\1>', '', fragment)
    t = re.sub(r'(?i)<br\s*/?>|</p>|</li>|</div>', '\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = html.unescape(t).replace('\xa0', ' ')
    lines = [re.sub(r'[ \t]+', ' ', ln).strip() for ln in t.split('\n')]
    out, blank = [], False
    for ln in lines:
        if not ln:
            blank = True
            continue
        if blank and out:
            out.append('')
        out.append(ln)
        blank = False
    return '\n'.join(out).strip()


def parse_contents(raw):
    """getContents(Introduce) html → {제목: 본문}. 블록은 Ere_prod_mconts_box 단위."""
    raw = re.sub(r'(?is)<(script|style).*?</\1>', '', raw)
    blocks = {}
    for part in re.split(r'class="Ere_prod_mconts_box"', raw)[1:]:
        tm = re.search(r'(?is)class="Ere_prod_mconts_LS"[^>]*>(.*?)</div>', part)
        title = clean_html(tm.group(1)) if tm else ''
        if title == '목차':
            full = re.search(r'(?is)id="div_TOC_All"[^>]*>(.*?)(?:<a [^>]*>\s*접기|</div>\s*<div class="Ere_line2")', part)
            short = re.search(r'(?is)id="div_TOC_Short"[^>]*>(.*?)</div>', part)
            body = clean_html((full or short).group(1)) if (full or short) else ''
        else:
            bm = re.search(r'(?is)class="Ere_prod_mconts_R"[^>]*>(.*?)<div class="Ere_line2"', part)
            body = clean_html(bm.group(1)) if bm else ''
        body = re.sub(r'\n?(접기|펼치기|더보기)\s*$', '', body).strip()
        if title and body and title not in blocks:
            blocks[title] = body
    return blocks


def aladin_contents(isbn10, item_id, isbn13):
    """상품 페이지의 '책소개' 지연 로딩 블록 (원본 html은 data/cache/raw 에 보관 → --reparse)"""
    rp = os.path.join(RAW, f'{isbn13}.html')
    if os.path.exists(rp) and not REFRESH:
        raw = open(rp, encoding='utf-8').read()
    else:
        ref = f'https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item_id}'
        raw = get(f'https://www.aladin.co.kr/shop/product/getContents.aspx?ISBN={isbn10}&name=Introduce&type=0&infoType=0&date={time.localtime().tm_hour}', referer=ref)
        if raw:
            open(rp, 'w', encoding='utf-8').write(raw)
    return parse_contents(raw)


def fetch_book(book):
    isbn = find_item(book)
    if not isbn:
        return None
    path = os.path.join(BOOKS, f'{isbn}.json')
    if os.path.exists(path) and REPARSE:
        rec = json.load(open(path, encoding='utf-8'))
        blocks = aladin_contents(rec['isbn10'], rec['itemId'], rec['isbn13'])
        rec['intro'] = blocks.get('책소개', rec['intro'] if 'aladin-page' not in rec['sources'] else '')
        rec['toc'] = blocks.get('목차', '')
        rec['publisherReview'] = next((v for k, v in blocks.items() if '출판사' in k), '')
        rec.pop('extra', None)
        json.dump(rec, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        return isbn
    if os.path.exists(path) and not REFRESH:
        return isbn
    res = api('ItemLookUp', ItemId=isbn, ItemIdType='ISBN13' if len(isbn) == 13 else 'ISBN',
              Cover='Big', OptResult='authors,ratingInfo,Toc,fulldescription,Story,categoryIdList')
    items = res.get('item') or []
    if not items:
        print('   ! 조회 실패', isbn, res.get('errorMessage'))
        return None
    it = items[0]
    sub = it.get('subInfo') or {}
    rec = {
        'isbn13': it.get('isbn13') or isbn,
        'isbn10': it.get('isbn'),
        'itemId': it.get('itemId'),
        'title': html.unescape(it.get('title', '')),
        'subTitle': html.unescape(sub.get('subTitle') or ''),
        'originalTitle': html.unescape(sub.get('originalTitle') or ''),
        'author': html.unescape(it.get('author', '')),
        'authors': sub.get('authors') or [],
        'publisher': html.unescape(it.get('publisher', '')),
        'pubDate': it.get('pubDate'),
        'priceStandard': it.get('priceStandard'),
        'priceSales': it.get('priceSales'),
        'pages': sub.get('itemPage'),
        'category': it.get('categoryName'),
        'series': (it.get('seriesInfo') or {}).get('seriesName'),
        'description': html.unescape(it.get('description') or ''),
        'coverUrl': it.get('cover'),
        'link': html.unescape(it.get('link') or ''),
        'stockStatus': it.get('stockStatus'),
        'toc': clean_html(sub.get('toc') or ''),
        'intro': clean_html(sub.get('fulldescription') or ''),
        'publisherReview': clean_html(sub.get('fulldescription2') or ''),
        'fetchedAt': time.strftime('%Y-%m-%d %H:%M'),
        'sources': ['aladin-api'],
    }
    # 상품 페이지 소개 블록
    if rec['isbn10'] and rec['itemId']:
        blocks = aladin_contents(rec['isbn10'], rec['itemId'], rec['isbn13'])
        if blocks:
            rec['sources'].append('aladin-page')
        for k, v in blocks.items():
            if k == '책소개' and not rec['intro']:
                rec['intro'] = v
            elif k == '목차' and not rec['toc']:
                rec['toc'] = v
            elif '출판사' in k and not rec['publisherReview']:
                rec['publisherReview'] = v
    # 표지
    cov = os.path.join(COVERS, f'{rec["isbn13"]}.jpg')
    if rec['coverUrl'] and (REFRESH or not os.path.exists(cov)):
        url = rec['coverUrl'].replace('/cover200/', '/cover500/').replace('/coversum/', '/cover500/')
        for u in (url, rec['coverUrl']):
            try:
                req = urllib.request.Request(u, headers={'User-Agent': UA, 'Referer': 'https://www.aladin.co.kr/'})
                with urllib.request.urlopen(req, timeout=25) as r:
                    data = r.read()
                if len(data) > 2000:
                    open(cov, 'wb').write(data)
                    break
            except Exception:  # noqa: BLE001
                continue
    json.dump(rec, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return rec['isbn13']


def main():
    os.makedirs(BOOKS, exist_ok=True)
    os.makedirs(COVERS, exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    only = [a for a in sys.argv[1:] if not a.startswith('--')]
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith('.json') or (only and fn[:-5] not in only):
            continue
        sp = os.path.join(SRC, fn)
        src = json.load(open(sp, encoding='utf-8'))
        print(f'■ {src["title"]} ({len(src["books"])}권)')
        changed = False
        for b in src['books']:
            isbn = fetch_book(b)
            mark = '✓' if isbn else '✗'
            info = ''
            if isbn:
                rec = json.load(open(os.path.join(BOOKS, f'{isbn}.json'), encoding='utf-8'))
                info = f'{rec["title"][:28]} / {rec["publisher"]} / 목차 {"O" if rec["toc"] else "-"} 소개 {"O" if rec["intro"] or rec["description"] else "-"}'
                if b.get('isbn13') != isbn:
                    b['isbn13'] = isbn
                    changed = True
            print(f'  {mark} {b["title"][:30]:<30} {isbn or ""} {info}')
        if changed:  # 찾은 ISBN을 소스에 고정 → 다음부터 검색 생략, 잘못 잡히면 손으로 고치면 됨
            json.dump(src, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
