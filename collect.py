#!/usr/bin/env python3
"""매체별 추천 도서 수집 — 새 호/새 글만 찾아 data/issues/<매체>/<호>.json 에 쌓는다.

  python3 collect.py                  # 모든 매체, 새 것만
  python3 collect.py teum newsnjoy    # 일부 매체만
  python3 collect.py --since 2025-01  # 수집 시작 시점 (기본: data/media.json 의 since)

원칙
- 이미 있는 항목의 summary(비북스 요약)·isbn13 등 손으로 고친 값은 절대 덮어쓰지 않는다.
- 원문 텍스트는 요약 작성용으로 data/raw/ 에만 저장 (공개 저장소에 올리지 않음, .gitignore).
- 사이트별 간격 3초 이상. 엠마오 PDF는 data/raw/emmaus/pdf/ 에 보관.

매체
  emmaus     그리스도교 서평지 엠마오 (stibee 아카이브 → Dropbox PDF)        호 단위
  teum       청어람ARMC 뉴스레터 틈 (maily.so/secularsaints)                   호 단위
  goscon     복음과상황 〈서사의 서사〉 (기사 메타 '리뷰 > 서사의 서사')        호 단위
  newsnjoy   뉴스앤조이 [1일1책]                                               월 단위로 묶음
  cbooknews  크리스찬북뉴스 편집자추천도서 · 베스트서평                         월 단위로 묶음
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, 'data')
ISSUES = os.path.join(DATA, 'issues')
RAW = os.path.join(DATA, 'raw')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
MEDIA = json.load(open(os.path.join(DATA, 'media.json'), encoding='utf-8'))
_last = {}
LOG = []
RETRY = '--retry' in sys.argv  # 책을 못 찾았던 글 다시 보기


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


# ───────────────────────── 공통 ─────────────────────────

def get(url, gap=3.0, binary=False, referer=None):
    host = urllib.parse.urlparse(url).netloc
    wait = gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    headers = {'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9', 'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}
    if referer:
        headers['Referer'] = referer
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as r:
                body = r.read()
            _last[host] = time.time()
            if binary:
                return body
            for enc in ('utf-8', 'cp949'):
                try:
                    return body.decode(enc)
                except UnicodeDecodeError:
                    pass
            return body.decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            _last[host] = time.time()
            if e.code == 404:
                return None
            if attempt == 2:
                log('   ! 실패', url[:100], e)
                return None
        except Exception as e:  # noqa: BLE001
            _last[host] = time.time()
            if attempt == 2:
                log('   ! 실패', url[:100], e)
                return None
        time.sleep(5 * (attempt + 1))


def text_of(fragment):
    t = re.sub(r'(?is)<(script|style).*?</\1>', '', fragment or '')
    t = re.sub(r'(?i)<br\s*/?>|</p>|</li>|</div>|</h\d>', '\n', t)
    t = html.unescape(re.sub(r'<[^>]+>', '', t)).replace('\xa0', ' ').replace('​', '')
    lines = [re.sub(r'[ \t]+', ' ', x).strip() for x in t.split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def meta(t, prop):
    m = re.search(r'<meta (?:property|name)="%s" content="([^"]*)"' % re.escape(prop), t)
    return html.unescape(m.group(1)).strip() if m else ''


def norm(s):
    return re.sub(r'[^0-9a-z가-힣]', '', (s or '').lower())


def item_key(title, publisher=''):
    return (norm(title)[:24] + '-' + norm(publisher)[:10]).strip('-')


def season_of(d):
    y, m = int(d[:4]), int(d[5:7])
    if m in (12, 1, 2):
        return f'{y if m == 12 else y - 1} 겨울'
    return f'{y} ' + ('봄' if m <= 5 else '여름' if m <= 8 else '가을')


def issue_path(media, iid):
    return os.path.join(ISSUES, media, f'{iid}.json')


def load_issue(media, iid):
    p = issue_path(media, iid)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None


def save_issue(issue):
    """기존 항목의 손댄 값(summary, isbn13, by, section …)은 보존하고 새 항목만 추가"""
    os.makedirs(os.path.join(ISSUES, issue['media']), exist_ok=True)
    old = load_issue(issue['media'], issue['id'])
    if old:
        keep = {it['key']: it for it in old.get('items', [])}
        merged = []
        for it in issue['items']:
            o = keep.pop(it['key'], None)
            if o:
                for k, v in it.items():
                    if k not in o or (o[k] in ('', None, []) and v):
                        o[k] = v
                merged.append(o)
            else:
                merged.append(it)
        merged.extend(keep.values())  # 손으로 추가한 항목
        for k, v in old.items():
            if k not in ('items',) and k not in issue:
                issue[k] = v
        for k in ('lead', 'theme', 'title'):  # 손으로 고친 머리말 보존
            if old.get(k) and old.get('_edited', {}).get(k):
                issue[k] = old[k]
        issue['items'] = merged
    issue['season'] = season_of(issue['date'])
    with open(issue_path(issue['media'], issue['id']), 'w', encoding='utf-8') as f:
        json.dump(issue, f, ensure_ascii=False, indent=1)


def save_raw(media, iid, key, text):
    d = os.path.join(RAW, media, iid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f'{key}.txt'), 'w', encoding='utf-8') as f:
        f.write(text)


def state(media):
    p = os.path.join(RAW, media, '_state.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}


def save_state(media, st):
    os.makedirs(os.path.join(RAW, media), exist_ok=True)
    json.dump(st, open(os.path.join(RAW, media, '_state.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ───────────────────────── 엠마오 ─────────────────────────

def emmaus(since):
    """stibee 아카이브 /p/<n> → 제목·날짜·Dropbox PDF → 텍스트(data/raw/emmaus/<id>.txt).
    PDF 지면은 형식이 호마다 달라 자동 파싱 대신 '정리 대기'로 남기고, 요약 작성 때 항목을 만든다."""
    base = 'https://emmausbooksreview.stibee.com/p/'
    st = state('emmaus')
    pdfdir = os.path.join(RAW, 'emmaus', 'pdf')
    os.makedirs(pdfdir, exist_ok=True)
    misses, n = 0, 0
    found = []
    while misses < 3 and n < 400:
        n += 1
        if str(n) in st.get('pages', {}):
            found.append(st['pages'][str(n)])
            continue
        t = get(base + str(n), gap=1.5)
        if not t:
            misses += 1
            continue
        misses = 0
        tm = re.search(r'<title>(.*?)</title>', t, re.S)
        title = meta(t, 'og:title') or (tm.group(1).strip() if tm else '')
        if not title:  # 지워진 호나 마지막 호 다음의 빈 페이지
            misses += 1
            continue
        dm = re.search(r'(20\d\d)\.\s*(\d{1,2})\.\s*(\d{1,2})\.', text_of(t))
        pdf = re.search(r'href="(https://www\.dropbox\.com/[^"]+\.pdf[^"]*)"', t)
        sent = f'{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}' if dm else ''
        ym = re.search(r'(?:(\d\d)년\s*)?([\d,\s]+)월', title)
        months = [int(x) for x in re.findall(r'\d+', ym.group(2))] if ym else []
        year = 2000 + int(ym.group(1)) if ym and ym.group(1) else (int(sent[:4]) if sent else None)
        if year and months and sent and months[0] > int(sent[5:7]) + 1:  # 1월에 보낸 12월호
            year -= 1
        rec = {'n': n, 'title': html.unescape(title), 'sent': sent, 'pdf': html.unescape(pdf.group(1)) if pdf else '',
               'year': year, 'months': months}
        st.setdefault('pages', {})[str(n)] = rec
        found.append(rec)
        save_state('emmaus', st)
    save_state('emmaus', st)
    new = 0
    for rec in found:
        if not rec.get('pdf') or not rec.get('year'):
            continue
        months = rec['months'] or [int(rec['sent'][5:7])]
        iid = f'{rec["year"]}-{months[0]:02d}'
        if f'{iid}' < since[:7]:
            continue
        pdf_path = os.path.join(pdfdir, f'{iid}.pdf')
        if not os.path.exists(pdf_path):
            url = re.sub(r'([?&])dl=0', r'\1dl=1', rec['pdf'])
            # urllib 는 Dropbox CDN 리다이렉트에서 멈추는 일이 있어 curl 사용
            subprocess.run(['curl', '-sL', '--max-time', '120', '-A', UA, '-o', pdf_path + '.part', url])
            data = open(pdf_path + '.part', 'rb').read() if os.path.exists(pdf_path + '.part') else b''
            if os.path.exists(pdf_path + '.part'):
                os.remove(pdf_path + '.part')
            time.sleep(2)
            if not data or data[:4] != b'%PDF':
                log('   ! PDF 받기 실패', iid, rec['title'])
                continue
            open(pdf_path, 'wb').write(data)
            log(f'  ↓ 엠마오 {rec["title"]} ({len(data) // 1024}KB)')
        txt_path = os.path.join(RAW, 'emmaus', f'{iid}.txt')
        if not os.path.exists(txt_path):
            py = os.path.join(ROOT, '.venv', 'bin', 'python')
            code = ("import pypdf,sys;r=pypdf.PdfReader(sys.argv[1]);"
                    "print('\\n'.join('=== PAGE %d ===\\n' % (i + 1) + (p.extract_text() or '') for i, p in enumerate(r.pages)))")
            out = subprocess.run([py, '-c', code, pdf_path], capture_output=True, text=True)
            open(txt_path, 'w', encoding='utf-8').write(out.stdout)
        if not load_issue('emmaus', iid):
            mlabel = ','.join(str(m) for m in months)
            save_issue({'media': 'emmaus', 'id': iid, 'no': '', 'title': f'엠마오 {rec["year"]}년 {mlabel}월호',
                        'date': f'{rec["year"]}-{months[-1]:02d}-28', 'column': '', 'url': base + str(rec['n']),
                        'status': 'pending', 'items': []})
            new += 1
    log(f'■ 엠마오: 아카이브 {len(found)}개 호, 새로 정리 대기 {new}개')


# ───────────────────────── 틈 ─────────────────────────

BOOK_LINE = re.compile(r'(지음|엮음|옮김|펴냄)')


def parse_teum_books(body_html):
    """'제목 / 저자 지음, 출판사 펴냄, 270쪽 [도서정보보기](네이버)' 다음 문단이 소개글"""
    t = re.sub(r'(?is)<(script|style).*?</\1>', '', body_html)
    parts = re.split(r'(<a [^>]*href="(https://search\.shopping\.naver\.com/book/catalog/\d+)[^"]*"[^>]*>\s*\[?\s*도서정보보기\s*\]?\s*</a>)', t)
    books = []
    # parts: [앞, a태그, url, 뒤, a태그, url, 뒤...]
    for i in range(1, len(parts), 3):
        before, link, after = parts[i - 1], parts[i + 1], parts[i + 2] if i + 2 < len(parts) else ''
        head = text_of(before).split('\n')
        head = [x for x in head if x.strip()]
        # 뒤에서부터: 서지 줄들(지음/펴냄/쪽) → 그 앞 줄이 제목
        joined = ' '.join(head[-8:])
        biblio = re.search(r'([^\n]*?)\s*(?:지음|엮음)[\s,·]*(.*?)펴냄', joined)
        j = len(head) - 1
        while j > 0 and (BOOK_LINE.search(head[j]) or re.match(r'^[\d,\s쪽\[\]·,]+$', head[j]) or head[j] in (',', '·', '쪽', '[')):
            j -= 1
        title = head[j].strip() if head else ''
        # 제목 줄과 서지 줄 분리
        tail = ' '.join(head[j + 1:])
        author = re.split(r'\s*(?:지음|엮음)', tail)[0].strip(' ,·') if tail else ''
        pub_m = re.search(r'([^,]+?)\s*펴냄', tail)
        publisher = pub_m.group(1).strip(' ,') if pub_m else ''
        publisher = re.sub(r'^.*옮김\s*,?\s*', '', publisher).strip(' ,')
        trans = re.search(r'([^,]+?)\s*옮김', tail)
        pages = re.search(r'(\d+)\s*쪽', tail)
        review = text_of(after.split('도서정보보기')[0])
        # 다음 책 서지 직전까지만
        review_lines = [x for x in review.split('\n') if x.strip()]
        # 마지막 몇 줄은 다음 책의 제목·서지일 수 있음 → 다음 루프에서 head로 쓰이니 잘라냄
        k = len(review_lines)
        if i + 3 < len(parts):
            while k > 0 and (BOOK_LINE.search(review_lines[k - 1]) or len(review_lines[k - 1]) < 40):
                k -= 1
        review = '\n'.join(review_lines[:k]).lstrip('] ').strip()
        review = re.split(r'\n[^\n]*(?:이용약관|사업자|수신거부|구독|후원|🔗|흥미로우셨나요|참여 링크|무단 전재|maily|메일리)', review)[0][:4000]
        if title and len(title) < 80:
            books.append({'title': title, 'author': author, 'translator': trans.group(1).strip(' ,') if trans else '',
                          'publisher': publisher, 'pages': int(pages.group(1)) if pages else None,
                          'link': link, 'review': review, '_biblio': biblio.group(0)[:120] if biblio else ''})
    return books


def parse_teum_heading_books(body_html):
    """소제목(h2/h3) 뒤에 '저자 지음, 출판사 펴냄, 쪽' 서지가 오는 꼴 — 예전·지금 형식 모두"""
    t = re.sub(r'(?is)<(script|style|button|svg).*?</\1>', '', body_html)
    parts = re.split(r'(?is)<h[23][^>]*>(.*?)</h[23]>', t)
    books = []
    for i in range(1, len(parts), 2):
        title = text_of(parts[i]).strip()
        after = parts[i + 1] if i + 1 < len(parts) else ''
        lines = [x for x in text_of(after).split('\n') if x.strip()]
        if not title or not lines or len(title) > 80 or re.search(r'뉴스레터|구독|목차', title):
            continue
        bib = next((x for x in lines[:3] if re.search(r'(지음|엮음|씀)', x) and re.search(r'펴냄|출판|\d+\s*쪽', x)), '')
        if not bib:
            continue
        author = re.split(r'\s*(?:지음|엮음|씀)', bib)[0].strip(' ,·')
        pm = re.search(r'([^,]+?)\s*펴냄', bib)
        pub = re.sub(r'^.*옮김\s*,?\s*', '', pm.group(1)).strip(' ,') if pm else ''
        tm = re.search(r'([^,]+?)\s*옮김', bib)
        pg = re.search(r'(\d+)\s*쪽', bib)
        link = re.search(r'href="(https://search\.shopping\.naver\.com/book/catalog/\d+)', parts[i] + after[:3000])
        review = '\n'.join(x for x in lines if x != bib and '도서정보보기' not in x)
        review = re.split(r'\n[^\n]*(?:이용약관|사업자|수신거부|구독|후원|🔗|흥미로우셨나요|참여 링크|무단 전재|maily|메일리)', review)[0][:4000]
        books.append({'title': re.sub(r'^[『「《<]|[』」》>]$', '', title), 'author': author, 'translator': tm.group(1).strip(' ,') if tm else '',
                      'publisher': pub, 'pages': int(pg.group(1)) if pg else None, 'link': link.group(1) if link else '', 'review': review})
    return books


def teum(since):
    base = 'https://maily.so/secularsaints'
    st = state('teum')
    seen = st.setdefault('posts', {})
    page, stop, new = 1, False, 0
    while not stop and page < 30:
        t = get(f'{base}?page={page}', gap=2)
        if not t:
            break
        ids = []
        for pid in re.findall(r'/secularsaints/posts/([a-z0-9]+)', t):
            if pid not in ids:
                ids.append(pid)
        if not ids:
            break
        for pid in ids:
            if pid in seen and seen[pid].get('done') and not (RETRY and seen[pid]['done'] == 'nobook'):
                if seen[pid].get('date', '9999') < since:
                    stop = True
                continue
            p = get(f'{base}/posts/{pid}', gap=2)
            if not p:
                continue
            h1 = re.search(r'<h1[^>]*>(.*?)</h1>', p, re.S)
            title = text_of(h1.group(1)) if h1 else meta(p, 'og:title')
            dm = re.search(r'<span class="text-slate-600[^"]*">\s*(20\d\d)\.(\d\d)\.(\d\d)\s*</span>', p)
            d = f'{dm.group(1)}-{dm.group(2)}-{dm.group(3)}' if dm else ''
            subt = re.search(r'</h1>\s*<div[^>]*>\s*<h2[^>]*>(.*?)</h2>', p, re.S)
            no_m = re.match(r'(\d+)호\s*[:：]\s*(.*)', title)
            no, name = (no_m.group(1), no_m.group(2)) if no_m else ('', title)
            seen[pid] = {'title': title, 'date': d, 'done': True}
            if d and d < since:
                stop = True
                continue
            body = re.search(r'(?is)<div[^>]*class="[^"]*(?:prose|post-content|ProseMirror)[^"]*"[^>]*>(.*)', p)
            books = parse_teum_books(body.group(1) if body else p)
            hb = parse_teum_heading_books(body.group(1) if body else p)
            if len(hb) > len(books):  # 소제목 형식이 더 많이 잡히면 그쪽을 씀
                books = hb
            kind = 'new' if '잡솨봐' in name or '신간' in name else 'year' if '올해의 책' in name else 'curation'
            curator = re.search(r'([가-힣A-Za-z]{2,10})\s*(?:님|기자님|목사님)?의 (?:논픽션 )?큐레이션', text_of(subt.group(1)) if subt else name + ' ' + text_of(p[:20000]))
            by = '박현철' if kind == 'new' else (curator.group(1) if curator else '')
            items = []
            for b in books:
                key = item_key(b['title'], b['publisher'])
                save_raw('teum', no or pid, key, f"{b['title']} / {b['author']} / {b['publisher']}\n\n{b['review']}")
                items.append({'key': key, 'title': b['title'], 'author': b['author'], 'translator': b['translator'],
                              'publisher': b['publisher'], 'pages': b['pages'], 'link': b['link'],
                              'section': kind, 'by': [by] if by else [], 'summary': ''})
            if not items:
                seen[pid]['done'] = 'nobook'
                log(f'  · 틈 {title[:40]} — 책 없음(인터뷰 등) 건너뜀')
                continue
            save_issue({'media': 'teum', 'id': no or pid, 'no': f'{no}호' if no else '', 'title': name,
                        'subtitle': text_of(subt.group(1)) if subt else '', 'date': d, 'column': {'new': '이 책 한번 잡솨봐', 'year': '올해의 책', 'curation': '큐레이션'}[kind],
                        'url': f'{base}/posts/{pid}', 'items': items})
            new += 1
            log(f'  + 틈 {title[:50]} ({d}) {len(items)}권')
        page += 1
    save_state('teum', st)
    log(f'■ 틈: 새 호 {new}개')


# ───────────────────────── 복음과상황 〈서사의 서사〉 ─────────────────────────

GOSCON_SEED = [42224, 42171, 42141, 42119, 42089, 42039, 42015, 41447, 41398]  # 2026-10 브라우저 목록 기준


def goscon(since):
    """과거분은 SEED, 새 글은 전체기사 RSS에서 기사 메타 '리뷰 > 서사의 서사'로 골라냄"""
    st = state('goscon')
    done = set(st.get('done', []))
    cand = list(GOSCON_SEED) + [int(r['idxno']) for r in goscon_list(since, 'S2N67')]
    rss = get('https://www.goscon.co.kr/rss/allArticle.xml', gap=2) or ''
    cand += [int(x) for x in re.findall(r'articleView\.html\?idxno=(\d+)', rss)]
    new = 0
    for idx in sorted(set(cand), reverse=True):
        if idx in done:
            continue
        t = get(f'https://www.goscon.co.kr/news/articleView.html?idxno={idx}', gap=3)
        done.add(idx)
        if not t or meta(t, 'article:section1') != '서사의 서사':
            continue
        d = meta(t, 'article:published_time')[:10]
        if d < since:
            continue
        sub = re.search(r'class="subheading">\[(\d+)호[^\]]*\]', t)
        no = sub.group(1) if sub else ''
        body_m = re.search(r'id="article-view-content-div"[^>]*>(.*?)</article>', t, re.S)
        body = text_of(body_m.group(1)) if body_m else ''
        headline = meta(t, 'og:title').replace(' - 복음과상황', '').strip()
        # 본문에 언급된 책: 저자의 《제목》(출판사)
        items = []
        for m in re.finditer(r'(?:([가-힣A-Za-z.\s·]{2,20}?)의\s*)?《([^》]{1,60})》\s*\(([^)]{1,20})\)', body):
            author, title, pub = (m.group(1) or '').strip(), m.group(2).strip(), m.group(3).strip()
            key = item_key(title, pub)
            if any(x['key'] == key for x in items):
                continue
            items.append({'key': key, 'title': title, 'author': author, 'publisher': pub, 'section': 'essay',
                          'by': [meta(t, 'dable:author') or '복음과상황'], 'headline': headline, 'summary': ''})
        if not items:
            log(f'  · 복상 {headline} — 서지 표기된 책 없음')
        save_raw('goscon', no or str(idx), 'essay', f'{headline}\n\n{body}')
        iid = no or d[:7]
        issue = load_issue('goscon', iid) or {'media': 'goscon', 'id': iid, 'no': f'{no}호' if no else '', 'items': []}
        if issue.get('_curated'):  # 손으로 정리한 호는 건드리지 않음
            continue
        issue.update({'title': f'복음과상황 {no}호 〈서사의 서사〉 {headline}', 'date': d, 'column': '서사의 서사',
                      'url': f'https://www.goscon.co.kr/news/articleView.html?idxno={idx}', 'headline': headline})
        issue['items'] = items
        save_issue(issue)
        new += 1
        log(f'  + 복상 {no}호 서사의 서사 「{headline}」 책 {len(items)}권')
    st['done'] = sorted(done)
    save_state('goscon', st)
    log(f'■ 복음과상황: 새 글 {new}개')


# ───────────────────────── 뉴스앤조이 [1일1책] ─────────────────────────

def parse_biblio_slash(line):
    """'＜제목＞ / 저자 지음 / 역자 옮김 / 출판사 펴냄 / 190쪽 / 1만 5000원'"""
    line = re.sub(r'[＞>〉]\s*/', '＞ /', line)  # '＜제목＞/ 저자' 처럼 붙여 쓴 경우
    parts = [x.strip() for x in re.split(r'\s/\s?', line)]
    title = re.sub(r'^[＜<〈]|[＞>〉]$', '', parts[0]).strip() if parts else ''
    author = next((re.sub(r'\s*(지음|엮음|씀|글)$', '', x) for x in parts[1:] if re.search(r'(지음|엮음|씀)$', x)), '')
    trans = next((re.sub(r'\s*옮김$', '', x) for x in parts[1:] if x.endswith('옮김')), '')
    pub = next((re.sub(r'\s*(펴냄|출판|발행)$', '', x) for x in parts[1:] if re.search(r'(펴냄|발행)$', x)), '')
    pages = next((int(re.sub(r'\D', '', x)) for x in parts[1:] if re.match(r'^\d+\s*쪽$', x)), None)
    return title, author, trans, pub, pages


def newsnjoy(since):
    st = state('newsnjoy')
    done = set(st.get('done', []))
    page, stop, new = 1, False, 0
    list_url = 'https://www.newsnjoy.or.kr/news/articleList.html?page={p}&sc_sub_section_code=S2N61&view_type=sm'
    ajax = ('https://www.newsnjoy.or.kr/news/ajaxArticlePaging.php?total={total}&list_per_page=20&page_per_page=10'
            '&page={p}&sc_sub_section_code=S2N61&view_type=sm&box_idxno=0')
    total = 0
    while not stop and page < 60:
        # 1쪽은 목록 HTML, 2쪽부터는 사이트의 '더보기' JSON (목록 HTML 2쪽은 연재 필터가 풀림)
        if page == 1:
            t = get(list_url.format(p=1), gap=3) or ''
            tm = re.search(r'total=(\d+)', t)
            total = int(tm.group(1)) if tm else 600
            ids = []
            for x in re.findall(r'articleView\.html\?idxno=(\d+)"[^>]*>\s*\[1일1책\]', t):
                if x not in ids:
                    ids.append(x)
        else:
            ids = []
            for attempt in range(8):  # 이 엔드포인트는 가끔 '정상적인 접근이 아닙니다'로 거절 → 간격 두고 재시도
                j = get(ajax.format(total=total, p=page), gap=4, referer=list_url.format(p=1))
                try:
                    d = json.loads(j or '{}')
                except ValueError:
                    d = {}
                if d.get('result') == 'success':
                    ids = [x['idxno'] for x in d.get('data', [])]
                    if d.get('data') and d['data'][-1].get('viewDate', '9999') < since:
                        stop = True
                    break
                time.sleep(8)
        if not ids:
            break
        for idx in ids:
            if int(idx) in done:
                continue
            a = get(f'https://www.newsnjoy.or.kr/news/articleView.html?idxno={idx}', gap=3)
            if not a:
                continue
            d = meta(a, 'article:published_time')[:10]
            if d and d < since:
                stop = True
                break
            done.add(int(idx))
            body_m = re.search(r'id="article-view-content-div"[^>]*>(.*?)</article>', a, re.S)
            body = text_of(body_m.group(1)) if body_m else ''
            line = next((x for x in body.split('\n') if re.match(r'^[＜<〈].+[＞>〉]\s*/', x.strip())), '')
            title, author, trans, pub, pages = parse_biblio_slash(line) if line else ('', '', '', '', None)
            headline = meta(a, 'og:title').replace('[1일1책]', '').replace(' - 뉴스앤조이', '').strip()
            if not title:
                m = re.search(r'[＜<〈]([^＞>〉]{1,60})[＞>〉]\s*\(([^)]{1,20})\)', body)
                if m:
                    title, pub = m.group(1), m.group(2)
            if not title:
                log(f'  ? 뉴조 {idx} 서지 못 찾음: {headline}')
                continue
            iid = d[:7]
            key = item_key(title, pub)
            save_raw('newsnjoy', iid, key, f'{headline}\n{line}\n\n{body[:6000]}')
            issue = load_issue('newsnjoy', iid) or {'media': 'newsnjoy', 'id': iid, 'no': '', 'items': []}
            issue.update({'title': f'뉴스앤조이 [1일1책] {int(iid[:4])}년 {int(iid[5:])}월', 'date': max(issue.get('date', ''), d),
                          'column': '1일1책', 'url': 'https://www.newsnjoy.or.kr/news/articleList.html?sc_sub_section_code=S2N61&view_type=sm'})
            item = {'key': key, 'title': title, 'author': author, 'translator': trans, 'publisher': pub, 'pages': pages,
                    'section': 'daily', 'by': [meta(a, 'dable:author')] if meta(a, 'dable:author') else [], 'headline': headline,
                    'date': d, 'url': f'https://www.newsnjoy.or.kr/news/articleView.html?idxno={idx}', 'summary': ''}
            issue['items'] = [x for x in issue.get('items', []) if x['key'] != key] + [item] if not any(x['key'] == key for x in issue.get('items', [])) else issue['items']
            save_issue(issue)
            new += 1
            log(f'  + 뉴조 {d} 《{title}》 {pub} — {headline[:30]}')
        page += 1
        st['done'] = sorted(done)
        save_state('newsnjoy', st)
    log(f'■ 뉴스앤조이: 새 글 {new}개')


# ───────────────────────── 크리스찬북뉴스 ─────────────────────────

CBOOK_BOARDS = {'75/80': ('편집자추천도서', 'editor'), '25/37': ('베스트서평', 'best')}


def cbooknews(since):
    st = state('cbooknews')
    done = set(st.get('done', []))
    new = 0
    for c, (label, sec) in CBOOK_BOARDS.items():
        page, stop = 1, False
        while not stop and page < 40:
            t = get(f'https://www.cbooknews.com/?c={c}&p={page}', gap=3)
            if not t:
                break
            uids = []
            for u in re.findall(r'uid=(\d+)', t):
                if u not in uids:
                    uids.append(u)
            if not uids:
                break
            for uid in uids:
                if f'{c}:{uid}' in done:
                    continue
                a = get(f'https://www.cbooknews.com/?c={c}&uid={uid}', gap=3)
                if not a:
                    continue
                d = meta(a, 'article:published_time')[:10]
                if d and d < since:
                    stop = True
                    break
                done.add(f'{c}:{uid}')
                bold = re.search(r'id="vContent"[^>]*>.*?<span style="font-weight:\s*bold;?">(.*?)</span>', a, re.S)
                fields = [x.strip() for x in text_of(bold.group(1)).split('/')] if bold else []
                headline = meta(a, 'og:image:alt') or ''
                title = fields[0] if fields else meta(a, 'og:title').split(' - ')[-1]
                has_rev = bool(fields) and re.search(r'(편집인|편집위원|편집고문|발행인|목사|기자|교수|전도사)$', fields[-1])
                bib = fields[:-1] if has_rev else fields  # 제목/저자/(역자)/출판사[/서평자]
                reviewer = (fields[-1] if has_rev else '') or meta(a, 'article:author')
                author = bib[1] if len(bib) > 1 else ''
                pub = bib[-1] if len(bib) >= 3 else ''
                trans = bib[2] if len(bib) >= 4 else ''
                body_m = re.search(r'id="vContent"[^>]*>(.*?)<div class="(?:bottom|tag|attach|btnbox)', a, re.S)
                body = text_of(body_m.group(1) if body_m else '')
                iid = d[:7]
                key = item_key(title, pub)
                save_raw('cbooknews', iid, key, f'{headline}\n{" / ".join(fields)}\n\n{body[:6000]}')
                issue = load_issue('cbooknews', iid) or {'media': 'cbooknews', 'id': iid, 'no': '', 'items': []}
                issue.update({'title': f'크리스찬북뉴스 {int(iid[:4])}년 {int(iid[5:])}월', 'date': max(issue.get('date', ''), d),
                              'column': '편집자추천도서 · 베스트서평', 'url': 'https://www.cbooknews.com/?c=75/80'})
                items = issue.get('items', [])
                if any(x['key'] == key and x.get('section') == sec for x in items):
                    continue
                items.append({'key': key if not any(x['key'] == key for x in items) else f'{key}-{sec}', 'title': title, 'author': author,
                              'translator': trans, 'publisher': pub, 'section': sec, 'by': [re.sub(r'\s*(편집인|편집위원|편집고문|발행인|목사)$', '', reviewer)] if reviewer else [],
                              'role': reviewer, 'headline': headline, 'date': d, 'url': f'https://www.cbooknews.com/?c={c}&uid={uid}', 'summary': ''})
                issue['items'] = items
                save_issue(issue)
                new += 1
                log(f'  + 북뉴스 {label} {d} 《{title}》 {pub}')
            page += 1
            st['done'] = sorted(done)
            save_state('cbooknews', st)
    log(f'■ 크리스찬북뉴스: 새 글 {new}개')


# ───────────────────────── 복음과상황 리뷰 코너 (서사의 서사 외) ─────────────────────────
# 리뷰 섹션(S1N36) 목록은 사이트의 '더보기' JSON 으로 받음 (Referer 필요). 책 서지는 본문의 정형화된 줄에서 뽑음:
#   ▲ 제목 / 저자 지음 / 역자 옮김 / 출판사 펴냄 / 15,000원    · 제목｜저자 지음｜출판사    · (제목 줄) ↵ : 한줄평 ↵ 저자 지음 | 출판사 | 가격
GOSCON_CORNERS = {  # 코너 코드: (사이트 코너 이름, 비북스 섹션)
    'S2N13': ('에디터가 고른 책', 'editor'), 'S2N15': ('새 책 나들이', 'new'), 'S2N78': ('새 책 맛보기', 'new'),
    'S2N14': ('잠깐 독서', 'new'), 'S2N77': ('책방에서', 'review'), 'S2N61': ('시대를 잇는 읽기', 'review'),
    'S2N12': ('독서일기', 'review'), 'S2N24': ('삶과 독서', 'review'), 'S2N42': ('교회력, 계절의 독서', 'review'),
    'S2N26': ('팬데믹 시대의 신학서 읽기', 'review'), 'S2N34': ('에디터의 책꽂이', 'review'), 'S2N11': ('편애하는 리뷰', 'review'),
}
_SEP = re.compile(r'\s*[/|｜]\s*')


def parse_goscon_books(lines):
    """본문 줄 목록 → [{'title','author','translator','publisher','blurb'}]"""
    out = []
    for i, ln in enumerate(lines):
        if not re.search(r'(지음|엮음|글·그림|그림|편저|저|쓰고)\s*([/|｜]|$)', ln) or not re.search(r'[/|｜]', ln):
            continue
        parts = [x.strip(' ▲·') for x in _SEP.split(ln.strip(' ▲')) if x.strip(' ▲')]
        title = author = tr = pub = ''
        for j, x in enumerate(parts):
            if re.search(r'[\d,]{3,}\s*원$', x):
                continue
            if re.search(r'(지음|엮음|그림|편저|쓰고|글)$', x) and not author:
                author = re.sub(r'\s*(지음|엮음|글·그림|그림|편저|쓰고|글)$', '', x).strip()
            elif x.endswith('옮김'):
                tr = x[:-2].strip()
            elif x.endswith('펴냄') or (author and not pub and j > 0):
                pub = x.replace('펴냄', '').strip()
            elif j == 0 and not author:
                title = x
        if not title:  # 제목이 윗줄에 있는 형식
            k = i - 1
            while k >= 0 and (lines[k].startswith(':') or not lines[k].strip()):
                k -= 1
            title = lines[k].strip(' ▲') if k >= 0 else ''
        title = re.sub(r'^[《〈]|[》〉]$', '', title).strip()
        if not title or len(title) > 70 or not pub or len(pub) > 25:
            continue
        blurb = []
        for k in range(i + 1, min(i + 8, len(lines))):
            if re.search(r'(지음|엮음|옮김|펴냄)\s*([/|｜]|$)', lines[k]):
                break
            blurb.append(lines[k])
        out.append({'title': title, 'author': author, 'translator': tr, 'publisher': pub, 'blurb': '\n'.join(blurb)[:1500]})
    return out


def goscon_list(since, sub=None):
    """리뷰 섹션 기사 목록 [{idxno, sub_section_code, title, viewDate, user_name}] — since 이후"""
    ref = 'https://www.goscon.co.kr/news/articleList.html?sc_section_code=S1N36&view_type=sm'
    rows = []
    for p in range(1, 120):
        u = ('https://www.goscon.co.kr/news/ajaxArticlePaging.php?total=5000&list_per_page=20&page_per_page=10'
             f'&page={p}&sc_section_code=S1N36&view_type=sm&box_idxno=0')
        try:
            d = json.loads(get(u, gap=2, referer=ref) or '{}')
        except ValueError:
            d = {}
        data = d.get('data') or []
        if not data:
            break
        rows += [r for r in data if (r.get('viewDate') or '').replace('.', '-') >= since and (not sub or r.get('sub_section_code') == sub)]
        if (data[-1].get('viewDate') or '9').replace('.', '-') < since:
            break
    return rows


def goscon_reviews(since):
    st = state('goscon_reviews')
    done = set(st.get('done', []))
    new = 0
    for r in goscon_list(since):
        code = r.get('sub_section_code')
        if code not in GOSCON_CORNERS or r['idxno'] in done:
            continue
        corner, sec = GOSCON_CORNERS[code]
        t = get(f"https://www.goscon.co.kr/news/articleView.html?idxno={r['idxno']}", gap=3)
        if not t:
            continue
        done.add(r['idxno'])
        sub = re.search(r'class="subheading">\[(\d+)호', t)
        no = sub.group(1) if sub else ''
        d = meta(t, 'article:published_time')[:10] or r['viewDate'].replace('.', '-')
        bm = re.search(r'id="article-view-content-div"[^>]*>(.*?)</article>', t, re.S)
        lines = [x.strip() for x in text_of(bm.group(1)).split('\n')] if bm else []
        lines = [x for x in lines if x]
        if any('유료회원만' in x for x in lines[:40]):
            log(f"  · 복상 {corner} {r['idxno']} — 유료 기사, 건너뜀")
            continue
        books = parse_goscon_books(lines)
        headline = html.unescape(r.get('title') or '')
        url = f"https://www.goscon.co.kr/news/articleView.html?idxno={r['idxno']}"
        writer = html.unescape(r.get('user_name') or '').strip()
        items = []
        for b in books:
            key = item_key(b['title'], b['publisher'])
            if any(x['key'] == key for x in items):
                continue
            save_raw('goscon', no or d[:7], key, f"[{corner}] {headline}\n{b['title']} / {b['author']} / {b['publisher']}\n\n{b['blurb']}")
            items.append({'key': key, 'title': b['title'], 'author': b['author'], 'translator': b['translator'],
                          'publisher': b['publisher'], 'link': url, 'section': sec, 'corner': corner, 'headline': headline,
                          'by': [writer] if writer and sec in ('editor', 'review') else ['복음과상황'], 'summary': ''})
        if not items:
            log(f"  · 복상 {corner} {headline[:30]} — 서지 줄 없음")
            continue
        iid = no or d[:7]
        old = load_issue('goscon', iid) or {}
        issue = {k: v for k, v in old.items() if k != 'items'}
        issue.update({'media': 'goscon', 'id': iid, 'items': items})
        issue.setdefault('no', f'{no}호' if no else '')
        issue.setdefault('title', f'복음과상황 {no}호' if no else f'복음과상황 {d[:7]}')
        issue.setdefault('date', d)
        issue.setdefault('column', '리뷰')
        issue.setdefault('url', url)
        save_issue(issue)
        new += 1
        log(f"  + 복상 {no}호 {corner} 「{headline[:30]}」 {len(items)}권")
        st['done'] = sorted(done)
        save_state('goscon_reviews', st)
    st['done'] = sorted(done)
    save_state('goscon_reviews', st)
    log(f'■ 복상 리뷰 코너: 새 기사 {new}개')


COLLECTORS = {'emmaus': emmaus, 'teum': teum, 'goscon': goscon, 'goscon_reviews': goscon_reviews, 'newsnjoy': newsnjoy, 'cbooknews': cbooknews}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    since = MEDIA.get('_since', '2025-01-01')
    if '--since' in sys.argv:
        since = sys.argv[sys.argv.index('--since') + 1]
        args = [a for a in args if a != since]
        since = (since + '-01')[:10] if len(since) == 7 else since
    for name in (args or COLLECTORS):
        try:
            COLLECTORS[name](since)
        except Exception as e:  # noqa: BLE001  한 매체가 실패해도 나머지는 진행
            import traceback
            traceback.print_exc()
            log(f'■ {name}: 실패 — {e}')
    os.makedirs(RAW, exist_ok=True)
    with open(os.path.join(RAW, f'collect-{date.today()}.log'), 'a', encoding='utf-8') as f:
        f.write('\n'.join(LOG) + '\n')


if __name__ == '__main__':
    main()
