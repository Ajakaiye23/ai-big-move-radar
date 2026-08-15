'use client';

import { useState } from 'react';
import { centsToChips, chipsToCents } from '@/lib/ledger';
import { formatMoney, parseMoney } from '@/lib/money';
import type { ChipCounts, ChipDenomination } from '@/lib/types';
import { ChipDot, inputClass } from './ui';

export type StackValue = { cents: number; chips: ChipCounts | null };

/**
 * One control for "how much", usable two ways: type a dollar amount and see the
 * chips it buys, or count the chips in front of you and see what they're worth
 * at this round's prices.
 */
export function StackInput({
  chips,
  value,
  onChange,
  autoFocus = false,
  quickAmounts = true,
}: {
  chips: ChipDenomination[];
  value: StackValue;
  onChange: (next: StackValue) => void;
  autoFocus?: boolean;
  /** Off when several of these are stacked up, as in the end-of-round count. */
  quickAmounts?: boolean;
}) {
  const [mode, setMode] = useState<'money' | 'chips'>('money');
  const [draft, setDraft] = useState<string>(value.cents ? (value.cents / 100).toString() : '');

  function setMoney(raw: string) {
    setDraft(raw);
    const cents = parseMoney(raw);
    onChange({ cents: cents ?? 0, chips: cents ? centsToChips(cents, chips) : null });
  }

  function setCount(key: string, raw: string) {
    const n = Math.max(0, Math.floor(Number(raw) || 0));
    const counts = { ...(value.chips ?? {}), [key]: n };
    for (const k of Object.keys(counts)) if (!counts[k]) delete counts[k];
    const cents = chipsToCents(counts, chips);
    setDraft((cents / 100).toString());
    onChange({ cents, chips: counts });
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-1 rounded-lg bg-black/30 p-1 text-sm">
        {(['money', 'chips'] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`pressable flex-1 rounded-md py-1.5 ${
              mode === m ? 'bg-white/10 font-medium' : 'text-ink-500'
            }`}
          >
            {m === 'money' ? 'Amount' : 'Count chips'}
          </button>
        ))}
      </div>

      {mode === 'money' ? (
        <>
          <div className="relative">
            <span className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-xl text-ink-500">
              $
            </span>
            <input
              className={`${inputClass} py-3 pl-9 text-2xl tabular`}
              inputMode="decimal"
              autoFocus={autoFocus}
              value={draft}
              placeholder="0.00"
              onChange={(e) => setMoney(e.target.value)}
              aria-label="Amount in dollars"
            />
          </div>
          <div className={`flex-wrap gap-2 ${quickAmounts ? 'flex' : 'hidden'}`}>
            {[20, 40, 60, 100].map((amount) => (
              <button
                key={amount}
                type="button"
                onClick={() => setMoney(String(amount))}
                className="pressable rounded-lg border border-white/10 px-3 py-1.5 text-sm text-ink-300 hover:bg-white/10"
              >
                ${amount}
              </button>
            ))}
          </div>
          {value.chips && value.cents > 0 ? (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-500">
              <span>That&apos;s</span>
              {chips
                .filter((c) => value.chips?.[c.key])
                .map((c) => (
                  <span key={c.key} className="inline-flex items-center gap-1.5">
                    <ChipDot chip={c} size={14} />
                    {value.chips?.[c.key]} × {c.label}
                  </span>
                ))}
            </p>
          ) : null}
        </>
      ) : (
        <div className="space-y-2">
          {chips.map((chip) => (
            <div key={chip.key} className="flex items-center gap-3">
              <ChipDot chip={chip} size={24} />
              <span className="flex-1 text-sm">
                {chip.label}{' '}
                <span className="text-ink-500">{formatMoney(chip.valueCents)}</span>
              </span>
              <input
                className={`${inputClass} w-24 text-right tabular`}
                inputMode="numeric"
                aria-label={`${chip.label} chips`}
                value={value.chips?.[chip.key] ?? ''}
                placeholder="0"
                onChange={(e) => setCount(chip.key, e.target.value)}
              />
            </div>
          ))}
          <p className="text-right text-sm text-ink-300">
            Worth <span className="font-semibold tabular">{formatMoney(value.cents)}</span>
          </p>
        </div>
      )}
    </div>
  );
}
