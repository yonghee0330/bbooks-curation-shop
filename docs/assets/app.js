/* 비북스 큐레이션 서점 — 장바구니(localStorage) · 필터 · 탭 · 주문 요청 */
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
  function totals(c, cat, ship) {
    var std = 0, sub = 0;
    Object.keys(c).forEach(function (i) { if (cat[i]) { std += cat[i].priceStandard * c[i]; sub += cat[i].price * c[i]; } });
    var p = CFG.pricing || {};
    var fee = ship === 'delivery' && sub < (p.freeShippingOver || 0) ? (p.shipping || 0) : 0;
    return { std: std, sub: sub, fee: fee, total: sub + fee };
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
    var ship = form.ship.value, t = totals(cart(), cat, ship);
    $('.addr', form).hidden = ship !== 'delivery';
    var save = t.std - t.sub;
    $('#sum').innerHTML =
      '<div><span>정가 합계</span><span>' + won(t.std) + '</span></div>' +
      (save ? '<div><span>비북스 할인</span><span>−' + won(save) + '</span></div>' : '') +
      '<div><span>' + (ship === 'delivery' ? '택배비' : '매장 픽업') + '</span><span>' + (t.fee ? won(t.fee) : '무료') + '</span></div>' +
      '<div class="total"><span>결제 예정 금액</span><span>' + won(t.total) + '</span></div>';
  }

  document.addEventListener('change', function (ev) {
    var li = ev.target.closest('.cart-list li');
    if (li && ev.target.matches('input[type=number]')) {
      var c = cart(); c[li.getAttribute('data-id')] = Math.max(1, Math.min(20, parseInt(ev.target.value, 10) || 1)); setCart(c); renderCart();
    }
    if (ev.target.name === 'ship') getCatalog().then(summary);
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
      if (!form.agree.checked) bad.push(form.agree);
      $$('.err', form).forEach(function (x) { x.classList.remove('err'); });
      if (bad.length) { bad.forEach(function (x) { x.classList.add('err'); }); bad[0].focus(); toast('표시된 칸을 확인해 주세요'); return; }
      getCatalog().then(function (cat) {
        var c = cart(), t = totals(c, cat, form.ship.value);
        var order = {
          no: orderNo(), at: new Date().toISOString(),
          name: form.name.value.trim(), phone: form.phone.value.trim(), email: form.email.value.trim(),
          ship: form.ship.value, address: form.address.value.trim(), note: form.note.value.trim(),
          items: Object.keys(c).filter(function (i) { return cat[i]; }).map(function (i) {
            return { isbn13: i, title: cat[i].title, publisher: cat[i].publisher, qty: c[i], price: cat[i].price, priceStandard: cat[i].priceStandard, from: cat[i].recs[0] || '' };
          }),
          subtotal: t.sub, shipping: t.fee, total: t.total
        };
        var btn = $('button[type=submit]', form); btn.disabled = true; btn.textContent = '보내는 중…';
        var send = CFG.apiUrl
          ? fetch(CFG.apiUrl, { method: 'POST', headers: { 'Content-Type': 'text/plain;charset=utf-8' }, body: JSON.stringify({ action: 'order', order: order }) })
              .then(function (r) { return r.json(); }).then(function (res) { if (!res || !res.ok) throw new Error((res && res.error) || '접수 실패'); return res; })
          : Promise.resolve({ ok: true, demo: true });
        send.then(function () {
          var hist = load('bbshop.orders', []); hist.unshift(order); save('bbshop.orders', hist.slice(0, 20));
          save(KEY, {}); paint();
          var lines = order.items.map(function (x) { return '· ' + x.title + ' × ' + x.qty + '  ' + won(x.price * x.qty); }).join('\n');
          var txt = '[비북스 주문 ' + order.no + ']\n' + lines + '\n' + (order.ship === 'delivery' ? '택배 ' + (order.shipping ? won(order.shipping) : '무료') : '매장 픽업') + '\n합계 ' + won(order.total);
          $('#cart-box').hidden = true;
          var done = $('#done'); done.hidden = false;
          done.innerHTML = '<h2>주문 요청을 받았어요</h2><p>주문번호 <b>' + order.no + '</b></p><p class="muted">' + esc(CFG.eta || '') + '<br>입고가 확인되면 ' + esc(order.phone) + '로 결제 안내를 보내 드릴게요.</p><pre>' + esc(txt) + '</pre>' +
            (CFG.apiUrl ? '' : '<p class="demo-note">데모 모드: 이 주문은 서점으로 전송되지 않았습니다.</p>') +
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

  paint();
  renderCart();
})();
