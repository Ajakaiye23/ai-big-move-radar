'use client';

import { useState } from 'react';
import type { GameData } from '@/hooks/use-game';
import type { GameState, PlayerState } from '@/lib/ledger';
import { addGuestPlayer, recordMoney, setPlayerStatus } from '@/lib/actions';
import { formatMoney } from '@/lib/money';
import type { ChipDenomination, GamePlayer } from '@/lib/types';
import { StackInput, type StackValue } from './stack-input';
import { Button, Empty, Field, Money, Sheet, inputClass } from './ui';

export function PlayersPanel({
  data,
  state,
  userId,
  displayName,
  isHost,
  openRoundId,
  settled,
  onChange,
}: {
  data: GameData;
  state: GameState;
  userId: string;
  displayName: string;
  isHost: boolean;
  openRoundId: string | null;
  settled: boolean;
  onChange: () => void;
}) {
  const [money, setMoneySheet] = useState<{ player: GamePlayer; kind: 'buy_in' | 'cash_out' } | null>(null);
  const [addingGuest, setAddingGuest] = useState(false);

  const me = data.players.find((p) => p.user_id === userId) ?? null;
  const chipValues = currentChipValues(data);
  const seated = state.players.filter((p) => p.player.status !== 'left');
  const gone = state.players.filter((p) => p.player.status === 'left');

  return (
    <div className="space-y-4">
      <ul className="space-y-2">
        {seated.map((p) => (
          <PlayerRow
            key={p.player.id}
            entry={p}
            isMe={p.player.user_id === userId}
            canManage={isHost || p.player.user_id === userId}
            settled={settled}
            onMoney={(kind) => setMoneySheet({ player: p.player, kind })}
            onStatus={async (status) => {
              await setPlayerStatus(p.player.id, status);
              onChange();
            }}
          />
        ))}
      </ul>

      {gone.length > 0 ? (
        <details className="card p-4">
          <summary className="cursor-pointer text-sm text-ink-300">
            Left the table ({gone.length})
          </summary>
          <ul className="mt-3 space-y-2">
            {gone.map((p) => (
              <PlayerRow
                key={p.player.id}
                entry={p}
                isMe={p.player.user_id === userId}
                canManage={isHost || p.player.user_id === userId}
                settled={settled}
                onMoney={(kind) => setMoneySheet({ player: p.player, kind })}
                onStatus={async (status) => {
                  await setPlayerStatus(p.player.id, status);
                  onChange();
                }}
              />
            ))}
          </ul>
        </details>
      ) : null}

      {state.players.length === 0 ? <Empty>Nobody has sat down yet.</Empty> : null}

      {!settled ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          {isHost ? (
            <Button variant="ghost" className="flex-1" onClick={() => setAddingGuest(true)}>
              Add someone without an account
            </Button>
          ) : null}
          {me ? (
            <Button
              variant="ghost"
              className="flex-1"
              onClick={async () => {
                await setPlayerStatus(me.id, me.status === 'left' ? 'active' : 'left');
                onChange();
              }}
            >
              {me.status === 'left' ? "I'm back" : 'Leave the table'}
            </Button>
          ) : null}
        </div>
      ) : null}

      <p className="text-xs text-ink-500">
        Leaving keeps your chips and your history — walk away, come back three rounds later,
        and the ledger picks up exactly where you left off.
      </p>

      <MoneySheet
        open={money !== null}
        onClose={() => setMoneySheet(null)}
        player={money?.player ?? null}
        kind={money?.kind ?? 'buy_in'}
        chipValues={chipValues}
        gameId={data.game.id}
        roundId={openRoundId}
        userId={userId}
        onDone={onChange}
      />

      <AddGuestSheet
        open={addingGuest}
        onClose={() => setAddingGuest(false)}
        gameId={data.game.id}
        suggestion={`${displayName}'s friend`}
        onDone={onChange}
      />
    </div>
  );
}

