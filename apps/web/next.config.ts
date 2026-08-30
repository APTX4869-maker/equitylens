import type { NextConfig } from "next";

const API_TARGET = process.env.EQUITYLENS_API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    console.log("[next.config] rewrites() invoked, target:", API_TARGET);
    return [
      {
        source: "/api/v1/:path*",
        destination: `${API_TARGET}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
