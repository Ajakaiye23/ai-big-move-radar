import { PreviewShell } from '@/components/preview-shell';

export const metadata = { title: 'Preview — Chip Ledger' };

/**
 * A working look at the app with a made-up Friday night in it. No account, no
 * backend, nothing saved — useful for judging the thing before wiring Supabase up.
 */
export default function PreviewPage() {
  return <PreviewShell />;
}
