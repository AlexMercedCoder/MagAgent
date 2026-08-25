import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

// The bundle is committed and ships inside the wheel, so installed users never
// need Node. CI rebuilds and fails when the committed output drifts.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(import.meta.dirname, "../src/magent/webui/static"),
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
