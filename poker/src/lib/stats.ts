import type { Game } from './types';
import type { PlayerState } from './ledger';

export type GameSummary = {
  game: Game;
  state: PlayerState;
  /** When this game counts as "played" for time windows. */
  playedAt: number;
};

export type StatWindow = {
  key: string;
  label: string;
  /** Total money put on the table — buy-ins, not winnings. */
  volumeCents: number;
  /** Won or lost across those games. */
  netCents: number;
  games: number;
  /** Games in the window that haven't been settled yet, so the net can still move. */
  liveGames: number;
};

const DAY = 24 * 60 * 60 * 1000;

/**
 * A game is attributed to the moment it wrapped up: its end time, or its last
 * closed round, or failing both the time it was created. That keeps one long
 * night from being smeared across two weeks.
 */
export function playedAt(game: Game, lastRoundClosedAt: string | null): number {
  const stamp = game.ended_at ?? lastRoundClosedAt ?? game.created_at;
  return new Date(stamp).getTime();
}

export function buildWindows(summaries: GameSummary[], now = Date.now()): StatWindow[] {
  const byRecency = [...summaries].sort((a, b) => b.playedAt - a.playedAt);

  const windows: Array<{ key: string; label: string; pick: (s: GameSummary[]) => GameSummary[] }> = [
    { key: 'day', label: 'Last 24 hours', pick: (s) => s.filter((g) => now - g.playedAt <= DAY) },
    { key: 'week', label: 'Last 7 days', pick: (s) => s.filter((g) => now - g.playedAt <= 7 * DAY) },
    { key: 'month', label: 'Last 30 days', pick: (s) => s.filter((g) => now - g.playedAt <= 30 * DAY) },
    { key: 'last10', label: 'Last 10 games', pick: (s) => s.slice(0, 10) },
    { key: 'all', label: 'All time', pick: (s) => s },
  ];

  return windows.map(({ key, label, pick }) => {
    const picked = pick(byRecency);
    return {
      key,
      label,
      volumeCents: picked.reduce((sum, g) => sum + g.state.totalBuyInCents, 0),
      netCents: picked.reduce((sum, g) => sum + g.state.netCents, 0),
      games: picked.length,
      liveGames: picked.filter((g) => g.game.status === 'active').length,
    };
  });
}

/** Per-round history across every game, newest first — the "how am I running" feed. */
export function recentRounds(summaries: GameSummary[], limit = 25) {
  return summaries
    .flatMap((s) =>
      s.state.rounds
        .filter((r) => r.recorded)
        .map((r) => ({
          gameName: s.game.name,
          gameCode: s.game.code,
          roundNumber: r.roundNumber,
          netCents: r.netCents,
          playedAt: s.playedAt,
        })),
    )
    .sort((a, b) => b.playedAt - a.playedAt || b.roundNumber - a.roundNumber)
    .slice(0, limit);
}
