import Link from 'next/link';
import { redirect } from 'next/navigation';
import { SignIn } from '@/components/sign-in';
import { SetupNotice } from '@/components/setup-notice';
import { InstallHint } from '@/components/install-prompt';
import { isSupabaseConfigured } from '@/lib/supabase/config';
import { createClient } from '@/lib/supabase/server';

export default async function LandingPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;

  if (isSupabaseConfigured) {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (user) redirect(next ?? '/dashboard');
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-5xl flex-col gap-10 px-5 py-10 lg:flex-row lg:items-center lg:gap-16 lg:py-20">
      <section className="flex-1 space-y-6">
        <div className="flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/icons/icon-192.png" alt="" width={44} height={44} className="rounded-xl" />
          <span className="text-lg font-semibold tracking-tight">Chip Ledger</span>
        </div>

        <h1 className="text-4xl leading-tight font-semibold tracking-tight sm:text-5xl">
          The home game,
          <br />
          <span className="text-brass-400">counted properly.</span>
        </h1>

        <p className="max-w-md text-ink-300">
          Open a table, everyone joins with a six-character code, and the ledger keeps
          itself: buy-ins, what each chip colour is worth this round, who won what, and
          who owes whom at the end — in the fewest payments possible.
        </p>

        <ul className="max-w-md space-y-2.5 text-sm text-ink-300">
          {[
            'Set chip values per round — blue is $5 tonight, $10 next round.',
            'Buy in for as many chips as you like, rebuy any time.',
            'Leave and rejoin, or join at round nine — nothing is lost.',
            'Per-round profit for every player, and lifetime stats for you.',
            'Settle up with the smallest possible number of payments.',
          ].map((line) => (
            <li key={line} className="flex gap-2.5">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brass-500" />
              {line}
            </li>
          ))}
        </ul>
      </section>

      <section className="w-full lg:max-w-sm">
        <div className="card space-y-5 p-6">
          <div>
            <h2 className="text-lg font-semibold">Sign in</h2>
            <p className="mt-1 text-sm text-ink-500">
              Use the account you already have on your phone.
            </p>
          </div>

          {isSupabaseConfigured ? <SignIn next={next ?? '/dashboard'} /> : <SetupNotice />}

          {error ? (
            <p className="rounded-lg bg-red-500/10 p-3 text-sm text-red-300">{error}</p>
          ) : null}

          <Link
            href="/preview"
            className="block text-center text-sm text-ink-500 underline underline-offset-4 hover:text-ink-300"
          >
            Have a look around first
          </Link>
        </div>
        <InstallHint />
      </section>
    </main>
  );
}
