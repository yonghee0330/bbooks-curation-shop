/**
 * 비북스 큐레이션 서점 — 주문 접수 (Google Apps Script 웹앱)
 *
 * 설치 (5분)
 *  1. 구글 드라이브 → 새 구글 시트 (이름 예: 비북스 서가 주문)
 *  2. 시트 메뉴 확장 프로그램 → Apps Script → 기본 코드를 지우고 이 파일 전체 붙여넣기 → 저장
 *  3. 위쪽 함수 선택에서 setup 선택 → 실행 → 권한 허용 (주문 시트·서식·월 1회 정리 트리거가 만들어짐)
 *     · 알림 메일을 다른 주소로 받으려면: 프로젝트 설정(톱니) → 스크립트 속성 → OPERATOR_EMAIL 추가
 *  4. 배포 → 새 배포 → 유형 '웹 앱' → 실행: 나 / 액세스 권한: 모든 사용자 → 배포 → 웹 앱 URL 복사
 *  5. data/site.json 의 "apiUrl" 에 그 URL 을 넣고 python3 build.py --pages → 커밋·푸시
 *
 * 코드를 고친 뒤에는 배포 → 배포 관리 → 연필 → 버전 '새 버전' → 배포 (URL 은 그대로 유지)
 *
 * 시트 '주문' 한 줄 = 주문 한 건. 상태 열(입고대기 → 입고완료 → 결제안내 → 결제완료 → 수령완료 / 취소)은 드롭다운으로 관리.
 * 금액은 브라우저가 보낸 값이 아니라 공개된 catalog.json 가격으로 서버에서 다시 계산합니다.
 * 개인정보(이름·연락처·주소)는 이 시트에만 저장되고, 접수 1년이 지나면 매달 자동으로 가립니다(주문 기록은 남김).
 * 시트 공유 범위는 운영자만으로 두세요.
 */
var SHEET = '주문';
var HEAD = ['접수일시', '주문번호', '상태', '이름', '휴대폰', '이메일', '수령', '주소', '요청사항', '도서', '권수', '도서금액', '배송비', '합계', '추천 출처', 'ISBN 목록', '메모'];
var STATUS = ['입고대기', '입고완료', '결제안내', '결제완료', '수령완료', '취소'];
var DEFAULTS = {
  CATALOG_URL: 'https://yonghee0330.github.io/bbooks-curation-shop/data/catalog.json',
  SHIPPING: '3000',          // 택배비 (site.json pricing.shipping 과 맞출 것)
  FREE_OVER: '30000',        // 이 금액 이상 무료배송
  STORE_NAME: '비북스 서가',
  MAX_QTY: '20'
};

function prop_(k) {
  return PropertiesService.getScriptProperties().getProperty(k) || DEFAULTS[k] || '';
}

/* ───────── 웹앱 ───────── */

