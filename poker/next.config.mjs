/** @type {import('next').NextConfig} */
const nextConfig = {
  async headers() {
    return [
      {
        // The service worker must not be cached, or installs get stuck on an old build.
        source: '/sw.js',
        headers: [
          { key: 'Cache-Control', value: 'no-cache, no-store, must-revalidate' },
          { key: 'Service-Worker-Allowed', value: '/' },
        ],
      },
    ];
  },
};

export default nextConfig;
