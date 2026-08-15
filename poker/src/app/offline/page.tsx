export const metadata = { title: 'Offline — Chip Ledger' };

export default function OfflinePage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-2xl font-semibold">No signal at the table</h1>
      <p className="text-ink-300">
        Chip Ledger needs a connection to keep everyone&apos;s numbers in sync. The page will work
        again as soon as you&apos;re back online.
      </p>
      <p className="text-sm text-ink-500">
        Nothing has been lost — the ledger lives on the server, not on this phone.
      </p>
    </main>
  );
}
