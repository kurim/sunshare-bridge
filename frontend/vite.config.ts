import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The bridge serves the build under /app/. `npm run dev` proxies the API to a running bridge.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: { proxy: { "/api": process.env.BRIDGE_URL ?? "http://localhost:8099" } },
});
