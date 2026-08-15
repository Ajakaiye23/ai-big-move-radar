import type { SupabaseClient } from '@supabase/supabase-js';
import { computeGameState, type GameState } from './ledger';
import { playedAt, type GameSummary } from './stats';
import type { Game, GamePlayer, LedgerEntry, Round, RoundStack, Settlement } from './types';

export type GameBundle = {
  game: Game;
  players: GamePlayer[];
  rounds: Round[];
  entries: LedgerEntry[];
  stacks: RoundStack[];
  settlement: Settlement | null;
  state: GameState;
};

/** Everything one game needs, in five round-trips. */
export async function loadGame(
  supabase: SupabaseClient,
  gameId: string,
): Promise<GameBundle | null> {
  const [gameRes, playersRes, roundsRes, entriesRes, settlementRes] = await Promise.all([
    supabase.from('games').select('*').eq('id', gameId).maybeSingle(),
    supabase.from('game_players').select('*').eq('game_id', gameId).order('joined_at'),
    supabase.from('rounds').select('*').eq('game_id', gameId).order('number'),
    supabase.from('ledger_entries').select('*').eq('game_id', gameId).order('created_at'),
    supabase.from('settlements').select('*').eq('game_id', gameId).maybeSingle(),
  ]);

  const game = gameRes.data as Game | null;
  if (!game) return null;

  const rounds = (roundsRes.data ?? []) as Round[];
  const stacksRes = rounds.length
    ? await supabase.from('round_stacks').select('*').in('round_id', rounds.map((r) => r.id))
    : { data: [] as RoundStack[] };

  const players = (playersRes.data ?? []) as GamePlayer[];
  const entries = (entriesRes.data ?? []) as LedgerEntry[];
  const stacks = (stacksRes.data ?? []) as RoundStack[];

  return {
    game,
    players,
    rounds,
    entries,
    stacks,
    settlement: (settlementRes.data ?? null) as Settlement | null,
    state: computeGameState({ players, rounds, entries, stacks }),
  };
}

export async function findGameByCode(supabase: SupabaseClient, code: string) {
  const { data } = await supabase
    .from('games')
    .select('*')
    .eq('code', code.toUpperCase())
    .maybeSingle();
  return (data ?? null) as Game | null;
}

/**
 * Every game this account has ever sat in, reduced to that account's own
 * numbers. This is what the lifetime and rolling-window stats are built from.
 */
export async function loadAccountHistory(
  supabase: SupabaseClient,
  userId: string,
): Promise<GameSummary[]> {
  const { data: seats } = await supabase
    .from('game_players')
    .select('*, games(*)')
    .eq('user_id', userId);

  const rows = (seats ?? []) as Array<GamePlayer & { games: Game | null }>;
  const withGame = rows.filter((r) => r.games);
  if (withGame.length === 0) return [];

  const gameIds = withGame.map((r) => r.game_id);
  const playerIds = withGame.map((r) => r.id);

  const [roundsRes, entriesRes] = await Promise.all([
    supabase.from('rounds').select('*').in('game_id', gameIds).order('number'),
    supabase.from('ledger_entries').select('*').in('player_id', playerIds),
  ]);

  const rounds = (roundsRes.data ?? []) as Round[];
  const entries = (entriesRes.data ?? []) as LedgerEntry[];
  const stacksRes = rounds.length
    ? await supabase
        .from('round_stacks')
        .select('*')
        .in('round_id', rounds.map((r) => r.id))
        .in('player_id', playerIds)
    : { data: [] as RoundStack[] };
  const stacks = (stacksRes.data ?? []) as RoundStack[];

  return withGame
    .map((seat) => {
      const game = seat.games as Game;
      const gameRounds = rounds.filter((r) => r.game_id === game.id);
      const state = computeGameState({
        players: [seat],
        rounds: gameRounds,
        entries: entries.filter((e) => e.player_id === seat.id),
        stacks: stacks.filter((s) => s.player_id === seat.id),
      }).players[0];

      const lastClosed = [...gameRounds]
        .reverse()
        .find((r) => r.closed_at)?.closed_at ?? null;

      return { game, state, playedAt: playedAt(game, lastClosed) };
    })
    .sort((a, b) => b.playedAt - a.playedAt);
}
