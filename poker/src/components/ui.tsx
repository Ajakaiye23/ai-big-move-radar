'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import { formatMoney } from '@/lib/money';
import type { ChipDenomination } from '@/lib/types';

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  className = '',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'danger';
  size?: 'md' | 'sm';
}) {
  const styles = {
    primary: 'bg-brass-500 text-felt-950 hover:bg-brass-400 font-semibold',
    ghost: 'bg-white/5 text-ink-100 hover:bg-white/10 border border-white/10',
    danger: 'bg-red-600/90 text-white hover:bg-red-600',
  }[variant];

  // 44px tall by default: the smallest thing a thumb reliably hits.
  const sizing = size === 'sm' ? 'min-h-9 rounded-lg px-3 text-xs' : 'min-h-11 rounded-xl px-4 text-sm';

  return (
    <button
      className={`pressable inline-flex items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-40 ${sizing} ${styles} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium tracking-wide text-ink-300 uppercase">{label}</span>
      {children}
      {hint ? <span className="block text-xs text-ink-500">{hint}</span> : null}
    </label>
  );
}

export const inputClass =
  'w-full rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-ink-100 outline-none placeholder:text-ink-500 focus:border-brass-500/60';

/** Bottom sheet on phones, centred dialog on desktop. */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center"
      onClick={onClose}
    >
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="card max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-b-none p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] outline-none sm:rounded-b-[var(--radius-card)] sm:pb-5"
      >
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="pressable rounded-lg px-2 py-1 text-ink-300 hover:bg-white/10"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Money({ cents, sign = false, className = '' }: { cents: number; sign?: boolean; className?: string }) {
  const tone = cents > 0 ? 'text-emerald-400' : cents < 0 ? 'text-red-400' : 'text-ink-300';
  return (
    <span className={`tabular ${sign ? tone : ''} ${className}`}>
      {formatMoney(cents, { sign: sign && cents > 0 })}
    </span>
  );
}

export function ChipDot({ chip, size = 20 }: { chip: ChipDenomination; size?: number }) {
  return (
    <span
      aria-hidden
      className="inline-block shrink-0 rounded-full border-2 border-dashed"
      style={{
        width: size,
        height: size,
        background: chip.color,
        borderColor: 'rgba(255,255,255,0.55)',
      }}
    />
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-white/10 p-6 text-center text-sm text-ink-500">{children}</p>;
}
