/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    missingSuspenseWithCSRBailout: false,
  },
  async rewrites() {
    return {
      // Serve the static Beam marketing landing page at the root.
      beforeFiles: [
        { source: "/", destination: "/beam/index.html" },
        { source: "/onboarding", destination: "/beam/onboarding.html" },
      ],
    };
  },
};

export default nextConfig;
