# C.books 데이터 수정 가이드

책 정보·추천 문구·표지처럼 **작은 수정**을 할 때 보는 문서입니다.
원칙은 하나: **JSON 파일을 손으로 열어 고치지 말고 `tools/edit.py` 명령을 쓴다.**
(형식을 지켜 저장하고, 잘못된 값은 저장 전에 막아 줍니다.)

사이트: https://yonghee0330.github.io/bbooks-curation-shop/
작업 폴더: `/Users/mac/Desktop/INBOX-B/bbooks-shop`

---

## 1. 기본 순서 (모든 수정 공통)

```bash
python3 tools/edit.py find 책 제목 일부        # ① 항목 찾기 → 첫 줄의 '항목ID' 복사
python3 tools/edit.py ...                      # ② 고치기 (아래 표)
python3 build.py                               # ③ 확인용 빌드 (dist/)
tools/deploy.sh "무엇을 고쳤는지 한 줄"          # ④ 배포용 빌드 + 커밋 (푸시는 안 함)
git push origin main                           # ⑤ 사용자가 "배포해줘" 한 뒤에만
```

- 항목ID 모양: `매체/호/키` 예) `emmaus/2025-05/신의일식-복있는사람-pick`
- 같은 책이 여러 매체·코너에 있으면 find 결과가 여러 줄 나옵니다. **고칠 곳을 사용자에게 확인**하세요.
- 확인 화면: `python3 -m http.server 8810 --directory dist` 를 백그라운드로 켜고 `http://localhost:8810/` (이미 켜져 있으면 다시 켜지 않기).
  앱 안 브라우저에서는 알라딘 표지가 빈칸으로 보일 수 있습니다(브라우저 제한). 표지 주소가 HTML에 들어갔는지는 `grep` 으로 확인하세요.
- 사이트 반영은 푸시 후 1–3분 걸립니다.

## 2. 무엇을 고칠 때 어떤 명령?

| 하고 싶은 일 | 명령 |
|---|---|
| 추천 요약 문장 고치기 | `edit.py set <항목ID> summary "새 문장"` |
| 추천자 이름 고치기 | `edit.py set <항목ID> by "홍길동, 김철수"` |
| 항목의 제목·저자·출판사 고치기 | `edit.py set <항목ID> title "…"` (author, publisher 동일) |
| 엉뚱한 책이 연결됨 / 표지가 다른 책 | `edit.py search "제목 저자"` → 맞는 ISBN 골라 `edit.py isbn <항목ID> <ISBN>` |
| 국내에 없는 책이라 연결을 끊기 | `edit.py isbn <항목ID> none` |
| 연결을 지우고 자동으로 다시 찾기 | `edit.py isbn <항목ID> auto` |
| 항목을 사이트에서 빼기 | `edit.py hide <항목ID>` (되돌리기: `unhide`) |
| 표지 이미지만 바꾸기 (주소) | `edit.py cover <ISBN> https://…jpg` |
| 표지 이미지만 바꾸기 (파일) | `edit.py cover <ISBN> ~/Desktop/표지.jpg` |
| 표지 보정 지우기 | `edit.py cover <ISBN> reset` |
| 책 페이지의 제목·정가 표시 보정 | `edit.py book <ISBN> title "…"` / `book <ISBN> priceStandard 18000` |
| 항목 전체 내용 보기 | `edit.py show <항목ID>` |

`set` 으로 바꿀 수 있는 칸: title, author, publisher, summary, section, field, translator, by

## 3. 꼭 알아야 할 함정

1. **표지가 틀렸다 = 대개 ISBN이 틀렸다.** 표지만 바꾸지 말고 먼저 `search` 로 맞는 판본의 ISBN으로 `isbn` 을 바꾸세요. 같은 책인데 그림만 다를 때만 `cover` 를 씁니다.
2. **판본 고르기**: 같은 제목이 여러 개면 저자·역자·출판사를 원문 추천과 맞추고, 세트·분권(예: “1권”, “상”)보다 단권/최신판을 우선. 애매하면 후보 2–3개를 사용자에게 보여 주고 고르게 하세요.
3. **엠마오**: `emmaus_apply.py` 를 다시 돌려도 이미 있는 항목의 제목·ISBN은 **바뀌지 않습니다**(키 기준 병합). 제목 수정은 꼭 `edit.py set` 으로.
4. **복음과상황**은 한 파일(`data/issues/goscon/<호>.json`)을 빌드 때 〈서사의 서사〉(코너 essay·related)와 ‘서평·새 책’(나머지)으로 나눠 보여 줍니다. 항목ID는 항상 `goscon/…` 입니다(`gosconbook/…` 은 없음).
5. **틈 올해의 책**도 `teum/12`, `teum/38` 파일입니다(빌드 때 특별 리스트로 분리).
6. `isbn none` 인 책은 자동 검색에서 빠집니다. 나중에 번역본이 나오면 `isbn <항목ID> auto` 또는 ISBN 지정.
7. `dist/`, `docs/` 안의 HTML은 **생성물**입니다. 직접 고치지 마세요(다음 빌드에서 사라짐).
8. `docs/` 파일 수천 개가 바뀐 것으로 나오는 건 빌드 시각 표시 때문이라 정상입니다.

## 4. 파일 위치 (참고만)

| 파일 | 내용 |
|---|---|
| `data/issues/<매체>/<호>.json` | 매체·호별 추천 목록 (edit.py가 고치는 곳) |
| `data/house/*.json` | C.C(C.books Curating) 목록 |
| `data/media.json` | 매체 이름·설명·색·그룹(regular 정기 / special 특별 리스트 / house) |
| `data/site.json` | 사이트 이름·소개·가격 정책·사업자 정보 |
| `data/overrides.json` | 표지·책 정보 보정 (edit.py cover/book) |
| `site/assets/covers/` | 직접 넣은 표지 이미지 |
| `data/cache/books/<ISBN>.json` | 알라딘에서 받은 책 정보 (직접 고치지 않기) |

매체 키: emmaus 엠마오 · teum 틈 · goscon 복음과상황 · newsnjoy 뉴스앤조이 · cbooknews 크리스찬북뉴스 · kmib 국민일보 · ct100 크리스채너티 100 · churchtimes 처치타임즈 100 · house C.C

## 5. 이 가이드 범위를 넘는 일 (큰 모델로 하거나 사용자에게 먼저 묻기)

- 새 매체·새 특별 리스트 추가, 수집기(`collect.py`) 수정, 페이지 디자인·구조 변경
- 추천 요약을 수십 개 이상 새로 쓰기, 새 호(PDF) 정리
- 회원·주문·결제(Supabase, Apps Script) 관련 무엇이든
- `build.py`, `fetch.py` 등 코드 수정

## 6. 요약 문장 쓰는 법 (조금 고칠 때)

- 원문 문장을 옮기지 않고 C.books의 말로 1–2문장(60–120자).
- 무엇을 다룬 책인지 + 왜 권하는지. 추천자 이름은 문장에 쓰지 않음(by 칸에 있음).
- 존댓말 대신 ‘~한다 / ~책.’ 같은 평서문으로, 기존 문장들과 같은 톤.
