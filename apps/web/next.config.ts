import type { NextConfig } from "next";

const API_TARGET = process.env.EQUITYLENS_API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Next 16 dev blocks cross-origin requests by default (only localhost allowed).
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${API_TARGET}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
