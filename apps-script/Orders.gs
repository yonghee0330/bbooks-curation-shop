/**
 * 비북스 큐레이션 서점 — 주문 접수 (Google Apps Script 웹앱)
 *
 * 설치
 *  1. 새 구글 시트 → 확장 프로그램 → Apps Script → 이 파일 내용 붙여넣기
 *  2. 프로젝트 설정 → 스크립트 속성: OPERATOR_EMAIL (주문 알림 받을 메일)
 *  3. 배포 → 새 배포 → 웹 앱 (실행: 나 / 액세스: 모든 사용자) → 웹앱 URL 복사
 *  4. data/site.json 의 "apiUrl" 에 붙여넣고 python3 build.py
 *
 * 시트 '주문' 한 줄 = 주문 한 건. 상태 열(입고대기 → 입고완료 → 결제완료 → 수령완료)은 손으로 바꿔 관리.
 * 개인정보(이름·연락처·주소)는 이 시트에만 저장됩니다. 시트 공유 범위를 운영자로 제한하세요.
 */
var SHEET = '주문';
var HEAD = ['접수일시', '주문번호', '상태', '이름', '휴대폰', '이메일', '수령', '주소', '요청사항', '도서', '권수', '도서금액', '배송비', '합계', '추천 출처', 'ISBN 목록'];

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (body.action !== 'order') return out_({ ok: false, error: 'unknown action' });
    var o = body.order || {};
    if (!o.name || !o.phone || !(o.items && o.items.length)) return out_({ ok: false, error: '필수 항목 누락' });
    var lock = LockService.getScriptLock(); lock.waitLock(10000);
    try {
      var sh = sheet_();
      var books = o.items.map(function (x) { return x.title + ' ×' + x.qty; }).join('\n');
      var qty = o.items.reduce(function (s, x) { return s + Number(x.qty || 0); }, 0);
      sh.appendRow([new Date(), String(o.no), '입고대기', o.name, "'" + o.phone, o.email || '', o.ship === 'delivery' ? '택배' : '매장 픽업',
        o.address || '', o.note || '', books, qty, o.subtotal, o.shipping, o.total,
        o.items.map(function (x) { return x.from; }).filter(String).join('\n'),
        o.items.map(function (x) { return x.isbn13 + '×' + x.qty; }).join(', ')]);
    } finally { lock.releaseLock(); }
    notify_(o);
    return out_({ ok: true, no: o.no });
  } catch (err) {
    return out_({ ok: false, error: String(err) });
  }
}

function sheet_() {
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(SHEET) || ss.insertSheet(SHEET);
  if (sh.getLastRow() === 0) { sh.appendRow(HEAD); sh.setFrozenRows(1); }
  return sh;
}

function notify_(o) {
  var to = PropertiesService.getScriptProperties().getProperty('OPERATOR_EMAIL') || Session.getEffectiveUser().getEmail();
  var lines = o.items.map(function (x) { return '· ' + x.title + ' (' + x.publisher + ') ×' + x.qty + '  ' + x.isbn13; }).join('\n');
  MailApp.sendEmail(to, '[비북스 서가] 새 주문 ' + o.no + ' · ' + o.name,
    lines + '\n\n수령: ' + (o.ship === 'delivery' ? '택배 ' + (o.address || '') : '매장 픽업') +
    '\n합계: ' + Number(o.total).toLocaleString() + '원\n연락처: ' + o.phone + (o.note ? '\n요청: ' + o.note : ''));
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
