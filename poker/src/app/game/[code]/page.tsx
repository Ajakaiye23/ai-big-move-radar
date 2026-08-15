import { redirect } from 'next/navigation';
import Link from 'next/link';
import { GameRoom } from '@/components/game-room';
import { JoinPrompt } from '@/components/join-prompt';
import { createClient } from '@/lib/supabase/server';
import { findGameByCode, loadGame } from '@/lib/queries';

export const dynamic = 'force-dynamic';

export default async function GamePage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect(`/?next=${encodeURIComponent(`/game/${code}`)}`);

  // Row-level security hides games you aren't in, so "not found" here means
  // either a bad code or an invitation you haven't accepted yet.
  const game = await findGameByCode(supabase, code);
  if (!game) {
    return <JoinPrompt code={code.toUpperCase()} />;
  }

  const bundle = await loadGame(supabase, game.id);
  if (!bundle) {
    return (
      <main className="mx-auto max-w-md px-6 py-20 text-center">
        <p className="text-ink-300">That table couldn&apos;t be loaded.</p>
        <Link href="/dashboard" className="mt-4 inline-block text-brass-400 underline">
          Back to your games
        </Link>
      </main>
    );
  }

  const { data: profile } = await supabase
    .from('profiles')
    .select('display_name')
    .eq('id', user.id)
    .maybeSingle();

  return (
    <GameRoom
      userId={user.id}
      displayName={(profile?.display_name as string | undefined) ?? 'Player'}
      initial={{
        game: bundle.game,
        players: bundle.players,
        rounds: bundle.rounds,
        entries: bundle.entries,
        stacks: bundle.stacks,
        settlement: bundle.settlement,
      }}
    />
  );
}
