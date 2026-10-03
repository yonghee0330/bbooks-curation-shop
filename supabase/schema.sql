-- =====================================================================
-- Q.books(가칭) 회원·주문 DB — Supabase (비북스 기존 프로젝트와 별도)
--
-- 구조
--   profiles        회원 (auth.users 1:1) — 가입 완료·등급·탈퇴
--   consents        약관·개인정보·만14세·마케팅 동의 이력 (버전·시각)
--   addresses       회원 배송지
--   books           판매 도서 (사이트 빌드 때 catalog.json 으로 동기화)
--   settings        가격·배송·회원 혜택 규칙 (운영자가 값만 바꿔서 조정)
--   orders          주문 (회원/비회원 공통)
--   order_items     주문 도서
--   order_events    주문 상태 변경 이력
--   point_ledger    적립금 원장 (+적립 / −사용)
--   admins          운영자 계정
--
-- 쓰기는 모두 RPC(security definer)로만: place_order / complete_signup / ...
-- 테이블 직접 쓰기는 막고(RLS), 회원은 자기 행만 읽기 가능.
-- =====================================================================

create extension if not exists pg_net with schema extensions;
create extension if not exists pgcrypto with schema extensions;

-- ── 설정 ─────────────────────────────────────────────────────────────
create table if not exists settings (
  key   text primary key,
  value jsonb not null,
  note  text,
  updated_at timestamptz default now()
);

insert into settings (key, value, note) values
  ('pricing', '{"discount_rate":0.10, "shipping_fee":3000, "free_shipping_over":30000}',
   '정가 대비 할인율(도서정가제 직접 할인 최대 10%), 택배비, 무료배송 기준'),
  ('member_benefits', '{"point_rate":0.05, "welcome_points":1000, "free_shipping_over":20000, "max_points_ratio":1.0, "min_points_use":1000}',
   '회원 혜택: 결제금액(도서) 적립률, 가입 적립금, 회원 무료배송 기준, 사용 한도(도서금액 대비), 최소 사용 단위. 도서정가제: 할인율+적립률 합 15% 이내'),
  ('notify', '{"webhook_url":""}',
   '주문·상태 변경 시 메일을 보내는 Apps Script 웹앱 주소 (운영자만 읽음)'),
  ('consent_versions', '{"terms":"2026-10-03", "privacy":"2026-10-03", "marketing":"2026-10-03"}',
   '현재 약관 버전. 바꾸면 회원에게 다시 동의를 받을 수 있음')
on conflict (key) do nothing;

-- 도서정가제 상한(할인 10% + 적립 포함 15%) 넘는 값 저장 방지
create or replace function check_price_law() returns trigger language plpgsql as $$
declare d numeric; p numeric;
begin
  if new.key in ('pricing', 'member_benefits') then
    select (value->>'discount_rate')::numeric into d from settings where key = 'pricing';
    select (value->>'point_rate')::numeric into p from settings where key = 'member_benefits';
    if new.key = 'pricing' then d := (new.value->>'discount_rate')::numeric; end if;
    if new.key = 'member_benefits' then p := (new.value->>'point_rate')::numeric; end if;
    if coalesce(d, 0) > 0.10 then raise exception '도서정가제: 직접 할인은 정가의 10%%까지입니다'; end if;
    if coalesce(d, 0) + coalesce(p, 0) > 0.15 then raise exception '도서정가제: 할인+적립 합계는 정가의 15%%까지입니다'; end if;
  end if;
  new.updated_at := now();
  return new;
end $$;
drop trigger if exists settings_price_law on settings;
create trigger settings_price_law before insert or update on settings for each row execute function check_price_law();

create or replace function setting(k text) returns jsonb language sql stable security definer set search_path = public as $$
  select value from settings where key = k
$$;

-- ── 운영자 ───────────────────────────────────────────────────────────
create table if not exists admins (
  user_id uuid primary key references auth.users on delete cascade,
  created_at timestamptz default now()
);
create or replace function is_admin() returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from admins where user_id = auth.uid())
$$;