function PlayerRow({
  entry,
  isMe,
  canManage,
  settled,
  onMoney,
  onStatus,
}: {
  entry: PlayerState;
  isMe: boolean;
  canManage: boolean;
  settled: boolean;
  onMoney: (kind: 'buy_in' | 'cash_out') => void;
  onStatus: (status: 'active' | 'away' | 'left') => void;
}) {
  const { player } = entry;
  const lastRound = entry.rounds.filter((r) => r.recorded).at(-1);

  return (
    <li className="card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 truncate font-medium">
            {player.display_name}
            {isMe ? <span className="text-xs text-brass-400">you</span> : null}
            {player.user_id === null ? (
              <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-ink-500">guest</span>
            ) : null}
            {player.status === 'left' ? (
              <span className="text-xs text-ink-500">away</span>
            ) : null}
          </p>
          <p className="mt-0.5 text-xs text-ink-500">
            bought in {formatMoney(entry.totalBuyInCents)}
            {entry.totalCashOutCents > 0 ? ` · took ${formatMoney(entry.totalCashOutCents)} off` : ''}
            {lastRound && lastRound.netCents !== 0
              ? ` · last round ${lastRound.netCents > 0 ? '+' : ''}${formatMoney(lastRound.netCents)}`
              : ''}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-lg font-semibold tabular">{formatMoney(entry.currentStackCents)}</p>
          <p className="text-xs">
            <Money cents={entry.netCents} sign />
          </p>
        </div>
      </div>

      {canManage && !settled ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" onClick={() => onMoney('buy_in')}>
            Buy in
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onMoney('cash_out')}>
            Cash out
          </Button>
          {player.status === 'left' ? (
            <Button size="sm" variant="ghost" onClick={() => onStatus('active')}>
              Back in
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => onStatus('left')}>
              Mark away
            </Button>
          )}
        </div>
      ) : null}
    </li>
  );
}

function MoneySheet({
  open,
  onClose,
  player,
  kind,
  chipValues,
  gameId,
  roundId,
  userId,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  player: GamePlayer | null;
  kind: 'buy_in' | 'cash_out';
  chipValues: ChipDenomination[];
  gameId: string;
  roundId: string | null;
  userId: string;
  onDone: () => void;
}) {
  const [value, setValue] = useState<StackValue>({ cents: 0, chips: null });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!player || value.cents <= 0) return;
    setBusy(true);
    setError(null);
    try {
      await recordMoney({
        gameId,
        playerId: player.id,
        roundId,
        kind,
        amountCents: value.cents,
        chips: value.chips,
        userId,
      });
      setValue({ cents: 0, chips: null });
      onDone();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={kind === 'buy_in' ? `Buy in — ${player?.display_name ?? ''}` : `Cash out — ${player?.display_name ?? ''}`}
    >
      <div className="space-y-5">
        <p className="text-sm text-ink-500">
          {kind === 'buy_in'
            ? 'Money onto the table. Buy as many chips as you like, as often as you like.'
            : 'Chips off the table and money back in a pocket. This is not a win or a loss.'}
        </p>
        <StackInput chips={chipValues} value={value} onChange={setValue} autoFocus />
        {error ? <p className="text-sm text-red-400">{error}</p> : null}
        <Button className="w-full" onClick={submit} disabled={busy || value.cents <= 0}>
          {busy
            ? 'Saving…'
            : value.cents <= 0
              ? kind === 'buy_in'
                ? 'Buy in'
                : 'Cash out'
              : kind === 'buy_in'
                ? `Buy in for ${formatMoney(value.cents)}`
                : `Cash out ${formatMoney(value.cents)}`}
        </Button>
      </div>
    </Sheet>
  );
}

function AddGuestSheet({
  open,
  onClose,
  gameId,
  suggestion,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  gameId: string;
  suggestion: string;
  onDone: () => void;
}) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

  return (
    <Sheet open={open} onClose={onClose} title="Add a player">
      <div className="space-y-5">
        <p className="text-sm text-ink-500">
          For someone at the table without the app. You keep their ledger; they can claim a
          seat later by joining with the code.
        </p>
        <Field label="Name">
          <input
            className={inputClass}
            value={name}
            placeholder={suggestion}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Button
          className="w-full"
          disabled={busy || name.trim().length === 0}
          onClick={async () => {
            setBusy(true);
            try {
              await addGuestPlayer(gameId, name.trim());
              setName('');
              onDone();
              onClose();
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? 'Adding…' : 'Add to the table'}
        </Button>
      </div>
    </Sheet>
  );
}

/** The open round's prices if there is one, otherwise the table defaults. */
export function currentChipValues(data: GameData): ChipDenomination[] {
  const open = data.rounds.find((r) => r.status === 'open');
  const fromRound = open?.chip_values;
  if (fromRound && fromRound.length > 0) return fromRound;
  const latest = [...data.rounds].reverse().find((r) => r.chip_values?.length);
  return latest?.chip_values ?? data.game.default_chip_values;
}
