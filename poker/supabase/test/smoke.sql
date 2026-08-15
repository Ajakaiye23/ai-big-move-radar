-- Exercises the schema the way the app does: host opens a table, someone joins by
-- code, money goes in, a round is scored, someone leaves and comes back, and the
-- game gets settled. Also checks that the RLS policies actually keep strangers out.
--
-- Run with: npm run test:db

\set ON_ERROR_STOP on

-- ------------------------------------------------------------- fixtures --

insert into auth.users (id, email, raw_user_meta_data) values
  ('11111111-1111-1111-1111-111111111111', 'host@example.com', '{"full_name":"Host Hannah"}'),
  ('22222222-2222-2222-2222-222222222222', 'sam@example.com', '{"full_name":"Sam"}'),
  ('33333333-3333-3333-3333-333333333333', 'nosy@example.com', '{"full_name":"Nosy Neighbour"}');

do $$
begin
  assert (select count(*) from public.profiles) = 3,
    'the auth trigger should have created a profile per user';
  assert (select display_name from public.profiles
          where id = '11111111-1111-1111-1111-111111111111') = 'Host Hannah',
    'display name should come from the OAuth metadata';
end;
$$;

-- --------------------------------------------------- host opens a table --

set role authenticated;
set test.uid = '11111111-1111-1111-1111-111111111111';

select public.create_game(
  'Friday night',
  '[{"key":"blue","label":"Blue","color":"#2563eb","valueCents":500}]'::jsonb,
  'Hannah'
) as game \gset

\set game_code `echo ''`
select code as game_code, id as game_id from public.games limit 1 \gset

do $$
begin
  assert (select count(*) from public.games) = 1, 'the game should exist';
  assert (select length(code) from public.games) = 6, 'join code should be six characters';
  assert (select count(*) from public.game_players) = 1, 'the host should be seated';
end;
$$;

-- ------------------------------------------------------- a stranger looks --

set test.uid = '33333333-3333-3333-3333-333333333333';
do $$
begin
  assert (select count(*) from public.games) = 0,
    'RLS should hide a game from someone who is not in it';
  assert (select count(*) from public.game_players) = 0,
    'RLS should hide the seats too';
end;
$$;

-- ------------------------------------------------------- Sam joins by code --

set test.uid = '22222222-2222-2222-2222-222222222222';
select public.join_game(:'game_code', 'Sam') as joined \gset

do $$
begin
  assert (select count(*) from public.games) = 1, 'Sam can now see the game';
  assert (select count(*) from public.game_players) = 2, 'two seats at the table';
end;
$$;

-- Joining a second time must reuse the same seat, not create a new one.
select public.join_game(:'game_code', 'Sam') as rejoined \gset
do $$
begin
  assert (select count(*) from public.game_players) = 2,
    'rejoining should reuse the existing seat';
end;
$$;

-- ------------------------------------------------------------ round one --

-- Only the host can start a round.
set test.uid = '22222222-2222-2222-2222-222222222222';
do $$
declare
  denied boolean := false;
begin
  begin
    insert into public.rounds (game_id, number, chip_values)
    values ((select id from public.games limit 1), 1, '[]'::jsonb);
  exception when insufficient_privilege then
    denied := true;
  end;
  assert denied, 'a non-host should not be able to open a round';
end;
$$;

set test.uid = '11111111-1111-1111-1111-111111111111';
insert into public.rounds (game_id, number, chip_values)
values (:'game_id', 1, '[{"key":"blue","label":"Blue","color":"#2563eb","valueCents":500}]'::jsonb);

select id as round_id from public.rounds where game_id = :'game_id' and number = 1 \gset

-- Both players buy in for $20. Either player may record money.
insert into public.ledger_entries (game_id, player_id, round_id, kind, amount_cents)
select :'game_id', id, :'round_id', 'buy_in', 2000 from public.game_players;

set test.uid = '22222222-2222-2222-2222-222222222222';
insert into public.round_stacks (round_id, player_id, stack_cents)
select :'round_id', id, case when display_name = 'Sam' then 1000 else 3000 end
from public.game_players;

set test.uid = '11111111-1111-1111-1111-111111111111';
update public.rounds set status = 'closed', closed_at = now() where id = :'round_id';

do $$
begin
  assert (select sum(amount_cents) from public.ledger_entries) = 4000, '$40 on the table';
  assert (select sum(stack_cents) from public.round_stacks) = 4000, 'chips are conserved';
end;
$$;

-- -------------------------------------------------- Sam leaves, then returns --

set test.uid = '22222222-2222-2222-2222-222222222222';
update public.game_players set status = 'left', left_at = now() where user_id = auth.uid();
select public.join_game(:'game_code', 'Sam') as back \gset

do $$
begin
  assert (select status from public.game_players
          where user_id = '22222222-2222-2222-2222-222222222222') = 'active',
    'rejoining should put Sam back in play';
  assert (select count(*) from public.round_stacks) = 2,
    'leaving must not touch recorded history';
end;
$$;

-- --------------------------------------------------- chip values per round --

set test.uid = '11111111-1111-1111-1111-111111111111';
insert into public.rounds (game_id, number, chip_values)
values (:'game_id', 2, '[{"key":"blue","label":"Blue","color":"#2563eb","valueCents":1000}]'::jsonb);

do $$
begin
  assert (select (chip_values->0->>'valueCents')::int from public.rounds where number = 1) = 500,
    'round one keeps the price it was scored at';
  assert (select (chip_values->0->>'valueCents')::int from public.rounds where number = 2) = 1000,
    'round two can re-price the same colour';
end;
$$;

-- Non-host cannot re-price a round.
set test.uid = '22222222-2222-2222-2222-222222222222';
update public.rounds set chip_values = '[]'::jsonb where number = 2;
do $$
begin
  assert (select jsonb_array_length(chip_values) from public.rounds where number = 2) = 1,
    'RLS should have silently filtered out a non-host re-pricing';
end;
$$;

-- ------------------------------------------------------------- settlement --

set test.uid = '11111111-1111-1111-1111-111111111111';
insert into public.settlements (game_id, payments, totals)
values (:'game_id', '[{"fromPlayerId":"a","toPlayerId":"b","amountCents":1000}]'::jsonb, '[]'::jsonb);
update public.games set status = 'settled', ended_at = now() where id = :'game_id';

do $$
begin
  assert (select status from public.games) = 'settled', 'the game should be closed out';
end;
$$;

set test.uid = '33333333-3333-3333-3333-333333333333';
do $$
begin
  assert (select count(*) from public.settlements) = 0,
    'a stranger must not see the settlement either';
end;
$$;

reset role;
\echo '--- schema smoke test passed ---'
