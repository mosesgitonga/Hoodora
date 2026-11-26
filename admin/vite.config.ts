import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    target: "es2022",
    sourcemap: false,
    // One origin, no inline code: the CSP allows scripts from 'self' only.
    modulePreload: { polyfill: false },
    // One bundle, loaded once by a handful of staff on laptops: not worth splitting.
    chunkSizeWarningLimit: 2500,
  },
  server: { port: 5174 },
  test: {
    environment: "jsdom",
    // Refine's packages run through Vite too, so they and the app share one copy
    // of react-router (its CommonJS and ES builds would otherwise both load).
    server: { deps: { inline: [/@refinedev\//] } },
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    testTimeout: 15000,
  },
});
