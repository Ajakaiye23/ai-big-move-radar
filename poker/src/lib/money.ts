/** Everything in this app is stored and computed in integer cents. */

export function formatMoney(cents: number, opts: { sign?: boolean } = {}): string {
  const negative = cents < 0;
  const abs = Math.abs(cents);
  const body = (abs / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  if (negative) return `-$${body}`;
  if (opts.sign) return `+$${body}`;
  return `$${body}`;
}

/**
 * Compact form for stat tiles: $270 / $1,240 / $12.4k. Whole dollars lose the
 * ".00" so a row of tiles reads as one set of numbers rather than a mix.
 */
export function formatMoneyShort(cents: number): string {
  const abs = Math.abs(cents);
  const sign = cents < 0 ? '-' : '';
  if (abs >= 1_000_00) return `${sign}$${(abs / 100_000).toFixed(1)}k`;
  if (abs % 100 === 0) return `${sign}$${(abs / 100).toLocaleString()}`;
  return formatMoney(cents);
}

/**
 * Parse user-typed money ("12", "$12.50", "1,200") into cents.
 * Returns null when the text isn't a usable number.
 */
export function parseMoney(input: string): number | null {
  const cleaned = input.replace(/[$,\s]/g, '');
  if (cleaned === '' || cleaned === '-' || cleaned === '.') return null;
  if (!/^-?\d*\.?\d*$/.test(cleaned)) return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value)) return null;
  return Math.round(value * 100);
}
