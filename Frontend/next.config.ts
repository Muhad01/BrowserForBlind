import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // NFR-SEC-05: keep Django's trailing slashes so session + CSRF cookies work
  skipTrailingSlashRedirect: true,
  cacheComponents: true,
  partialPrefetching: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*/",
      },
    ];
  },
};

export default nextConfig;