function doGet() {
  return out_({ ok: true, service: 'bbooks-orders' });
}

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    if (body.action !== 'order') return out_({ ok: false, error: '알 수 없는 요청' });
    var o = body.order || {};
    if (o.website) return out_({ ok: true, no: String(o.no || '') });   // 스팸 봇(숨은 칸을 채움) → 조용히 무시

    var name = clip_(o.name, 40), phone = clip_(o.phone, 20).replace(/[^\d-]/g, ''), email = clip_(o.email, 80);
    var ship = o.ship === 'delivery' ? 'delivery' : 'pickup', address = clip_(o.address, 200), note = clip_(o.note, 500);
    var no = clip_(o.no, 20).replace(/[^A-Z0-9-]/g, '') || newNo_();
    if (!name || !/^0\d{1,2}-?\d{3,4}-?\d{4}$/.test(phone)) return out_({ ok: false, error: '이름과 휴대폰 번호를 확인해 주세요' });
    if (ship === 'delivery' && !address) return out_({ ok: false, error: '받을 주소를 적어 주세요' });
    if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) email = '';

    var cache = CacheService.getScriptCache(), rk = 'rate:' + phone.replace(/-/g, '');
    if (cache.get(rk)) return out_({ ok: false, error: '방금 주문을 받았어요. 1분 뒤에 다시 시도해 주세요' });

    var priced = price_(o.items || [], ship);
    if (!priced.items.length) return out_({ ok: false, error: '주문할 책이 없어요' });

    var lock = LockService.getScriptLock(); lock.waitLock(10000);
    try {
      var sh = sheet_();
      var dup = sh.getLastRow() > 1 && sh.getRange(2, 2, sh.getLastRow() - 1, 1).getValues().some(function (r) { return r[0] === no; });
      if (dup) return out_({ ok: true, no: no, dup: true });
      sh.appendRow([new Date(), no, STATUS[0], safe_(name), "'" + phone, safe_(email), ship === 'delivery' ? '택배' : '매장 픽업',
        safe_(address), safe_(note),
        priced.items.map(function (x) { return x.title + ' ×' + x.qty; }).join('\n'),
        priced.qty, priced.sub, priced.fee, priced.total,
        priced.items.map(function (x) { return x.from; }).filter(String).join('\n'),
        priced.items.map(function (x) { return x.isbn13 + '×' + x.qty; }).join(', '),
        priced.notes.join(' / ')]);
    } finally { lock.releaseLock(); }
    cache.put(rk, '1', 60);

    var order = { no: no, name: name, phone: phone, email: email, ship: ship, address: address, note: note };
    try { notify_(order, priced); } catch (err) { console.error(err); }
    if (email) { try { confirm_(order, priced); } catch (err) { console.error(err); } }
    return out_({ ok: true, no: no, subtotal: priced.sub, shipping: priced.fee, total: priced.total });
  } catch (err) {
    console.error(err);
    return out_({ ok: false, error: '접수 중 오류가 났어요. 잠시 후 다시 시도해 주세요' });
  }
}

/* 공개 카탈로그 가격으로 다시 계산 — 브라우저에서 바꾼 금액은 무시 */
function price_(items, ship) {
  var cat = catalog_(), max = Number(prop_('MAX_QTY')), out = [], notes = [], sub = 0, qty = 0;
  items.slice(0, 50).forEach(function (x) {
    var b = cat[String(x.isbn13)];
    if (!b) { notes.push('목록에 없는 책 제외: ' + clip_(x.title, 40)); return; }
    var q = Math.max(1, Math.min(max, parseInt(x.qty, 10) || 1));
    if (Number(x.price) && Number(x.price) !== b.price) notes.push(b.title + ' 가격 ' + x.price + '→' + b.price);
    out.push({ isbn13: b.isbn13, title: b.title, publisher: b.publisher, qty: q, price: b.price, from: (b.recs || [])[0] || '' });
    sub += b.price * q; qty += q;
  });
  var fee = ship === 'delivery' && sub < Number(prop_('FREE_OVER')) ? Number(prop_('SHIPPING')) : 0;
  return { items: out, sub: sub, fee: fee, total: sub + fee, qty: qty, notes: notes };
}

function catalog_() {
  var url = prop_('CATALOG_URL');
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: { 'Cache-Control': 'no-cache' } });
  if (res.getResponseCode() !== 200) throw new Error('catalog ' + res.getResponseCode());
  return JSON.parse(res.getContentText());
}

/* ───────── 알림 ───────── */

function notify_(o, p) {
  var to = prop_('OPERATOR_EMAIL') || Session.getEffectiveUser().getEmail();
  var lines = p.items.map(function (x) { return '· ' + x.title + ' (' + x.publisher + ') ×' + x.qty + '  ' + x.isbn13; }).join('\n');
  MailApp.sendEmail(to, '[' + prop_('STORE_NAME') + '] 새 주문 ' + o.no + ' · ' + o.name,
    lines + '\n\n수령: ' + (o.ship === 'delivery' ? '택배 ' + o.address : '매장 픽업') +
    '\n도서 ' + won_(p.sub) + ' + 배송 ' + won_(p.fee) + ' = 합계 ' + won_(p.total) +
    '\n연락처: ' + o.phone + (o.email ? ' / ' + o.email : '') + (o.note ? '\n요청: ' + o.note : '') +
    (p.notes.length ? '\n\n확인 필요: ' + p.notes.join(' / ') : '') +
    '\n\n주문 시트: ' + SpreadsheetApp.getActive().getUrl());
}