-- ── 회원 ─────────────────────────────────────────────────────────────
create table if not exists profiles (
  id            uuid primary key references auth.users on delete cascade,
  email         text,
  name          text,
  phone         text,
  provider      text,                         -- google / kakao
  tier          text not null default 'member',
  signup_completed_at timestamptz,            -- 약관 동의 + 정보 입력을 마친 시각 (그 전엔 혜택 없음)
  marketing_email boolean not null default false,
  marketing_sms   boolean not null default false,
  withdrawn_at  timestamptz,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

create table if not exists consents (
  id         bigint generated always as identity primary key,
  user_id    uuid references auth.users on delete set null,
  order_id   uuid,                            -- 비회원 주문 동의일 때
  kind       text not null check (kind in ('terms','privacy','age14','marketing_email','marketing_sms','guest_order_privacy')),
  version    text not null,
  agreed     boolean not null,
  created_at timestamptz default now()
);
create index if not exists consents_user on consents(user_id);

create table if not exists addresses (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users on delete cascade,
  label      text,
  recipient  text not null,
  phone      text not null,
  zipcode    text,
  address1   text not null,
  address2   text,
  is_default boolean not null default false,
  created_at timestamptz default now()
);
create index if not exists addresses_user on addresses(user_id);

-- 가입(첫 로그인) 시 프로필 자리 만들기
create or replace function handle_new_user() returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into profiles (id, email, name, provider)
  values (new.id, new.email,
          coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name', new.raw_user_meta_data->>'preferred_username'),
          new.raw_app_meta_data->>'provider')
  on conflict (id) do nothing;
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function handle_new_user();

-- ── 도서 ─────────────────────────────────────────────────────────────
create table if not exists books (
  isbn13         text primary key,
  title          text not null,
  author         text,
  publisher      text,
  price_standard int not null check (price_standard >= 0),
  cover          text,
  source         text,                        -- 대표 추천 출처 (예: 엠마오 이달의 책)
  active         boolean not null default true,
  updated_at     timestamptz default now()
);

-- ── 주문 ─────────────────────────────────────────────────────────────
create table if not exists orders (
  id              uuid primary key default gen_random_uuid(),
  order_no        text unique not null,
  user_id         uuid references auth.users on delete set null,
  is_member       boolean not null default false,
  buyer_name      text not null,
  buyer_phone     text not null,
  buyer_email     text,
  ship_method     text not null check (ship_method in ('pickup','delivery')),
  recipient       text,
  recipient_phone text,
  zipcode         text,
  address1        text,
  address2        text,
  memo            text,
  subtotal_standard int not null,             -- 정가 합계
  discount        int not null default 0,     -- 정가 할인액
  subtotal        int not null,               -- 도서 판매가 합계
  points_used     int not null default 0,
  shipping_fee    int not null default 0,
  total           int not null,               -- 결제할 금액
  points_to_earn  int not null default 0,     -- 수령 완료 시 적립될 금액
  status          text not null default 'requested'
                  check (status in ('requested','stocked','payment_requested','paid','shipped','ready_pickup','completed','cancelled')),
  carrier         text,
  tracking_no     text,
  admin_note      text,
  created_at      timestamptz default now(),
  updated_at      timestamptz default now()
);
create index if not exists orders_user on orders(user_id, created_at desc);
create index if not exists orders_status on orders(status, created_at desc);
create index if not exists orders_phone on orders(buyer_phone);

create table if not exists order_items (
  id             bigint generated always as identity primary key,
  order_id       uuid not null references orders on delete cascade,
  isbn13         text not null,
  title          text not null,
  publisher      text,
  qty            int not null check (qty between 1 and 20),
  price_standard int not null,
  price          int not null,
  source         text
);
create index if not exists order_items_order on order_items(order_id);

create table if not exists order_events (
  id         bigint generated always as identity primary key,
  order_id   uuid not null references orders on delete cascade,
  status     text not null,
  note       text,
  actor      uuid,
  created_at timestamptz default now()
);
create index if not exists order_events_order on order_events(order_id, created_at);

create table if not exists point_ledger (
  id         bigint generated always as identity primary key,
  user_id    uuid not null references auth.users on delete cascade,
  delta      int not null,
  reason     text not null check (reason in ('welcome','order_use','order_earn','order_cancel_refund','order_cancel_revoke','admin','expire')),
  order_id   uuid references orders on delete set null,
  note       text,
  created_at timestamptz default now()
);
create index if not exists point_ledger_user on point_ledger(user_id, created_at desc);

create or replace function point_balance(uid uuid) returns int language sql stable security definer set search_path = public as $$
  select coalesce(sum(delta), 0)::int from point_ledger where user_id = uid
$$;

-- ── RLS: 직접 쓰기 금지, 본인 행만 읽기 ───────────────────────────────
alter table settings     enable row level security;
alter table admins       enable row level security;
alter table profiles     enable row level security;
alter table consents     enable row level security;
alter table addresses    enable row level security;
alter table books        enable row level security;
alter table orders       enable row level security;
alter table order_items  enable row level security;
alter table order_events enable row level security;
alter table point_ledger enable row level security;

drop policy if exists "공개 설정 읽기" on settings;
create policy "공개 설정 읽기" on settings for select using (key in ('pricing','member_benefits','consent_versions') or is_admin());
drop policy if exists "운영자 설정 변경" on settings;
create policy "운영자 설정 변경" on settings for update using (is_admin()) with check (is_admin());

drop policy if exists "도서 공개" on books;
create policy "도서 공개" on books for select using (true);

drop policy if exists "본인 프로필" on profiles;
create policy "본인 프로필" on profiles for select using (id = auth.uid() or is_admin());
drop policy if exists "본인 동의 이력" on consents;
create policy "본인 동의 이력" on consents for select using (user_id = auth.uid() or is_admin());
drop policy if exists "본인 배송지 읽기" on addresses;
create policy "본인 배송지 읽기" on addresses for select using (user_id = auth.uid() or is_admin());
drop policy if exists "본인 배송지 쓰기" on addresses;
create policy "본인 배송지 쓰기" on addresses for insert with check (user_id = auth.uid());
drop policy if exists "본인 배송지 수정" on addresses;
create policy "본인 배송지 수정" on addresses for update using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "본인 배송지 삭제" on addresses;
create policy "본인 배송지 삭제" on addresses for delete using (user_id = auth.uid());

drop policy if exists "본인 주문" on orders;
create policy "본인 주문" on orders for select using (user_id = auth.uid() or is_admin());
drop policy if exists "본인 주문 도서" on order_items;
create policy "본인 주문 도서" on order_items for select using (exists (select 1 from orders o where o.id = order_id and (o.user_id = auth.uid() or is_admin())));
drop policy if exists "본인 주문 이력" on order_events;
create policy "본인 주문 이력" on order_events for select using (exists (select 1 from orders o where o.id = order_id and (o.user_id = auth.uid() or is_admin())));
drop policy if exists "본인 적립금" on point_ledger;
create policy "본인 적립금" on point_ledger for select using (user_id = auth.uid() or is_admin());
drop policy if exists "운영자 확인" on admins;
create policy "운영자 확인" on admins for select using (user_id = auth.uid());

-- ── 가입 완료 (약관 동의 + 이름·연락처) ──────────────────────────────
create or replace function complete_signup(p_name text, p_phone text, p_consents jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare uid uuid := auth.uid(); v jsonb := setting('consent_versions'); first boolean; k text;
begin
  if uid is null then raise exception '로그인이 필요해요'; end if;
  if coalesce(trim(p_name), '') = '' then raise exception '이름을 적어 주세요'; end if;
  if p_phone !~ '^0\d{1,2}-?\d{3,4}-?\d{4}$' then raise exception '휴대폰 번호를 확인해 주세요'; end if;
  foreach k in array array['terms','privacy','age14'] loop
    if coalesce((p_consents->>k)::boolean, false) is not true then raise exception '필수 항목에 동의해 주세요'; end if;
  end loop;

  select signup_completed_at is null into first from profiles where id = uid;
  update profiles set name = left(trim(p_name), 40), phone = p_phone,
         marketing_email = coalesce((p_consents->>'marketing_email')::boolean, false),
         marketing_sms   = coalesce((p_consents->>'marketing_sms')::boolean, false),
         signup_completed_at = coalesce(signup_completed_at, now()), updated_at = now()
   where id = uid;

  insert into consents (user_id, kind, version, agreed)
  select uid, x.kind, case when x.kind like 'marketing%' then v->>'marketing' when x.kind = 'age14' then v->>'terms' else v->>x.kind end,
         coalesce((p_consents->>x.kind)::boolean, false)
    from (values ('terms'),('privacy'),('age14'),('marketing_email'),('marketing_sms')) as x(kind);

  if first and coalesce((setting('member_benefits')->>'welcome_points')::int, 0) > 0 then
    insert into point_ledger (user_id, delta, reason, note)
    values (uid, (setting('member_benefits')->>'welcome_points')::int, 'welcome', '가입 축하 적립금');
  end if;
  return jsonb_build_object('ok', true, 'points', point_balance(uid));
end $$;

-- 마케팅 수신 변경 (이력 남김)
create or replace function set_marketing(p_email boolean, p_sms boolean) returns void
language plpgsql security definer set search_path = public as $$
declare uid uuid := auth.uid(); v text := setting('consent_versions')->>'marketing';
begin
  if uid is null then raise exception '로그인이 필요해요'; end if;
  update profiles set marketing_email = p_email, marketing_sms = p_sms, updated_at = now() where id = uid;
  insert into consents (user_id, kind, version, agreed) values (uid, 'marketing_email', v, p_email), (uid, 'marketing_sms', v, p_sms);
end $$;

-- 회원 정보 수정
create or replace function update_profile(p_name text, p_phone text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception '로그인이 필요해요'; end if;
  if p_phone !~ '^0\d{1,2}-?\d{3,4}-?\d{4}$' then raise exception '휴대폰 번호를 확인해 주세요'; end if;
  update profiles set name = left(trim(p_name), 40), phone = p_phone, updated_at = now() where id = auth.uid();
end $$;

-- ── 주문 ─────────────────────────────────────────────────────────────
-- p: {name, phone, email, ship:'pickup'|'delivery', recipient, recipient_phone, zipcode, address1, address2, memo,
--     items:[{isbn13, qty, source}], points_use, guest_privacy_agreed, save_address}
create or replace function place_order(p jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  uid uuid := auth.uid();
  prof profiles;
  member boolean := false;
  pr jsonb := setting('pricing');
  mb jsonb := setting('member_benefits');
  rate numeric := coalesce((pr->>'discount_rate')::numeric, 0);
  ship text := case when p->>'ship' = 'delivery' then 'delivery' else 'pickup' end;
  phone text := regexp_replace(coalesce(p->>'phone', ''), '[^0-9-]', '', 'g');
  it jsonb; b books; q int;
  std int := 0; sub int := 0; fee int := 0; use_pts int := 0; earn int := 0; bal int := 0; free_over int;
  oid uuid := gen_random_uuid(); ono text;
  lines jsonb := '[]'::jsonb;
begin
  if coalesce(trim(p->>'name'), '') = '' or phone !~ '^0\d{1,2}-?\d{3,4}-?\d{4}$' then
    raise exception '이름과 휴대폰 번호를 확인해 주세요';
  end if;
  if ship = 'delivery' and coalesce(trim(p->>'address1'), '') = '' then raise exception '받을 주소를 적어 주세요'; end if;

  if uid is not null then
    select * into prof from profiles where id = uid;
    member := prof.signup_completed_at is not null and prof.withdrawn_at is null;
  end if;
  if not member and coalesce((p->>'guest_privacy_agreed')::boolean, false) is not true then
    raise exception '개인정보 수집·이용에 동의해 주세요';
  end if;

  -- 같은 번호로 1분 안 연속 주문 방지
  if exists (select 1 from orders where buyer_phone = phone and created_at > now() - interval '1 minute') then
    raise exception '방금 주문을 받았어요. 1분 뒤에 다시 시도해 주세요';
  end if;

  for it in select * from jsonb_array_elements(coalesce(p->'items', '[]'::jsonb)) limit 50 loop
    select * into b from books where isbn13 = it->>'isbn13' and active;
    continue when not found;
    q := greatest(1, least(20, coalesce((it->>'qty')::int, 1)));
    std := std + b.price_standard * q;
    sub := sub + (floor(b.price_standard * (1 - rate) / 10) * 10)::int * q;
    lines := lines || jsonb_build_object('isbn13', b.isbn13, 'title', b.title, 'publisher', b.publisher, 'qty', q,
               'price_standard', b.price_standard, 'price', (floor(b.price_standard * (1 - rate) / 10) * 10)::int,
               'source', coalesce(nullif(it->>'source', ''), b.source));
  end loop;
  if jsonb_array_length(lines) = 0 then raise exception '주문할 책이 없어요'; end if;

  free_over := case when member then coalesce((mb->>'free_shipping_over')::int, (pr->>'free_shipping_over')::int)
                    else (pr->>'free_shipping_over')::int end;
  fee := case when ship = 'delivery' and sub < free_over then (pr->>'shipping_fee')::int else 0 end;

  if member then
    bal := point_balance(uid);
    use_pts := greatest(0, least(coalesce((p->>'points_use')::int, 0), bal, floor(sub * coalesce((mb->>'max_points_ratio')::numeric, 1))::int));
    if use_pts > 0 and use_pts < coalesce((mb->>'min_points_use')::int, 0) then use_pts := 0; end if;
    earn := floor((sub - use_pts) * coalesce((mb->>'point_rate')::numeric, 0))::int;
  end if;

  ono := 'QB-' || to_char(now() at time zone 'Asia/Seoul', 'MMDD') || '-' ||
         upper(substr(translate(encode(extensions.gen_random_bytes(6), 'base64'), '+/=0O1Il', 'XYZ2345'), 1, 5));

  insert into orders (id, order_no, user_id, is_member, buyer_name, buyer_phone, buyer_email, ship_method,
                      recipient, recipient_phone, zipcode, address1, address2, memo,
                      subtotal_standard, discount, subtotal, points_used, shipping_fee, total, points_to_earn)
  values (oid, ono, case when member then uid end, member, left(trim(p->>'name'), 40), phone, nullif(left(trim(coalesce(p->>'email', '')), 80), ''), ship,
          nullif(left(trim(coalesce(p->>'recipient', p->>'name')), 40), ''), nullif(coalesce(p->>'recipient_phone', phone), ''),
          nullif(left(p->>'zipcode', 10), ''), nullif(left(trim(coalesce(p->>'address1', '')), 200), ''), nullif(left(trim(coalesce(p->>'address2', '')), 100), ''),
          nullif(left(trim(coalesce(p->>'memo', '')), 500), ''),
          std, std - sub, sub, use_pts, fee, sub - use_pts + fee, earn);

  insert into order_items (order_id, isbn13, title, publisher, qty, price_standard, price, source)
  select oid, x->>'isbn13', x->>'title', x->>'publisher', (x->>'qty')::int, (x->>'price_standard')::int, (x->>'price')::int, x->>'source'
    from jsonb_array_elements(lines) x;

  insert into order_events (order_id, status, note, actor) values (oid, 'requested', '주문 접수', uid);
  if use_pts > 0 then
    insert into point_ledger (user_id, delta, reason, order_id, note) values (uid, -use_pts, 'order_use', oid, ono);
  end if;
  if not member then
    insert into consents (order_id, kind, version, agreed) values (oid, 'guest_order_privacy', setting('consent_versions')->>'privacy', true);
  end if;
  if member and coalesce((p->>'save_address')::boolean, false) and ship = 'delivery' then
    insert into addresses (user_id, label, recipient, phone, zipcode, address1, address2, is_default)
    values (uid, '기본', coalesce(p->>'recipient', p->>'name'), coalesce(p->>'recipient_phone', phone), p->>'zipcode', p->>'address1', p->>'address2',
            not exists (select 1 from addresses where user_id = uid));
  end if;

  perform notify_order(oid, 'created');
  return jsonb_build_object('ok', true, 'order_no', ono, 'member', member, 'subtotal_standard', std, 'subtotal', sub,
                            'points_used', use_pts, 'shipping', fee, 'total', sub - use_pts + fee, 'points_to_earn', earn);
end $$;

-- 비회원 주문 조회: 주문번호 + 휴대폰
create or replace function lookup_order(p_order_no text, p_phone text) returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'order', to_jsonb(o) - 'user_id' - 'admin_note',
    'items', (select jsonb_agg(to_jsonb(i) - 'id' - 'order_id' order by i.id) from order_items i where i.order_id = o.id),
    'events', (select jsonb_agg(jsonb_build_object('status', e.status, 'note', e.note, 'at', e.created_at) order by e.created_at) from order_events e where e.order_id = o.id))
  from orders o
  where o.order_no = upper(trim(p_order_no))
    and regexp_replace(o.buyer_phone, '\D', '', 'g') = regexp_replace(p_phone, '\D', '', 'g')
$$;

-- 회원 본인 주문 취소 (입고 전까지만)
create or replace function cancel_my_order(p_order_id uuid) returns void
language plpgsql security definer set search_path = public as $$
declare o orders;
begin
  select * into o from orders where id = p_order_id and user_id = auth.uid();
  if not found then raise exception '주문을 찾을 수 없어요'; end if;
  if o.status not in ('requested') then raise exception '입고가 진행된 주문은 서점에 문의해 주세요'; end if;
  perform set_status_internal(o.id, 'cancelled', '회원 직접 취소', auth.uid(), null, null);
end $$;

-- 상태 변경 (운영자) — 적립/환급 처리 포함
create or replace function set_status_internal(p_id uuid, p_status text, p_note text, p_actor uuid, p_carrier text, p_tracking text)
returns void language plpgsql security definer set search_path = public as $$
declare o orders;
begin
  select * into o from orders where id = p_id for update;
  if not found then raise exception '주문 없음'; end if;
  if o.status = p_status and p_carrier is null and p_tracking is null then return; end if;
  if o.status in ('completed','cancelled') and p_status <> o.status then raise exception '이미 끝난 주문입니다'; end if;

  update orders set status = p_status, updated_at = now(),
         carrier = coalesce(p_carrier, carrier), tracking_no = coalesce(p_tracking, tracking_no)
   where id = p_id;
  insert into order_events (order_id, status, note, actor) values (p_id, p_status, p_note, p_actor);

  if o.user_id is not null then
    if p_status = 'completed' and o.points_to_earn > 0 then
      insert into point_ledger (user_id, delta, reason, order_id, note) values (o.user_id, o.points_to_earn, 'order_earn', p_id, o.order_no);
    elsif p_status = 'cancelled' and o.points_used > 0 then
      insert into point_ledger (user_id, delta, reason, order_id, note) values (o.user_id, o.points_used, 'order_cancel_refund', p_id, o.order_no);
    end if;
  end if;
  perform notify_order(p_id, p_status);
end $$;
revoke all on function set_status_internal(uuid, text, text, uuid, text, text) from public, anon, authenticated;

create or replace function admin_set_status(p_order_id uuid, p_status text, p_note text default null, p_carrier text default null, p_tracking text default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception '운영자만 바꿀 수 있어요'; end if;
  perform set_status_internal(p_order_id, p_status, p_note, auth.uid(), nullif(p_carrier, ''), nullif(p_tracking, ''));
end $$;

create or replace function admin_adjust_points(p_user uuid, p_delta int, p_note text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception '운영자만'; end if;
  insert into point_ledger (user_id, delta, reason, note) values (p_user, p_delta, 'admin', p_note);
end $$;

-- 탈퇴: 로그인 계정 삭제, 주문 기록은 전자상거래법에 따라 5년 보관(회원 연결만 끊음)
create or replace function withdraw_me() returns void
language plpgsql security definer set search_path = public, auth as $$
declare uid uuid := auth.uid();
begin
  if uid is null then raise exception '로그인이 필요해요'; end if;
  update orders set user_id = null where user_id = uid;
  delete from auth.users where id = uid;   -- profiles·addresses·point_ledger 는 cascade 삭제, consents 는 user_id null
end $$;

-- ── 메일 알림: Apps Script 웹앱으로 주문 내용을 보냄 ──────────────────
create or replace function notify_order(p_id uuid, p_event text) returns void
language plpgsql security definer set search_path = public, extensions as $$
declare url text := setting('notify')->>'webhook_url';
begin
  if coalesce(url, '') = '' then return; end if;
  -- 주문 id 와 사건만 보냄. Apps Script 가 order_for_notify 로 실제 내용을 다시 읽어 확인(위조 방지)
  perform net.http_post(url := url, body := jsonb_build_object('action', 'notify', 'event', p_event, 'order_id', p_id),
                        headers := '{"Content-Type":"application/json"}'::jsonb, timeout_milliseconds := 8000);
exception when others then
  raise warning 'notify failed: %', sqlerrm;   -- 메일 실패가 주문을 막지 않게
end $$;

-- 알림용 주문 읽기: 최근 15분 안에 바뀐 주문만 (주문 id 는 추측 불가한 uuid)
create or replace function order_for_notify(p_id uuid) returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object('order', to_jsonb(o) - 'user_id',
           'items', (select jsonb_agg(to_jsonb(i) - 'id' - 'order_id' order by i.id) from order_items i where i.order_id = o.id),
           'last_event', (select jsonb_build_object('status', e.status, 'note', e.note) from order_events e where e.order_id = o.id order by e.created_at desc limit 1))
  from orders o where o.id = p_id and o.updated_at > now() - interval '15 minutes'
$$;
grant execute on function order_for_notify(uuid) to anon;
revoke all on function notify_order(uuid, text) from public, anon, authenticated;

-- ── 실행 권한 ─────────────────────────────────────────────────────────
grant execute on function place_order(jsonb), lookup_order(text, text) to anon, authenticated;
grant execute on function complete_signup(text, text, jsonb), set_marketing(boolean, boolean), update_profile(text, text),
      cancel_my_order(uuid), withdraw_me(), point_balance(uuid), admin_set_status(uuid, text, text, text, text),
      admin_adjust_points(uuid, int, text) to authenticated;
