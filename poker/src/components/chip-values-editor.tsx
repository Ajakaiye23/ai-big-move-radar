'use client';

import { useState } from 'react';
import { formatMoney, parseMoney } from '@/lib/money';
import type { ChipDenomination } from '@/lib/types';
import { Button, ChipDot, inputClass } from './ui';

const PALETTE = ['#f4f4f5', '#dc2626', '#2563eb', '#16a34a', '#18181b', '#7c3aed', '#f97316', '#0891b2'];

/**
 * What each colour is worth. Editing this on a round re-values every stack
 * recorded against that round, which is exactly the "blue is $5 tonight" case.
 */
export function ChipValuesEditor({
  chips,
  onChange,
  disabled = false,
}: {
  chips: ChipDenomination[];
  onChange: (next: ChipDenomination[]) => void;
  disabled?: boolean;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  function setValue(key: string, raw: string) {
    setDrafts((d) => ({ ...d, [key]: raw }));
    const cents = parseMoney(raw);
    if (cents === null || cents < 0) return;
    onChange(chips.map((c) => (c.key === key ? { ...c, valueCents: cents } : c)));
  }

  function addColour() {
    const used = new Set(chips.map((c) => c.color));
    const color = PALETTE.find((p) => !used.has(p)) ?? PALETTE[0];
    const key = `chip${chips.length + 1}-${Math.random().toString(36).slice(2, 6)}`;
    onChange([...chips, { key, label: 'New chip', color, valueCents: 100 }]);
  }

  return (
    <div className="space-y-2">
      {chips.map((chip) => (
        <div key={chip.key} className="flex items-center gap-2.5">
          <label className="relative shrink-0" title="Chip colour">
            <ChipDot chip={chip} size={28} />
            <input
              type="color"
              value={chip.color}
              disabled={disabled}
              onChange={(e) =>
                onChange(chips.map((c) => (c.key === chip.key ? { ...c, color: e.target.value } : c)))
              }
              className="absolute inset-0 cursor-pointer opacity-0"
              aria-label={`${chip.label} colour`}
            />
          </label>

          <input
            className={`${inputClass} flex-1`}
            value={chip.label}
            disabled={disabled}
            aria-label="Chip name"
            onChange={(e) =>
              onChange(chips.map((c) => (c.key === chip.key ? { ...c, label: e.target.value } : c)))
            }
          />

          <div className="relative w-28 shrink-0">
            <span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-500">$</span>
            <input
              className={`${inputClass} pl-6 text-right tabular`}
              inputMode="decimal"
              disabled={disabled}
              aria-label={`${chip.label} value`}
              value={drafts[chip.key] ?? (chip.valueCents / 100).toString()}
              onChange={(e) => setValue(chip.key, e.target.value)}
              // Drop the raw draft on blur so the field snaps back to the stored value.
              onBlur={() => setDrafts(({ [chip.key]: _dropped, ...rest }) => rest)}
            />
          </div>

          {!disabled && chips.length > 1 ? (
            <button
              onClick={() => onChange(chips.filter((c) => c.key !== chip.key))}
              aria-label={`Remove ${chip.label}`}
              className="pressable shrink-0 rounded-lg px-2 py-2 text-ink-500 hover:bg-white/10"
            >
              ✕
            </button>
          ) : null}
        </div>
      ))}

      {!disabled ? (
        <Button variant="ghost" onClick={addColour} className="w-full">
          Add a colour
        </Button>
      ) : null}

      <p className="text-xs text-ink-500">
        A full rack:{' '}
        {chips.map((c) => `${c.label} ${formatMoney(c.valueCents)}`).join(' · ')}
      </p>
    </div>
  );
}
