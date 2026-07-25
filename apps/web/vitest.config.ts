import { defineConfig } from "vitest/config";
import path from "node:path";

// Vitest for apps/web unit tests (Handoff Detection H5, Test Infra decision A).
// First JS unit runner in apps/web — scoped to pure `src/lib` logic (e.g. the
// fetch-beacon matcher). Node environment: these tests exercise pure functions,
// not the DOM. `@/` mirrors the tsconfig path alias so imports match app code.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
