import type { NextConfig } from 'next';
const config: NextConfig = { output: 'standalone', devIndicators: false, turbopack: { root: process.cwd() }, async rewrites() { return [{ source: '/api/:path*', destination: `${process.env.INTERNAL_API_URL || 'http://127.0.0.1:8000'}/api/:path*` }]; } };
export default config;
