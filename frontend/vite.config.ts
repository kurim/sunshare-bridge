import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The bridge serves the build under /app/, but possibly behind a further, only-known-at-runtime
// prefix (Home Assistant Ingress) - relative asset URLs work at any mount depth (see basePath.ts
// for the runtime routing/API-prefix counterpart). `npm run dev` proxies the API to a running bridge.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: { proxy: { "/api": process.env.BRIDGE_URL ?? "http://localhost:8099" } },
});
