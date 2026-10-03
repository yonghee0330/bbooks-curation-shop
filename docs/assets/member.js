/* Q.books(가칭) 회원 — Supabase 로그인(구글·카카오) · 가입 동의 · 내 정보 · 주문 조회 · 운영자 */
(function () {
  'use strict';
  var CFG = window.SHOP || {}, SB = CFG.supabase || {}, ROOT = CFG.root || '', IDX = CFG.idx || '';
  var PAGE = document.body.getAttribute('data-page') || '';
  var BRAND = CFG.brand || 'Q.books';

  function $(s, el) { return (el || document).querySelector(s); }
  function $$(s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function won(n) { return Number(n || 0).toLocaleString('ko-KR') + '원'; }
  function dt(s) { var d = new Date(s); return d.getFullYear() + '. ' + (d.getMonth() + 1) + '. ' + d.getDate() + '. ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }
  function abs(path) { return new URL(ROOT + path, location.href).href; }
  function go(path) { location.href = ROOT + path + IDX; }
  function toast(m) { var t = $('#toast'); if (!t) return alert(m); t.innerHTML = esc(m); t.classList.add('show'); setTimeout(function () { t.classList.remove('show'); }, 2800); }
  function errMsg(e) { return (e && (e.message || e.error_description)) || '잠시 후 다시 시도해 주세요'; }

  var STATUS = {
    requested: ['주문 접수', '도매처에 입고를 요청했어요'],
    stocked: ['입고 완료', '책이 서점에 도착했어요'],
    payment_requested: ['결제 안내', '문자로 결제 안내를 보냈어요'],
    paid: ['결제 완료', '결제를 확인했어요'],
    shipped: ['발송', '택배로 보냈어요'],
    ready_pickup: ['픽업 대기', '서점에서 찾아가실 수 있어요'],
    completed: ['수령 완료', '책을 받으셨어요'],
    cancelled: ['취소', '주문이 취소됐어요']
  };
  function stLabel(s) { return (STATUS[s] || [s])[0]; }

  var configured = !!(SB.url && SB.anonKey && window.supabase && window.supabase.createClient);
  if (!configured) {
    $$('[data-account]').forEach(function (a) { a.hidden = true; });
    window.QB = null;
    if (PAGE && PAGE !== 'cart') $$('[data-need-sb]').forEach(function (el) { el.innerHTML = '<p class="muted">회원 기능을 준비하고 있어요.</p>'; });
    return;
  }

  var sb = window.supabase.createClient(SB.url, SB.anonKey, { auth: { persistSession: true, detectSessionInUrl: true, flowType: 'pkce' } });
  var S = { user: null, profile: null, points: 0, settings: {}, addresses: [], admin: false };

  function rpc(name, args) {
    return sb.rpc(name, args || {}).then(function (r) { if (r.error) throw r.error; return r.data; });
  }
  function q(p) { return p.then(function (r) { if (r.error) throw r.error; return r.data; }); }

  var ready = sb.auth.getSession().then(function (r) {
    S.user = r.data.session ? r.data.session.user : null;
    var jobs = [q(sb.from('settings').select('key,value')).then(function (rows) { rows.forEach(function (x) { S.settings[x.key] = x.value; }); })];
    if (S.user) {
      jobs.push(q(sb.from('profiles').select('*').eq('id', S.user.id).maybeSingle()).then(function (p) { S.profile = p; }));
      jobs.push(rpc('point_balance', { uid: S.user.id }).then(function (n) { S.points = n || 0; }));
      jobs.push(q(sb.from('addresses').select('*').eq('user_id', S.user.id).order('is_default', { ascending: false }).order('created_at')).then(function (a) { S.addresses = a || []; }));
      jobs.push(q(sb.from('admins').select('user_id').eq('user_id', S.user.id)).then(function (a) { S.admin = (a || []).length > 0; }));
    }
    return Promise.all(jobs);
  }).then(function () {
    S.member = !!(S.profile && S.profile.signup_completed_at && !S.profile.withdrawn_at);
    header();
    if (S.user && !S.member && PAGE !== 'join' && PAGE !== 'terms' && PAGE !== 'privacy') {
      return go('join/?next=' + encodeURIComponent(location.pathname + location.search));
    }
    return S;
  }).catch(function (e) { console.error(e); header(); return S; });

  function header() {
    $$('[data-account]').forEach(function (a) {
      a.hidden = false;
      if (S.user) { a.textContent = S.member ? (S.profile.name || '내 정보') + '님' : '가입 마무리'; a.href = ROOT + (S.member ? 'me/' : 'join/') + IDX; }
      else { a.textContent = '로그인'; a.href = ROOT + 'login/' + IDX + '?next=' + encodeURIComponent(location.pathname + location.search); }
    });
  }

  function nextUrl(def) {
    var n = new URLSearchParams(location.search).get('next');
    return n && n.charAt(0) === '/' && n.indexOf('//') !== 0 ? n : ROOT + def + IDX;
  }

  // ───────── 장바구니 연동 (app.js 가 사용) ─────────
  window.QB = {
    ready: ready,
    ctx: function () {
      var mb = S.settings.member_benefits || {}, pr = S.settings.pricing || {};
      return { member: S.member, profile: S.profile, points: S.points, addresses: S.addresses, benefits: mb, pricing: pr, user: S.user };
    },
    placeOrder: function (payload) { return rpc('place_order', { p: payload }); },
    loginUrl: function () { return ROOT + 'login/' + IDX + '?next=' + encodeURIComponent(location.pathname); }
  };

  // ───────── 로그인 ─────────
  if (PAGE === 'login') {
    ready.then(function () {
      if (S.user) return location.replace(S.member ? nextUrl('me/') : ROOT + 'join/' + IDX + location.search);
      $$('[data-provider]').forEach(function (b) {
        if ((CFG.providers || ['google']).indexOf(b.getAttribute('data-provider')) < 0) { b.hidden = true; return; }
        b.addEventListener('click', function () {
          var redirect = abs('login/' + IDX) + (location.search || '');
          b.disabled = true;
          sb.auth.signInWithOAuth({ provider: b.getAttribute('data-provider'), options: { redirectTo: redirect } })
            .then(function (r) { if (r.error) { b.disabled = false; toast(errMsg(r.error)); } });
        });
      });
    });
  }

  // ───────── 가입 마무리: 약관 동의 + 정보 ─────────
  if (PAGE === 'join') {
    ready.then(function () {
      var f = $('#join');
      if (!S.user) return go('login/');
      if (S.member) return location.replace(nextUrl('me/'));
      var mb = S.settings.member_benefits || {};
      $('#join-benefit').textContent = '가입하면 적립금 ' + won(mb.welcome_points) + ' · 주문마다 ' + Math.round((mb.point_rate || 0) * 100) + '% 적립 · ' + won(mb.free_shipping_over) + ' 이상 무료배송';
      f.name.value = (S.profile && S.profile.name) || '';
      $('#join-email').textContent = S.user.email || '(이메일 없음)';
      f.hidden = false;
      var req = ['terms', 'privacy', 'age14'], opt = ['marketing_email', 'marketing_sms'];
      f.all.addEventListener('change', function () { req.concat(opt).forEach(function (k) { f[k].checked = f.all.checked; }); });
      f.addEventListener('change', function (ev) { if (ev.target !== f.all) f.all.checked = req.concat(opt).every(function (k) { return f[k].checked; }); });
      f.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var c = {}; req.concat(opt).forEach(function (k) { c[k] = f[k].checked; });
        if (!req.every(function (k) { return c[k]; })) return toast('필수 항목에 모두 동의해 주세요');
        var btn = $('button[type=submit]', f); btn.disabled = true;
        rpc('complete_signup', { p_name: f.name.value, p_phone: f.phone.value, p_consents: c })
          .then(function (r) { toast('가입을 마쳤어요. 적립금 ' + won(r.points)); setTimeout(function () { location.replace(nextUrl('me/')); }, 900); })
          .catch(function (e) { btn.disabled = false; toast(errMsg(e)); });
      });
      $('#join-cancel').addEventListener('click', function () {
        if (!confirm('가입을 그만두고 로그인 정보를 지울까요?')) return;
        rpc('withdraw_me').then(function () { return sb.auth.signOut(); }).then(function () { go(''); });
      });
    });
  }

  // ───────── 주문 표시 공통 ─────────
  function orderCard(o, items, events, opts) {
    opts = opts || {};
    var st = STATUS[o.status] || [o.status, ''];
    var steps = o.ship_method === 'delivery'
      ? ['requested', 'stocked', 'payment_requested', 'paid', 'shipped', 'completed']
      : ['requested', 'stocked', 'payment_requested', 'paid', 'ready_pickup', 'completed'];
    var idx = steps.indexOf(o.status);
    var bar = o.status === 'cancelled' ? '<p class="st-cancel">취소된 주문</p>' :
      '<ol class="steps">' + steps.map(function (s, i) { return '<li class="' + (i < idx ? 'done' : i === idx ? 'now' : '') + '">' + stLabel(s) + '</li>'; }).join('') + '</ol>';
    var lines = (items || []).map(function (i) {
      return '<li><a href="' + ROOT + 'b/' + esc(i.isbn13) + '/' + IDX + '">' + esc(i.title) + '</a> <span class="muted">× ' + i.qty + '</span><span>' + won(i.price * i.qty) + '</span></li>';
    }).join('');
    var ev = (events || []).map(function (e) { return '<li><b>' + esc(stLabel(e.status)) + '</b> <span class="muted">' + dt(e.at || e.created_at) + '</span>' + (e.note ? ' · ' + esc(e.note) : '') + '</li>'; }).join('');
    return '<article class="ord">' +
      '<header><div><span class="kicker">' + dt(o.created_at) + (o.is_member ? ' · 회원 주문' : ' · 비회원 주문') + '</span><h3>' + esc(o.order_no) + '</h3></div><span class="badge st-' + esc(o.status) + '">' + esc(st[0]) + '</span></header>' +
      bar + '<p class="muted small">' + esc(st[1]) + '</p>' +
      '<ul class="ord-items">' + lines + '</ul>' +
      '<dl class="ord-sum"><dt>도서</dt><dd>' + won(o.subtotal) + ' <small class="muted">(정가 ' + won(o.subtotal_standard) + ')</small></dd>' +
      (o.points_used ? '<dt>적립금 사용</dt><dd>−' + won(o.points_used) + '</dd>' : '') +
      '<dt>' + (o.ship_method === 'delivery' ? '택배비' : '매장 픽업') + '</dt><dd>' + (o.shipping_fee ? won(o.shipping_fee) : '무료') + '</dd>' +
      '<dt><b>결제 금액</b></dt><dd><b>' + won(o.total) + '</b></dd>' +
      (o.points_to_earn ? '<dt>적립 예정</dt><dd>' + won(o.points_to_earn) + ' <small class="muted">(수령 완료 시)</small></dd>' : '') + '</dl>' +
      '<p class="small">' + (o.ship_method === 'delivery' ? '택배 · ' + esc([o.recipient, o.address1, o.address2].filter(Boolean).join(' ')) : '매장 픽업') +
      (o.tracking_no ? ' · 송장 ' + esc((o.carrier || '') + ' ' + o.tracking_no) : '') + '</p>' +
      (ev ? '<details><summary>진행 기록</summary><ul class="ord-ev">' + ev + '</ul></details>' : '') +
      (opts.cancel && o.status === 'requested' ? '<button class="btn small" data-cancel="' + esc(o.id) + '">주문 취소</button>' : '') +
      '</article>';
  }

  // ───────── 내 정보 ─────────
  if (PAGE === 'me') {
    ready.then(function () {
      if (!S.user) return go('login/?next=' + encodeURIComponent(location.pathname));
      var p = S.profile, mb = S.settings.member_benefits || {};
      $('#me-box').hidden = false;
      $('#me-name').textContent = p.name || '';
      $('#me-sub').textContent = (p.email || '') + ' · ' + (p.provider === 'kakao' ? '카카오' : p.provider === 'google' ? '구글' : p.provider || '') + ' 로그인 · ' + dt(p.signup_completed_at) + ' 가입';
      $('#me-points').textContent = won(S.points);
      $('#me-benefit').textContent = '주문마다 ' + Math.round((mb.point_rate || 0) * 100) + '% 적립 · ' + won(mb.free_shipping_over) + ' 이상 무료배송';
      if (S.admin) $('#me-admin').hidden = false;

      var pf = $('#profile'); pf.name.value = p.name || ''; pf.phone.value = p.phone || '';
      pf.addEventListener('submit', function (ev) {
        ev.preventDefault();
        rpc('update_profile', { p_name: pf.name.value, p_phone: pf.phone.value }).then(function () { toast('저장했어요'); $('#me-name').textContent = pf.name.value; }).catch(function (e) { toast(errMsg(e)); });
      });
      var mk = $('#marketing'); mk.email.checked = p.marketing_email; mk.sms.checked = p.marketing_sms;
      mk.addEventListener('change', function () {
        rpc('set_marketing', { p_email: mk.email.checked, p_sms: mk.sms.checked }).then(function () { toast('수신 설정을 바꿨어요 (' + dt(new Date()) + ')'); }).catch(function (e) { toast(errMsg(e)); });
      });

      function loadOrders() {
        return q(sb.from('orders').select('*, order_items(*), order_events(status,note,created_at)').eq('user_id', S.user.id).order('created_at', { ascending: false }).limit(50)).then(function (rows) {
          $('#me-orders').innerHTML = rows.length ? rows.map(function (o) {
            o.order_events.sort(function (a, b) { return a.created_at < b.created_at ? -1 : 1; });
            return orderCard(o, o.order_items, o.order_events, { cancel: true });
          }).join('') : '<p class="muted">아직 주문이 없어요. <a href="' + ROOT + IDX + '">추천 도서 보러 가기 →</a></p>';
        });
      }
      loadOrders();
      $('#me-orders').addEventListener('click', function (ev) {
        var b = ev.target.closest('[data-cancel]'); if (!b) return;
        if (!confirm('이 주문을 취소할까요?')) return;
        rpc('cancel_my_order', { p_order_id: b.getAttribute('data-cancel') }).then(function () { toast('취소했어요'); loadOrders(); }).catch(function (e) { toast(errMsg(e)); });
      });

      q(sb.from('point_ledger').select('*').eq('user_id', S.user.id).order('created_at', { ascending: false }).limit(30)).then(function (rows) {
        var R = { welcome: '가입 축하', order_use: '주문 사용', order_earn: '주문 적립', order_cancel_refund: '취소 환급', order_cancel_revoke: '취소 회수', admin: '서점 조정', expire: '소멸' };
        $('#me-ledger').innerHTML = rows.map(function (x) {
          return '<li><span>' + esc(R[x.reason] || x.reason) + (x.note ? ' · ' + esc(x.note) : '') + '<small class="muted"> ' + dt(x.created_at) + '</small></span><b class="' + (x.delta < 0 ? 'minus' : 'plus') + '">' + (x.delta > 0 ? '+' : '') + won(x.delta) + '</b></li>';
        }).join('') || '<li class="muted">기록이 없어요</li>';
      });

      function drawAddr() {
        $('#me-addr').innerHTML = S.addresses.map(function (a) {
          return '<li><div><b>' + esc(a.label || '배송지') + '</b>' + (a.is_default ? ' <span class="badge">기본</span>' : '') + '<br>' + esc(a.recipient) + ' · ' + esc(a.phone) + '<br><span class="muted">' + esc([a.zipcode, a.address1, a.address2].filter(Boolean).join(' ')) + '</span></div><button class="btn small" data-del-addr="' + a.id + '">삭제</button></li>';
        }).join('') || '<li class="muted">저장한 배송지가 없어요</li>';
      }
      drawAddr();
      $('#me-addr').addEventListener('click', function (ev) {
        var b = ev.target.closest('[data-del-addr]'); if (!b || !confirm('이 배송지를 지울까요?')) return;
        q(sb.from('addresses').delete().eq('id', b.getAttribute('data-del-addr'))).then(function () {
          S.addresses = S.addresses.filter(function (a) { return a.id !== b.getAttribute('data-del-addr'); }); drawAddr();
        }).catch(function (e) { toast(errMsg(e)); });
      });
      var af = $('#addr-form');
      af.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var row = { user_id: S.user.id, label: af.label.value || '배송지', recipient: af.recipient.value, phone: af.phone.value, zipcode: af.zipcode.value, address1: af.address1.value, address2: af.address2.value, is_default: !S.addresses.length };
        if (!row.recipient || !row.phone || !row.address1) return toast('받는 분, 연락처, 주소를 적어 주세요');
        q(sb.from('addresses').insert(row).select().single()).then(function (a) { S.addresses.push(a); drawAddr(); af.reset(); toast('배송지를 저장했어요'); }).catch(function (e) { toast(errMsg(e)); });
      });

      $('#logout').addEventListener('click', function () { sb.auth.signOut().then(function () { go(''); }); });
      $('#withdraw').addEventListener('click', function () {
        var w = prompt('탈퇴하면 회원 정보·배송지·적립금(' + won(S.points) + ')이 바로 삭제됩니다.\n주문 기록은 전자상거래법에 따라 5년간 회원 정보와 분리해 보관합니다.\n\n탈퇴하려면 "탈퇴"라고 입력해 주세요.');
        if (w !== '탈퇴') return;
        rpc('withdraw_me').then(function () { return sb.auth.signOut(); }).then(function () { alert('탈퇴했어요. 그동안 고마웠습니다.'); go(''); }).catch(function (e) { toast(errMsg(e)); });
      });
    });
  }

  // ───────── 주문 조회 (비회원) ─────────
  if (PAGE === 'order') {
    ready.then(function () {
      var f = $('#lookup'), out = $('#lookup-out');
      var qs = new URLSearchParams(location.search);
      if (qs.get('no')) f.no.value = qs.get('no');
      if (S.member) $('#lookup-member').hidden = false;
      f.addEventListener('submit', function (ev) {
        ev.preventDefault();
        rpc('lookup_order', { p_order_no: f.no.value, p_phone: f.phone.value }).then(function (r) {
          out.innerHTML = r ? orderCard(r.order, r.items, r.events) : '<p class="muted">주문번호와 휴대폰 번호가 맞는 주문을 찾지 못했어요.</p>';
        }).catch(function (e) { toast(errMsg(e)); });
      });
    });
  }

  // ───────── 운영자 ─────────
  if (PAGE === 'admin') {
    ready.then(function () {
      if (!S.user) return go('login/?next=' + encodeURIComponent(location.pathname));
      if (!S.admin) { $('#adm').innerHTML = '<p class="muted">운영자 계정이 아니에요.</p>'; return; }
      var filt = $('#adm-filter'), list = $('#adm-list');
      function load() {
        var qy = sb.from('orders').select('*, order_items(*), order_events(status,note,created_at)').order('created_at', { ascending: false }).limit(200);
        if (filt.value === 'open') qy = qy.not('status', 'in', '(completed,cancelled)');
        else if (filt.value) qy = qy.eq('status', filt.value);
        q(qy).then(function (rows) {
          $('#adm-count').textContent = rows.length + '건';
          list.innerHTML = rows.map(function (o) {
            o.order_events.sort(function (a, b) { return a.created_at < b.created_at ? -1 : 1; });
            var opts = Object.keys(STATUS).map(function (s) { return '<option value="' + s + '"' + (s === o.status ? ' selected' : '') + '>' + STATUS[s][0] + '</option>'; }).join('');
            return '<div class="adm-row">' + orderCard(o, o.order_items, o.order_events) +
              '<div class="adm-who"><b>' + esc(o.buyer_name) + '</b> ' + esc(o.buyer_phone) + (o.buyer_email ? ' · ' + esc(o.buyer_email) : '') + (o.memo ? '<br>요청: ' + esc(o.memo) : '') + '</div>' +
              '<form class="adm-form" data-id="' + o.id + '"><select name="status">' + opts + '</select>' +
              '<input name="carrier" placeholder="택배사" value="' + esc(o.carrier || '') + '"><input name="tracking" placeholder="송장번호" value="' + esc(o.tracking_no || '') + '">' +
              '<input name="note" placeholder="메모(고객에게 보임)"><button class="btn small primary">저장</button></form></div>';
          }).join('') || '<p class="muted">주문이 없어요</p>';
        }).catch(function (e) { toast(errMsg(e)); });
      }
      filt.addEventListener('change', load);
      list.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var f = ev.target;
        rpc('admin_set_status', { p_order_id: f.getAttribute('data-id'), p_status: f.status.value, p_note: f.note.value || null, p_carrier: f.carrier.value, p_tracking: f.tracking.value })
          .then(function () { toast('저장했어요'); load(); }).catch(function (e) { toast(errMsg(e)); });
      });
      $('#adm').hidden = false;
      load();
    });
  }
})();
