'use client';

import { useState } from 'react';
import { Dashboard } from './dashboard';
import { GameRoomView } from './game-room';
import { PREVIEW_USER_ID, sampleGame, sampleSummaries } from '@/lib/sample-game';

export function PreviewShell() {
  const [view, setView] = useState<'dashboard' | 'game'>('game');
  const summaries = sampleSummaries();

  return (
    <div>
      <div className="sticky top-0 z-40 flex flex-wrap items-center justify-center gap-3 bg-brass-500/15 px-4 py-2 text-xs text-brass-400">
        <span>Preview with made-up data — nothing you do here is saved.</span>
        <div className="flex gap-1">
          {(['game', 'dashboard'] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`rounded px-2 py-1 ${view === v ? 'bg-brass-500/25 font-medium' : 'underline'}`}
            >
              {v === 'game' ? 'The table' : 'Your stats'}
            </button>
          ))}
        </div>
      </div>

      {view === 'game' ? (
        <GameRoomView
          userId={PREVIEW_USER_ID}
          displayName="Hannah"
          data={sampleGame}
          syncing={false}
          onChange={() => {}}
        />
      ) : (
        <Dashboard displayName="Hannah" avatarUrl={null} summaries={summaries} />
      )}
    </div>
  );
}
