'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase/client';
import { Button, Field, inputClass } from './ui';

/** Shown when you open a game link for a table you haven't sat at yet. */
export function JoinPrompt({ code }: { code: string }) {
  const router = useRouter();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function join() {
    setBusy(true);
    setError(null);
    const { error } = await createClient().rpc('join_game', {
      p_code: code,
      p_display_name: name,
    });
    if (error) {
      setError(error.message.replace(/^.*?:\s*/, ''));
      setBusy(false);
      return;
    }
    router.refresh();
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 px-6 py-10">
      <div className="card space-y-5 p-6">
        <div>
          <p className="text-sm text-ink-500">Table</p>
          <p className="font-mono text-3xl tracking-[0.3em]">{code}</p>
        </div>
        <p className="text-sm text-ink-300">
          You&apos;re not seated here yet. Take a seat and the host will see you at the table.
        </p>
        <Field label="Name at the table">
          <input
            className={inputClass}
            value={name}
            placeholder="How the others know you"
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        {error ? <p className="text-sm text-red-400">{error}</p> : null}
        <Button className="w-full" onClick={join} disabled={busy}>
          {busy ? 'Sitting down…' : 'Sit down'}
        </Button>
      </div>
      <Link href="/dashboard" className="text-center text-sm text-ink-500 underline">
        Back to your games
      </Link>
    </main>
  );
}
