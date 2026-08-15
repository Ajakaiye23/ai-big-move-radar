import { describe, expect, it } from 'vitest';
import { centsToChips, chipsToCents, computeGameState } from './ledger';
import { DEFAULT_CHIPS, type GamePlayer, type LedgerEntry, type Round, type RoundStack } from './types';

const player = (id: string, name = id): GamePlayer => ({
  id,
  game_id: 'g1',
  user_id: null,
  display_name: name,
  status: 'active',
  joined_at: '2026-01-01T00:00:00Z',
  left_at: null,
});

const round = (id: string, number: number): Round => ({
  id,
  game_id: 'g1',
  number,
  status: 'closed',
  chip_values: DEFAULT_CHIPS,
  started_at: '2026-01-01T00:00:00Z',
  closed_at: '2026-01-01T01:00:00Z',
});

const buyIn = (playerId: string, roundId: string | null, dollars: number): LedgerEntry => ({
  id: `${playerId}-${roundId}-${dollars}`,
  game_id: 'g1',
  player_id: playerId,
  round_id: roundId,
  kind: 'buy_in',
  amount_cents: dollars * 100,
  chips: null,
  note: null,
  created_at: '2026-01-01T00:00:00Z',
});

const stack = (roundId: string, playerId: string, dollars: number): RoundStack => ({
  id: `${roundId}-${playerId}`,
  round_id: roundId,
  player_id: playerId,
  chips: null,
  stack_cents: dollars * 100,
});

describe('chip maths', () => {
  it('values a stack from its chip counts', () => {
    expect(chipsToCents({ red: 3, blue: 2 }, DEFAULT_CHIPS)).toBe(3 * 100 + 2 * 500);
  });

  it('re-values the same chips when a round changes what blue is worth', () => {
    const reprice = DEFAULT_CHIPS.map((c) => (c.key === 'blue' ? { ...c, valueCents: 1000 } : c));
    expect(chipsToCents({ blue: 4 }, reprice)).toBe(4000);
  });

  it('breaks an amount into chips, biggest first', () => {
    expect(centsToChips(11_25, DEFAULT_CHIPS)).toEqual({ blue: 2, red: 1, white: 1 });
    expect(centsToChips(137_50, DEFAULT_CHIPS)).toEqual({ black: 1, green: 1, blue: 2, red: 2, white: 2 });
  });
});

