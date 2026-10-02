# 비북스 큐레이션 서점 (bbooks-shop)

서평지·뉴스레터가 추천한 책 목록 → 알라딘 정보(표지·정가·책소개·목차) + 추천 글 요약 → 장바구니·주문 요청까지 되는 정적 사이트.

## 쓰는 법
```
python3 fetch.py            # 추천 목록 책 정보 수집 (캐시: data/cache, 알라딘 간격 3초)
python3 build.py            # dist/ 생성
python3 build.py --serve    # http://localhost:8810
```

## 새 호·새 매체 추가
1. `data/sources/<매체>-<호>.json` 하나 만들기 (형식은 `emmaus-28.json` 참고)
   - `books[].title / search / publisher` 만 쓰면 fetch.py가 ISBN을 찾아 `isbn13`을 채워 넣음 (잘못 잡히면 손으로 고치기)
   - `recs[]` = 그 책을 추천한 글: `section`(pick·mention·editor·special·preview·person·related), `by`, `page`, `summary`
2. 새 매체면 `data/site.json` → `media` 에 이름·소개·구독 링크·색 추가
3. `python3 fetch.py && python3 build.py`

## 주의
- `summary`는 비북스가 다시 쓴 요약. 매체 원문 인용은 해당 매체 허락 후에만.
- 가격: `site.json` pricing.discountRate (도서정가제 10% 이내), 택배비·무료배송 기준.
- 주문: `apiUrl` 비어 있으면 데모(브라우저에만 저장). `apps-script/Orders.gs` 배포 → URL 넣으면 구글 시트 접수 + 메일 알림.
- 알라딘 TTB 키는 `../bbooks-curation/config.json` 또는 `ALADIN_TTB_KEY` 환경변수에서 읽음.
- 목차·책소개는 알라딘 상품 페이지의 소개 블록(getContents)에서 가져옴 — 원본 html은 `data/cache/raw` (`fetch.py --reparse`로 재파싱).
