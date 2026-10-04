# C.books (bbooks-shop) — 작업 규칙

크리스천북 큐레이팅 서비스 C.books의 정적 사이트. 사용자는 한국어로 대화합니다(답도 한국어).

## 데이터·표지 수정 요청이 오면
1. **먼저 `EDITING.md`를 읽고 그 순서대로** 작업합니다.
2. 데이터는 `python3 tools/edit.py …` 로만 고칩니다. `data/issues/*.json` 을 손으로 편집하지 않습니다.
3. 고친 뒤 `python3 build.py` → 결과 확인 → `tools/deploy.sh "메시지"` (커밋까지).
4. **`git push` 는 사용자가 배포를 확인한 뒤에만.** 끝나면 무엇을 바꿨는지와 배포 여부를 짧게 보고합니다.
5. 같은 책이 여러 곳에 있거나 맞는 ISBN이 애매하면 추측하지 말고 후보를 보여 주고 묻습니다.

## 하지 않는 것
- `dist/`, `docs/` 생성물 직접 수정, `data/cache/` 직접 수정
- `.secrets/`, Supabase, Apps Script, 결제 관련 변경 (요청이 있어도 범위 밖이면 사용자에게 알리기)
- 사업자·통신판매업 정보 찾아 넣기 (사용자가 직접 줌)
- 코드(`build.py`, `fetch.py`, `collect.py`) 구조 변경 — EDITING.md 5절 참고
