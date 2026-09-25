import type { NextConfig } from "next";

/**
 * The browser talks only to the Next.js origin; /api/* is proxied to FastAPI.
 *
 * One origin means no CORS configuration, no mixed-origin cookies when Clerk
 * lands, and no API URL baked into the client bundle. In production the same
 * rewrite points at the deployed API via API_ORIGIN.
 */
const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
