#!/usr/bin/env python3
"""책 정보 수집 — data/issues/**/*.json · data/house/*.json 의 모든 추천 항목마다

  1) 알라딘 Open API(ItemSearch → ItemLookUp)로 ISBN·표지·정가·분류·쪽수
  2) 알라딘 상품 페이지 소개 블록(getContents Introduce)으로 책소개·목차
  (예스24 검색은 스크립트 접근 시 메인으로 돌려보내 오매칭 위험 → 쓰지 않음. 목차가 없으면 비워 둠)

결과는 data/cache/books/<isbn13>.json. 표지는 알라딘 이미지 주소(cover500)를 그대로 씀.
찾은 ISBN은 각 항목의 isbn13 으로 고정되고, 검색 결과는 data/cache/match.json 에 캐시.
잘못 잡힌 책은 항목의 isbn13 을 손으로 고치고, 알라딘에 없는 책은 "none".

  python3 fetch.py                 # 전체 (이미 받은 책은 건너뜀)
  python3 fetch.py teum            # 경로에 'teum' 이 들어간 목록만
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
    url = f'https://www.aladin.co.kr/ttb/api/{op}.aspx?' + urllib.parse.urlencode(q)
    for attempt in range(4):  # 알라딘이 가끔 JSON 대신 오류 페이지를 줌 → 잠시 쉬고 재시도
        txt = get(url, host_gap=1.0) or ''
        try:
            return json.loads(txt)
        except ValueError:
            try:  # 알라딘 js 출력은 가끔 제어문자/역슬래시가 섞여 있음
                return json.loads(re.sub(r'[\x00-\x1f]', ' ', txt).replace("\\'", "'"))
            except ValueError:
                time.sleep(5 * (attempt + 1))
    print('   ! 알라딘 응답 오류, 건너뜀:', params.get('Query') or params.get('ItemId'))
    return {}


def norm(s):
    return re.sub(r'[\s·・,.\-()（）\[\]:;!?「」『』《》<>]', '', (s or '')).lower()


MATCH_PATH = os.path.join(ROOT, 'data', 'cache', 'match.json')
MATCH = json.load(open(MATCH_PATH, encoding='utf-8')) if os.path.exists(MATCH_PATH) else {}


def find_item(book):
    """제목·출판사·저자로 검색해 가장 잘 맞는 상품 하나. 결과는 data/cache/match.json 에 캐시
    (못 찾은 책은 30일 뒤 다시 시도 — 출간 전 소개된 책이 나중에 등록되는 경우)."""
    if book.get('isbn13'):
        return book['isbn13']
    mk = norm(book['title']) + '|' + norm(book.get('publisher'))
    hit = MATCH.get(mk)
    if hit and (hit.get('isbn') or time.time() - hit.get('t', 0) < 30 * 86400):
        return hit.get('isbn')
    main = re.split(r'\s+-\s+|\s*:\s+|\s*＞', book['title'])[0].strip() or book['title']  # 부제 떼고 검색
    want_t, want_p, want_a = norm(main), norm(book.get('publisher')), norm((book.get('author') or '').split('·')[0].split(',')[0])
    best, best_score, items = None, -1, []
    for q in ([book.get('search')] if book.get('search') else []) + [f"{main} {book.get('publisher') or ''}".strip(), main]:
        res = api('ItemSearch', Query=q, QueryType='Keyword', SearchTarget='Book', MaxResults=20, Sort='Accuracy')
        items = res.get('item') or []
        for it in items:
            t, p, au = norm(html.unescape(it.get('title', ''))), norm(it.get('publisher')), norm(it.get('author'))
            score = 0
            if want_p and p and (want_p in p or p in want_p):
                score += 5
            if want_t and (t.startswith(want_t) or want_t.startswith(t.split('-')[0][:len(want_t)])):
                score += 5
            elif want_t[:8] and want_t[:8] in t:
                score += 3
            if want_a and len(want_a) >= 2 and want_a[:3] in au:
                score += 3
            if it.get('mallType') == 'BOOK':
                score += 1
            score += min(int(it.get('salesPoint') or 0), 50000) / 50000
            if score > best_score:
                best, best_score = it, score
        if best_score >= 9:
            break
    isbn = (best.get('isbn13') or best.get('isbn')) if best and best_score >= 8 else None
    if not isbn:
        print(f'   ? 일치 없음: {book["title"]} / {book.get("publisher")} → 후보', [(html.unescape(i["title"])[:24], i["publisher"]) for i in items[:3]])
    MATCH[mk] = {'isbn': isbn, 't': int(time.time()), 'score': round(best_score, 1)}
    return isbn


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
    rec['cover500'] = (rec['coverUrl'] or '').replace('/cover200/', '/cover500/').replace('/coversum/', '/cover500/')
    json.dump(rec, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return rec['isbn13']


def all_lists():
    """data/issues/<매체>/<호>.json 과 data/house/<목록>.json"""
    for base in ('issues', 'house'):
        root = os.path.join(ROOT, 'data', base)
        for dp, _, fns in os.walk(root):
            for fn in sorted(fns):
                if fn.endswith('.json') and not fn.startswith('_'):
                    yield os.path.join(dp, fn)


def main():
    os.makedirs(BOOKS, exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    only = [a for a in sys.argv[1:] if not a.startswith('--')]
    ok = miss = 0
    try:
        for path in all_lists():
            rel = os.path.relpath(path, os.path.join(ROOT, 'data'))
            if only and not any(o in rel for o in only):
                continue
            doc = json.load(open(path, encoding='utf-8'))
            changed = False
            for it in doc.get('items', []):
                if it.get('isbn13') == 'none' or str(it.get('isbn13') or '').startswith('custom-'):
                    continue
                isbn = fetch_book(it)
                if isbn:
                    ok += 1
                    if it.get('isbn13') != isbn:
                        it['isbn13'] = isbn
                        changed = True
                else:
                    miss += 1
            if changed:  # 찾은 ISBN을 고정 → 다음부터 검색 생략. 잘못 잡히면 손으로 고치고, 없는 책은 "none"
                json.dump(doc, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                print(f'  ✓ {rel}')
    finally:
        json.dump(MATCH, open(MATCH_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(f'■ 도서 정보: 연결 {ok}건, 못 찾음 {miss}건')


if __name__ == '__main__':
    main()
