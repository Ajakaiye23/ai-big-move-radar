import type { Metadata, Viewport } from 'next';
import './globals.css';
import { ServiceWorker } from '@/components/service-worker';

export const metadata: Metadata = {
  title: 'Chip Ledger — home game bookkeeping',
  description:
    'Track buy-ins, chip values and per-round results for your home poker game, then settle up in the fewest possible payments.',
  applicationName: 'Chip Ledger',
  manifest: '/manifest.webmanifest',
  appleWebApp: {
    capable: true,
    title: 'Chip Ledger',
    statusBarStyle: 'black-translucent',
  },
  icons: {
    icon: [
      { url: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { url: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: [{ url: '/icons/apple-touch-icon.png', sizes: '180x180' }],
  },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: '#06120d',
  width: 'device-width',
  initialScale: 1,
  // Stops the double-tap-to-zoom jump on score buttons without trapping pinch-zoom.
  maximumScale: 5,
  viewportFit: 'cover',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh antialiased">
        {children}
        <ServiceWorker />
      </body>
    </html>
  );
}
