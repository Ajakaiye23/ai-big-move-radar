import type { Payment } from './types';

export type Balance = { playerId: string; netCents: number };

/**
 * Turn end-of-game net positions into the shortest possible list of payments.
 *
 * The naive approach (biggest loser pays biggest winner, repeat) always finishes
 * in at most n-1 payments, but it misses free wins: if a subset of players already
 * nets to zero among themselves, that subset can be settled independently and every
 * extra independent subset saves exactly one payment. So the real problem is
 * "split the players into as many zero-sum groups as possible", which is a
 * subset-sum partition — NP-hard, but trivial at home-game sizes.
 *
 * We do an exact bitmask DP up to EXACT_LIMIT players and fall back to plain greedy
 * above that (which is still correct, just possibly one or two payments longer).
 */
const EXACT_LIMIT = 15;

export function settle(balances: Balance[]): Payment[] {
  const active = balances.filter((b) => b.netCents !== 0);
  if (active.length === 0) return [];

  const total = active.reduce((sum, b) => sum + b.netCents, 0);
  if (total !== 0) {
    // Chips didn't reconcile (someone's stack was mistyped). Absorb the difference
    // on the largest position so we still produce a usable, fully-balanced plan.
    const idx = active.reduce(
      (best, b, i) => (Math.abs(b.netCents) > Math.abs(active[best].netCents) ? i : best),
      0,
    );
    active[idx] = { ...active[idx], netCents: active[idx].netCents - total };
  }

  const groups =
    active.length <= EXACT_LIMIT ? partitionIntoZeroSumGroups(active) : [active];

  return groups.flatMap(greedyWithinGroup);
}

/** Largest debtor pays largest creditor until everyone is square. */
function greedyWithinGroup(group: Balance[]): Payment[] {
  const debtors = group
    .filter((b) => b.netCents < 0)
    .map((b) => ({ ...b }))
    .sort((a, b) => a.netCents - b.netCents);
  const creditors = group
    .filter((b) => b.netCents > 0)
    .map((b) => ({ ...b }))
    .sort((a, b) => b.netCents - a.netCents);

  const payments: Payment[] = [];
  let i = 0;
  let j = 0;
  while (i < debtors.length && j < creditors.length) {
    const amount = Math.min(-debtors[i].netCents, creditors[j].netCents);
    if (amount > 0) {
      payments.push({
        fromPlayerId: debtors[i].playerId,
        toPlayerId: creditors[j].playerId,
        amountCents: amount,
      });
    }
    debtors[i].netCents += amount;
    creditors[j].netCents -= amount;
    if (debtors[i].netCents === 0) i++;
    if (creditors[j].netCents === 0) j++;
  }
  return payments;
}

/**
 * Split players into the maximum number of subsets that each sum to zero.
 * DP over subsets: best[mask] = max groups the players in `mask` can be split into.
 */
function partitionIntoZeroSumGroups(balances: Balance[]): Balance[][] {
  const n = balances.length;
  const full = (1 << n) - 1;

  const sums = new Int32Array(full + 1);
  for (let mask = 1; mask <= full; mask++) {
    const low = mask & -mask;
    const idx = 31 - Math.clz32(low);
    sums[mask] = sums[mask ^ low] + balances[idx].netCents;
  }

  const best = new Int32Array(full + 1).fill(-1);
  const choice = new Int32Array(full + 1);
  best[0] = 0;

  for (let mask = 1; mask <= full; mask++) {
    // Anchor on the lowest set bit so each partition is generated exactly once.
    const anchor = mask & -mask;
    const rest = mask ^ anchor;
    // Enumerate every sub-subset of `rest`, each combined with the anchor.
    for (let sub = rest; ; sub = (sub - 1) & rest) {
      const group = sub | anchor;
      if (sums[group] === 0) {
        const remainder = best[mask ^ group];
        if (remainder >= 0 && remainder + 1 > best[mask]) {
          best[mask] = remainder + 1;
          choice[mask] = group;
        }
      }
      if (sub === 0) break;
    }
    // best[mask] stays -1 when the subset doesn't sum to zero, so it can never be
    // used as the remainder of another split. The full set always sums to zero.
  }

  const groups: Balance[][] = [];
  let mask = full;
  while (mask > 0) {
    const group = choice[mask] || mask;
    groups.push(balances.filter((_, i) => (group >> i) & 1));
    mask ^= group;
  }
  return groups;
}

/** Human-readable check that a payment plan actually squares everyone up. */
export function verifyPlan(balances: Balance[], payments: Payment[]): boolean {
  const net = new Map<string, number>();
  for (const b of balances) net.set(b.playerId, b.netCents);
  for (const p of payments) {
    net.set(p.fromPlayerId, (net.get(p.fromPlayerId) ?? 0) + p.amountCents);
    net.set(p.toPlayerId, (net.get(p.toPlayerId) ?? 0) - p.amountCents);
  }
  return [...net.values()].every((v) => v === 0);
}
