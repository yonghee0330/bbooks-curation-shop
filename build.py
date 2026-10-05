#!/usr/bin/env python3
"""C.books 크리스천북 큐레이팅 서비스 빌드 — data/(매체별 호 + C.C 목록 + 알라딘 캐시) → 정적 사이트

  python3 collect.py          # 1) 매체별 새 호·새 글 수집 → data/issues/
  python3 pending.py          # 2) 요약이 비어 있는 추천 확인 (요약은 C.books가 다시 씀)
  python3 fetch.py            # 3) 책 정보·목차 (알라딘)
  python3 build.py            # 4) dist/ 생성       (--serve: http://localhost:8810)
  python3 build.py --pages    #    GitHub Pages용 docs/ → commit · push 하면 배포

출력
  index.html                  홈 — 이번 달, 여러 매체가 함께 고른 책, C.C 큐레이션, 매체
  m/<매체>/                   매체별 — 연도·계절별 호 목록
  i/<매체>/<호>/              호별 — 코너별 추천 (한 번에 담기)
  t/                          시기별 — 월별 타임라인
  t/<YYYY-MM>/                같은 시기, 매체마다 고른 책
  b/<isbn13>/                 도서 — 같은 책에 대한 매체별 추천 글, 책소개·목차, 구매
  x/                          탐색 — 매체·기간·코너·겹침·검색을 조합
  y/ , y/<목록>/              C.C 큐레이션
  cart/                       장바구니 · 주문 요청
  data/catalog.json, data/index.json
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import shutil
import sys
from collections import defaultdict, OrderedDict
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
SITE_DIR = os.path.join(ROOT, 'site')
SHARE = '--share' in sys.argv  # 공유용(클로드 아티팩트): 폴더 주소 대신 index.html, 허용된 폰트만 → share/
PAGES = '--pages' in sys.argv  # GitHub Pages 배포용 → docs/ (main 브랜치 /docs 에서 서빙)
DIST = os.path.join(ROOT, 'share' if SHARE else 'docs' if PAGES else 'dist')
VER = datetime.now().strftime('%m%d%H%M')
BASE = '/bbooks-curation-shop/' if PAGES else '/'  # 사이트 루트 경로 (손으로 넣은 표지 이미지 주소에 사용)
_ovp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'overrides.json')
OVERRIDES = {k: v for k, v in json.load(open(_ovp, encoding='utf-8')).items() if not k.startswith('_')} if os.path.exists(_ovp) else {}

SITE = json.load(open(os.path.join(DATA, 'site.json'), encoding='utf-8'))
MEDIA = OrderedDict(sorted(((k, v) for k, v in json.load(open(os.path.join(DATA, 'media.json'), encoding='utf-8')).items()
                            if not k.startswith('_')), key=lambda kv: kv[1]['order']))

# 코너: (이름, 무게 — 작을수록 강한 추천, 묶음)
SECTIONS = {
    'pick': ('이달의 책', 1, 'pick'), 'mention': ('이달의 책 두 번째', 2, 'pick'), 'year': ('올해의 책', 2, 'pick'),
    'house': ('C.C 추천', 2, 'house'),
    'editor': ('편집자 추천', 3, 'pick'), 'curation': ('큐레이션', 3, 'pick'), 'best': ('베스트서평', 3, 'review'),
    'essay': ('서사의 서사', 3, 'review'), 'special': ('특별 기고', 4, 'review'),
    'preview': ('신간 프리뷰', 4, 'new'), 'new': ('이 책 한번 잡솨봐', 4, 'new'), 'daily': ('1일1책', 4, 'new'),
    'person': ('인물 여백', 5, 'review'), 'review': ('서평', 3, 'review'), 'classic': ('고전 목록', 3, 'pick'),
    'related': ('함께 읽기', 9, 'related'),
}
SECTION_BY_MEDIA = {('emmaus', 'editor'): '기획위원 Pick', ('cbooknews', 'editor'): '편집자추천도서', ('goscon', 'editor'): '에디터가 고른 책',
                    ('goscon', 'new'): '새 책 소개', ('kmib', 'pick'): '올해 최고의 책', ('kmib', 'curation'): '놓치기 아까운 책',
                    ('ct100', 'classic'): '20세기 기독교 책 100권', ('churchtimes', 'classic'): '최고의 기독교 서적 100선'}
GROUPS = [('pick', '대표 추천'), ('review', '서평·에세이'), ('new', '신간 소개'), ('house', 'C.C'), ('related', '함께 읽기')]
SEASON_ORDER = {'봄': 1, '여름': 2, '가을': 3, '겨울': 4}

e = html.escape


def won(n):
    return f'{int(n):,}원'


def sale_price(std):
    rate = float(SITE['pricing'].get('discountRate') or 0)
    return int(math.floor((std or 0) * (1 - rate) / 10) * 10)


def short_title(t):
    return re.split(r'\s+-\s+', t, maxsplit=1)[0].strip()


def first_author(a):
    return re.sub(r'\s*\([^)]*\)', '', (a or '').split(',')[0]).strip()


def ymd(d):
    return (d or '').replace('-', '. ')


def month_label(ym):
    return f'{int(ym[:4])}년 {int(ym[5:7])}월'


def season_of(d):
    y, m = int(d[:4]), int(d[5:7])
    if m in (12, 1, 2):
        return f'{y if m == 12 else y - 1} 겨울'
    return f'{y} ' + ('봄' if m <= 5 else '여름' if m <= 8 else '가을')


def season_key(s):
    y, n = s.split()
    return (int(y), SEASON_ORDER[n])


def sec_label(media, sec, item=None):
    if item and (item.get('label') or item.get('corner')):
        return item.get('label') or item['corner']
    return SECTION_BY_MEDIA.get((media, sec)) or SECTIONS.get(sec, (sec, 8, 'review'))[0]


def paras(text):
    out = []
    for p in re.split(r'\n\s*\n', text or ''):
        p = p.strip()
        if p:
            out.append('<p>' + '<br>'.join(e(x) for x in p.split('\n')) + '</p>')
    return '\n'.join(out)


def toc_html(toc):
    lines = [ln.strip() for ln in (toc or '').split('\n') if ln.strip()]
    items = []
    for ln in lines:
        part = re.match(r'^(제\s*\d+\s*부|\d+\s*부[\s.:]|Part\s|PART\s|[1-9]부$|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s])', ln) or \
            re.match(r'^(서론|결론|들어가며|나가며|머리말|맺음말|프롤로그|에필로그|부록)', ln)
        items.append(f'<li{" class=part" if part else ""}>{e(ln)}</li>')
    return '<ol class="toc">' + ''.join(items) + '</ol>', len(lines)


# ───────────────────────── 데이터 ─────────────────────────

def unit_n(mm, n):
    return {'호': f'{n}개 호', '년': f'{n}개 연도', '목록': f'{n}개 목록'}.get(mm.get('unit'), f'{n}개월')


def line_title(i):
    """목록 줄 제목 — 엠마오는 '제N호 · 월 · 타이틀' 중 호 뒤쪽(월 · 타이틀)"""
    if i['media'] == 'emmaus' and ' · ' in i['title']:
        return i['title'].split(' · ', 1)[1]
    return i.get('headline') or i.get('subtitle') or i.get('theme') or i['title']


def fam(m):
    """같은 매체에서 나뉜 목록(복음과상황 서평·새 책 / 서사의 서사, 틈 / 틈 올해의 책)은 한 매체로 센다"""
    return MEDIA[m].get('family', m)


def is_regular(m):
    return MEDIA[m].get('group') == 'regular'


def split_issue(m, iss):
    """한 파일을 화면용 목록으로 나눈다 — 복음과상황: 〈서사의 서사〉 / 정기 서평·새 책 코너, 틈: 연말 올해의 책은 특별 리스트"""
    items = iss.get('items') or []
    if m == 'goscon':
        essay = [it for it in items if it.get('section') in ('essay', 'related')]
        rest = [it for it in items if it.get('section') not in ('essay', 'related')]
        out = []
        if essay:
            out.append(('goscon', dict(iss, items=essay, column='서사의 서사')))
        if rest:
            link = next((it.get('link') for it in rest if it.get('link')), '') or iss.get('url', '')
            out.append(('gosconbook', dict(iss, items=rest, title=f'복음과상황 {iss.get("no", "")} 서평·새 책'.replace('  ', ' '),
                                           headline='', column='정기 코너', url=link)))
        return out
    if m == 'teum' and items and all(it.get('section') == 'year' for it in items):
        return [('teumyear', iss)]
    return [(m, iss)]


STOCK_NOTICE = {
    '절판': ('이 책은 현재 절판 상태예요. 새로 구입할 수 없어 주문을 받지 않아요.', '절판'),
    '구판절판': ('이 판본은 절판되었어요. 새로 구입할 수 없어 주문을 받지 않아요.', '절판'),
    '품절': ('이 책은 현재 품절 상태예요. 재입고되면 다시 주문할 수 있어요.', '품절'),
    '일시품절': ('이 책은 일시 품절 상태예요. 재입고되면 다시 주문할 수 있어요.', '일시 품절'),
}


class Catalog:
    def __init__(self):
        self.issues = []          # 호/월 묶음/C.C 목록
        self.recs = []            # 추천 한 건 = (책, 매체, 호, 코너, 추천자, 요약)
        self.books = {}           # isbn13 → 알라딘 정보 + recs
        self.load()

    def book_info(self, isbn):
        if isbn in self.books:
            return self.books[isbn]
        if isbn.startswith('custom-'):  # data/custom_books.json — 알라딘에 없는 책(직접 구매 안내 등)
            cp = os.path.join(DATA, 'custom_books.json')
            cb = json.load(open(cp, encoding='utf-8')).get(isbn) if os.path.exists(cp) else None
            if not cb:
                return None
            b = dict(cb, isbn13=isbn)
        else:
            p = os.path.join(DATA, 'cache', 'books', f'{isbn}.json')
            if not os.path.exists(p):
                return None
            b = json.load(open(p, encoding='utf-8'))
        b['short'] = short_title(b['title'])
        b['subTitle'] = b.get('subTitle') or b['title'].partition(' - ')[2].strip()
        b['price'] = sale_price(b.get('priceStandard'))
        b['cover'] = b.get('cover500') or (b.get('coverUrl') or '').replace('/cover200/', '/cover500/').replace('/coversum/', '/cover500/')
        b['thumb'] = b.get('coverUrl') or b['cover']
        ov = OVERRIDES.get(isbn) or {}  # data/overrides.json — 표지·제목·정가 손 보정
        st = STOCK_NOTICE.get(b.get('stockStatus') or '')  # 알라딘 재고 상태: 품절·절판은 주문 불가로 안내
        if st:
            b['noSale'], b['tag'] = st
        for k in ('noSale', 'tag', 'buyUrl', 'buyLabel'):  # 온라인 주문 불가 책: 안내 문구·링크
            if ov.get(k):
                b[k] = ov[k]
        for k in ('title', 'author', 'publisher', 'priceStandard'):
            if ov.get(k):
                b[k] = ov[k]
        if ov.get('title'):
            b['short'] = short_title(b['title'])
        if ov.get('priceStandard'):
            b['price'] = sale_price(b['priceStandard'])
        if ov.get('noCover'):
            b['cover'] = b['thumb'] = ''
        if ov.get('cover'):
            c = ov['cover'] if ov['cover'].startswith('http') else BASE + 'assets/' + ov['cover'].lstrip('/')
            b['cover'] = b['thumb'] = c
        b['recs'] = []
        self.books[isbn] = b
        return b

    def load(self):
        lists = []
        for m in MEDIA:
            d = os.path.join(DATA, 'issues', m)
            if os.path.isdir(d):
                lists += [(m, os.path.join(d, fn)) for fn in sorted(os.listdir(d)) if fn.endswith('.json') and not fn.startswith('_')]
        hd = os.path.join(DATA, 'house')
        if os.path.isdir(hd):
            lists += [('yong', os.path.join(hd, fn)) for fn in sorted(os.listdir(hd)) if fn.endswith('.json') and not fn.startswith('_')]
        expanded = []
        for m, path in lists:
            expanded += split_issue(m, json.load(open(path, encoding='utf-8')))
        for m, iss in expanded:
            iss['media'] = m
            if not iss.get('items') or iss.get('hidden'):
                continue
            iss.setdefault('season', season_of(iss['date']))
            iss['month'] = iss['date'][:7]
            iss['path'] = f'y/{iss["id"]}/' if m == 'yong' else f'i/{m}/{iss["id"]}/'
            iss['recs'] = []
            for it in iss['items']:
                if it.get('hidden'):  # tools/edit.py hide — 사이트에서 숨김
                    continue
                sec = it.get('section') or ('house' if m == 'yong' else 'review')
                d = it.get('date') or iss['date']
                r = {'media': m, 'mname': MEDIA[m]['name'], 'issue': iss, 'item': it, 'section': sec,
                     'secKo': sec_label(m, sec, it), 'weight': SECTIONS.get(sec, ('', 6, ''))[1],
                     'group': 'house' if m == 'yong' else SECTIONS.get(sec, ('', 6, 'review'))[2],
                     'date': d, 'month': d[:7], 'season': season_of(d), 'by': [x for x in it.get('by', []) if x],
                     'summary': it.get('summary') or it.get('note') or '', 'headline': it.get('headline', ''),
                     'url': it.get('url') or iss.get('url', ''), 'isbn': it.get('isbn13') if it.get('isbn13') not in (None, 'none') else None}
                r['book'] = self.book_info(r['isbn']) if r['isbn'] else None
                if r['book'] is not None:
                    r['book']['recs'].append(r)
                iss['recs'].append(r)
                self.recs.append(r)
            self.issues.append(iss)
        self.issues.sort(key=lambda i: (i['date'], i['media']), reverse=True)
        for b in self.books.values():
            b['recs'].sort(key=lambda r: (r['date'], -r['weight']), reverse=True)
            b['media'] = sorted({r['media'] for r in b['recs']}, key=lambda m: MEDIA[m]['order'])
            b['outside'] = [m for m in b['media'] if m != 'yong']
            b['fams'] = sorted({fam(m) for m in b['outside']})
            b['weight'] = min((r['weight'] for r in b['recs']), default=9)
            b['last'] = max((r['date'] for r in b['recs']), default='')
            b['first'] = min((r['date'] for r in b['recs']), default='')
        self.books = {k: v for k, v in self.books.items() if v['recs']}

    def months(self):
        return sorted({r['month'] for r in self.recs if is_regular(r['media'])}, reverse=True)


# ───────────────────────── 조각 ─────────────────────────

def biz_footer():
    b = SITE.get('business', {})
    parts = [('상호', b.get('name')), ('대표', b.get('owner')), ('사업자등록번호', b.get('bizNo')), ('통신판매업', b.get('mailOrderNo')),
             ('주소', b.get('address')), ('전화', b.get('phone')), ('이메일', b.get('email'))]
    return ' · '.join(e(f'{k} {v}') for k, v in parts if v and not str(v).startswith('('))


def page(title, body, depth, desc='', active='', og_image=None, page_id='', noindex=False):
    up = '../' * depth
    desc = desc or SITE['intro']
    nav = [('', '홈', 'home'), ('m/', '매체별', 'media'), ('t/', '시기별', 'time'), ('x/', '탐색', 'explore'),
           ('y/', 'C.C', 'yong'), ('cart/', '장바구니', 'cart')]
    navh = ''.join(
        f'<a href="{up}{href}" class="{"on" if key == active else ""}">{label}{"<b class=cart-n data-cart-count></b>" if key == "cart" else ""}</a>'
        for href, label, key in nav) + f'<a href="{up}login/" class="acct{" on" if active == "me" else ""}" data-account hidden>로그인</a>'
    og = f'<meta property="og:image" content="{e(og_image)}">' if og_image else ''
    pretendard = '' if SHARE else '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css">'
    cfg = {'apiUrl': SITE['apiUrl'], 'pricing': SITE['pricing'], 'pickup': SITE['store']['pickup'], 'eta': SITE['store']['eta'],
           'root': up, 'idx': 'index.html' if SHARE else '', 'brand': SITE.get('brand', ''),
           'providers': SITE.get('loginProviders', ['google']), 'supabase': SITE.get('supabase') if (SITE.get('supabase') or {}).get('url') and not SHARE else {}}
    sbjs = '<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js"></script>' if cfg['supabase'] else ''
    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc[:160])}">{'<meta name="robots" content="noindex">' if noindex else ''}
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc[:160])}">
{og}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Gowun+Batang:wght@400;700&family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,650;1,9..144,400&display=swap">
{pretendard}
<link rel="stylesheet" href="{up}assets/app.css?v={VER}">
</head>
<body data-page="{page_id}">
<header class="top">
  <div class="wrap top-in">
    <a class="logo" href="{up}"><span class="logo-mark">C</span><span><b>{e(SITE['short'])}</b><small>{e(SITE['tagline'])}</small></span></a>
    <nav>{navh}</nav>
  </div>
</header>
<main>
{body}
</main>
<footer class="foot">
  <div class="wrap">
    <p><b>{e(SITE['name'])}</b> · {e(SITE['store']['address'])} · <a href="{SITE['store']['instagram']}" target="_blank" rel="noopener">@{e(SITE['store']['instagram'].rstrip('/').rsplit('/', 1)[-1])}</a></p>
    <p class="muted">추천 글 요약은 C.books가 각 매체의 글을 읽고 다시 쓴 것입니다. 원문은 각 매체에서 읽어 주세요 — {' · '.join(f'<a href="{mm["home"]}" target="_blank" rel="noopener">{e(mm["name"])}</a>' for k, mm in MEDIA.items() if mm.get('home'))}. 도서 정보·표지·목차 제공: 알라딘.</p>
    <p class="small muted">{biz_footer()}</p>
    <p class="small"><a href="{up}terms/">이용약관</a> · <a href="{up}privacy/"><b>개인정보 처리방침</b></a> · <a href="{up}order/">비회원 주문 조회</a></p>
  </div>
</footer>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script>window.SHOP={json.dumps(cfg, ensure_ascii=False)};</script>
{sbjs}
<script src="{up}assets/member.js?v={VER}"></script>
<script src="{up}assets/app.js?v={VER}"></script>
</body>
</html>
'''


def cover(b, cls='cover', big=False):
    if b and (b.get('cover') or b.get('thumb')):
        src = b['cover'] if big else b['thumb']
        return f'<img class="{cls}" src="{e(src)}" alt="{e(b["short"])} 표지" loading="lazy" referrerpolicy="no-referrer">'
    return f'<div class="{cls} nocover"><span>{e(b["short"] if b else "")}</span></div>'


def mchip(m, extra=''):
    mm = MEDIA[m]
    return f'<span class="mchip" style="--mc:{mm["color"]}">{e(mm["name"])}{extra}</span>'


def media_dots(b):
    return ''.join(mchip(m) for m in b['media'])


def add_btn(b, label='담기', cls='btn add'):
    if b.get('noSale'):
        return ''
    return f'<button class="{cls}" data-add="{b["isbn13"]}">{label}</button>'


def price(b):
    if b.get('noSale'):
        return f'<span class="price"><b class="nosale">{e(b.get("tag") or "구매 안내")}</b></span>'
    return f'<span class="price"><s>{won(b["priceStandard"])}</s> <b>{won(b["price"])}</b></span>'


def nosale_box(b):
    if not b.get('noSale'):
        return ''
    link = f' <a class="btn primary" href="{e(b["buyUrl"])}" target="_blank" rel="noopener">{e(b.get("buyLabel") or "구매처 보기")}</a>' if b.get('buyUrl') else ''
    return f'<div class="buybox nosale-box"><p>{e(b["noSale"])}</p>{link}</div>'


ROUNDUP = re.compile(r'외\s*\d+\s*권')  # 여러 권을 묶은 신간 소개 기사 제목은 요약 자리에 반복하지 않음


def rec_text(r):
    """요약이 있으면 요약, 없으면 매체의 기사 제목 + 원문 링크"""
    if r['summary']:
        return f'<p class="why">{e(r["summary"])}</p>'
    if r['headline'] and not ROUNDUP.search(r['headline']):
        return f'<p class="why headline">「{e(r["headline"])}」</p>'
    return '<p class="why muted">요약 준비 중 — 원문에서 읽어 주세요.</p>'


def book_card(b, up, note=None):
    lead = note or b['recs'][0]
    groups = ' '.join(sorted({r['group'] for r in b['recs']}))
    return f'''<article class="card" data-groups="{groups}" data-media="{' '.join(b['media'])}">
  <a class="card-cover" href="{up}b/{b['isbn13']}/">{cover(b)}</a>
  <div class="card-body">
    <div class="mchips">{media_dots(b)}</div>
    <h3><a href="{up}b/{b['isbn13']}/">{e(b['short'])}</a></h3>
    <p class="meta">{e(first_author(b['author']))} · {e(b['publisher'])}</p>
    <p class="by">{e(lead['mname'])} {e(lead['secKo'])}{(' · ' + e(', '.join(lead['by'][:2]))) if lead['by'] else ''}</p>
    <div class="card-foot">{price(b)}{add_btn(b)}</div>
  </div>
</article>'''


def rec_row(r, up, show_issue=True, show_book=False):
    """추천 한 건 (도서 페이지·호 페이지 공용)"""
    it, iss, b = r['item'], r['issue'], r['book']
    who = ', '.join(r['by'])
    src = f'<a class="rec-src" href="{up}{iss["path"]}">{e(MEDIA[r["media"]]["name"])} {e(iss.get("no") or month_label(iss["month"]) if r["media"] in ("newsnjoy", "cbooknews") else iss.get("no") or "")}</a>' if show_issue else ''
    orig = f' <a class="orig" href="{e(r["url"])}" target="_blank" rel="noopener">원문 ↗</a>' if r['url'] and r['media'] != 'yong' else ''
    book = ''
    if show_book:
        if b:
            book = f'<a class="rec-book" href="{up}b/{b["isbn13"]}/">{cover(b, "cover xs")}<span><b>{e(b["short"])}</b><small>{e(b["publisher"])}</small></span></a>'
        else:
            book = f'<div class="rec-book"><div class="cover xs nocover"></div><span><b>{e(it["title"])}</b><small>{e(it.get("publisher", ""))} · 도서 정보 없음</small></span></div>'
    field = f' · {e(it["field"])}' if it.get('field') else ''
    return f'''<article class="rec" style="--mc:{MEDIA[r['media']]['color']}">
  {book}
  <div class="rec-main">
    <header>{mchip(r['media'])}<span class="sec">{e(r['secKo'])}{field}</span>{src}<time>{ymd(r['date'])}</time></header>
    {rec_text(r)}
    <footer>{('<b>' + e(who) + '</b>') if who else ''}{orig}</footer>
  </div>
</article>'''


def strip(books, up, n=6):
    return '<div class="strip">' + ''.join(f'<a href="{up}b/{b["isbn13"]}/" title="{e(b["short"])}">{cover(b, "cover xs")}</a>' for b in books[:n]) + '</div>'


# ───────────────────────── 페이지 ─────────────────────────

def build_home(c):
    up = ''
    months = c.months()
    cur = months[0] if months else ''
    # 이번 달 — 매체별 최신 호
    latest_cols = ''
    for m, mm in MEDIA.items():
        if mm.get('group') != 'regular':
            continue
        iss = next((i for i in c.issues if i['media'] == m), None)
        if not iss:
            continue
        bs = [r['book'] for r in sorted(iss['recs'], key=lambda r: r['weight']) if r['book']]
        latest_cols += f'''<a class="latest" href="{iss['path']}" style="--mc:{mm['color']}">
  <span class="latest-m">{e(mm['name'])}</span>
  <b>{e(iss.get('no') or month_label(iss['month']))}</b>
  <span class="latest-t">{e(line_title(iss))}</span>
  <span class="latest-d">{ymd(iss['date'])} · {len(iss['recs'])}권</span>
  {strip(list(OrderedDict((x['isbn13'], x) for x in bs).values()), up, 5).replace('<a ', '<span ').replace('</a>', '</span>')}
</a>'''
    multi = [b for b in c.books.values() if len(b['fams']) >= 2]
    multi = sorted(multi, key=lambda b: (-len(b['fams']), -int(b['last'].replace('-', '') or 0)))
    multi_html = ''.join(f'''<a class="overlap" href="b/{b['isbn13']}/">
  {cover(b)}
  <div><b>{e(b['short'])}</b><span class="meta">{e(b['publisher'])}</span>
  <div class="mchips">{media_dots(b)}</div><small>{len(b['recs'])}편의 추천 · {ymd(b['first'])[:9]} ~ {ymd(b['last'])[:9]}</small></div>
</a>''' for b in multi[:12])
    house = [i for i in c.issues if i['media'] == 'yong']
    house_html = ''.join(f'''<a class="house" href="{i['path']}"><span class="kicker">C.C · {ymd(i['date'])[:9]}</span><b>{e(i['title'])}</b><p>{e(i.get('intro', '')[:110])}</p>{strip([r['book'] for r in i['recs'] if r['book']], up, 6).replace('<a ', '<span ').replace('</a>', '</span>')}</a>''' for i in house[:3])
    n_media = len({fam(m) for m, mm in MEDIA.items() if mm.get('group') == 'regular' and any(i['media'] == m for i in c.issues)})
    n_special = sum(1 for m, mm in MEDIA.items() if mm.get('group') == 'special' and any(i['media'] == m for i in c.issues))
    n_reviews = sum(1 for r in c.recs if r['media'] != 'yong')
    media_cards, special_cards = '', ''
    for m, mm in MEDIA.items():
        if mm.get('house'):
            continue
        iss = [i for i in c.issues if i['media'] == m]
        if not iss:
            continue
        nb = len({r['isbn'] for i in iss for r in i['recs'] if r['isbn']})
        card = f'''<a class="media-card" href="m/{m}/" style="--mc:{mm['color']}"><div><b>{e(mm['full'])}</b><span>{e(mm['kind'])} · {e(mm['cadence'])}</span><p>{e(mm['about'])}</p></div><small>{unit_n(mm, len(iss))} · {nb}권<br>{ymd(min(i['date'] for i in iss))[:9]} ~</small></a>'''
        if mm.get('group') == 'special':
            special_cards += card
        else:
            media_cards += card
    body = f'''
<section class="hero">
  <div class="wrap hero-in">
    <div class="hero-txt">
      <p class="kicker">C.books · 크리스천북 큐레이팅 서비스 · {month_label(cur) if cur else ''}</p>
      <h1>좋은 매체가 고른 책,<br>한자리에서 비교하며 고르기</h1>
      <p class="sub">{e(SITE['intro'])}</p>
      <p class="stats"><b>{n_media}</b>개 정기 매체 · <b>{n_special}</b>개 특별 리스트 · <b>{len([i for i in c.issues if i['media'] != 'yong'])}</b>개 호 · <b>{n_reviews:,}</b>편의 추천 · <b>{len(c.books):,}</b>권</p>
      <div class="row"><a class="btn primary" href="x/">조건으로 찾아보기</a><a class="btn ghost" href="t/{cur}/">{month_label(cur) if cur else ''}에 고른 책 →</a></div>
    </div>
  </div>
</section>

<section class="wrap block">
  <div class="sec-head"><h2>정기 매체 최신 호</h2><p>꾸준히 업데이트되는 매체들이 같은 시기에 고른 책</p></div>
  <div class="latests">{latest_cols}</div>
</section>

<section class="wrap block">
  <div class="sec-head"><h2>여러 매체가 함께 고른 책</h2><p>두 곳 이상에서 추천된 {len(multi)}권 · 같은 책, 다른 리뷰</p><a class="more" href="x/?multi">모두 보기 →</a></div>
  <div class="overlaps">{multi_html or '<p class="muted">아직 겹친 책이 없어요.</p>'}</div>
</section>

{f'<section class="wrap block"><div class="sec-head"><h2>C.books Curating - C.C</h2><p>매체들의 추천을 함께 읽고 C.books가 고른 목록</p><a class="more" href="y/">전체 →</a></div><div class="houses">{house_html}</div></section>' if house else ''}

<section class="wrap block">
  <div class="sec-head"><h2>정기 업데이트 매체</h2><p>매달·매주 새 추천이 올라오는 곳</p></div>
  <div class="media-list">{media_cards}</div>
</section>

<section class="wrap block">
  <div class="sec-head"><h2>특별 추천도서 리스트</h2><p>해마다, 혹은 한 번 발표된 선정 목록</p></div>
  <div class="media-list">{special_cards}</div>
</section>
'''
    write('index.html', page(SITE['name'], body, 0, active='home'))


def build_media(c):
    idx = {'regular': '', 'special': ''}
    for m, mm in MEDIA.items():
        if mm.get('house'):
            continue
        iss = [i for i in c.issues if i['media'] == m]
        if not iss:
            continue
        up = '../../'
        by_season = OrderedDict()
        for i in iss:
            by_season.setdefault(i['season'], []).append(i)
        sec_html = ''
        for s, lst in by_season.items():
            rows = ''
            for i in lst:
                bs = list(OrderedDict((r['book']['isbn13'], r['book']) for r in sorted(i['recs'], key=lambda r: r['weight']) if r['book']).values())
                rows += f'''<a class="issue-line" href="{up}{i['path']}">
  <span class="il-no">{e(i.get('no') or month_label(i['month']))}</span>
  <span class="il-t"><b>{e(line_title(i))}</b><small>{ymd(i['date'])} · {e(i.get('column') or '')} · {len(i['recs'])}편</small></span>
  {strip(bs, up, 6).replace('<a ', '<span ').replace('</a>', '</span>')}
</a>'''
            sec_html += f'<section class="season"><h3>{e(s)}</h3>{rows}</section>'
        nb = len({r['isbn'] for i in iss for r in i['recs'] if r['isbn']})
        body = f'''
<section class="issue-hero" style="--mc:{mm['color']}">
  <div class="wrap">
    <p class="kicker">{e(mm['en'])} · {e(mm['kind'])}</p>
    <h1>{e(mm['full'])}</h1>
    <p class="sub">{e(mm['about'])}</p>
    <p class="stats light">{unit_n(mm, len(iss))} · 추천 {sum(len(i['recs']) for i in iss)}편 · {nb}권</p>
    <div class="row">{f'<a class="btn ghost light" href="{mm["subscribe"]}" target="_blank" rel="noopener">{e(mm["name"])} 원문 ↗</a>' if mm.get('subscribe') else ''}<a class="btn ghost light" href="{up}x/?m={m}">이 매체의 책 탐색</a></div>
  </div>
</section>
<div class="wrap seasons">{sec_html}</div>'''
        write(f'm/{m}/index.html', page(f'{mm["full"]} 추천 도서 — {SITE["short"]}', body, 2, desc=mm['about'], active='media'))
        idx[mm.get('group', 'regular')] += f'''<a class="media-issue" href="{m}/" style="--mc:{mm['color']}"><span class="mag-en">{e(mm['en'])}</span><b>{e(mm['full'])}</b><span>{e(mm['about'])}</span><small>{unit_n(mm, len(iss))} · {nb}권 · 최근 {ymd(iss[0]['date'])}</small></a>'''
    body = (f'<section class="wrap block"><div class="sec-head"><h1>정기 업데이트 매체</h1><p>매체를 고르면 연도·계절별로 호를 볼 수 있어요</p></div><div class="issues">{idx["regular"]}</div></section>'
            f'<section class="wrap block"><div class="sec-head"><h2>특별 추천도서 리스트</h2><p>연말 선정·고전 목록처럼 따로 발표된 리스트</p></div><div class="issues">{idx["special"]}</div></section>')
    write('m/index.html', page(f'매체별 — {SITE["short"]}', body, 1, active='media'))


def build_issues(c):
    for iss in c.issues:
        m = iss['media']
        mm = MEDIA[m]
        up = '../../../' if m != 'yong' else '../../'
        groups = OrderedDict()
        for r in sorted(iss['recs'], key=lambda r: (r['weight'], r['item'].get('rank') or 0, r['item'].get('field', ''), r['date'])):
            groups.setdefault(r['secKo'], []).append(r)
        body_groups = ''
        for label, rs in groups.items():
            rows = ''
            for r in rs:
                b = r['book']
                others = [x for x in b['outside'] if x != m] if b else []
                other = f'<span class="also">다른 매체도 추천: {"".join(mchip(x) for x in others)}</span>' if others else ''
                buy = f'<div class="issue-buy">{price(b)}{add_btn(b)}</div>' if b else f'<div class="issue-buy"><span class="muted small">{"국내 번역본을 찾지 못했어요" if mm.get("group") == "special" else "도서 정보를 찾지 못했어요"}</span></div>'
                title = f'<a href="{up}b/{b["isbn13"]}/">{e(b["short"])}</a>' if b else e(r['item']['title'])
                orig = f' · <a class="orig" href="{e(r["url"])}" target="_blank" rel="noopener">원문 ↗</a>' if r['url'] and r['url'] != iss.get('url') and m != 'yong' else ''
                rows += f'''<article class="issue-row">
  {f'<a href="{up}b/{b["isbn13"]}/">{cover(b, "cover sm")}</a>' if b else '<div class="cover sm nocover"></div>'}
  <div>
    <p class="eyebrow">{e(r['item'].get('field', ''))}{(' · p.' + str(r['item']['page'])) if r['item'].get('page') else ''}{(' · ' + ymd(r['date'])) if m in ('newsnjoy', 'cbooknews') else ''}</p>
    <h3>{title}</h3>
    <p class="meta">{e(b['author'] if b else r['item'].get('author', ''))} · {e(b['publisher'] if b else r['item'].get('publisher', ''))}</p>
    {rec_text(r)}
    <p class="by">{('— ' + e(', '.join(r['by']))) if r['by'] else ''}{orig}</p>
    {other}
  </div>
  {buy}
</article>'''
            body_groups += f'<section class="issue-sec"><div class="issue-sec-head"><h2>{e(label)}</h2><span>{len(rs)}</span></div>{rows}</section>'
        ids = list(OrderedDict.fromkeys(r['isbn'] for r in iss['recs'] if r['book'] and r['section'] != 'related'))
        total = sum(c.books[i]['price'] for i in ids)
        same_month = [i for i in c.issues if i['month'] == iss['month'] and i['media'] != m and is_regular(i['media'])] if is_regular(m) else []
        sm = ''.join(f'<a href="{up}{i["path"]}">{mchip(i["media"])} {e(i.get("no") or month_label(i["month"]))}</a>' for i in same_month)
        head_t = iss.get('headline') or iss.get('subtitle') or ''
        body = f'''
<section class="issue-hero" style="--mc:{mm['color']}">
  <div class="wrap">
    <p class="kicker"><a href="{up}{'m/' + m + '/' if m != 'yong' else 'y/'}">{e(mm['full'])}</a> · {e(iss.get('no', ''))} · {ymd(iss['date'])}</p>
    <h1>{e(iss['title'])}</h1>
    {f'<p class="lead">{e(head_t)}</p>' if head_t else ''}
    {f'<p class="lead">{e(iss["theme"])}</p>' if iss.get('theme') and iss['theme'] not in iss['title'] else ''}
    {f'<p class="sub">{e(iss["intro"])}</p>' if iss.get('intro') else ''}
    <div class="row">
      {f'<button class="btn primary" data-add-many="{e(json.dumps(ids))}">추천 도서 {len(ids)}권 모두 담기 · {won(total)}</button>' if ids else ''}
      {f'<a class="btn ghost light" href="{e(iss["url"])}" target="_blank" rel="noopener">원문 보기 ↗</a>' if iss.get('url') else ''}
      {f'<a class="btn ghost light" href="{up}t/{iss["month"]}/">같은 달 다른 매체 →</a>' if is_regular(m) else ''}
    </div>
    {f'<p class="same">같은 달: {sm}</p>' if sm else ''}
  </div>
</section>
<div class="wrap issue">{body_groups}</div>'''
        write(f'{iss["path"]}index.html', page(f'{iss["title"]} — {SITE["short"]}', body, up.count('../'), desc=head_t or iss.get('theme') or mm['about'],
                                               active='yong' if m == 'yong' else 'media'))


def build_time(c):
    months = c.months()
    up1 = '../'
    by_season = OrderedDict()
    for ym in months:
        by_season.setdefault(season_of(ym + '-15'), []).append(ym)
    tl = ''
    for s, yms in by_season.items():
        rows = ''
        for ym in yms:
            cells = ''
            for m, mm in MEDIA.items():
                if mm.get('group') != 'regular':
                    continue
                rs = [r for r in c.recs if r['month'] == ym and r['media'] == m]
                bs = list(OrderedDict((r['book']['isbn13'], r['book']) for r in sorted(rs, key=lambda r: r['weight']) if r['book']).values())
                cells += f'<div class="tl-cell" style="--mc:{mm["color"]}">{f"<b>{len(rs)}</b>" + strip(bs, up1, 3).replace("<a ", "<span ").replace("</a>", "</span>") if rs else "<span class=muted>—</span>"}</div>'
            overlap = [b for b in c.books.values() if len({fam(r['media']) for r in b['recs'] if r['month'] == ym and is_regular(r['media'])}) >= 2]
            rows += f'<a class="tl-row" href="{ym}/"><span class="tl-m">{int(ym[5:7])}월<small>{ym[:4]}</small></span>{cells}<span class="tl-ov">{f"겹침 {len(overlap)}" if overlap else ""}</span></a>'
        tl += f'<section class="season"><h3>{e(s)}</h3>{rows}</section>'
    head = ''.join(f'<span style="--mc:{mm["color"]}">{e(mm["name"])}</span>' for m, mm in MEDIA.items() if mm.get('group') == 'regular')
    body = f'''<section class="wrap block"><div class="sec-head"><h1>시기별</h1><p>같은 시기에 매체마다 어떤 책을 골랐는지 — 달을 누르면 나란히 볼 수 있어요</p></div>
<div class="tl"><div class="tl-head"><span></span>{head}<span></span></div>{tl}</div></section>'''
    write('t/index.html', page(f'시기별 — {SITE["short"]}', body, 1, active='time'))

    for ym in months:
        up = '../../'
        cols = ''
        month_books = defaultdict(set)
        for r in c.recs:
            if r['month'] == ym and r['book'] and is_regular(r['media']):
                month_books[r['isbn']].add(r['media'])
        for m, mm in MEDIA.items():
            if mm.get('group') != 'regular':
                continue
            rs = sorted([r for r in c.recs if r['month'] == ym and r['media'] == m], key=lambda r: (r['weight'], r['date']))
            if not rs:
                continue
            seen, items = set(), ''
            for r in rs:
                k = r['isbn'] or r['item']['key']
                if k in seen:
                    continue
                seen.add(k)
                b = r['book']
                hot = ' hot' if b and len({fam(x) for x in month_books[r['isbn']]}) >= 2 else ''
                items += f'''<li class="{hot}">{f'<a href="{up}b/{b["isbn13"]}/">{cover(b, "cover xs")}</a>' if b else '<div class="cover xs nocover"></div>'}
<div><a href="{up}b/{b['isbn13']}/" class="t">{e(b['short'])}</a>''' if b else f'''<li>{'<div class="cover xs nocover"></div>'}<div><span class="t">{e(r['item']['title'])}</span>'''
                items += f'<small>{e(r["secKo"])}{(" · " + e(r["by"][0])) if r["by"] else ""}</small>{"".join(mchip(x) for x in sorted(month_books[r["isbn"]] - {m})) if hot else ""}</div></li>'
            issues = [i for i in c.issues if i['media'] == m and i['month'] == ym]
            cols += f'''<section class="mcol" style="--mc:{mm['color']}"><h2><a href="{up}m/{m}/">{e(mm['name'])}</a></h2>
<p class="muted small">{' · '.join(f'<a href="{up}{i["path"]}">{e(i.get("no") or "목록")}</a>' for i in issues)}</p><ol>{items}</ol></section>'''
        overlap = [c.books[i] for i, ms in month_books.items() if len({fam(x) for x in ms}) >= 2]
        i_ = months.index(ym)
        prev_m = months[i_ + 1] if i_ + 1 < len(months) else None
        next_m = months[i_ - 1] if i_ > 0 else None
        links = ''.join(f'<a href="{up}b/{b["isbn13"]}/">{e(b["short"])}</a>' for b in overlap)
        callout = f'<div class="callout"><b>이달 여러 매체가 함께 고른 책</b> {links}</div>' if overlap else ''
        body = f'''
<section class="wrap block">
  <div class="sec-head"><h1>{month_label(ym)}, 매체들이 고른 책</h1><p>{e(season_of(ym + '-15'))} · {sum(1 for r in c.recs if r['month'] == ym and is_regular(r['media']))}편의 추천</p>
  <span class="pager">{f'<a href="../{prev_m}/">← {month_label(prev_m)}</a>' if prev_m else ''}{f'<a href="../{next_m}/">{month_label(next_m)} →</a>' if next_m else ''}</span></div>
  {callout}
  <div class="mcols">{cols}</div>
</section>'''
        write(f't/{ym}/index.html', page(f'{month_label(ym)} 추천 도서 비교 — {SITE["short"]}', body, 2, active='time'))


def build_books(c):
    for b in c.books.values():
        up = '../../'
        toc, n_toc = toc_html(b.get('toc'))
        by_media = OrderedDict()
        for r in sorted(b['recs'], key=lambda r: (MEDIA[r['media']]['order'], r['date'])):
            by_media.setdefault(r['media'], []).append(r)
        recs_html = ''.join(rec_row(r, up) for r in sorted(b['recs'], key=lambda r: r['date']))
        details = [('출판사', b['publisher']), ('출간', ymd(b.get('pubDate'))), ('쪽수', f'{b["pages"]}쪽' if b.get('pages') else ''),
                   ('ISBN', '' if b['isbn13'].startswith('custom-') else b['isbn13']), ('원제', b.get('originalTitle')), ('시리즈', b.get('series')),
                   ('분야', ' › '.join((b.get('category') or '').split('>')[1:]))]
        dl = ''.join(f'<dt>{k}</dt><dd>{e(str(v))}</dd>' for k, v in details if v)
        # 같은 호에서 함께 추천된 책
        mates = []
        for r in b['recs']:
            for r2 in r['issue']['recs']:
                if r2['book'] and r2['isbn'] != b['isbn13'] and r2['book'] not in mates:
                    mates.append(r2['book'])
        mates_html = ''.join(f'<a class="mate" href="{up}b/{x["isbn13"]}/">{cover(x, "cover xs")}<span>{e(x["short"])}</span></a>' for x in mates[:10])
        intro = b.get('intro') or b.get('description') or ''
        summary_line = f'{len(b["outside"])}개 매체 · {len(b["recs"])}편의 추천' + (f' · {ymd(b["first"])[:9]} ~ {ymd(b["last"])[:9]}' if b['first'] != b['last'] else '')
        body = f'''
<div class="wrap crumbs"><a href="{up}">홈</a> › <a href="{up}{b['recs'][0]['issue']['path']}">{e(b['recs'][0]['issue']['title'])}</a></div>
<section class="wrap detail">
  <div class="detail-cover">{cover(b, big=True)}</div>
  <div class="detail-info">
    <div class="mchips">{media_dots(b)}</div>
    <h1>{e(b['short'])}</h1>
    {f'<p class="subtitle">{e(b["subTitle"])}</p>' if b.get('subTitle') else ''}
    <p class="meta">{e(b['author'])}</p>
    <dl class="facts">{dl}</dl>
    {nosale_box(b)}
    <div class="buybox"{' hidden' if b.get('noSale') else ''}>
      <div class="prices"><span>정가 <s>{won(b['priceStandard'])}</s></span><span class="now">C.books <b>{won(b['price'])}</b></span></div>
      <div class="qty" data-qty><button data-q="-1" aria-label="수량 빼기">−</button><input type="number" min="1" max="20" value="1" aria-label="수량"><button data-q="1" aria-label="수량 더하기">+</button></div>
      <div class="row">{add_btn(b, '장바구니 담기', 'btn add big')}<button class="btn primary big" data-buy="{b['isbn13']}">바로 주문</button></div>
      <p class="muted small">{e(SITE['store']['eta'])} 매장 픽업 또는 택배</p>
    </div>
  </div>
</section>

<section class="wrap block narrow">
  <div class="sec-head"><h2>이 책을 추천한 글</h2><p>{summary_line}</p></div>
  <div class="recs">{recs_html}</div>
</section>

<section class="wrap block narrow">
  <div class="tabs" role="tablist">
    <button class="tab on" data-tab="intro">책소개</button>
    {'<button class="tab" data-tab="toc">목차 <small>' + str(n_toc) + '</small></button>' if n_toc else ''}
  </div>
  <div class="tab-panel prose" data-panel="intro">{paras(intro) or '<p class="muted">소개 정보가 아직 없어요.</p>'}</div>
  {f'<div class="tab-panel" data-panel="toc" hidden>{toc}</div>' if n_toc else ''}
</section>

{f'<section class="wrap block"><div class="sec-head"><h2>같은 호에서 함께 추천된 책</h2></div><div class="mates">{mates_html}</div></section>' if mates else ''}
'''
        write(f'b/{b["isbn13"]}/index.html', page(f'{b["short"]} — {", ".join(MEDIA[m]["name"] for m in b["media"])} 추천 · {SITE["short"]}', body, 2,
                                                   desc=(b['recs'][0]['summary'] or b.get('description') or '')[:150], og_image=b.get('cover')))


def build_explore(c):
    """탐색: data/index.json 을 읽어 브라우저에서 조합 필터"""
    issues = {}
    for i in c.issues:
        issues[f'{i["media"]}/{i["id"]}'] = [i['path'], i.get('no') or (month_label(i['month']) if i['media'] != 'yong' else i['title'])]
    books = []
    for b in c.books.values():
        books.append({'i': b['isbn13'], 't': b['short'], 'a': first_author(b['author']), 'p': b['publisher'],
                      'c': b['thumb'], 'pr': b['price'], 'ps': b['priceStandard'], 'pd': (b.get('pubDate') or '')[:7],
                      'cat': ' '.join((b.get('category') or '').split('>')[1:3]),
                      'r': [[r['media'], r['issue']['id'], r['date'], r['section'], r['secKo'], ', '.join(r['by'][:2]), r['summary'][:120] or ('' if ROUNDUP.search(r['headline']) else r['headline'][:80])] for r in b['recs']]})
    data = {'media': {m: [mm['name'], mm['color']] for m, mm in MEDIA.items()}, 'groups': {k: v[2] for k, v in SECTIONS.items()},
            'issues': issues, 'books': books, 'months': c.months()}
    write('data/index.json', json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    months = c.months()
    opt = ''.join(f'<option value="{ym}">{ym.replace("-", ".")}</option>' for ym in months)
    opt_asc = ''.join(f'<option value="{ym}">{ym.replace("-", ".")}</option>' for ym in reversed(months))
    mchecks = ''.join(f'<label class="chk" style="--mc:{mm["color"]}"><input type="checkbox" name="m" value="{m}" checked> {e(mm["name"])}</label>' for m, mm in MEDIA.items())
    gchecks = ''.join(f'<label class="chk"><input type="checkbox" name="g" value="{g}" checked> {e(l)}</label>' for g, l in GROUPS)
    body = f'''
<section class="wrap block explore">
  <div class="sec-head"><h1>탐색</h1><p>매체 · 기간 · 코너 · 겹침을 조합해 보세요</p></div>
  <form id="xf" class="xf" onsubmit="return false">
    <div class="xf-row"><span class="xf-l">매체</span>{mchecks}</div>
    <div class="xf-row"><span class="xf-l">코너</span>{gchecks}</div>
    <div class="xf-row"><span class="xf-l">기간</span><select name="from" aria-label="시작">{opt_asc}</select> ~ <select name="to" aria-label="끝">{opt}</select>
      <span class="xf-l gap">겹침</span><select name="multi" aria-label="겹침"><option value="1">모든 책</option><option value="2">2개 매체 이상</option><option value="3">3개 매체 이상</option></select></div>
    <div class="xf-row"><input type="search" name="q" placeholder="제목 · 저자 · 출판사 · 추천자 검색" aria-label="검색">
      <select name="sort" aria-label="정렬"><option value="recent">최근 추천 순</option><option value="many">추천 많은 순</option><option value="title">제목 순</option><option value="pub">출간 순</option></select>
      <span class="seg"><button type="button" class="on" data-view="books">책</button><button type="button" data-view="recs">추천 글</button></span></div>
  </form>
  <p class="xcount" id="xcount"></p>
  <div id="xres" class="grid"></div>
  <div class="row center"><button class="btn" id="xmore" hidden>더 보기</button></div>
</section>
<script src="../assets/explore.js?v={VER}"></script>'''
    write('x/index.html', page(f'탐색 — {SITE["short"]}', body, 1, active='explore'))


def build_house(c):
    lists = [i for i in c.issues if i['media'] == 'yong']
    rows = ''.join(f'''<a class="house" href="{i['id']}/"><span class="kicker">{ymd(i['date'])} · {len(i['recs'])}권{(' · ' + e(i['curator'])) if i.get('curator') else ''}</span><b>{e(i['title'])}</b><p>{e(i.get('intro', ''))}</p>{strip([r['book'] for r in i['recs'] if r['book']], '../', 8).replace('<a ', '<span ').replace('</a>', '</span>')}</a>''' for i in lists)
    mm = MEDIA['yong']
    body = f'''
<section class="issue-hero" style="--mc:{mm['color']}"><div class="wrap">
  <p class="kicker">{e(mm['en'])}</p><h1>{e(mm['full'])}</h1><p class="sub">{e(mm['about'])}</p>
</div></section>
<section class="wrap block"><div class="houses">{rows or '<p class="muted">아직 목록이 없어요.</p>'}</div></section>'''
    write('y/index.html', page(f'C.books Curating - C.C — {SITE["short"]}', body, 1, active='yong'))


def build_cart():
    p = SITE['pricing']
    body = f'''
<section class="wrap block narrow cart-page">
  <div class="sec-head"><h1>장바구니</h1><p>담은 책을 확인하고 주문을 요청하세요</p></div>
  <div id="cart-empty" class="empty" hidden>
    <p>아직 담은 책이 없어요.</p><a class="btn primary" href="../">추천 도서 보러 가기</a>
  </div>
  <div id="cart-box" hidden>
    <ul id="cart-list" class="cart-list"></ul>
    <form id="order" class="order" novalidate>
      <div id="member-box" class="mbox" hidden><b>회원 주문</b> · <span id="member-benefit"></span>
        <label class="pts">적립금 사용 <small>(보유 <span id="member-points"></span>)</small><span class="row"><input name="points" type="number" min="0" step="100" value="0" inputmode="numeric"><button type="button" class="btn small" id="points-all">전액</button></span></label>
      </div>
      <p id="guest-box" class="mbox guest"><span id="guest-benefit">비회원으로도 주문할 수 있어요.</span></p>
      <fieldset>
        <legend>받는 방법</legend>
        <label class="opt"><input type="radio" name="ship" value="pickup" checked> <span><b>매장 픽업</b> · 무료<br><small>{e(SITE['store']['pickup'])}</small></span></label>
        <label class="opt"><input type="radio" name="ship" value="delivery"> <span><b>택배</b> · {won(p['shipping'])} <small>({won(p['freeShippingOver'])} 이상 무료)</small></span></label>
      </fieldset>
      <fieldset>
        <legend>주문하시는 분</legend>
        <label>이름<input name="name" id="o-name" required autocomplete="name"></label>
        <label>휴대폰<input name="phone" id="o-phone" required inputmode="tel" autocomplete="tel" placeholder="010-0000-0000"></label>
        <label>이메일 <small>(선택 · 주문 확인 메일)</small><input name="email" id="o-email" type="email" autocomplete="email"></label>
        <label class="hp" aria-hidden="true">웹사이트<input name="website" tabindex="-1" autocomplete="off"></label>
      </fieldset>
      <fieldset class="addr" hidden>
        <legend>받는 곳</legend>
        <label hidden>저장한 배송지<select id="addr-pick"></select></label>
        <div class="two"><label>받는 분<input name="recipient" autocomplete="shipping name" placeholder="주문자와 같으면 비워 두세요"></label>
        <label>받는 분 연락처<input name="recipient_phone" inputmode="tel" autocomplete="shipping tel" placeholder="010-0000-0000"></label></div>
        <label>우편번호 <small>(선택)</small><input name="zipcode" inputmode="numeric" autocomplete="shipping postal-code"></label>
        <label>주소<input name="address" id="o-address" autocomplete="shipping street-address" placeholder="도로명 주소"></label>
        <label>상세 주소<input name="address2" autocomplete="shipping address-line2" placeholder="동·호수 등"></label>
        <label class="agree member-only"><input type="checkbox" name="save_address"> 이 주소를 내 배송지로 저장</label>
      </fieldset>
      <fieldset>
        <label>요청사항 <small>(선택)</small><textarea name="note" id="o-note" rows="2" placeholder="선물 포장, 입고 연락 방법 등"></textarea></label>
      </fieldset>
      <div class="sum" id="sum"></div>
      <label class="agree"><input type="checkbox" name="agree" required> [비회원 필수] 주문 처리(입고 연락·결제 안내·배송)를 위해 이름·휴대폰·이메일·주소를 수집·이용하는 데 동의합니다. 주문 기록은 전자상거래법에 따라 5년간 보관합니다. <a href="../privacy/" target="_blank">개인정보 처리방침</a></label>
      <p class="muted small">{e(SITE['store']['eta'])} 입고가 확인되면 결제 안내를 문자로 보내 드립니다.</p>
      <button class="btn primary big wide" type="submit">주문 요청하기</button>
      <p class="muted small center">이미 주문하셨나요? <a href="../order/">비회원 주문 조회</a></p>
      <p class="demo-note" id="demo-note" hidden>지금은 미리보기(데모) 모드예요. 주문은 이 브라우저에만 저장되고 서점으로 전송되지 않습니다.</p>
    </form>
  </div>
  <div id="done" class="done" hidden></div>
</section>'''
    write('cart/index.html', page(f'장바구니 — {SITE["short"]}', body, 1, active='cart', page_id='cart'))


def build_member():
    """회원(로그인·가입·내 정보)·주문 조회·운영자·약관 페이지 — 동작은 assets/member.js"""
    B = e(SITE.get('brand', 'C.books'))
    biz = SITE.get('business', {})
    login = f'''
<section class="wrap block narrow auth" data-need-sb>
  <div class="sec-head"><h1>로그인 · 가입</h1><p>{B} 회원이 되면 주문 내역을 한곳에서 보고 적립 혜택을 받아요</p></div>
  <div class="auth-box">
    <button class="btn wide sns kakao" data-provider="kakao"><span>카카오로 계속하기</span></button>
    <button class="btn wide sns google" data-provider="google"><span>구글로 계속하기</span></button>
    <p class="muted small">처음이면 로그인 뒤 약관 동의와 이름·연락처 입력으로 가입이 끝나요. 비밀번호는 만들지 않아요.</p>
    <p class="small"><a href="../cart/">회원가입 없이 주문하기 →</a> · <a href="../order/">비회원 주문 조회</a></p>
  </div>
</section>'''
    write('login/index.html', page(f'로그인 — {B}', login, 1, active='me', page_id='login', noindex=True))

    join = f'''
<section class="wrap block narrow auth" data-need-sb>
  <div class="sec-head"><h1>가입 마무리</h1><p id="join-benefit"></p></div>
  <form id="join" class="order" hidden novalidate>
    <fieldset><legend>회원 정보</legend>
      <p class="small">로그인 계정 <b id="join-email"></b></p>
      <label>이름<input name="name" required autocomplete="name"></label>
      <label>휴대폰<input name="phone" required inputmode="tel" autocomplete="tel" placeholder="010-0000-0000"><small class="muted">입고·결제 안내 문자를 받을 번호</small></label>
    </fieldset>
    <fieldset class="consent"><legend>약관 동의</legend>
      <label class="all"><input type="checkbox" name="all"> <b>전체 동의</b> <small>(선택 항목 포함)</small></label>
      <label><input type="checkbox" name="terms"> [필수] 이용약관 <a href="../terms/" target="_blank">보기</a></label>
      <label><input type="checkbox" name="privacy"> [필수] 개인정보 수집·이용 <a href="../privacy/" target="_blank">보기</a></label>
      <table class="ctable"><tr><th>항목</th><td>이름, 휴대폰 번호, 이메일, 로그인 서비스 식별값, 배송지(입력 시), 주문·적립 기록</td></tr>
      <tr><th>목적</th><td>회원 식별, 주문 처리(입고 연락·결제 안내·배송), 적립금 관리, 고객 문의 응대</td></tr>
      <tr><th>보유 기간</th><td>탈퇴 시 즉시 삭제. 단 주문·결제·배송 기록은 전자상거래법에 따라 5년 보관</td></tr></table>
      <p class="muted small">동의를 거부할 수 있으나, 거부하면 회원 가입을 할 수 없어요(비회원 주문은 가능).</p>
      <label><input type="checkbox" name="age14"> [필수] 만 14세 이상입니다</label>
      <label><input type="checkbox" name="marketing_email"> [선택] 새 큐레이션·이벤트 소식 이메일 받기</label>
      <label><input type="checkbox" name="marketing_sms"> [선택] 새 큐레이션·이벤트 소식 문자 받기</label>
      <p class="muted small">선택 항목은 동의하지 않아도 가입할 수 있고, 내 정보에서 언제든 바꿀 수 있어요. 주문 안내 문자·메일은 수신 동의와 관계없이 보내 드려요.</p>
    </fieldset>
    <button class="btn primary big wide" type="submit">가입 완료</button>
    <button class="btn wide" type="button" id="join-cancel">가입하지 않기</button>
  </form>
</section>'''
    write('join/index.html', page(f'가입 — {B}', join, 1, active='me', page_id='join', noindex=True))

    me = f'''
<section class="wrap block narrow me" data-need-sb>
  <div id="me-box" hidden>
    <div class="sec-head"><h1 id="me-name"></h1><p id="me-sub" class="muted"></p></div>
    <div class="me-cards">
      <div class="me-card"><span class="kicker">적립금</span><b id="me-points" class="big"></b><p class="muted small" id="me-benefit"></p></div>
      <div class="me-card"><span class="kicker">바로가기</span><p><a href="../cart/">장바구니</a> · <a href="../">추천 도서</a></p><p id="me-admin" hidden><a href="../admin/">운영자 화면 →</a></p></div>
    </div>
    <h2>주문 내역</h2>
    <div id="me-orders" class="orders"><p class="muted">불러오는 중…</p></div>
    <h2>적립금 내역</h2>
    <ul id="me-ledger" class="ledger"></ul>
    <h2>배송지</h2>
    <ul id="me-addr" class="addr-list"></ul>
    <details class="addr-new"><summary>배송지 추가</summary>
      <form id="addr-form" class="order">
        <div class="two"><label>이름표<input name="label" placeholder="집, 회사…"></label><label>받는 분<input name="recipient"></label></div>
        <div class="two"><label>연락처<input name="phone" inputmode="tel"></label><label>우편번호<input name="zipcode" inputmode="numeric"></label></div>
        <label>주소<input name="address1"></label><label>상세 주소<input name="address2"></label>
        <button class="btn primary">저장</button>
      </form>
    </details>
    <h2>회원 정보</h2>
    <form id="profile" class="order"><div class="two"><label>이름<input name="name"></label><label>휴대폰<input name="phone" inputmode="tel"></label></div><button class="btn">저장</button></form>
    <form id="marketing" class="order consent"><label><input type="checkbox" name="email"> 새 큐레이션·이벤트 소식 이메일 받기</label><label><input type="checkbox" name="sms"> 새 큐레이션·이벤트 소식 문자 받기</label></form>
    <p class="row"><button class="btn" id="logout">로그아웃</button><button class="btn ghost" id="withdraw">회원 탈퇴</button></p>
  </div>
</section>'''
    write('me/index.html', page(f'내 정보 — {B}', me, 1, active='me', page_id='me', noindex=True))

    order = f'''
<section class="wrap block narrow" data-need-sb>
  <div class="sec-head"><h1>주문 조회</h1><p>비회원 주문은 주문번호와 휴대폰 번호로 확인해요</p></div>
  <p id="lookup-member" class="mbox" hidden>회원 주문은 <a href="../me/">내 정보 → 주문 내역</a>에서 볼 수 있어요.</p>
  <form id="lookup" class="order"><div class="two"><label>주문번호<input name="no" placeholder="QB-1003-XXXXX" autocomplete="off"></label><label>휴대폰<input name="phone" inputmode="tel" placeholder="010-0000-0000"></label></div><button class="btn primary">조회</button></form>
  <div id="lookup-out" class="orders"></div>
</section>'''
    write('order/index.html', page(f'주문 조회 — {B}', order, 1, page_id='order', noindex=True))

    admin = f'''
<section class="wrap block" data-need-sb>
  <div class="sec-head"><h1>주문 관리</h1><p>상태를 바꾸면 고객에게 안내 메일이 가고(이메일이 있을 때) 진행 기록이 남아요</p></div>
  <div id="adm" hidden>
    <p class="row"><select id="adm-filter"><option value="open">진행 중</option><option value="">전체</option><option value="requested">주문 접수</option><option value="stocked">입고 완료</option><option value="payment_requested">결제 안내</option><option value="paid">결제 완료</option><option value="shipped">발송</option><option value="ready_pickup">픽업 대기</option><option value="completed">수령 완료</option><option value="cancelled">취소</option></select> <span id="adm-count" class="muted"></span></p>
    <div id="adm-list" class="orders"></div>
  </div>
</section>'''
    write('admin/index.html', page(f'주문 관리 — {B}', admin, 1, page_id='admin', noindex=True))

    def biz_line():
        return ' · '.join(e(f'{k} {v}') for k, v in [('상호', biz.get('name')), ('대표', biz.get('owner')), ('사업자등록번호', biz.get('bizNo')),
                                                     ('통신판매업', biz.get('mailOrderNo')), ('주소', biz.get('address')), ('연락처', biz.get('phone')), ('이메일', biz.get('email'))])
    draft = '<p class="demo-note">초안입니다. 사업자 정보를 채우고, 운영 전에 내용을 한 번 검토해 주세요.</p>'
    terms = f'''
<article class="wrap block narrow legal">
  <h1>{B} 이용약관</h1>{draft}
  <p class="muted small">시행일 2026년 10월 3일</p>
  <h2>제1조 (목적)</h2><p>이 약관은 {e(biz.get('name'))}(이하 "서점")가 운영하는 {B}(이하 "서비스")에서 도서 주문과 회원 서비스를 이용하는 데 필요한 서점과 이용자의 권리·의무를 정합니다.</p>
  <h2>제2조 (회원 가입)</h2><p>이용자는 카카오 또는 구글 계정으로 로그인한 뒤 이 약관과 개인정보 수집·이용에 동의하고 이름·휴대폰 번호를 입력해 회원이 됩니다. 만 14세 미만은 가입할 수 없습니다.</p>
  <h2>제3조 (주문과 계약)</h2><p>서비스의 주문은 "주문 요청"입니다. 서점이 도매처 입고를 확인하고 결제 안내를 보낸 뒤 이용자가 결제하면 계약이 성립합니다. 품절·절판 등으로 입고되지 않으면 서점은 이를 알리고 주문을 취소할 수 있습니다.</p>
  <h2>제4조 (가격과 혜택)</h2><p>도서 가격은 「출판문화산업 진흥법」(도서정가제)에 따라 정가의 10% 이내에서 할인하며, 할인과 적립금을 합한 경제적 이익은 정가의 15%를 넘지 않습니다. 회원 혜택(적립률, 무료배송 기준 등)은 서비스에 표시된 내용을 따르며, 바뀌면 미리 알립니다.</p>
  <h2>제5조 (적립금)</h2><p>적립금은 주문한 책을 수령 완료한 때 쌓이며, 다음 주문에서 현금처럼 쓸 수 있습니다. 주문을 취소하면 사용한 적립금은 돌려드리고, 쌓인 적립금은 회수합니다. 탈퇴하면 남은 적립금은 사라집니다. 적립금은 현금으로 바꿀 수 없습니다.</p>
  <h2>제6조 (취소·교환·반품)</h2><p>입고 전에는 언제든 취소할 수 있습니다. 결제 후에는 「전자상거래 등에서의 소비자보호에 관한 법률」에 따라 책을 받은 날부터 7일 이내에 청약을 철회할 수 있습니다. 단, 이용자의 책임으로 책이 훼손된 경우 등 법에서 정한 경우는 제외합니다. 파손·오배송은 서점이 비용을 부담해 교환합니다.</p>
  <h2>제7조 (회원 탈퇴)</h2><p>회원은 내 정보 화면에서 언제든 탈퇴할 수 있으며, 서점은 개인정보 처리방침에 따라 정보를 처리합니다.</p>
  <h2>제8조 (책임과 분쟁)</h2><p>서점은 천재지변 등 불가항력으로 인한 손해에 책임지지 않습니다. 분쟁은 서점 소재지를 관할하는 법원을 따릅니다.</p>
  <p class="muted small">{biz_line()}</p>
</article>'''
    write('terms/index.html', page(f'이용약관 — {B}', terms, 1, page_id='terms'))

    privacy = f'''
<article class="wrap block narrow legal">
  <h1>{B} 개인정보 처리방침</h1>{draft}
  <p class="muted small">시행일 2026년 10월 3일</p>
  <h2>1. 수집하는 항목과 목적</h2>
  <table class="ctable"><tr><th>구분</th><th>항목</th><th>목적</th></tr>
  <tr><td>회원 가입</td><td>이름, 휴대폰 번호, 이메일, 로그인 서비스(카카오·구글) 식별값</td><td>회원 식별, 주문 안내, 적립금 관리</td></tr>
  <tr><td>주문(회원·비회원)</td><td>주문자 이름·휴대폰·이메일(선택), 받는 분·연락처·주소, 요청사항</td><td>입고 연락, 결제 안내, 배송·픽업</td></tr>
  <tr><td>마케팅(선택 동의)</td><td>이메일, 휴대폰 번호</td><td>새 큐레이션·이벤트 소식 안내</td></tr>
  <tr><td>자동 수집</td><td>로그인 기록, 접속 일시</td><td>부정 이용 방지, 서비스 안정성</td></tr></table>
  <h2>2. 보유 기간</h2><p>회원 정보는 탈퇴 시 바로 삭제합니다. 다만 관계 법령에 따라 다음 기록은 정해진 기간 보관합니다: 계약·청약철회 기록 5년, 대금 결제·재화 공급 기록 5년, 소비자 불만·분쟁 처리 기록 3년(전자상거래법), 접속 기록 3개월(통신비밀보호법). 비회원 주문 정보도 같은 기준을 따릅니다.</p>
  <h2>3. 제3자 제공</h2><p>서점은 개인정보를 제3자에게 제공하지 않습니다. 택배 발송 시에는 받는 분 이름·연락처·주소를 택배사에 전달합니다.</p>
  <h2>4. 처리 위탁</h2>
  <table class="ctable"><tr><th>받는 곳</th><th>위탁 업무</th></tr>
  <tr><td>Supabase Inc.</td><td>회원·주문 데이터 보관(클라우드 데이터베이스)</td></tr>
  <tr><td>Google LLC</td><td>주문 알림 메일 발송, 주문 관리 시트, 구글 로그인</td></tr>
  <tr><td>Kakao Corp.</td><td>카카오 로그인</td></tr>
  <tr><td>(택배사 입력)</td><td>도서 배송</td></tr></table>
  <p class="muted small">Supabase·Google 서버는 국외(미국 등)에 있을 수 있습니다. 이전 항목은 위 1의 항목이며, 서비스 이용 기간 동안 네트워크로 전송·보관됩니다.</p>
  <h2>5. 이용자의 권리</h2><p>이용자는 내 정보 화면에서 정보를 확인·수정하고, 마케팅 수신 동의를 철회하고, 탈퇴할 수 있습니다. 그 밖의 열람·정정·삭제·처리정지 요청은 아래 연락처로 해 주시면 지체 없이 처리합니다.</p>
  <h2>6. 안전성 확보 조치</h2><p>데이터베이스 접근 권한을 행 단위로 제한해 회원은 자기 정보만 볼 수 있게 하고, 운영자 계정만 주문 관리에 접근합니다. 전송 구간은 HTTPS로 암호화합니다.</p>
  <h2>7. 개인정보 보호책임자</h2><p>{e(biz.get('privacyOfficer'))} · {e(biz.get('email'))} · {e(biz.get('phone'))}</p>
  <p class="muted small">{biz_line()}</p>
</article>'''
    write('privacy/index.html', page(f'개인정보 처리방침 — {B}', privacy, 1, page_id='privacy'))


def build_redirects():
    """예전 주소 → 새 주소"""
    for old, new in {'s/emmaus-28/index.html': '../../i/emmaus/2026-09/', 's/index.html': '../m/'}.items():
        write(old, f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={new}"><link rel="canonical" href="{new}"><a href="{new}">이동</a>')


def share_links(rel, text):
    """공유 빌드: 상대 폴더 링크(…/)를 …/index.html 로, 홈은 문서 뼈대 없이(아티팩트가 감쌈)"""
    def fix(m):
        h = m.group(1)
        if h.startswith(('http', '#', 'mailto:')) or not (h == '' or h.endswith('/')):
            return m.group(0)
        return f'href="{h}index.html"'
    text = re.sub(r'href="([^"]*)"', fix, text)
    if rel == 'index.html':
        text = text.replace('<!doctype html>\n<html lang="ko">\n<head>\n', '').replace('</head>\n', '')
        text = re.sub(r'<body[^>]*>\n', '', text).replace('</body>\n</html>\n', '')
    return text


def write(rel, text):
    if SHARE and rel.endswith('.html'):
        text = share_links(rel, text)
    p = os.path.join(DIST, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)


def main():
    c = Catalog()
    if os.path.exists(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    shutil.copytree(os.path.join(SITE_DIR, 'assets'), os.path.join(DIST, 'assets'))
    build_home(c)
    build_media(c)
    build_issues(c)
    build_time(c)
    build_books(c)
    build_explore(c)
    build_house(c)
    build_member()
    build_cart()
    build_redirects()
    cat = {i: {'isbn13': i, 'title': b['short'], 'author': b['author'], 'publisher': b['publisher'],
               'priceStandard': b['priceStandard'], 'price': b['price'], 'cover': b['thumb'],
               'recs': [f'{r["mname"]} {r["secKo"]}' for r in b['recs'][:3]]}
           for i, b in c.books.items() if not b.get('noSale')}
    write('data/catalog.json', json.dumps(cat, ensure_ascii=False, separators=(',', ':')))
    open(os.path.join(DIST, '.nojekyll'), 'w').close()
    nohit = sum(1 for r in c.recs if not r['book'])
    nosum = sum(1 for r in c.recs if not r['summary'])
    print(f'✓ {os.path.basename(DIST)}/ — 호 {len(c.issues)}개, 추천 {len(c.recs)}편, 도서 {len(c.books)}권 (도서 미연결 {nohit}편, 요약 대기 {nosum}편)')
    if '--serve' in sys.argv:
        import functools
        import http.server
        port = 8810
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIST)
        print(f'  http://localhost:{port}')
        http.server.ThreadingHTTPServer(('127.0.0.1', port), handler).serve_forever()


if __name__ == '__main__':
    main()
