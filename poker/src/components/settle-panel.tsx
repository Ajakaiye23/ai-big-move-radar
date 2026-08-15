'use client';

import { useMemo, useState } from 'react';
import type { GameData } from '@/hooks/use-game';
import type { GameState } from '@/lib/ledger';
import { finishGame, reopenGame } from '@/lib/actions';
import { formatMoney } from '@/lib/money';
import { settle } from '@/lib/settle';
import type { Payment } from '@/lib/types';
import { Button, Empty, Money } from './ui';

export function SettlePanel({
  data,
  state,
  isHost,
  onChange,
}: {
  data: GameData;
  state: GameState;
  isHost: boolean;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const settled = data.game.status === 'settled';

  const balances = useMemo(
    () => state.players.map((p) => ({ playerId: p.player.id, netCents: p.netCents })),
    [state],
  );

  // A locked settlement is the record of what people actually agreed to pay.
  const payments: Payment[] = useMemo(
    () => (settled && data.settlement ? data.settlement.payments : settle(balances)),
    [settled, data.settlement, balances],
  );

  const nameOf = (playerId: string) =>
    state.byPlayerId.get(playerId)?.player.display_name ?? 'Player';

  const inPlay = balances.filter((b) => b.netCents !== 0).length;
  const naive = Math.max(inPlay - 1, 0);

  async function copySummary() {
    const lines = [
      `${data.game.name} — settle up`,
      ...payments.map((p) => `${nameOf(p.fromPlayerId)} pays ${nameOf(p.toPlayerId)} ${formatMoney(p.amountCents)}`),
    ];
    await navigator.clipboard?.writeText(lines.join('\n'));
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }

  return (
    <div className="space-y-5">
      <section className="card p-4">
        <h2 className="mb-3 font-semibold">Where everyone stands</h2>
        <ul className="divide-y divide-white/5">
          {state.players.map((p) => (
            <li key={p.player.id} className="flex items-center justify-between py-2.5 text-sm">
              <span>
                {p.player.display_name}
                <span className="ml-2 text-xs text-ink-500">
                  in {formatMoney(p.totalBuyInCents)} · out{' '}
                  {formatMoney(p.currentStackCents + p.totalCashOutCents)}
                </span>
              </span>
              <Money cents={p.netCents} sign className="font-semibold" />
            </li>
          ))}
        </ul>
      </section>

      <section className="card space-y-4 p-4">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="font-semibold">Who pays whom</h2>
          {payments.length > 0 ? (
            <span className="text-xs text-ink-500">
              {payments.length} {payments.length === 1 ? 'payment' : 'payments'}
              {naive > payments.length ? ` instead of ${naive}` : ''}
            </span>
          ) : null}
        </div>

        {payments.length === 0 ? (
          <Empty>Nobody owes anybody. Either the night hasn&apos;t started or it ended dead even.</Empty>
        ) : (
          <>
            <ul className="space-y-2">
              {payments.map((p, i) => (
                <li
                  key={`${p.fromPlayerId}-${p.toPlayerId}-${i}`}
                  className="flex items-center gap-3 rounded-xl bg-black/25 p-3"
                >
                  <span className="min-w-0 flex-1 truncate">{nameOf(p.fromPlayerId)}</span>
                  <span aria-hidden className="text-brass-400">→</span>
                  <span className="min-w-0 flex-1 truncate">{nameOf(p.toPlayerId)}</span>
                  <span className="shrink-0 font-semibold tabular">{formatMoney(p.amountCents)}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-ink-500">
              Fewest possible transfers: anyone whose debts already cancel out inside a smaller
              group settles there instead of passing money around the whole table.
            </p>
            <Button variant="ghost" className="w-full" onClick={copySummary}>
              {copied ? 'Copied' : 'Copy the list'}
            </Button>
          </>
        )}
      </section>

      {isHost ? (
        <section className="card space-y-3 p-4">
          {settled ? (
            <>
              <p className="text-sm text-ink-300">
                This game is settled and locked. Reopening lets you fix a miscount, and the
                payment plan will be recalculated.
              </p>
              <Button
                variant="ghost"
                className="w-full"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await reopenGame(data.game.id);
                    onChange();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Reopen the game
              </Button>
            </>
          ) : (
            <>
              <p className="text-sm text-ink-300">
                Locking the game freezes these numbers into everyone&apos;s history and stops
                further buy-ins.
              </p>
              <Button
                className="w-full"
                disabled={busy || payments.length === 0}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    await finishGame({
                      gameId: data.game.id,
                      payments,
                      totals: state.players.map((p) => ({
                        playerId: p.player.id,
                        netCents: p.netCents,
                        buyInCents: p.totalBuyInCents,
                      })),
                    });
                    onChange();
                  } catch (e) {
                    setError(e instanceof Error ? e.message : 'Could not settle the game.');
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? 'Settling…' : 'Settle and close the game'}
              </Button>
              {error ? <p className="text-sm text-red-400">{error}</p> : null}
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}
