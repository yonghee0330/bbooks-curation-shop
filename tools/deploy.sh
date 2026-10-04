#!/bin/zsh
# 배포 준비: 확인용 빌드(dist) → 배포용 빌드(docs) → 회원 DB 책 목록 동기화 → 커밋.
# 푸시는 하지 않는다. 사용자가 "배포해줘"라고 확인하면 그때: git push origin main
# 사용: tools/deploy.sh "커밋 메시지"
set -e
cd "$(dirname "$0")/.."
msg="${1:-데이터 수정}"
python3 build.py | tail -1
python3 build.py --pages | tail -1
python3 sync_books.py --docs | tail -1
git add -A
if git diff --cached --quiet; then
  echo "· 바뀐 내용이 없어 커밋하지 않았습니다."
else
  git commit -q -m "$msg" && git log --oneline -1
  echo "· 커밋 완료. 사용자 확인 후: git push origin main"
fi
