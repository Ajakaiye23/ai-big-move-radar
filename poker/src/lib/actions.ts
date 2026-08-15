'use client';

import { createClient } from './supabase/client';
import type { ChipCounts, ChipDenomination, LedgerKind, Payment, PlayerStatus } from './types';

/** Thin wrappers over the tables. Every write is guarded by RLS on the server. */

export async function recordMoney(args: {
  gameId: string;
  playerId: string;
  roundId: string | null;
  kind: LedgerKind;
  amountCents: number;
  chips?: ChipCounts | null;
  note?: string | null;
  userId: string;
}) {
  const { error } = await createClient().from('ledger_entries').insert({
    game_id: args.gameId,
    player_id: args.playerId,
    round_id: args.roundId,
    kind: args.kind,
    amount_cents: args.amountCents,
    chips: args.chips ?? null,
    note: args.note ?? null,
    created_by: args.userId,
  });
  if (error) throw new Error(error.message);
}

export async function startRound(gameId: string, number: number, chipValues: ChipDenomination[]) {
  const { error } = await createClient()
    .from('rounds')
    .insert({ game_id: gameId, number, chip_values: chipValues, status: 'open' });
  if (error) throw new Error(error.message);
}

export async function setRoundChipValues(roundId: string, chipValues: ChipDenomination[]) {
  const { error } = await createClient().from('rounds').update({ chip_values: chipValues }).eq('id', roundId);
  if (error) throw new Error(error.message);
}

export async function closeRound(args: {
  roundId: string;
  userId: string;
  stacks: Array<{ playerId: string; stackCents: number; chips: ChipCounts | null }>;
}) {
  const supabase = createClient();
  if (args.stacks.length > 0) {
    const { error } = await supabase.from('round_stacks').upsert(
      args.stacks.map((s) => ({
        round_id: args.roundId,
        player_id: s.playerId,
        stack_cents: s.stackCents,
        chips: s.chips,
        recorded_by: args.userId,
        recorded_at: new Date().toISOString(),
      })),
      { onConflict: 'round_id,player_id' },
    );
    if (error) throw new Error(error.message);
  }

  const { error } = await supabase
    .from('rounds')
    .update({ status: 'closed', closed_at: new Date().toISOString() })
    .eq('id', args.roundId);
  if (error) throw new Error(error.message);
}

export async function addGuestPlayer(gameId: string, displayName: string) {
  const { error } = await createClient()
    .from('game_players')
    .insert({ game_id: gameId, display_name: displayName, user_id: null });
  if (error) throw new Error(error.message);
}

export async function setPlayerStatus(playerId: string, status: PlayerStatus) {
  const { error } = await createClient()
    .from('game_players')
    .update({ status, left_at: status === 'left' ? new Date().toISOString() : null })
    .eq('id', playerId);
  if (error) throw new Error(error.message);
}

export async function setDefaultChipValues(gameId: string, chipValues: ChipDenomination[]) {
  const { error } = await createClient()
    .from('games')
    .update({ default_chip_values: chipValues })
    .eq('id', gameId);
  if (error) throw new Error(error.message);
}

/** Locks the game: stores the payment plan and stops further edits. */
export async function finishGame(args: {
  gameId: string;
  payments: Payment[];
  totals: Array<{ playerId: string; netCents: number; buyInCents: number }>;
}) {
  const supabase = createClient();
  const { error: settleError } = await supabase.from('settlements').upsert(
    { game_id: args.gameId, payments: args.payments, totals: args.totals },
    { onConflict: 'game_id' },
  );
  if (settleError) throw new Error(settleError.message);

  const { error } = await supabase
    .from('games')
    .update({ status: 'settled', ended_at: new Date().toISOString() })
    .eq('id', args.gameId);
  if (error) throw new Error(error.message);
}

export async function reopenGame(gameId: string) {
  const { error } = await createClient()
    .from('games')
    .update({ status: 'active', ended_at: null })
    .eq('id', gameId);
  if (error) throw new Error(error.message);
}
