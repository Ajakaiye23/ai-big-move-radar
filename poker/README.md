# Chip Ledger

Bookkeeping for a home poker game. Everyone signs in with the Google or Apple
account already on their phone, one person opens a table, the rest join with a
six-character code, and the app keeps the ledger: buy-ins, what each chip colour
is worth in each round, what every player won or lost round by round, and — at
the end — who pays whom, in the fewest possible payments.

It installs to a phone home screen as a standalone app, and works the same on a
laptop.

## Look before you build

```bash
npm install
npm run dev
```

Then open http://localhost:3000/preview — a made-up Friday night you can click
through with no accounts and no backend. Nothing there is saved.

## What it does

**Accounts.** Google and Apple sign-in through Supabase Auth. A profile row is
created on first sign-in; everything a player does is tied to it.

**Your numbers.** Money played through and net result over the last 24 hours,
7 days, 30 days, your last 10 games, and all time — plus a round-by-round feed.
A game counts toward a window based on when it wrapped up, so one long night
doesn't smear across two weeks.

**Tables.** A table is a shared room with a join code. Anyone with the code takes
a seat. The host can also add people who don't have the app at all — they get a
seat that the host keeps the books for.

**Chip values, per round.** Each round stores its own price list. Blue is $5 in
round one and $10 in round two if you want it to be, and round one keeps the
prices it was scored at.

**Buy in for whatever you like.** Type a dollar amount and see the chips it buys,
or count out the chips and see what they're worth. Rebuy as often as you want.
Cashing out takes money off the table without it counting as a loss.

**Leave and come back.** Sitting out, walking away, or joining at round nine are
all just rows in an append-only history. Rejoining reuses your seat rather than
making a new one, so nothing is ever orphaned.

**Settling up.** At the end, the app computes the shortest list of payments that
squares everyone. See [How the settle-up works](#how-the-settle-up-works).

**Installable.** Manifest, icons, service worker, iOS meta tags. Android offers a
real install prompt; iOS gets Share → Add to Home Screen instructions.

## Setting up the backend

1. **Create a Supabase project** at [supabase.com](https://supabase.com) (the free
   tier is plenty for a home game).

2. **Run the migration.** Open the SQL editor and paste in
   `supabase/migrations/0001_init.sql`. That creates the tables, the row-level
   security policies, the join-by-code function, and turns on realtime.

3. **Turn on the providers.** Authentication → Providers:
   - **Google**: create an OAuth client in Google Cloud Console, paste the client
     ID and secret in. Add Supabase's callback URL
     (`https://<project-ref>.supabase.co/auth/v1/callback`) as an authorised
     redirect URI.
   - **Apple**: needs a paid Apple Developer account ($99/yr) to create a
     Services ID and key. If you don't have one, Google alone works fine — the
     Apple button will just error until it's configured.

4. **Add redirect URLs.** Authentication → URL Configuration → Redirect URLs:
   add `http://localhost:3000/auth/callback` and your deployed
   `https://your-domain/auth/callback`.

5. **Point the app at it.**

   ```bash
   cp .env.example .env.local   # then fill in the URL and anon key
   npm run dev
   ```

The anon key is meant to be public — every table has row-level security on it,
so the database itself enforces that you only ever see games you're sitting at.

## Deploying

Any host that runs Next.js works. Vercel is the least effort:

```bash
npx vercel
```

Set `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` in the project's
environment variables, then add the deployed callback URL to Supabase (step 4).

Installing to a home screen requires HTTPS, which you get automatically on
Vercel/Netlify and on `localhost` for testing.

## How the settle-up works

Say four people finish a night at +$15, −$15, +$5, −$5. The obvious approach —
biggest loser pays biggest winner, repeat — always finishes in at most n−1
payments, and often takes exactly that many. But here the table splits into two
pairs that cancel out, so two payments do the whole job instead of three.

That generalises: every group of players whose balances already sum to zero can
settle among themselves, and each extra independent group saves one payment. So
the real problem is *split the table into as many zero-sum groups as possible*,
which is a subset-sum partition — NP-hard in general, trivial at eight players.
`src/lib/settle.ts` solves it exactly with a bitmask DP up to 15 players and
falls back to greedy above that (still correct, occasionally a payment longer).

If someone's chip count was typed wrong and the totals don't reconcile, the app
says so, and settling anyway puts the difference on the largest position rather
than producing a plan nobody can actually pay.

## How the round maths works

The whole ledger rests on one identity. A player's stack at the end of a round is

```
end = start + bought in − cashed out + won/lost
```

so their profit for that round is `end − (start + bought in − cashed out)`, and
their profit for the night is `final stack + cashed out − bought in`.

Nothing is ever overwritten: buy-ins and round stacks are append-only rows, and a
player who wasn't at the table for a round simply has no row for it. That's why
late joins, walk-aways and rejoins need no special handling — see
`src/lib/ledger.ts` and its tests.

## Tests

```bash
npm test          # settlement + ledger maths (22 tests)
npm run test:db   # schema, RLS policies and RPCs against a local Postgres
npm run typecheck
```

`test:db` needs a Postgres you can reach with `psql`. It creates a throwaway
database, stubs out the parts of Supabase the migration depends on (the `auth`
schema, `auth.uid()`, the `anon`/`authenticated` roles), applies the migration
and then plays out a game: a stranger is checked to be unable to read the table,
a non-host is checked to be unable to open or re-price a round, and rejoining is
checked to reuse the existing seat.

## Layout

```
src/lib/settle.ts      minimum-payment settlement
src/lib/ledger.ts      rebuilds the game from its rows: per-round nets, totals
src/lib/stats.ts       the rolling account windows
src/lib/queries.ts     reads (a game; an account's whole history)
src/lib/actions.ts     writes (buy-ins, rounds, stacks, settlement)
src/hooks/use-game.ts  live sync for everyone at the table
src/components/        the UI
supabase/migrations/   schema, RLS, join-by-code
scripts/make-icons.mjs draws the PWA icons (no image dependencies)
```

## Notes and limits

- **Trust model.** This is a home game, so any player at a table can record a
  buy-in or enter a chip count; only the host opens and closes rounds, re-prices
  chips, and locks the settlement. Rows are attributed to whoever wrote them.
- **Offline.** The service worker keeps the app shell, not the ledger. Money data
  is always fetched fresh — a stale balance is worse than a spinner.
- **Currency.** Everything is integer cents with a `$` in front. There's no
  multi-currency support.
