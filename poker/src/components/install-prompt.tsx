'use client';

import { useEffect, useState } from 'react';
import { Button } from './ui';

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

const DISMISS_KEY = 'chip-ledger:install-dismissed';

/**
 * Android/Chrome hands us a real install event. iOS never will, so Safari users
 * get the Share → Add to Home Screen instructions instead — which is the actual
 * way an iPhone turns this into an app.
 */
export function InstallHint() {
  const [deferred, setDeferred] = useState<InstallEvent | null>(null);
  const [platform, setPlatform] = useState<'ios' | 'other'>('other');
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    const standalone =
      window.matchMedia('(display-mode: standalone)').matches ||
      // iOS Safari's non-standard flag.
      (window.navigator as unknown as { standalone?: boolean }).standalone === true;
    if (standalone || localStorage.getItem(DISMISS_KEY)) return;

    const isIos = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
    setPlatform(isIos ? 'ios' : 'other');
    setHidden(false);

    const onPrompt = (event: Event) => {
      event.preventDefault();
      setDeferred(event as InstallEvent);
    };
    window.addEventListener('beforeinstallprompt', onPrompt);
    return () => window.removeEventListener('beforeinstallprompt', onPrompt);
  }, []);

  if (hidden) return null;
  if (platform !== 'ios' && !deferred) return null;

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, '1');
    setHidden(true);
  }

  return (
    <div className="card mt-4 flex items-start gap-3 p-4 text-sm">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/icons/icon-192.png" alt="" width={36} height={36} className="rounded-lg" />
      <div className="flex-1 space-y-2">
        {platform === 'ios' ? (
          <p className="text-ink-300">
            Put it on your home screen: tap <span className="text-ink-100">Share</span> in Safari,
            then <span className="text-ink-100">Add to Home Screen</span>. It opens full-screen,
            like any other app.
          </p>
        ) : (
          <>
            <p className="text-ink-300">Install it as an app on this device.</p>
            <Button
              onClick={async () => {
                await deferred?.prompt();
                await deferred?.userChoice;
                setDeferred(null);
                dismiss();
              }}
            >
              Add to home screen
            </Button>
          </>
        )}
      </div>
      <button onClick={dismiss} aria-label="Dismiss" className="pressable rounded px-1 text-ink-500">
        ✕
      </button>
    </div>
  );
}
