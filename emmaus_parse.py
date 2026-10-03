#!/usr/bin/env python3
"""엠마오 PDF 텍스트(data/raw/emmaus/<호>.txt) → 책 단위 후보 (요약 작성 전 확인용)

  python3 emmaus_parse.py 2025-01          # 후보 목록 보기
  python3 emmaus_parse.py 2025-01 --write  # 요약 없이 항목으로 저장 (status: draft)

지면 구성: EMMAUS PREVIEW(신간 둘러보기) · EDITOR'S PICK(기획위원 분야별) · EMMAUS PICK(이달의 책)
· HONORABLE MENTION(두 번째) · Marginalia(인물). 서지 줄은 '저자 지음' 다음 '역자 옮김 | 출판사' 꼴.
PDF 줄바꿈이 제각각이라 완벽하지 않음 → 결과를 보고 손으로 다듬는다.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'data', 'raw', 'emmaus')

AUTH = re.compile(r'^(?P<a>.{1,60}?)\s*(?:지음|엮음|씀|역주|편저|편역|외 지음|글|그림)\s*(?:\|\s*(?P<rest>.*))?$')
SEC_MARK = [('EMMAUS PREVIEW', 'preview'), ("EDITOR’S PICK", 'editor'), ("EDITOR'S PICK", 'editor'),
            ('HONORABLE MENTION', 'mention'), ('EMMAUS PICK', 'pick'), ('Marginalia', 'person'),
            ('SPECIAL ARTICLE', 'special'), ('OUTRO', 'end'), ('INTRO', 'intro')]
FIELD = re.compile(r'Pick\s*-\s*(구약|신약|신학|신앙|교회사|역사|영성|문학|인문|사회|기타)')


def pages(txt):
    parts = re.split(r'=== PAGE (\d+) ===\n', txt)
    return [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]


def page_section(body, prev):
    for mark, sec in SEC_MARK:
        if mark in body[:400]:
            return sec
    return prev


def is_title_line(s):
    s = s.strip()
    if not (0 < len(s) <= 40) or AUTH.match(s) or '옮김' in s or re.search(r'추천하는|도서 두 번째|신간 둘러보기|기획위원 Pick', s):
        return False
    if re.match(r'^(EMMAUS|EDITOR|HONORABLE|20\d\d년|\d+$|- )', s):
        return False
    # 서평 본문 줄은 PDF에서 거의 꽉 찬 길이(38자 안팎)로 끊김. 짧은 줄은 '~다'로 끝나도 제목일 수 있음
    if re.search(r'[.。]$', s) or (re.search(r'(다|요)$|[?!]$', s) and len(s) > 22):
        return False
    return True


def parse(iid):
    txt = open(os.path.join(RAW, f'{iid}.txt'), encoding='utf-8').read()
    books, sec, field, reviewer = [], 'intro', '', ''
    for no, body in pages(txt):
        sec = page_section(body, sec)
        fm = FIELD.search(body)
        if sec == 'editor' and fm:
            field = fm.group(1)
            # 기획위원 이름: 'Pick - 구약' 다음 첫 짧은 줄
            after = body[fm.end():].strip().split('\n')
            reviewer = next((x.strip() for x in after if 1 < len(x.strip()) <= 5), '')
        lines = [x.rstrip() for x in body.split('\n')]
        i, last_end = 0, 0
        while i < len(lines):
            ln = lines[i].strip()
            # 한 줄 서지: '저자 지음 | 역자 옮김 | 출판사'
            one = re.match(r'^(.+?)\s*(?:지음|엮음)\s*\|\s*(?:(.+?)\s*(?:옮김|역주)\s*\|\s*)?(.+)$', ln)
            m = AUTH.match(ln)
            if one or m:
                author = (one.group(1) if one else m.group('a')).strip()
                trans, pub = (one.group(2) or '', one.group(3)) if one else ('', '')
                j = i + 1
                if not one:
                    rest = m.group('rest') or ''
                    nxt = lines[j].strip() if j < len(lines) else ''
                    if '옮김' in nxt or '역주' in nxt or '번역' in nxt:
                        tm = re.match(r'^(.*?)\s*(?:옮김|역주|번역)\s*(?:\|\s*(.*))?$', nxt)
                        trans, pub = tm.group(1).strip(), (tm.group(2) or '').strip()
                        j += 1
                        if not pub and j < len(lines) and 0 < len(lines[j].strip()) <= 20:
                            pub = lines[j].strip()
                            j += 1
                    elif rest:
                        pub = rest
                    elif 0 < len(nxt) <= 20 and not AUTH.match(nxt):
                        pub = nxt
                        j += 1
                # 제목: 서지 줄 바로 위 짧은 줄들 (한 줄 서지는 아래에 제목이 오기도 함)
                k = i - 1
                tl = []
                while k >= last_end and is_title_line(lines[k]) and len(tl) < 5:
                    tl.insert(0, lines[k].strip())
                    k -= 1
                if one and not tl and j < len(lines) and is_title_line(lines[j]):
                    tl = [lines[j].strip()]
                    j += 1
                title = ' '.join(tl).replace(' · ', ' · ').strip()
                review = '\n'.join(x for x in lines[last_end:k + 1]).strip()
                if sec in ('editor', 'person'):  # 서평이 서지 앞뒤에 걸친 지면 → 페이지 전체
                    review = re.sub(r'\s+', ' ', body)[:2500]
                if title and len(title) < 90:
                    books.append({'title': title, 'author': author, 'translator': trans, 'publisher': pub.strip(' |'),
                                  'section': sec if sec not in ('intro',) else 'preview', 'field': field if sec == 'editor' else '',
                                  'by': [reviewer] if sec == 'editor' and reviewer else [], 'page': no, 'review': review})
                last_end = j
                i = j
                continue
            i += 1
        if sec == 'pick' or sec == 'mention':  # 한마디 추천자들: '- 이름'
            names = re.findall(r'^-\s*([가-힣]{2,4})\s*$', body, re.M)
            names += re.findall(r'-\s*([가-힣]{2,4})\s*$', body, re.M)
            for b in books:
                if b['page'] == no and names:
                    b['by'] = list(dict.fromkeys(names))
    # 같은 책 같은 코너 중복 제거
    seen, out = set(), []
    for b in books:
        k = (re.sub(r'\W', '', b['title'])[:12], b['section'])
        if k not in seen:
            seen.add(k)
            out.append(b)
    return out


if __name__ == '__main__':
    iid = sys.argv[1]
    bs = parse(iid)
    for b in bs:
        print(f"[{b['section']}{'/' + b['field'] if b['field'] else ''} p{b['page']}] 《{b['title']}》 {b['author']} / {b['translator']} / {b['publisher']} — {', '.join(b['by'])} ({len(b['review'])}자)")
    if '--write' in sys.argv:
        sys.path.insert(0, ROOT)
        import collect
        iss = collect.load_issue('emmaus', iid)
        items = []
        for b in bs:
            key = collect.item_key(b['title'], b['publisher']) + '-' + b['section']
            collect.save_raw('emmaus', iid, key, f"{b['title']} / {b['author']} / {b['publisher']}\n\n{b['review']}")
            items.append({'key': key, 'title': b['title'], 'author': b['author'], 'translator': b['translator'], 'publisher': b['publisher'],
                          'section': b['section'], 'field': b['field'], 'by': b['by'], 'page': b['page'], 'summary': ''})
        iss['items'] = items
        iss['status'] = 'draft'
        collect.save_issue(iss)
        print('저장:', len(items))
