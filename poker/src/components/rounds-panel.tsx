'use client';

import { useMemo, useState } from 'react';
import type { GameData } from '@/hooks/use-game';
import type { GameState } from '@/lib/ledger';
import { closeRound, setDefaultChipValues, setRoundChipValues, startRound } from '@/lib/actions';
import { chipsToCents } from '@/lib/ledger';
import { formatMoney } from '@/lib/money';
import type { ChipCounts, ChipDenomination } from '@/lib/types';
import { ChipValuesEditor } from './chip-values-editor';
import { currentChipValues } from './players-panel';
import { StackInput, type StackValue } from './stack-input';
import { Button, Empty, Money, Sheet } from './ui';

export function RoundsPanel({
  data,
  state,
  userId,
  isHost,
  settled,
  onChange,
}: {
  data: GameData;
  state: GameState;
  userId: string;
  isHost: boolean;
  settled: boolean;
  onChange: () => void;
}) {
  const [scoring, setScoring] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const openRound = data.rounds.find((r) => r.status === 'open') ?? null;
  const closed = data.rounds.filter((r) => r.status === 'closed');
  const nextNumber = (data.rounds.at(-1)?.number ?? 0) + 1;

  async function begin() {
    setBusy(true);
    setError(null);
    try {
      await startRound(data.game.id, nextNumber, currentChipValues(data));
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the round.');
    } finally {
      setBusy(false);
    }
  }

  async function saveChipValues(next: ChipDenomination[]) {
    if (!openRound) return;
    await setRoundChipValues(openRound.id, next);
    await setDefaultChipValues(data.game.id, next);
    onChange();
  }

  return (
    <div className="space-y-5">
      {settled ? null : openRound ? (
        <section className="card space-y-4 p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Round {openRound.number}</h2>
            <span className="text-xs text-brass-400">in play</span>
          </div>

          <div className="space-y-2">
            <p className="text-xs font-medium tracking-wide text-ink-300 uppercase">
              What the chips are worth this round
            </p>
            <ChipValuesEditor
              chips={openRound.chip_values}
              onChange={saveChipValues}
              disabled={!isHost}
            />
            {!isHost ? (
              <p className="text-xs text-ink-500">Only the host can re-price chips.</p>
            ) : null}
          </div>

          {isHost ? (
            <Button className="w-full" onClick={() => setScoring(true)}>
              Score and close round {openRound.number}
            </Button>
          ) : (
            <p className="text-sm text-ink-500">
              The host closes the round once the chips are counted.
            </p>
          )}
        </section>
      ) : (
        <section className="card space-y-3 p-4">
          <h2 className="font-semibold">
            {data.rounds.length === 0 ? 'No rounds yet' : `Round ${nextNumber - 1} is done`}
          </h2>
          <p className="text-sm text-ink-500">
            A round is however long you want it to be — one hand, one hour, or the whole
            night. Everyone&apos;s stack gets counted when it closes.
          </p>
          {isHost ? (
            <Button className="w-full" onClick={begin} disabled={busy}>
              {busy ? 'Starting…' : `Start round ${nextNumber}`}
            </Button>
          ) : (
            <p className="text-sm text-ink-500">Waiting on the host to deal the next round.</p>
          )}
          {error ? <p className="text-sm text-red-400">{error}</p> : null}
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-medium tracking-wide text-ink-300 uppercase">Round by round</h2>
        {closed.length === 0 ? (
          <Empty>Closed rounds and who won what will show up here.</Empty>
        ) : (
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-xs text-ink-500 uppercase">
                  <th className="px-4 py-2.5 font-medium">Player</th>
                  {closed.map((r) => (
                    <th key={r.id} className="px-3 py-2.5 text-right font-medium">
                      R{r.number}
                    </th>
                  ))}
                  <th className="px-4 py-2.5 text-right font-medium">Net</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {state.players.map((p) => (
                  <tr key={p.player.id}>
                    <td className="px-4 py-2.5 whitespace-nowrap">{p.player.display_name}</td>
                    {closed.map((r) => {
                      const result = p.rounds.find((x) => x.roundId === r.id);
                      return (
                        <td key={r.id} className="px-3 py-2.5 text-right">
                          {result?.recorded ? (
                            <Money cents={result.netCents} sign />
                          ) : (
                            <span className="text-ink-500">—</span>
                          )}
                        </td>
                      );
                    })}
                    <td className="px-4 py-2.5 text-right font-semibold">
                      <Money cents={p.netCents} sign />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {openRound ? (
        <ScoreRoundSheet
          open={scoring}
          onClose={() => setScoring(false)}
          data={data}
          state={state}
          userId={userId}
          roundId={openRound.id}
          roundNumber={openRound.number}
          chipValues={openRound.chip_values}
          onDone={onChange}
        />
      ) : null}
    </div>
  );
}

function ScoreRoundSheet({
  open,
  onClose,
  data,
  state,
  userId,
  roundId,
  roundNumber,
  chipValues,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  data: GameData;
  state: GameState;
  userId: string;
  roundId: string;
  roundNumber: number;
  chipValues: ChipDenomination[];
  onDone: () => void;
}) {
  // Everyone with chips in play this round, plus anyone who bought in during it.
  const contenders = useMemo(
    () =>
      state.players.filter((p) => {
        const thisRound = p.rounds.find((r) => r.roundId === roundId);
        return p.player.status !== 'left' || (thisRound && thisRound.startCents !== 0);
      }),
    [state, roundId],
  );

  const expected = useMemo(() => {
    const map = new Map<string, number>();
    for (const p of contenders) {
      const r = p.rounds.find((x) => x.roundId === roundId);
      map.set(p.player.id, r ? r.startCents + r.addedCents - r.removedCents : 0);
    }
    return map;
  }, [contenders, roundId]);

  const [values, setValues] = useState<Record<string, StackValue>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const entered = (playerId: string): StackValue =>
    values[playerId] ?? {
      cents: expected.get(playerId) ?? 0,
      chips: (data.stacks.find((s) => s.round_id === roundId && s.player_id === playerId)?.chips ??
        null) as ChipCounts | null,
    };

  const totalIn = contenders.reduce((sum, p) => sum + (expected.get(p.player.id) ?? 0), 0);
  const totalOut = contenders.reduce((sum, p) => sum + entered(p.player.id).cents, 0);
  const drift = totalOut - totalIn;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await closeRound({
        roundId,
        userId,
        stacks: contenders.map((p) => {
          const v = entered(p.player.id);
          return {
            playerId: p.player.id,
            stackCents: v.chips ? chipsToCents(v.chips, chipValues) : v.cents,
            chips: v.chips,
          };
        }),
      });
      setValues({});
      onDone();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not close the round.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={`Count up — round ${roundNumber}`}>
      <div className="space-y-5">
        <p className="text-sm text-ink-500">
          Enter what each player has in front of them now. The difference from what they
          started the round with is their profit.
        </p>

        {contenders.map((p) => {
          const start = expected.get(p.player.id) ?? 0;
          const now = entered(p.player.id).cents;
          return (
            <div key={p.player.id} className="rounded-xl border border-white/10 p-3">
              <div className="mb-2 flex items-baseline justify-between gap-3">
                <span className="font-medium">{p.player.display_name}</span>
                <span className="text-xs text-ink-500">
                  started with {formatMoney(start)} ·{' '}
                  <Money cents={now - start} sign />
                </span>
              </div>
              <StackInput
                chips={chipValues}
                value={entered(p.player.id)}
                onChange={(v) => setValues((prev) => ({ ...prev, [p.player.id]: v }))}
                quickAmounts={false}
              />
            </div>
          );
        })}

        {drift !== 0 ? (
          <p className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
            The chips counted are {formatMoney(Math.abs(drift))} {drift > 0 ? 'more' : 'less'} than
            what was on the table. Poker is zero-sum — worth a recount before you close.
          </p>
        ) : null}

        {error ? <p className="text-sm text-red-400">{error}</p> : null}

        <Button className="w-full" onClick={submit} disabled={busy}>
          {busy ? 'Saving…' : `Close round ${roundNumber}`}
        </Button>
      </div>
    </Sheet>
  );
}
