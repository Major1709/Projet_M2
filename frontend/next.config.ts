import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Keep Next.js inside this application when parent directories contain
  // unrelated package-lock files.
  outputFileTracingRoot: process.cwd(),
};

export default nextConfig;
