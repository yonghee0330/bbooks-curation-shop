/* 탐색 — data/index.json 을 매체·기간·코너·겹침·검색으로 조합 */
document.addEventListener('DOMContentLoaded', function () {
  'use strict';
  var CFG = window.SHOP || {}, ROOT = CFG.root || '', IDX = CFG.idx || '';
  var form = document.getElementById('xf'), res = document.getElementById('xres'), cnt = document.getElementById('xcount'), more = document.getElementById('xmore');
  var D = null, view = 'books', shown = 0, list = [], PAGE = 48;

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function won(n) { return Number(n).toLocaleString('ko-KR') + '원'; }
  function chip(m) { var x = D.media[m]; return '<span class="mchip" style="--mc:' + x[1] + '">' + esc(x[0]) + '</span>'; }
  function vals(name) { return Array.prototype.slice.call(form.querySelectorAll('input[name=' + name + ']:checked')).map(function (i) { return i.value; }); }

  // 주소로 미리 고르기: ?multi  ?m=teum  ?q=검색어
  var qs = location.search.replace(/^\?/, '').split('&');
  qs.forEach(function (kv) {
    var p = kv.split('='), k = p[0], v = decodeURIComponent(p[1] || '');
    if (k === 'multi') form.multi.value = '2';
    if (k === 'm' && v) Array.prototype.forEach.call(form.querySelectorAll('input[name=m]'), function (i) { i.checked = i.value === v; });
    if (k === 'q') form.q.value = v;
  });
  if (form.to.options.length) form.to.selectedIndex = 0;

  function run() {
    var ms = vals('m'), gs = vals('g'), from = form.from.value, to = form.to.value, multi = +form.multi.value;
    var q = form.q.value.trim().toLowerCase(), sort = form.sort.value;
    var books = [], recs = [];
    D.books.forEach(function (b) {
      var rs = b.r.filter(function (r) {
        var ym = r[2].slice(0, 7);
        return ms.indexOf(r[0]) >= 0 && gs.indexOf(D.groups[r[3]] || (r[0] === 'yong' ? 'house' : 'review')) >= 0 && ym >= from && ym <= to;
      });
      if (!rs.length) return;
      var allMedia = {}; b.r.forEach(function (r) { if (r[0] !== 'yong') allMedia[r[0]] = 1; });
      if (Object.keys(allMedia).length < multi) return;
      if (q && (b.t + ' ' + b.a + ' ' + b.p + ' ' + b.cat + ' ' + rs.map(function (r) { return r[5]; }).join(' ')).toLowerCase().indexOf(q) < 0) return;
      var last = rs.reduce(function (m, r) { return r[2] > m ? r[2] : m; }, '');
      books.push({ b: b, rs: rs, last: last, n: Object.keys(allMedia).length });
      rs.forEach(function (r) { recs.push({ b: b, r: r }); });
    });
    var by = {
      recent: function (x, y) { return x.last < y.last ? 1 : -1; },
      many: function (x, y) { return (y.n - x.n) || (y.b.r.length - x.b.r.length) || (x.last < y.last ? 1 : -1); },
      title: function (x, y) { return x.b.t.localeCompare(y.b.t, 'ko'); },
      pub: function (x, y) { return x.b.pd < y.b.pd ? 1 : -1; }
    };
    books.sort(by[sort]);
    recs.sort(function (x, y) { return x.r[2] < y.r[2] ? 1 : -1; });
    list = view === 'books' ? books : recs;
    cnt.textContent = view === 'books' ? books.length + '권 · 추천 ' + recs.length + '편' : '추천 ' + recs.length + '편 · ' + books.length + '권';
    res.className = view === 'books' ? 'grid' : 'recs';
    res.innerHTML = ''; shown = 0; page();
  }

  function card(x) {
    var b = x.b, ms = {};
    b.r.forEach(function (r) { ms[r[0]] = 1; });
    var lead = x.rs[0];
    return '<article class="card"><a class="card-cover" href="' + ROOT + 'b/' + b.i + '/' + IDX + '"><img class="cover" src="' + esc(b.c) + '" alt="" loading="lazy" referrerpolicy="no-referrer"></a>' +
      '<div class="card-body"><div class="mchips">' + Object.keys(ms).map(chip).join('') + '</div>' +
      '<h3><a href="' + ROOT + 'b/' + b.i + '/' + IDX + '">' + esc(b.t) + '</a></h3><p class="meta">' + esc(b.a) + ' · ' + esc(b.p) + '</p>' +
      '<p class="by">' + esc(D.media[lead[0]][0] + ' ' + lead[4]) + (lead[5] ? ' · ' + esc(lead[5]) : '') + ' · ' + lead[2].slice(0, 7).replace('-', '.') + '</p>' +
      '<div class="card-foot"><span class="price"><s>' + won(b.ps) + '</s> <b>' + won(b.pr) + '</b></span><button class="btn add" data-add="' + b.i + '">담기</button></div></div></article>';
  }

  function recRow(x) {
    var b = x.b, r = x.r, iss = D.issues[r[0] + '/' + r[1]] || ['', ''];
    return '<article class="rec" style="--mc:' + D.media[r[0]][1] + '"><a class="rec-book" href="' + ROOT + 'b/' + b.i + '/' + IDX + '"><img class="cover xs" src="' + esc(b.c) + '" alt="" loading="lazy" referrerpolicy="no-referrer"><span><b>' + esc(b.t) + '</b><small>' + esc(b.p) + '</small></span></a>' +
      '<div class="rec-main"><header>' + chip(r[0]) + '<span class="sec">' + esc(r[4]) + '</span><a class="rec-src" href="' + ROOT + iss[0] + IDX + '">' + esc(iss[1]) + '</a><time>' + r[2].replace(/-/g, '. ') + '</time></header>' +
      '<p class="why">' + (esc(r[6]) || '<span class="muted">요약 준비 중</span>') + '</p><footer>' + (r[5] ? '<b>' + esc(r[5]) + '</b>' : '') + '</footer></div></article>';
  }

  function page() {
    var slice = list.slice(shown, shown + PAGE);
    res.insertAdjacentHTML('beforeend', slice.map(view === 'books' ? card : recRow).join(''));
    shown += slice.length;
    more.hidden = shown >= list.length;
    if (window.SHOP_PAINT) window.SHOP_PAINT();
  }

  form.addEventListener('change', run);
  form.q.addEventListener('input', function () { clearTimeout(run.t); run.t = setTimeout(run, 200); });
  more.addEventListener('click', page);
  Array.prototype.forEach.call(document.querySelectorAll('[data-view]'), function (btn) {
    btn.addEventListener('click', function () {
      view = btn.getAttribute('data-view');
      Array.prototype.forEach.call(document.querySelectorAll('[data-view]'), function (x) { x.classList.toggle('on', x === btn); });
      run();
    });
  });

  cnt.textContent = '불러오는 중…';
  fetch(ROOT + 'data/index.json').then(function (r) { return r.json(); }).then(function (d) { D = d; run(); })
    .catch(function () { cnt.textContent = '목록을 불러오지 못했어요. 새로고침해 주세요.'; });
});
