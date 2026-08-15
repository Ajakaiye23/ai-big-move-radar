export function SetupNotice() {
  return (
    <div className="space-y-3 rounded-xl border border-brass-500/30 bg-brass-500/10 p-4 text-sm">
      <p className="font-medium text-brass-400">Backend not connected yet</p>
      <p className="text-ink-300">
        Add <code className="rounded bg-black/30 px-1">NEXT_PUBLIC_SUPABASE_URL</code> and{' '}
        <code className="rounded bg-black/30 px-1">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> to{' '}
        <code className="rounded bg-black/30 px-1">.env.local</code>, run the migration in{' '}
        <code className="rounded bg-black/30 px-1">supabase/migrations</code>, then reload.
      </p>
      <p className="text-ink-500">See the README for the five-minute version.</p>
    </div>
  );
}
