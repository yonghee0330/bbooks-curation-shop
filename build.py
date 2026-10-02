#!/usr/bin/env python3
"""비북스 큐레이션 서점 빌드 — data/(소스 + 알라딘 캐시) → dist/ 정적 사이트

  python3 fetch.py            # 먼저: 추천 목록의 책 정보·표지·목차 수집 (캐시)
  python3 build.py            # dist/ 생성
  python3 build.py --serve    # 생성 후 http://localhost:8810 미리보기
  python3 build.py --pages    # GitHub Pages용 docs/ 생성 → commit · push 하면 배포

출력
  dist/index.html                 홈 — 이번 달 매체 추천, 전체 추천 도서(필터)
  dist/s/<source-id>/index.html   매체 호별 페이지 (코너별 정리, 한 번에 담기)
  dist/b/<isbn13>/index.html      도서 상세 — 표지·가격·추천 글·책소개·목차
  dist/cart/index.html            장바구니 · 주문 요청
  dist/data/catalog.json          카트·외부 도구용 공개 데이터
  dist/covers/<isbn13>.jpg

새 매체/새 호 추가: data/sources/<id>.json 하나 만들고(형식은 emmaus-28.json 참고),
매체 정보는 data/site.json "media" 에 추가 → fetch.py → build.py.
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
SITE_DIR = os.path.join(ROOT, 'site')
SHARE = '--share' in sys.argv  # 공유용(클로드 아티팩트): 폴더 주소 대신 index.html, 허용된 폰트만 → share/
PAGES = '--pages' in sys.argv  # GitHub Pages 배포용 → docs/ (main 브랜치 /docs 에서 서빙)
DIST = os.path.join(ROOT, 'share' if SHARE else 'docs' if PAGES else 'dist')
VER = datetime.now().strftime('%m%d%H%M')

SITE = json.load(open(os.path.join(DATA, 'site.json'), encoding='utf-8'))
SECTION_RANK = {'pick': 1, 'mention': 2, 'editor': 3, 'special': 4, 'preview': 5, 'person': 6, 'related': 9}
SECTION_KO = {'pick': '이달의 책', 'mention': '이달의 책 두 번째', 'editor': '기획위원 Pick',
              'special': '특별 기고', 'preview': '신간 프리뷰', 'person': '인물 여백', 'related': '함께 읽기'}

e = html.escape


def won(n):
    return f'{int(n):,}원'


def sale_price(std):
    rate = float(SITE['pricing'].get('discountRate') or 0)
    return int(math.floor(std * (1 - rate) / 10) * 10)


def short_title(t):
    """알라딘 제목 '본제 - 부제' → 본제"""
    return re.split(r'\s+-\s+', t, maxsplit=1)[0].strip()


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
        cls = ''
        if re.match(r'^(제\s*\d+\s*부|\d+\s*부[\s.:]|Part\s|PART\s|[1-9]부$|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s])', ln) or re.match(r'^(서론|결론|들어가며|나가며|머리말|맺음말|프롤로그|에필로그|부록)', ln):
            cls = ' class="part"'
        items.append(f'<li{cls}>{e(ln)}</li>')
    return '<ol class="toc">' + ''.join(items) + '</ol>', len(lines)


# ───────────────────────── 데이터 모으기 ─────────────────────────

def load_catalog():
    sources, books = [], {}
    for fn in sorted(os.listdir(os.path.join(DATA, 'sources'))):
        if not fn.endswith('.json'):
            continue
        src = json.load(open(os.path.join(DATA, 'sources', fn), encoding='utf-8'))
        media = SITE['media'][src['media']]
        src['mediaInfo'] = media
        src['bookIds'] = []
        for b in src['books']:
            isbn = b.get('isbn13')
            cp = os.path.join(DATA, 'cache', 'books', f'{isbn}.json')
            if not isbn or not os.path.exists(cp):
                print('  (건너뜀: 정보 없음)', b['title'])
                continue
            info = books.get(isbn)
            if not info:
                info = json.load(open(cp, encoding='utf-8'))
                info['recs'] = []
                info['short'] = short_title(info['title'])
                main, _, sub = info['title'].partition(' - ')
                info['subTitle'] = info.get('subTitle') or sub.strip()
                info['price'] = sale_price(info['priceStandard'])
                info['hasCover'] = os.path.exists(os.path.join(DATA, 'cache', 'covers', f'{isbn}.jpg'))
                books[isbn] = info
            for r in b['recs']:
                info['recs'].append({**r, 'source': src['id'], 'media': src['media'], 'mediaName': media['name'],
                                     'issue': src['issue'], 'issueTitle': src['title'],
                                     'sectionKo': r.get('label') and SECTION_KO.get(r['section'], r['label']) or SECTION_KO.get(r['section'], r['section']),
                                     'roles': [src.get('editors', {}).get(n, '') for n in r['by']]})
            src['bookIds'].append(isbn)
        sources.append(src)
    for b in books.values():
        b['recs'].sort(key=lambda r: SECTION_RANK.get(r['section'], 8))
        b['rank'] = min((SECTION_RANK.get(r['section'], 8) for r in b['recs']), default=9)
        b['voices'] = len({n for r in b['recs'] for n in r['by'] if not n.endswith('편집부')})
    sources.sort(key=lambda s: s['issueDate'], reverse=True)
    return sources, books


# ───────────────────────── 템플릿 ─────────────────────────

def page(title, body, depth, desc='', og_image=None, active=''):
    up = '../' * depth
    desc = desc or SITE['intro']
    nav = [('', '추천 도서', 'home'), ('s/', '매체별', 'media'), ('cart/', '장바구니', 'cart')]
    navh = ''.join(
        f'<a href="{up}{href}" class="{"on" if key == active else ""}"{" data-cart-link" if key == "cart" else ""}>{label}{"<b class=cart-n data-cart-count></b>" if key == "cart" else ""}</a>'
        for href, label, key in nav)
    og = f'<meta property="og:image" content="{e(og_image)}">' if og_image else ''
    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc[:160])}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc[:160])}">
{og}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Gowun+Batang:wght@400;700&family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,650;1,9..144,400&display=swap">
{'' if SHARE else '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css">'}
<link rel="stylesheet" href="{up}assets/app.css?v={VER}">
</head>
<body>
<header class="top">
  <div class="wrap top-in">
    <a class="logo" href="{up}"><span class="logo-mark">b</span><span><b>{e(SITE['short'])}</b><small>{e(SITE['tagline'])}</small></span></a>
    <nav>{navh}</nav>
  </div>
</header>
<main>
{body}
</main>
<footer class="foot">
  <div class="wrap">
    <p><b>{e(SITE['name'])}</b> · {e(SITE['store']['address'])} · <a href="{SITE['store']['instagram']}" target="_blank" rel="noopener">@bbooks_bucheon</a></p>
    <p class="muted">추천 글 요약은 비북스가 각 매체의 글을 읽고 다시 쓴 것입니다. 원문은 해당 매체에서 구독해 읽어 주세요. 도서 정보·표지·목차 제공: 알라딘.</p>
  </div>
</footer>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script>window.SHOP={json.dumps({'apiUrl': SITE['apiUrl'], 'pricing': SITE['pricing'], 'pickup': SITE['store']['pickup'], 'eta': SITE['store']['eta'], 'root': up, 'idx': 'index.html' if SHARE else ''}, ensure_ascii=False)};</script>
<script src="{up}assets/app.js?v={VER}"></script>
</body>
</html>
'''


def cover(b, up, cls='cover'):
    if b['hasCover']:
        return f'<img class="{cls}" src="{up}covers/{b["isbn13"]}.jpg" alt="{e(b["short"])} 표지" loading="lazy">'
    return f'<div class="{cls} nocover"><span>{e(b["short"])}</span></div>'


def add_btn(b, label='담기', cls='btn add'):
    return f'<button class="{cls}" data-add="{b["isbn13"]}">{label}</button>'


def badges(b):
    seen, out = set(), []
    for r in b['recs']:
        k = (r['media'], r['section'])
        if k in seen:
            continue
        seen.add(k)
        out.append(f'<span class="badge s-{r["section"]}">{e(r["mediaName"])} · {e(r["sectionKo"])}</span>')
    return ''.join(out[:3])


def book_card(b, up, src_id=None):
    recs = [r for r in b['recs'] if not src_id or r['source'] == src_id]
    lead = recs[0] if recs else b['recs'][0]
    who = ', '.join(lead['by'])
    sections = ' '.join(sorted({r['section'] for r in b['recs']}))
    first_author = re.sub(r'\s*\([^)]*\)', '', b['author'].split(',')[0])
    return f'''<article class="card" data-sections="{sections}" data-media="{' '.join(sorted({r['media'] for r in b['recs']}))}">
  <a class="card-cover" href="{up}b/{b['isbn13']}/">{cover(b, up)}</a>
  <div class="card-body">
    <div class="badges">{badges(b)}</div>
    <h3><a href="{up}b/{b['isbn13']}/">{e(b['short'])}</a></h3>
    <p class="meta">{e(first_author)} · {e(b['publisher'])}</p>
    <p class="why">{e(lead['summary'][:96])}{'…' if len(lead['summary']) > 96 else ''}</p>
    <p class="by">— {e(who)}{' 외' if b['voices'] > len(lead['by']) else ''}</p>
    <div class="card-foot">
      <span class="price"><s>{won(b['priceStandard'])}</s> <b>{won(b['price'])}</b></span>
      {add_btn(b)}
    </div>
  </div>
</article>'''


def rec_block(r, up):
    people = ' · '.join(
        f'<b>{e(n)}</b>' + (f' <span class="roles">{e(role)}</span>' if role and len(r['by']) <= 2 else '')
        for n, role in zip(r['by'], r['roles']))
    field = f' · {e(r["field"])}' if r.get('field') else ''
    return f'''<article class="rec s-{r['section']}">
  <header><span class="badge s-{r['section']}">{e(r['sectionKo'])}{field}</span>
  <a class="rec-src" href="{up}s/{r['source']}/">{e(r['mediaName'])} {e(r['issue'])} · p.{r.get('page', '')}</a></header>
  <p>{e(r['summary'])}</p>
  <footer>{people}</footer>
</article>'''


# ───────────────────────── 페이지들 ─────────────────────────

def build_home(sources, books):
    up = ''
    latest = sources[0]
    m = latest['mediaInfo']
    feat = [books[i] for i in latest['bookIds'] if books[i]['rank'] <= 2]
    feat_html = ''
    for b in feat:
        r = b['recs'][0]
        feat_html += f'''<article class="feature">
  <a href="b/{b['isbn13']}/" class="feature-cover">{cover(b, up)}</a>
  <div>
    <span class="badge s-{r['section']}">{e(m['name'])} · {e(r['sectionKo'])}</span>
    <h3><a href="b/{b['isbn13']}/">{e(b['short'])}</a></h3>
    <p class="meta">{e(b['author'])}<br>{e(b['publisher'])} · {b['pubDate'][:7].replace('-', '.')}</p>
    <p class="why">{e(r['summary'])}</p>
    <p class="by">— {e(', '.join(r['by']))}</p>
    <div class="row"><span class="price"><s>{won(b['priceStandard'])}</s> <b>{won(b['price'])}</b></span>{add_btn(b, '장바구니에 담기')}</div>
  </div>
</article>'''
    all_books = sorted(books.values(), key=lambda b: (b['rank'], -b['voices'], b['short']))
    chips = [('all', '전체'), ('pick mention', '이달의 책'), ('editor', '기획위원 Pick'), ('preview', '신간 프리뷰'), ('person related', '인물·함께 읽기')]
    chip_html = ''.join(f'<button class="chip{" on" if i == 0 else ""}" data-filter="{k}">{l}</button>' for i, (k, l) in enumerate(chips))
    grid = '\n'.join(book_card(b, up) for b in all_books)
    issue_ids = json.dumps([i for i in latest['bookIds'] if books[i]['rank'] < 9])
    body = f'''
<section class="hero">
  <div class="wrap hero-in">
    <div class="hero-txt">
      <p class="kicker">{e(m['kind'])} 큐레이션 · {e(latest['issueDate'].replace('-', '. '))}</p>
      <h1>{e(m['name'])}가 고른<br>이달의 책들</h1>
      <p class="lead">{e(latest['theme'])}</p>
      <p class="sub">{e(SITE['intro'])}</p>
      <div class="row">
        <button class="btn primary" data-add-many='{issue_ids}'>이번 호 추천 도서 {len(json.loads(issue_ids))}권 모두 담기</button>
        <a class="btn ghost" href="s/{latest['id']}/">{e(latest['title'])} 펼쳐 보기 →</a>
      </div>
    </div>
    <a class="mag" href="s/{latest['id']}/" style="--mc:{m['color']}">
      <span class="mag-en">{e(m['en'])}</span>
      <span class="mag-ko">{e(m['full'])}</span>
      <span class="mag-no">{e(latest['issue'])}</span>
      <span class="mag-date">{e(latest['issueDate'].replace('-', '. '))}</span>
      <span class="mag-stack">{''.join(f'<i style="background-image:url(covers/{i}.jpg)"></i>' for i in latest['bookIds'][:5] if books[i]['hasCover'])}</span>
    </a>
  </div>
</section>

<section class="wrap block">
  <div class="sec-head"><h2>이달의 책</h2><p>{e(m['name'])} 기획위원들이 함께 고른 {len(feat)}권</p></div>
  <div class="features">{feat_html}</div>
</section>

<section class="wrap block" id="all">
  <div class="sec-head"><h2>추천 도서 전체</h2><p>매체가 추천한 {len(all_books)}권 · 추천이 겹친 책부터</p></div>
  <div class="chips" role="tablist">{chip_html}</div>
  <div class="grid" id="grid">{grid}</div>
</section>

<section class="wrap block media-list">
  <div class="sec-head"><h2>함께 읽는 매체</h2><p>추천 목록을 가져오는 곳</p></div>
  {''.join(f"""<div class="media-card" style="--mc:{mm['color']}"><div><b>{e(mm['full'])}</b><span>{e(mm['kind'])} · {e(mm['cadence'])}</span><p>{e(mm['about'])}</p></div><a class="btn ghost" href="{mm['subscribe']}" target="_blank" rel="noopener">구독하기</a></div>""" for mm in SITE['media'].values())}
  <p class="muted small">다음 매체를 준비하고 있어요. 추천하고 싶은 서평지·뉴스레터가 있으면 매장이나 인스타그램으로 알려 주세요.</p>
</section>
'''
    write('index.html', page(f'{SITE["name"]} — {m["name"]} {latest["issue"]} 추천 도서', body, 0, active='home'))


def build_sources(sources, books):
    idx = ''
    for src in sources:
        m = src['mediaInfo']
        up = '../../'
        groups = []
        for sec in sorted(src['sections'], key=lambda s: s['rank']):
            items = []
            for isbn in src['bookIds']:
                b = books[isbn]
                rs = [r for r in b['recs'] if r['source'] == src['id'] and r['section'] == sec['key']]
                for r in rs:
                    items.append((b, r))
            if sec['key'] == 'editor':
                items.sort(key=lambda x: ['구약', '신약', '신학', '신앙'].index(x[1].get('field', '신앙')) if x[1].get('field') in ['구약', '신약', '신학', '신앙'] else 9)
            if not items:
                continue
            rows = ''.join(f'''<article class="issue-row">
  <a href="{up}b/{b['isbn13']}/">{cover(b, up, 'cover sm')}</a>
  <div>
    <p class="eyebrow">{e(r.get('field', '') or '')}{' · ' if r.get('field') else ''}p.{r.get('page', '')}</p>
    <h3><a href="{up}b/{b['isbn13']}/">{e(b['short'])}</a></h3>
    <p class="meta">{e(b['author'])} · {e(b['publisher'])}</p>
    <p class="why">{e(r['summary'])}</p>
    <p class="by">— {e(', '.join(r['by']))}</p>
  </div>
  <div class="issue-buy"><span class="price"><s>{won(b['priceStandard'])}</s><b>{won(b['price'])}</b></span>{add_btn(b)}</div>
</article>''' for b, r in items)
            groups.append(f'<section class="issue-sec s-{sec["key"]}"><div class="issue-sec-head"><span>{e(sec["label"])}</span><h2>{e(sec["ko"])}</h2></div>{rows}</section>')
        ids = json.dumps([i for i in src['bookIds'] if books[i]['rank'] < 9])
        total = sum(books[i]['price'] for i in json.loads(ids))
        body = f'''
<section class="issue-hero" style="--mc:{m['color']}">
  <div class="wrap">
    <p class="kicker">{e(m['en'])} · {e(src['issue'])}</p>
    <h1>{e(src['title'])}</h1>
    <p class="lead">{e(src['coverage'])}을 다룬 호 · {e(src['theme'])}</p>
    <p class="sub">{e(m['about'])}</p>
    <div class="row">
      <button class="btn primary" data-add-many='{ids}'>추천 도서 {len(json.loads(ids))}권 모두 담기 · {won(total)}</button>
      <a class="btn ghost light" href="{m['subscribe']}" target="_blank" rel="noopener">{e(m['name'])} 무료 구독 ↗</a>
    </div>
  </div>
</section>
<div class="wrap issue">{''.join(groups)}</div>'''
        write(f's/{src["id"]}/index.html', page(f'{src["title"]} 추천 도서 — {SITE["short"]}', body, 2, desc=src['theme'], active='media'))
        idx += f'''<a class="media-issue" href="{src['id']}/" style="--mc:{m['color']}"><span class="mag-en">{e(m['en'])}</span><b>{e(src['title'])}</b><span>{e(src['theme'])}</span><small>{len(src['bookIds'])}권</small></a>'''
    body = f'<section class="wrap block"><div class="sec-head"><h1>매체별 추천</h1><p>서평지·뉴스레터의 호마다 고른 책</p></div><div class="issues">{idx}</div></section>'
    write('s/index.html', page(f'매체별 추천 — {SITE["short"]}', body, 1, active='media'))


def build_books(sources, books):
    for b in books.values():
        up = '../../'
        toc, n_toc = toc_html(b['toc'])
        recs = ''.join(rec_block(r, up) for r in b['recs'])
        details = [('출판사', b['publisher']), ('출간', (b['pubDate'] or '').replace('-', '. ')),
                   ('쪽수', f'{b["pages"]}쪽' if b.get('pages') else ''), ('ISBN', b['isbn13']),
                   ('원제', b.get('originalTitle')), ('시리즈', b.get('series')),
                   ('분야', ' › '.join((b.get('category') or '').split('>')[1:]))]
        dl = ''.join(f'<dt>{k}</dt><dd>{e(str(v))}</dd>' for k, v in details if v)
        # 같은 호에서 함께 추천된 책
        srcs = {r['source'] for r in b['recs']}
        mates = [books[i] for s in sources if s['id'] in srcs for i in s['bookIds'] if i != b['isbn13']][:8]
        mates_html = ''.join(f'<a class="mate" href="{up}b/{x["isbn13"]}/">{cover(x, up, "cover xs")}<span>{e(x["short"])}</span></a>' for x in mates)
        intro = b.get('intro') or b.get('description') or ''
        aladin = f'<a class="muted small" href="{e(b["link"])}" target="_blank" rel="noopener">알라딘에서 보기 ↗</a>' if SITE.get('aladinLink') else ''
        body = f'''
<div class="wrap crumbs"><a href="{up}">추천 도서</a> › <a href="{up}s/{b['recs'][0]['source']}/">{e(b['recs'][0]['issueTitle'])}</a></div>
<section class="wrap detail">
  <div class="detail-cover">{cover(b, up)}</div>
  <div class="detail-info">
    <div class="badges">{badges(b)}</div>
    <h1>{e(b['short'])}</h1>
    {f'<p class="subtitle">{e(b["subTitle"])}</p>' if b.get('subTitle') else ''}
    <p class="meta">{e(b['author'])}</p>
    <dl class="facts">{dl}</dl>
    <div class="buybox">
      <div class="prices"><span>정가 <s>{won(b['priceStandard'])}</s></span><span class="now">비북스 <b>{won(b['price'])}</b></span></div>
      <div class="qty" data-qty><button data-q="-1" aria-label="수량 빼기">−</button><input type="number" min="1" max="20" value="1" aria-label="수량"><button data-q="1" aria-label="수량 더하기">+</button></div>
      <div class="row">{add_btn(b, '장바구니 담기', 'btn add big')}<button class="btn primary big" data-buy="{b['isbn13']}">바로 주문</button></div>
      <p class="muted small">{e(SITE['store']['eta'])} 매장 픽업 또는 택배</p>
      {aladin}
    </div>
  </div>
</section>

<section class="wrap block narrow">
  <div class="sec-head"><h2>이 책을 추천한 글</h2><p>{len(b['recs'])}편 · {b['voices']}명의 추천</p></div>
  <div class="recs">{recs}</div>
</section>

<section class="wrap block narrow tabs-wrap">
  <div class="tabs" role="tablist">
    <button class="tab on" data-tab="intro">책소개</button>
    {'<button class="tab" data-tab="toc">목차 <small>' + str(n_toc) + '</small></button>' if n_toc else ''}
  </div>
  <div class="tab-panel prose" data-panel="intro">{paras(intro)}</div>
  {f'<div class="tab-panel" data-panel="toc" hidden>{toc}</div>' if n_toc else ''}
</section>

{f'<section class="wrap block"><div class="sec-head"><h2>같은 호에서 함께 추천된 책</h2></div><div class="mates">{mates_html}</div></section>' if mates else ''}
'''
        og = None
        write(f'b/{b["isbn13"]}/index.html', page(f'{b["short"]} — {b["recs"][0]["mediaName"]} 추천 · {SITE["short"]}', body, 2,
                                                   desc=b['recs'][0]['summary'], og_image=og))


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
      <fieldset>
        <legend>받는 방법</legend>
        <label class="opt"><input type="radio" name="ship" value="pickup" checked> <span><b>매장 픽업</b> · 무료<br><small>{e(SITE['store']['pickup'])}</small></span></label>
        <label class="opt"><input type="radio" name="ship" value="delivery"> <span><b>택배</b> · {won(p['shipping'])} <small>({won(p['freeShippingOver'])} 이상 무료)</small></span></label>
      </fieldset>
      <fieldset>
        <legend>주문하시는 분</legend>
        <label>이름<input name="name" required autocomplete="name"></label>
        <label>휴대폰<input name="phone" required inputmode="tel" autocomplete="tel" placeholder="010-0000-0000"></label>
        <label>이메일 <small>(선택)</small><input name="email" type="email" autocomplete="email"></label>
        <label class="addr" hidden>받을 주소<input name="address" autocomplete="street-address" placeholder="도로명 주소, 상세 주소"></label>
        <label>요청사항 <small>(선택)</small><textarea name="note" rows="2" placeholder="선물 포장, 입고 연락 방법 등"></textarea></label>
      </fieldset>
      <div class="sum" id="sum"></div>
      <label class="agree"><input type="checkbox" name="agree" required> 주문 처리(입고·연락·배송)를 위해 이름·연락처·주소를 수집하고, 주문 완료 후 1년간 보관하는 데 동의합니다.</label>
      <p class="muted small">{e(SITE['store']['eta'])} 입고가 확인되면 결제 안내를 문자로 보내 드립니다.</p>
      <button class="btn primary big wide" type="submit">주문 요청하기</button>
      <p class="demo-note" id="demo-note" hidden>지금은 미리보기(데모) 모드예요. 주문은 이 브라우저에만 저장되고 서점으로 전송되지 않습니다.</p>
    </form>
  </div>
  <div id="done" class="done" hidden></div>
</section>'''
    write('cart/index.html', page(f'장바구니 — {SITE["short"]}', body, 1, active='cart'))


def share_links(rel, text):
    """공유 빌드: 상대 폴더 링크(…/)를 …/index.html 로, 홈 페이지는 문서 뼈대 없이(아티팩트가 감쌈)"""
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
    sources, books = load_catalog()
    if os.path.exists(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    shutil.copytree(os.path.join(SITE_DIR, 'assets'), os.path.join(DIST, 'assets'))
    os.makedirs(os.path.join(DIST, 'covers'))
    for isbn, b in books.items():
        if b['hasCover']:
            shutil.copy(os.path.join(DATA, 'cache', 'covers', f'{isbn}.jpg'), os.path.join(DIST, 'covers', f'{isbn}.jpg'))
    build_home(sources, books)
    build_sources(sources, books)
    build_books(sources, books)
    build_cart()
    cat = {i: {'isbn13': i, 'title': b['short'], 'author': b['author'], 'publisher': b['publisher'],
               'priceStandard': b['priceStandard'], 'price': b['price'], 'cover': f'covers/{i}.jpg' if b['hasCover'] else '',
               'recs': [f'{r["mediaName"]} {r["issue"]} {r["sectionKo"]}' for r in b['recs']]}
           for i, b in books.items()}
    write('data/catalog.json', json.dumps(cat, ensure_ascii=False))
    open(os.path.join(DIST, '.nojekyll'), 'w').close()
    print(f'✓ {os.path.basename(DIST)}/ — 매체 {len(sources)}호, 도서 {len(books)}권')
    if '--serve' in sys.argv:
        import functools
        import http.server
        port = 8810
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIST)
        print(f'  http://localhost:{port}')
        http.server.ThreadingHTTPServer(('127.0.0.1', port), handler).serve_forever()


if __name__ == '__main__':
    main()