function confirm_(o, p) {
  var lines = p.items.map(function (x) { return '· ' + x.title + ' × ' + x.qty + '   ' + won_(x.price * x.qty); }).join('\n');
  MailApp.sendEmail({
    to: o.email,
    name: prop_('STORE_NAME'),
    replyTo: prop_('OPERATOR_EMAIL') || Session.getEffectiveUser().getEmail(),
    subject: '[' + prop_('STORE_NAME') + '] 주문 요청을 받았어요 (' + o.no + ')',
    body: o.name + '님, 주문 요청을 받았습니다.\n\n' + lines +
      '\n\n' + (o.ship === 'delivery' ? '택배비 ' + (p.fee ? won_(p.fee) : '무료') : '매장 픽업') +
      '\n결제 예정 금액 ' + won_(p.total) +
      '\n\n아직 결제 전입니다. 도매처 입고가 확인되면 ' + o.phone + '로 결제 안내를 보내 드릴게요.' +
      '\n문의는 이 메일에 답장해 주세요.'
  });
}

/* ───────── 시트 ───────── */

function sheet_() {
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(SHEET) || ss.insertSheet(SHEET);
  if (sh.getLastRow() === 0) {
    sh.appendRow(HEAD);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, HEAD.length).setFontWeight('bold').setBackground('#f3efe7');
    sh.getRange('A:A').setNumberFormat('yyyy-mm-dd hh:mm');
    sh.getRange('L:N').setNumberFormat('#,##0');
    sh.getRange('C2:C').setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(STATUS, true).build());
    sh.getRange('J:J').setWrap(true);
  }
  return sh;
}

/** 처음 한 번 실행: 시트 준비 + 권한 허용 + 월 1회 개인정보 정리 트리거 */
function setup() {
  sheet_();
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'purgeOld') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('purgeOld').timeBased().onMonthDay(1).atHour(4).create();
  catalog_();  // 외부 요청 권한도 이때 함께 허용
  MailApp.getRemainingDailyQuota();
  Logger.log('준비 완료. 이제 배포 → 새 배포 → 웹 앱으로 배포하세요.');
}

/** 접수 1년이 지난 주문의 이름·연락처·이메일·주소·요청사항을 가림 (주문·금액 기록은 남김) */
function purgeOld() {
  var sh = SpreadsheetApp.getActive().getSheetByName(SHEET);
  if (!sh || sh.getLastRow() < 2) return;
  var cut = new Date(); cut.setFullYear(cut.getFullYear() - 1);
  var rng = sh.getRange(2, 1, sh.getLastRow() - 1, 9), v = rng.getValues(), n = 0;
  v.forEach(function (r) {
    if (r[0] instanceof Date && r[0] < cut && r[3] !== '(삭제)') { r[3] = '(삭제)'; r[4] = ''; r[5] = ''; r[7] = ''; r[8] = ''; n++; }
  });
  if (n) rng.setValues(v);
}

/* ───────── 도구 ───────── */

function clip_(s, n) { return String(s == null ? '' : s).replace(/[\u0000-\u0008\u000b-\u001f]/g, '').trim().slice(0, n); }
function safe_(s) { return /^[=+\-@]/.test(s) ? "'" + s : s; }   // 시트 수식 주입 방지
function won_(n) { return Number(n).toLocaleString('ko-KR') + '원'; }
function newNo_() {
  var d = Utilities.formatDate(new Date(), 'Asia/Seoul', 'MMdd'), a = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789', s = '';
  for (var i = 0; i < 4; i++) s += a.charAt(Math.floor(Math.random() * a.length));
  return 'BS-' + d + '-' + s;
}
function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