describe('computeGameState', () => {
  it('nets out a simple two-round game', () => {
    const state = computeGameState({
      players: [player('p1'), player('p2')],
      rounds: [round('r1', 1), round('r2', 2)],
      entries: [buyIn('p1', 'r1', 20), buyIn('p2', 'r1', 20)],
      stacks: [
        stack('r1', 'p1', 30),
        stack('r1', 'p2', 10),
        stack('r2', 'p1', 25),
        stack('r2', 'p2', 15),
      ],
    });

    const p1 = state.byPlayerId.get('p1')!;
    expect(p1.rounds.map((r) => r.netCents)).toEqual([1000, -500]);
    expect(p1.netCents).toBe(500);
    expect(state.byPlayerId.get('p2')!.netCents).toBe(-500);
    expect(state.potInCents).toBe(4000);
    expect(state.imbalanceCents).toBe(0);
  });

  it('gives a late joiner no rounds before they showed up', () => {
    const state = computeGameState({
      players: [player('p1'), player('late')],
      rounds: [round('r1', 1), round('r2', 2)],
      entries: [buyIn('p1', 'r1', 20), buyIn('late', 'r2', 20)],
      stacks: [
        stack('r1', 'p1', 20),
        stack('r2', 'p1', 15),
        stack('r2', 'late', 25),
      ],
    });

    const late = state.byPlayerId.get('late')!;
    expect(late.rounds).toHaveLength(1);
    expect(late.rounds[0].roundNumber).toBe(2);
    expect(late.rounds[0].netCents).toBe(500);
    expect(late.netCents).toBe(500);
  });

  it('keeps a rebuy out of the round profit', () => {
    const state = computeGameState({
      players: [player('p1')],
      rounds: [round('r1', 1)],
      // Bought in for 20, rebought 20 mid-round, ended the round with 30.
      entries: [buyIn('p1', 'r1', 20), buyIn('p1', 'r1', 20)],
      stacks: [stack('r1', 'p1', 30)],
    });

    const p1 = state.byPlayerId.get('p1')!;
    expect(p1.totalBuyInCents).toBe(4000);
    expect(p1.rounds[0].netCents).toBe(-1000);
    expect(p1.netCents).toBe(-1000);
  });

  it('holds a stack steady across a round the player sat out', () => {
    const state = computeGameState({
      players: [player('p1')],
      rounds: [round('r1', 1), round('r2', 2), round('r3', 3)],
      entries: [buyIn('p1', 'r1', 50)],
      stacks: [stack('r1', 'p1', 60), stack('r3', 'p1', 45)],
    });

    const p1 = state.byPlayerId.get('p1')!;
    // Round 2 has no recorded stack, so it carries forward at zero net.
    expect(p1.rounds[1].recorded).toBe(false);
    expect(p1.rounds[1].netCents).toBe(0);
    expect(p1.rounds[2].netCents).toBe(-1500);
    expect(p1.netCents).toBe(-500);
  });

  it('counts a cash-out as money off the table, not a loss', () => {
    const state = computeGameState({
      players: [player('p1')],
      rounds: [round('r1', 1)],
      // Bought in for 20, walked away with the same 20, table empty.
      entries: [
        buyIn('p1', 'r1', 20),
        { ...buyIn('p1', 'r1', 20), id: 'cashout', kind: 'cash_out' },
      ],
      stacks: [stack('r1', 'p1', 0)],
    });

    const p1 = state.byPlayerId.get('p1')!;
    expect(p1.currentStackCents).toBe(0);
    expect(p1.netCents).toBe(0);
    expect(p1.rounds[0].netCents).toBe(0);
  });

  it('credits winnings to the round they were cashed out of', () => {
    const state = computeGameState({
      players: [player('p1')],
      rounds: [round('r1', 1)],
      // Bought in for 20, left the table with 35 in hand and no chips down.
      entries: [
        buyIn('p1', 'r1', 20),
        { ...buyIn('p1', 'r1', 35), id: 'cashout', kind: 'cash_out' },
      ],
      stacks: [stack('r1', 'p1', 0)],
    });

    const p1 = state.byPlayerId.get('p1')!;
    expect(p1.rounds[0].netCents).toBe(1500);
    expect(p1.netCents).toBe(1500);
  });

  it('reports an imbalance when a stack was typed wrong', () => {
    const state = computeGameState({
      players: [player('p1'), player('p2')],
      rounds: [round('r1', 1)],
      entries: [buyIn('p1', 'r1', 20), buyIn('p2', 'r1', 20)],
      stacks: [stack('r1', 'p1', 30), stack('r1', 'p2', 15)],
    });
    expect(state.imbalanceCents).toBe(500);
  });

  it('treats buy-ins made before the first round as part of it', () => {
    const state = computeGameState({
      players: [player('p1')],
      rounds: [round('r1', 1)],
      entries: [buyIn('p1', null, 20)],
      stacks: [stack('r1', 'p1', 20)],
    });
    expect(state.byPlayerId.get('p1')!.rounds[0].netCents).toBe(0);
  });

  it('shows bought-in chips before any round exists', () => {
    const state = computeGameState({
      players: [player('p1')],
      rounds: [],
      entries: [buyIn('p1', null, 40)],
      stacks: [],
    });
    const p1 = state.byPlayerId.get('p1')!;
    expect(p1.currentStackCents).toBe(4000);
    expect(p1.netCents).toBe(0);
  });
});
