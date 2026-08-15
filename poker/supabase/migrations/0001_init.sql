-- Chip Ledger schema.
-- Run this in the Supabase SQL editor (or `supabase db push`) on a fresh project.
--
-- Money is stored everywhere as integer cents. Rounds and ledger rows are
-- append-only history: nothing is overwritten when someone leaves and rejoins,
-- which is what lets a player's stats survive a walk-away mid-game.

-- ---------------------------------------------------------------- profiles --

create table if not exists public.profiles (
  id uuid primary key references auth.users on delete cascade,
  display_name text not null,
  email text,
  avatar_url text,
  created_at timestamptz not null default now()
);

-- Every Google / Apple sign-in lands here automatically.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, display_name, email, avatar_url)
  values (
    new.id,
    coalesce(
      new.raw_user_meta_data->>'full_name',
      new.raw_user_meta_data->>'name',
      split_part(coalesce(new.email, 'player'), '@', 1)
    ),
    new.email,
    new.raw_user_meta_data->>'avatar_url'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ------------------------------------------------------------------ games --

create table if not exists public.games (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  name text not null,
  host_id uuid not null references public.profiles(id) on delete cascade,
  status text not null default 'active' check (status in ('active', 'settled')),
  -- [{ key, label, color, valueCents }] — the table's default chip values.
  default_chip_values jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  ended_at timestamptz
);

create index if not exists games_host_idx on public.games (host_id);

create table if not exists public.game_players (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.games on delete cascade,
  -- Null for a guest the host is tracking on someone else's behalf.
  user_id uuid references public.profiles(id) on delete set null,
  display_name text not null,
  status text not null default 'active' check (status in ('active', 'away', 'left')),
  joined_at timestamptz not null default now(),
  left_at timestamptz
);

-- One seat per account per game: rejoining reuses the seat, so history follows you.
create unique index if not exists game_players_unique_user
  on public.game_players (game_id, user_id) where user_id is not null;
create index if not exists game_players_game_idx on public.game_players (game_id);
create index if not exists game_players_user_idx on public.game_players (user_id);

create table if not exists public.rounds (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.games on delete cascade,
  number int not null,
  status text not null default 'open' check (status in ('open', 'closed')),
  -- Snapshot of chip values for THIS round, so "blue is $5 this round, $10 next"
  -- re-values correctly and old rounds keep the numbers they were scored with.
  chip_values jsonb not null default '[]'::jsonb,
  started_at timestamptz not null default now(),
  closed_at timestamptz,
  unique (game_id, number)
);

create index if not exists rounds_game_idx on public.rounds (game_id);

create table if not exists public.ledger_entries (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.games on delete cascade,
  player_id uuid not null references public.game_players on delete cascade,
  round_id uuid references public.rounds on delete set null,
  kind text not null check (kind in ('buy_in', 'cash_out', 'adjustment')),
  amount_cents bigint not null,
  chips jsonb,
  note text,
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists ledger_game_idx on public.ledger_entries (game_id);
create index if not exists ledger_player_idx on public.ledger_entries (player_id);

create table if not exists public.round_stacks (
  id uuid primary key default gen_random_uuid(),
  round_id uuid not null references public.rounds on delete cascade,
  player_id uuid not null references public.game_players on delete cascade,
  chips jsonb,
  stack_cents bigint not null,
  recorded_by uuid references public.profiles(id) on delete set null,
  recorded_at timestamptz not null default now(),
  unique (round_id, player_id)
);

create index if not exists round_stacks_round_idx on public.round_stacks (round_id);

create table if not exists public.settlements (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null unique references public.games on delete cascade,
  -- [{ fromPlayerId, toPlayerId, amountCents }]
  payments jsonb not null,
  totals jsonb not null,
  created_at timestamptz not null default now()
);

-- ------------------------------------------------------------- membership --

-- Security definer so the policies below can ask "is this person in the game?"
-- without the policy on game_players recursing into itself.
create or replace function public.is_game_member(g uuid)
returns boolean
language sql
security definer stable set search_path = public
as $$
  select exists (
    select 1 from public.game_players p
    where p.game_id = g and p.user_id = auth.uid()
  ) or exists (
    select 1 from public.games gm
    where gm.id = g and gm.host_id = auth.uid()
  );
$$;

create or replace function public.is_game_host(g uuid)
returns boolean
language sql
security definer stable set search_path = public
as $$
  select exists (
    select 1 from public.games gm where gm.id = g and gm.host_id = auth.uid()
  );
$$;

-- Short, unambiguous join code (no O/0/I/1).
create or replace function public.generate_game_code()
returns text
language plpgsql
as $$
declare
  alphabet text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  candidate text;
  i int;
begin
  loop
    candidate := '';
    for i in 1..6 loop
      candidate := candidate || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
    end loop;
    exit when not exists (select 1 from public.games where code = candidate);
  end loop;
  return candidate;
end;
$$;

-- Creating a game: host row + their own seat, in one call.
create or replace function public.create_game(p_name text, p_chip_values jsonb, p_display_name text)
returns public.games
language plpgsql
security definer set search_path = public
as $$
declare
  new_game public.games;
begin
  if auth.uid() is null then
    raise exception 'not signed in';
  end if;

  insert into public.games (code, name, host_id, default_chip_values)
  values (public.generate_game_code(), coalesce(nullif(trim(p_name), ''), 'Home game'),
          auth.uid(), coalesce(p_chip_values, '[]'::jsonb))
  returning * into new_game;

  insert into public.game_players (game_id, user_id, display_name)
  values (new_game.id, auth.uid(), coalesce(nullif(trim(p_display_name), ''), 'Host'));

  return new_game;
end;
$$;

-- Joining by code. Security definer because you can't read a game you're not in
-- yet — this is the one door in. Rejoining flips your existing seat back to active
-- instead of creating a second one, so your chips and history are still there.
create or replace function public.join_game(p_code text, p_display_name text)
returns public.games
language plpgsql
security definer set search_path = public
as $$
declare
  target public.games;
  existing public.game_players;
begin
  if auth.uid() is null then
    raise exception 'not signed in';
  end if;

  select * into target from public.games where code = upper(trim(p_code));
  if target.id is null then
    raise exception 'no game with that code';
  end if;
  if target.status <> 'active' then
    raise exception 'that game is already settled';
  end if;

  select * into existing from public.game_players
  where game_id = target.id and user_id = auth.uid();

  if existing.id is not null then
    update public.game_players
      set status = 'active',
          left_at = null,
          display_name = coalesce(nullif(trim(p_display_name), ''), display_name)
    where id = existing.id;
  else
    insert into public.game_players (game_id, user_id, display_name)
    values (target.id, auth.uid(),
            coalesce(nullif(trim(p_display_name), ''), 'Player'));
  end if;

  return target;
end;
$$;

-- ------------------------------------------------------------------- RLS --

alter table public.profiles enable row level security;
alter table public.games enable row level security;
alter table public.game_players enable row level security;
alter table public.rounds enable row level security;
alter table public.ledger_entries enable row level security;
alter table public.round_stacks enable row level security;
alter table public.settlements enable row level security;

drop policy if exists "read own profile" on public.profiles;
create policy "read own profile" on public.profiles
  for select using (id = auth.uid());

drop policy if exists "read profiles of people at my tables" on public.profiles;
create policy "read profiles of people at my tables" on public.profiles
  for select using (
    exists (
      select 1 from public.game_players mine
      join public.game_players theirs on theirs.game_id = mine.game_id
      where mine.user_id = auth.uid() and theirs.user_id = public.profiles.id
    )
  );

drop policy if exists "update own profile" on public.profiles;
create policy "update own profile" on public.profiles
  for update using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists "read games i'm in" on public.games;
create policy "read games i'm in" on public.games
  for select using (public.is_game_member(id));

drop policy if exists "host manages the game" on public.games;
create policy "host manages the game" on public.games
  for update using (host_id = auth.uid()) with check (host_id = auth.uid());

drop policy if exists "read players in my games" on public.game_players;
create policy "read players in my games" on public.game_players
  for select using (public.is_game_member(game_id));

drop policy if exists "host adds players" on public.game_players;
create policy "host adds players" on public.game_players
  for insert with check (public.is_game_host(game_id));

drop policy if exists "host or self updates a seat" on public.game_players;
create policy "host or self updates a seat" on public.game_players
  for update using (public.is_game_host(game_id) or user_id = auth.uid())
  with check (public.is_game_host(game_id) or user_id = auth.uid());

drop policy if exists "read rounds in my games" on public.rounds;
create policy "read rounds in my games" on public.rounds
  for select using (public.is_game_member(game_id));

drop policy if exists "host runs rounds" on public.rounds;
create policy "host runs rounds" on public.rounds
  for all using (public.is_game_host(game_id)) with check (public.is_game_host(game_id));

drop policy if exists "read ledger in my games" on public.ledger_entries;
create policy "read ledger in my games" on public.ledger_entries
  for select using (public.is_game_member(game_id));

drop policy if exists "members record money" on public.ledger_entries;
create policy "members record money" on public.ledger_entries
  for insert with check (public.is_game_member(game_id));

drop policy if exists "host edits the ledger" on public.ledger_entries;
create policy "host edits the ledger" on public.ledger_entries
  for delete using (public.is_game_host(game_id));

drop policy if exists "read stacks in my games" on public.round_stacks;
create policy "read stacks in my games" on public.round_stacks
  for select using (
    exists (select 1 from public.rounds r
            where r.id = round_id and public.is_game_member(r.game_id))
  );

drop policy if exists "members record stacks" on public.round_stacks;
create policy "members record stacks" on public.round_stacks
  for all using (
    exists (select 1 from public.rounds r
            where r.id = round_id and public.is_game_member(r.game_id))
  ) with check (
    exists (select 1 from public.rounds r
            where r.id = round_id and public.is_game_member(r.game_id))
  );

drop policy if exists "read settlement in my games" on public.settlements;
create policy "read settlement in my games" on public.settlements
  for select using (public.is_game_member(game_id));

drop policy if exists "host settles" on public.settlements;
create policy "host settles" on public.settlements
  for all using (public.is_game_host(game_id)) with check (public.is_game_host(game_id));

-- ---------------------------------------------------------------- grants --
-- Supabase's default privileges usually cover this, but being explicit means the
-- migration also works on a plain Postgres. RLS above is what actually gates access.

grant usage on schema public to anon, authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
grant execute on all functions in schema public to authenticated;

-- --------------------------------------------------------------- realtime --
-- So everyone at the table sees buy-ins and round results as they land.

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    alter publication supabase_realtime add table public.games;
    alter publication supabase_realtime add table public.game_players;
    alter publication supabase_realtime add table public.rounds;
    alter publication supabase_realtime add table public.ledger_entries;
    alter publication supabase_realtime add table public.round_stacks;
    alter publication supabase_realtime add table public.settlements;
  end if;
exception when duplicate_object then
  null;
end;
$$;
