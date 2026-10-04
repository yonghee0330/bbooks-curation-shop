/* C.books 크리스천북 큐레이팅 서비스 — 장바구니(localStorage) · 필터 · 탭 · 주문 요청 */
(function () {
  'use strict';
  var CFG = window.SHOP || {};
  var ROOT = CFG.root || '';
  var IDX = CFG.idx || '';
  var KEY = 'bbshop.cart.v1';
  var catalog = null;

  function $(s, el) { return (el || document).querySelector(s); }
  function $$(s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); }
  function won(n) { return Number(n).toLocaleString('ko-KR') + '원'; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  // ── 저장소 (사생활 보호 모드 등에서 실패해도 동작) ──
  var mem = {};
  function load(k, d) { try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return mem[k] || d; } }
  function save(k, v) { mem[k] = v; try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

  function cart() { return load(KEY, {}); }
  function setCart(c) { save(KEY, c); paint(); }
  function count(c) { return Object.keys(c).reduce(function (s, k) { return s + c[k]; }, 0); }
  function add(isbn, q) {
    var c = cart(); c[isbn] = Math.min(20, (c[isbn] || 0) + (q || 1)); setCart(c);
  }

  function getCatalog() {
    if (catalog) return Promise.resolve(catalog);
    return fetch(ROOT + 'data/catalog.json').then(function (r) { return r.json(); }).then(function (d) { catalog = d; return d; });
  }

  var tt;
  function toast(html) {
    var t = $('#toast'); if (!t) return;
    t.innerHTML = html; t.classList.add('show');
    clearTimeout(tt); tt = setTimeout(function () { t.classList.remove('show'); }, 2600);
  }

  function paint() {
    var c = cart(), n = count(c);
    $$('[data-cart-count]').forEach(function (el) { el.textContent = n ? n : ''; });
    $$('[data-add]').forEach(function (b) {
      var inCart = !!c[b.getAttribute('data-add')];
      b.classList.toggle('in', inCart);
      if (!b.dataset.label) b.dataset.label = b.textContent;
      b.textContent = inCart ? '✓ 담김' : b.dataset.label;
    });
  }

  function qtyOf(btn) {
    var box = btn.closest('.buybox'); var inp = box && $('[data-qty] input', box);
    return inp ? Math.max(1, Math.min(20, parseInt(inp.value, 10) || 1)) : 1;
  }

  document.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-add]');
    if (b) {
      var id = b.getAttribute('data-add'), c = cart();
      if (c[id] && !b.closest('.buybox')) { toast('이미 담겨 있어요 <a href="' + ROOT + 'cart/' + IDX + '">장바구니 보기</a>'); return; }
      add(id, qtyOf(b));
      toast('장바구니에 담았어요 <a href="' + ROOT + 'cart/' + IDX + '">주문하기 →</a>');
      return;
    }
    var m = ev.target.closest('[data-add-many]');
    if (m) {
      var ids = JSON.parse(m.getAttribute('data-add-many')), cc = cart(), added = 0;
      ids.forEach(function (i) { if (!cc[i]) { cc[i] = 1; added++; } });
      setCart(cc);
      toast((added ? added + '권을 담았어요' : '이미 모두 담겨 있어요') + ' <a href="' + ROOT + 'cart/' + IDX + '">장바구니 보기 →</a>');
      return;
    }
    var buy = ev.target.closest('[data-buy]');
    if (buy) {
      var bid = buy.getAttribute('data-buy'), c2 = cart();
      c2[bid] = Math.max(c2[bid] || 0, qtyOf(buy)); save(KEY, c2);
      location.href = ROOT + 'cart/' + IDX;
      return;
    }
    var q = ev.target.closest('[data-q]');
    if (q) {
      var inp = $('input', q.parentNode);
      inp.value = Math.max(1, Math.min(20, (parseInt(inp.value, 10) || 1) + parseInt(q.getAttribute('data-q'), 10)));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }
    var chip = ev.target.closest('[data-filter]');
    if (chip) {
      $$('[data-filter]').forEach(function (x) { x.classList.toggle('on', x === chip); });
      var f = chip.getAttribute('data-filter').split(' ');
      $$('#grid .card').forEach(function (card) {
        var s = (card.getAttribute('data-sections') || '').split(' ');
        card.hidden = !(f[0] === 'all' || f.some(function (k) { return s.indexOf(k) >= 0; }));
      });
      return;
    }
    var tab = ev.target.closest('[data-tab]');
    if (tab) {
      $$('[data-tab]').forEach(function (x) { x.classList.toggle('on', x === tab); });
      $$('[data-panel]').forEach(function (p) { p.hidden = p.getAttribute('data-panel') !== tab.getAttribute('data-tab'); });
    }
  });

  // ── 장바구니 페이지 ──
  function qbCtx() { return window.QB ? window.QB.ctx() : { member: false }; }
  function totals(c, cat, ship, ptsWanted) {
    var std = 0, sub = 0;
    Object.keys(c).forEach(function (i) { if (cat[i]) { std += cat[i].priceStandard * c[i]; sub += cat[i].price * c[i]; } });
    var p = CFG.pricing || {}, x = qbCtx(), mb = x.benefits || {};
    var freeOver = x.member && mb.free_shipping_over != null ? mb.free_shipping_over : (p.freeShippingOver || 0);
    var fee = ship === 'delivery' && sub < freeOver ? (p.shipping || 0) : 0;
    var pts = 0, earn = 0;
    if (x.member) {
      pts = Math.max(0, Math.min(ptsWanted || 0, x.points || 0, Math.floor(sub * (mb.max_points_ratio == null ? 1 : mb.max_points_ratio))));
      if (pts && pts < (mb.min_points_use || 0)) pts = 0;
      earn = Math.floor((sub - pts) * (mb.point_rate || 0));
    }
    return { std: std, sub: sub, fee: fee, pts: pts, earn: earn, total: sub - pts + fee, member: x.member };
  }

  function renderCart() {
    var list = $('#cart-list'); if (!list) return;
    getCatalog().then(function (cat) {
      var c = cart(), ids = Object.keys(c).filter(function (i) { return cat[i]; });
      $('#cart-empty').hidden = ids.length > 0;
      $('#cart-box').hidden = ids.length === 0;
      list.innerHTML = ids.map(function (i) {
        var b = cat[i];
        return '<li data-id="' + i + '">' +
          (b.cover ? '<img class="cover" src="' + ROOT + b.cover + '" alt="">' : '<div class="cover nocover"></div>') +
          '<div><a class="t" href="' + ROOT + 'b/' + i + '/' + IDX + '">' + esc(b.title) + '</a><span class="s">' + esc(b.publisher) + ' · ' + esc(b.recs[0] || '') + '</span></div>' +
          '<div class="r"><b>' + won(b.price * c[i]) + '</b><div class="qty" data-qty><button type="button" data-q="-1" aria-label="빼기">−</button><input type="number" min="1" max="20" value="' + c[i] + '" aria-label="수량"><button type="button" data-q="1" aria-label="더하기">+</button></div><button type="button" class="rm" data-rm="' + i + '">삭제</button></div></li>';
      }).join('');
      summary(cat);
    });
  }

  function summary(cat) {
    var form = $('#order'); if (!form) return;
    var ship = form.ship.value, t = totals(cart(), cat, ship, form.points ? parseInt(form.points.value, 10) || 0 : 0);
    $$('.addr', form).forEach(function (el) { el.hidden = ship !== 'delivery'; });
    var save = t.std - t.sub;
    $('#sum').innerHTML =
      '<div><span>정가 합계</span><span>' + won(t.std) + '</span></div>' +
      (save ? '<div><span>할인</span><span>−' + won(save) + '</span></div>' : '') +
      (t.pts ? '<div><span>적립금 사용</span><span>−' + won(t.pts) + '</span></div>' : '') +
      '<div><span>' + (ship === 'delivery' ? '택배비' : '매장 픽업') + '</span><span>' + (t.fee ? won(t.fee) : '무료') + '</span></div>' +
      '<div class="total"><span>결제 예정 금액</span><span>' + won(t.total) + '</span></div>' +
      (t.earn ? '<div class="earn"><span>적립 예정 (수령 완료 시)</span><span>+' + won(t.earn) + '</span></div>' : '');
  }

  function memberForm(cat) {
    var form = $('#order'); if (!form || !window.QB) return;
    window.QB.ready.then(function () {
      var x = qbCtx(), mb = x.benefits || {};
      $('#guest-box').hidden = x.member; $('#member-box').hidden = !x.member;
      $$('.member-only', form).forEach(function (el) { el.hidden = !x.member; });
      form.agree.required = !x.member;
      if (!x.member) {
        var gb = $('#guest-benefit');
        if (gb && mb.point_rate != null) gb.innerHTML = '회원으로 주문하면 ' + Math.round(mb.point_rate * 100) + '% 적립 · ' + won(mb.free_shipping_over) + ' 이상 무료배송 <a class="btn small" href="' + window.QB.loginUrl() + '">로그인 / 가입</a>';
        return summary(cat);
      }
      var p = x.profile || {};
      if (!form.name.value) form.name.value = p.name || '';
      if (!form.phone.value) form.phone.value = p.phone || '';
      if (!form.email.value) form.email.value = p.email || '';
      $('#member-points').textContent = won(x.points);
      $('#member-benefit').textContent = Math.round((mb.point_rate || 0) * 100) + '% 적립 · ' + won(mb.free_shipping_over) + ' 이상 무료배송 적용';
      var sel = $('#addr-pick');
      if (sel && x.addresses.length) {
        sel.innerHTML = '<option value="">새 주소 입력</option>' + x.addresses.map(function (a, i) { return '<option value="' + i + '"' + (a.is_default ? ' selected' : '') + '>' + esc((a.label || '배송지') + ' · ' + a.address1) + '</option>'; }).join('');
        sel.parentNode.hidden = false;
        var fill = function () { var a = x.addresses[sel.value]; if (!a) return; form.recipient.value = a.recipient; form.recipient_phone.value = a.phone; form.zipcode.value = a.zipcode || ''; form.address.value = a.address1; form.address2.value = a.address2 || ''; };
        sel.addEventListener('change', fill); fill();
      }
      $('#points-all').addEventListener('click', function () { form.points.value = x.points; summary(cat); });
      summary(cat);
    });
  }

  document.addEventListener('change', function (ev) {
    var li = ev.target.closest('.cart-list li');
    if (li && ev.target.matches('input[type=number]')) {
      var c = cart(); c[li.getAttribute('data-id')] = Math.max(1, Math.min(20, parseInt(ev.target.value, 10) || 1)); setCart(c); renderCart();
    }
    if (ev.target.name === 'ship' || ev.target.name === 'points') getCatalog().then(summary);
  });
  document.addEventListener('click', function (ev) {
    var rm = ev.target.closest('[data-rm]');
    if (rm) { var c = cart(); delete c[rm.getAttribute('data-rm')]; setCart(c); renderCart(); }
  });

  function orderNo() {
    var d = new Date(), a = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789', s = '';
    for (var i = 0; i < 4; i++) s += a[Math.floor(Math.random() * a.length)];
    return 'BS-' + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0') + '-' + s;
  }

  var form = $('#order');
  if (form) {
    $('#demo-note').hidden = !!CFG.apiUrl;
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var bad = [];
      ['name', 'phone'].forEach(function (k) { if (!form[k].value.trim()) bad.push(form[k]); });
      if (!/^0\d{1,2}-?\d{3,4}-?\d{4}$/.test(form.phone.value.trim())) bad.push(form.phone);
      if (form.ship.value === 'delivery' && !form.address.value.trim()) bad.push(form.address);
      if (form.agree.required && !form.agree.checked) bad.push(form.agree);
      $$('.err', form).forEach(function (x) { x.classList.remove('err'); });
      if (bad.length) { bad.forEach(function (x) { x.classList.add('err'); }); bad[0].focus(); toast('표시된 칸을 확인해 주세요'); return; }
      getCatalog().then(function (cat) {
        var c = cart(), t = totals(c, cat, form.ship.value, form.points ? parseInt(form.points.value, 10) || 0 : 0);
        var order = {
          no: orderNo(), at: new Date().toISOString(),
          name: form.name.value.trim(), phone: form.phone.value.trim(), email: form.email.value.trim(),
          ship: form.ship.value, address: [form.address.value.trim(), form.address2 ? form.address2.value.trim() : ''].filter(Boolean).join(' '), note: form.note.value.trim(), website: form.website ? form.website.value : '',
          items: Object.keys(c).filter(function (i) { return cat[i]; }).map(function (i) {
            return { isbn13: i, title: cat[i].title, publisher: cat[i].publisher, qty: c[i], price: cat[i].price, priceStandard: cat[i].priceStandard, from: cat[i].recs[0] || '' };
          }),
          subtotal: t.sub, shipping: t.fee, total: t.total
        };
        var btn = $('button[type=submit]', form); btn.disabled = true; btn.textContent = '보내는 중…';
        var send;
        if (window.QB) {
          if (order.website) return;
          send = window.QB.placeOrder({
            name: order.name, phone: order.phone, email: order.email, ship: order.ship,
            recipient: form.recipient && form.recipient.value.trim() || order.name, recipient_phone: form.recipient_phone && form.recipient_phone.value.trim() || order.phone,
            zipcode: form.zipcode ? form.zipcode.value.trim() : '', address1: form.address.value.trim(), address2: form.address2 ? form.address2.value.trim() : '',
            memo: order.note, points_use: t.pts, guest_privacy_agreed: !!form.agree.checked, save_address: !!(form.save_address && form.save_address.checked),
            items: order.items.map(function (x) { return { isbn13: x.isbn13, qty: x.qty, source: x.from }; })
          }).then(function (r) { order.no = r.order_no; order.subtotal = r.subtotal; order.shipping = r.shipping; order.total = r.total; order.pts = r.points_used; order.earn = r.points_to_earn; order.member = r.member; return { ok: true }; });
        } else {
          send = CFG.apiUrl
          ? fetch(CFG.apiUrl, { method: 'POST', headers: { 'Content-Type': 'text/plain;charset=utf-8' }, body: JSON.stringify({ action: 'order', order: order }) })
              .then(function (r) { return r.json(); }).then(function (res) { if (!res || !res.ok) throw new Error((res && res.error) || '접수 실패'); return res; })
          : Promise.resolve({ ok: true, demo: true });
        }
        send.then(function (res) {
          if (res && res.total != null) { order.subtotal = res.subtotal; order.shipping = res.shipping; order.total = res.total; }
          delete order.website;
          var hist = load('bbshop.orders', []); hist.unshift(order); save('bbshop.orders', hist.slice(0, 20));
          save(KEY, {}); paint();
          var lines = order.items.map(function (x) { return '· ' + x.title + ' × ' + x.qty + '  ' + won(x.price * x.qty); }).join('\n');
          var txt = '[' + (CFG.brand || 'C.books') + ' 주문 ' + order.no + ']\n' + lines + '\n' + (order.pts ? '적립금 사용 −' + won(order.pts) + '\n' : '') + (order.ship === 'delivery' ? '택배 ' + (order.shipping ? won(order.shipping) : '무료') : '매장 픽업') + '\n합계 ' + won(order.total);
          $('#cart-box').hidden = true;
          var done = $('#done'); done.hidden = false;
          done.innerHTML = '<h2>주문 요청을 받았어요</h2><p>주문번호 <b>' + order.no + '</b></p><p class="muted">' + esc(CFG.eta || '') + '<br>입고가 확인되면 ' + esc(order.phone) + '로 결제 안내를 보내 드릴게요.</p><pre>' + esc(txt) + '</pre>' +
            (CFG.apiUrl || window.QB ? '' : '<p class="demo-note">데모 모드: 이 주문은 서점으로 전송되지 않았습니다.</p>') +
            (order.earn ? '<p>수령 완료 시 적립금 <b>' + won(order.earn) + '</b>이 쌓여요.</p>' : '') +
            (window.QB ? '<p class="small">' + (order.member ? '<a href="' + ROOT + 'me/' + IDX + '">내 주문에서 진행 상황 보기 →</a>' : '주문 조회: <a href="' + ROOT + 'order/' + IDX + '?no=' + encodeURIComponent(order.no) + '">주문번호와 휴대폰 번호로 조회 →</a>') + '</p>' : '') +
            '<div class="row" style="justify-content:center"><button class="btn" id="copy">주문 내용 복사</button><a class="btn primary" href="' + ROOT + IDX + '">계속 둘러보기</a></div>';
          $('#copy').onclick = function () { (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(function () { toast('복사했어요'); }, function () { toast('복사하지 못했어요'); }); };
          window.scrollTo(0, 0);
        }).catch(function (err) {
          btn.disabled = false; btn.textContent = '주문 요청하기';
          toast('주문을 보내지 못했어요: ' + esc(err.message) + ' — 잠시 후 다시 시도해 주세요');
        });
      });
    });
  }

  window.SHOP_PAINT = paint;
  paint();
  renderCart();
  if ($('#order')) { $$('.member-only').forEach(function (el) { el.hidden = true; }); getCatalog().then(memberForm); }
})();
