// Build the extension: bundle each MV3 entry point into dist/ as a
// self-contained IIFE (no runtime imports), then copy the popup HTML.
// Mirrors apps/pixel's esbuild approach (single build tool, pinned version).
import { build } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const outdir = `${root}/dist`;

await mkdir(outdir, { recursive: true });

await build({
  entryPoints: [
    `${root}/src/background.js`,
    `${root}/src/content.js`,
    `${root}/src/popup.js`,
  ],
  bundle: true,
  format: "iife",
  target: "es2017",
  outdir,
  logLevel: "info",
});

await copyFile(`${root}/src/popup.html`, `${outdir}/popup.html`);

console.log("extension build complete → dist/");
