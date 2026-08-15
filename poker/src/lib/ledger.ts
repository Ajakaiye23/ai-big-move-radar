import type { ChipCounts, ChipDenomination, GamePlayer, LedgerEntry, Round, RoundStack } from './types';

export function chipsToCents(chips: ChipCounts | null | undefined, denoms: ChipDenomination[]): number {
  if (!chips) return 0;
  return denoms.reduce((sum, d) => sum + (chips[d.key] ?? 0) * d.valueCents, 0);
}

/** Greedy chip breakdown for an amount — biggest denomination first. */
export function centsToChips(cents: number, denoms: ChipDenomination[]): ChipCounts {
  const sorted = [...denoms].sort((a, b) => b.valueCents - a.valueCents);
  const out: ChipCounts = {};
  let left = cents;
  for (const d of sorted) {
    if (d.valueCents <= 0) continue;
    const n = Math.floor(left / d.valueCents);
    if (n > 0) {
      out[d.key] = n;
      left -= n * d.valueCents;
    }
  }
  return out;
}

export type PlayerRoundResult = {
  roundId: string;
  roundNumber: number;
  /** Stack the player started the round with, before money added this round. */
  startCents: number;
  /** Buy-ins (and positive adjustments) recorded during this round. */
  addedCents: number;
  /** Cash-outs recorded during this round. */
  removedCents: number;
  /** Stack recorded at the end of the round. */
  endCents: number;
  /** What the player actually won or lost this round. */
  netCents: number;
  /** False when nobody has entered this player's stack for the round yet. */
  recorded: boolean;
};

export type PlayerState = {
  player: GamePlayer;
  totalBuyInCents: number;
  totalCashOutCents: number;
  /** Chips in front of the player right now (value of their last recorded stack). */
  currentStackCents: number;
  /** currentStack + cashed out - bought in. Positive means they're up. */
  netCents: number;
  rounds: PlayerRoundResult[];
};

export type GameState = {
  players: PlayerState[];
  byPlayerId: Map<string, PlayerState>;
  /** Total money that has been put on the table. */
  potInCents: number;
  /** Sum of every player's net. Non-zero means a stack entry is off somewhere. */
  imbalanceCents: number;
};

type Input = {
  players: GamePlayer[];
  rounds: Round[];
  entries: LedgerEntry[];
  stacks: RoundStack[];
};

/**
 * Rebuild the whole game from its append-only rows.
 *
 * The invariant that makes late joins, walk-aways and rejoins work without any
 * special cases: a player's stack at the end of a round is
 *     start + bought in - cashed out + won/lost
 * so their net for the round is just `end - (start + added - removed)`, and a
 * player who wasn't at the table simply has no rows for that round.
 */
export function computeGameState({ players, rounds, entries, stacks }: Input): GameState {
  const ordered = [...rounds].sort((a, b) => a.number - b.number);
  const firstRoundId = ordered[0]?.id ?? null;

  const stackKey = (roundId: string, playerId: string) => `${roundId}:${playerId}`;
  const stackMap = new Map<string, RoundStack>();
  for (const s of stacks) stackMap.set(stackKey(s.round_id, s.player_id), s);

  const states: PlayerState[] = players.map((player) => {
    const mine = entries.filter((e) => e.player_id === player.id);

    const totalBuyInCents = mine
      .filter((e) => e.kind === 'buy_in')
      .reduce((sum, e) => sum + e.amount_cents, 0);
    const totalCashOutCents = mine
      .filter((e) => e.kind === 'cash_out')
      .reduce((sum, e) => sum + e.amount_cents, 0);

    let running = 0;
    let sawStack = false;
    const results: PlayerRoundResult[] = [];

    for (const round of ordered) {
      const inRound = mine.filter(
        (e) => e.round_id === round.id || (e.round_id === null && round.id === firstRoundId),
      );
      const addedCents = inRound
        .filter((e) => e.kind === 'buy_in' || e.kind === 'adjustment')
        .reduce((sum, e) => sum + e.amount_cents, 0);
      const removedCents = inRound
        .filter((e) => e.kind === 'cash_out')
        .reduce((sum, e) => sum + e.amount_cents, 0);

      const startCents = running;
      const baseline = startCents + addedCents - removedCents;
      const recordedStack = stackMap.get(stackKey(round.id, player.id));
      const endCents = recordedStack ? recordedStack.stack_cents : baseline;

      // A player with nothing at stake in this round doesn't get a row at all.
      const touched = recordedStack != null || addedCents !== 0 || removedCents !== 0 || baseline !== 0;
      if (touched) {
        results.push({
          roundId: round.id,
          roundNumber: round.number,
          startCents,
          addedCents,
          removedCents,
          endCents,
          netCents: endCents - baseline,
          recorded: recordedStack != null,
        });
      }
      if (recordedStack) sawStack = true;
      running = endCents;
    }

    // Before any round has been scored, chips in front of you are just what you bought.
    const currentStackCents = sawStack || ordered.length > 0
      ? running
      : totalBuyInCents - totalCashOutCents;

    return {
      player,
      totalBuyInCents,
      totalCashOutCents,
      currentStackCents,
      netCents: currentStackCents + totalCashOutCents - totalBuyInCents,
      rounds: results,
    };
  });

  const byPlayerId = new Map(states.map((s) => [s.player.id, s]));
  return {
    players: states,
    byPlayerId,
    potInCents: states.reduce((sum, s) => sum + s.totalBuyInCents, 0),
    imbalanceCents: states.reduce((sum, s) => sum + s.netCents, 0),
  };
}
