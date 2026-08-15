import { redirect } from 'next/navigation';
import { Dashboard } from '@/components/dashboard';
import { createClient } from '@/lib/supabase/server';
import { loadAccountHistory } from '@/lib/queries';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect('/');

  const [{ data: profile }, summaries] = await Promise.all([
    supabase.from('profiles').select('*').eq('id', user.id).maybeSingle(),
    loadAccountHistory(supabase, user.id),
  ]);

  const displayName =
    (profile?.display_name as string | undefined) ??
    (user.user_metadata?.full_name as string | undefined) ??
    user.email?.split('@')[0] ??
    'Player';

  return (
    <Dashboard
      displayName={displayName}
      avatarUrl={(profile?.avatar_url as string | null) ?? null}
      summaries={summaries}
    />
  );
}
