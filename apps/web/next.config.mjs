/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  // In production nginx serves both the UI and /api on one origin, so the
  // browser talks to a relative path and no CORS is involved. In local dev we
  // proxy to the API process instead.
  async rewrites() {
    const target = process.env.API_PROXY_TARGET;
    return target ? [{ source: '/api/:path*', destination: `${target}/api/:path*` }] : [];
  },
};
export default nextConfig;
