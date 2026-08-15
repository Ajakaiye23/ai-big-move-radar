'use client';

import { useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { createClient } from '@/lib/supabase/client';
import { buildWindows, recentRounds, type GameSummary } from '@/lib/stats';
import { formatMoney, formatMoneyShort } from '@/lib/money';
import { DEFAULT_CHIPS, type ChipDenomination } from '@/lib/types';
import { ChipValuesEditor } from './chip-values-editor';
import { InstallHint } from './install-prompt';
import { Button, Empty, Field, Money, Sheet, inputClass } from './ui';

export function Dashboard({
  displayName,
  avatarUrl,
  summaries,
}: {
  displayName: string;
  avatarUrl: string | null;
  summaries: GameSummary[];
}) {
  const router = useRouter();
  const params = useSearchParams();
  const [creating, setCreating] = useState(params.get('new') === '1');
  const [joining, setJoining] = useState(params.get('join') === '1');

  const windows = useMemo(() => buildWindows(summaries), [summaries]);
  const rounds = useMemo(() => recentRounds(summaries, 12), [summaries]);
  const live = summaries.filter((s) => s.game.status === 'active');
  const finished = summaries.filter((s) => s.game.status !== 'active');

  async function signOut() {
    await createClient().auth.signOut();
    router.push('/');
    router.refresh();
  }

  return (
    <main className="mx-auto w-full max-w-4xl space-y-8 px-4 py-6 sm:px-6 sm:py-10">
      <header className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatarUrl} alt="" width={40} height={40} className="rounded-full" />
          ) : (
            <div className="grid h-10 w-10 place-items-center rounded-full bg-brass-500/20 font-semibold text-brass-400">
              {displayName.slice(0, 1).toUpperCase()}
            </div>
          )}
          <div>
            <p className="text-sm text-ink-500">Signed in as</p>
            <p className="font-medium">{displayName}</p>
          </div>
        </div>
        <Button variant="ghost" onClick={signOut}>
          Sign out
        </Button>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {windows.map((w) => (
          <div key={w.key} className="card p-4">
            <p className="text-xs tracking-wide text-ink-500 uppercase">{w.label}</p>
            <p className="mt-2 text-xl font-semibold tabular">{formatMoneyShort(w.volumeCents)}</p>
            <p className="text-xs text-ink-500">played through</p>
            <p className="mt-2 text-sm">
              <Money cents={w.netCents} sign />{' '}
              <span className="text-ink-500">
                · {w.games} {w.games === 1 ? 'game' : 'games'}
              </span>
            </p>
            {w.liveGames > 0 ? (
              <p className="mt-1 text-[11px] text-brass-400">{w.liveGames} still running</p>
            ) : null}
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-3 sm:flex-row">
        <Button className="flex-1" onClick={() => setCreating(true)}>
          Start a table
        </Button>
        <Button className="flex-1" variant="ghost" onClick={() => setJoining(true)}>
          Join with a code
        </Button>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium tracking-wide text-ink-300 uppercase">At the table now</h2>
        {live.length === 0 ? (
          <Empty>No games running. Start a table and share the code.</Empty>
        ) : (
          <ul className="space-y-2">
            {live.map((s) => (
              <GameRow key={s.game.id} summary={s} />
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium tracking-wide text-ink-300 uppercase">History</h2>
        {finished.length === 0 ? (
          <Empty>Settled games show up here.</Empty>
        ) : (
          <ul className="space-y-2">
            {finished.slice(0, 20).map((s) => (
              <GameRow key={s.game.id} summary={s} />
            ))}
          </ul>
        )}
      </section>

      {rounds.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-sm font-medium tracking-wide text-ink-300 uppercase">Recent rounds</h2>
          <ul className="card divide-y divide-white/5">
            {rounds.map((r, i) => (
              <li key={`${r.gameCode}-${r.roundNumber}-${i}`} className="flex items-center justify-between px-4 py-2.5 text-sm">
                <span className="text-ink-300">
                  {r.gameName} <span className="text-ink-500">· round {r.roundNumber}</span>
                </span>
                <Money cents={r.netCents} sign />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <InstallHint />

      <CreateGameSheet open={creating} onClose={() => setCreating(false)} displayName={displayName} />
      <JoinGameSheet open={joining} onClose={() => setJoining(false)} displayName={displayName} />
    </main>
  );
}

function GameRow({ summary }: { summary: GameSummary }) {
  const { game, state } = summary;
  return (
    <li>
      <Link
        href={`/game/${game.code}`}
        className="card pressable flex items-center justify-between gap-4 p-4 hover:bg-white/5"
      >
        <div className="min-w-0">
          <p className="truncate font-medium">{game.name}</p>
          <p className="text-xs text-ink-500">
            <span className="font-mono tracking-widest">{game.code}</span> ·{' '}
            {new Date(summary.playedAt).toLocaleDateString()} ·{' '}
            {game.status === 'active' ? 'live' : 'settled'}
          </p>
        </div>
        <div className="text-right">
          <Money cents={state.netCents} sign className="font-semibold" />
          <p className="text-xs text-ink-500">in {formatMoney(state.totalBuyInCents)}</p>
        </div>
      </Link>
    </li>
  );
}

function CreateGameSheet({
  open,
  onClose,
  displayName,
}: {
  open: boolean;
  onClose: () => void;
  displayName: string;
}) {
  const router = useRouter();
  const [name, setName] = useState('Friday night');
  const [chips, setChips] = useState<ChipDenomination[]>(DEFAULT_CHIPS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    const { data, error } = await createClient().rpc('create_game', {
      p_name: name,
      p_chip_values: chips,
      p_display_name: displayName,
    });
    if (error) {
      setError(error.message);
      setBusy(false);
      return;
    }
    router.push(`/game/${(data as { code: string }).code}`);
  }

  return (
    <Sheet open={open} onClose={onClose} title="Start a table">
      <div className="space-y-5">
        <Field label="Table name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>

        <div className="space-y-2">
          <p className="text-xs font-medium tracking-wide text-ink-300 uppercase">Chip values</p>
          <p className="text-xs text-ink-500">
            These are the table defaults. You can re-price any colour round by round once the
            game is running.
          </p>
          <ChipValuesEditor chips={chips} onChange={setChips} />
        </div>

        {error ? <p className="text-sm text-red-400">{error}</p> : null}

        <Button className="w-full" onClick={create} disabled={busy}>
          {busy ? 'Dealing in…' : 'Create table'}
        </Button>
      </div>
    </Sheet>
  );
}

function JoinGameSheet({
  open,
  onClose,
  displayName,
}: {
  open: boolean;
  onClose: () => void;
  displayName: string;
}) {
  const router = useRouter();
  const [code, setCode] = useState('');
  const [nameAtTable, setNameAtTable] = useState(displayName);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function join() {
    setBusy(true);
    setError(null);
    const { data, error } = await createClient().rpc('join_game', {
      p_code: code.trim().toUpperCase(),
      p_display_name: nameAtTable,
    });
    if (error) {
      setError(error.message.replace(/^.*?:\s*/, ''));
      setBusy(false);
      return;
    }
    router.push(`/game/${(data as { code: string }).code}`);
  }

  return (
    <Sheet open={open} onClose={onClose} title="Join a table">
      <div className="space-y-5">
        <Field label="Game code" hint="Six characters, from whoever is hosting.">
          <input
            className={`${inputClass} text-center font-mono text-2xl tracking-[0.4em] uppercase`}
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            maxLength={6}
            autoCapitalize="characters"
            autoCorrect="off"
            inputMode="text"
            placeholder="ABC123"
          />
        </Field>
        <Field label="Name at the table">
          <input
            className={inputClass}
            value={nameAtTable}
            onChange={(e) => setNameAtTable(e.target.value)}
          />
        </Field>

        {error ? <p className="text-sm text-red-400">{error}</p> : null}

        <Button className="w-full" onClick={join} disabled={busy || code.trim().length < 4}>
          {busy ? 'Taking a seat…' : 'Sit down'}
        </Button>
        <p className="text-xs text-ink-500">
          Rejoining a table you already played? Same code — your chips and history are still
          there.
        </p>
      </div>
    </Sheet>
  );
}
