'use client';

import { useCallback, useEffect, useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import { loadGame } from '@/lib/queries';
import type { Game, GamePlayer, LedgerEntry, Round, RoundStack, Settlement } from '@/lib/types';

export type GameData = {
  game: Game;
  players: GamePlayer[];
  rounds: Round[];
  entries: LedgerEntry[];
  stacks: RoundStack[];
  settlement: Settlement | null;
};

/**
 * Keeps the table in sync for everyone sitting at it. Any write by any player
 * pushes a Postgres change through Supabase realtime; we refetch the whole game
 * rather than patching rows, because the game is small and a stale ledger is
 * worse than an extra round-trip.
 */
export function useGame(initial: GameData) {
  const [data, setData] = useState<GameData>(initial);
  const [syncing, setSyncing] = useState(false);

  const refresh = useCallback(async () => {
    setSyncing(true);
    try {
      const bundle = await loadGame(createClient(), initial.game.id);
      if (bundle) {
        setData({
          game: bundle.game,
          players: bundle.players,
          rounds: bundle.rounds,
          entries: bundle.entries,
          stacks: bundle.stacks,
          settlement: bundle.settlement,
        });
      }
    } finally {
      setSyncing(false);
    }
  }, [initial.game.id]);

  useEffect(() => {
    const supabase = createClient();
    const gameFilter = `game_id=eq.${initial.game.id}`;
    const channel = supabase
      .channel(`game:${initial.game.id}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'game_players', filter: gameFilter }, refresh)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'rounds', filter: gameFilter }, refresh)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'ledger_entries', filter: gameFilter }, refresh)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'settlements', filter: gameFilter }, refresh)
      // round_stacks has no game_id, so it's filtered on the client side by refetch.
      .on('postgres_changes', { event: '*', schema: 'public', table: 'round_stacks' }, refresh)
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'games', filter: `id=eq.${initial.game.id}` }, refresh)
      .subscribe();

    // Phones suspend websockets in the background; catch up when the app returns.
    const onVisible = () => document.visibilityState === 'visible' && refresh();
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      supabase.removeChannel(channel);
    };
  }, [initial.game.id, refresh]);

  return { data, refresh, syncing };
}
