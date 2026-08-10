/**
 * fp2 browser fingerprint — a VERBATIM port of the pixel's implementation.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │ THIS MUST STAY BYTE-IDENTICAL TO apps/pixel/src/tracker.js fp2        │
 * │ (`hash128`, `canvasFp`, `webglFp`, `fpParts`, tracker.js:86 + 203-231)│
 * │ or the canary join silently fails: the dashboard computes one         │
 * │ fingerprint, the pixel on getbeam.fyi stores another, the lookup      │
 * │ matches nothing, and the reveal degrades with no error anywhere.      │
 * │ Change one side and you MUST change the other in the same patch.      │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Replaces the third copy that lived in
 * public/beam/onboarding-steps.js:23-76.
 *
 * `hash128` is exported separately from every DOM-touching helper so it can be
 * unit-tested under vitest's node environment (no jsdom in this repo).
 */

/** 4×FNV-1a-ish 32-bit lanes, base36-joined. Pure — safe in node. */
export function hash128(str: string): string {
  const h = [0x811c9dc5, 0xc6a4a793, 0x6c62272e, 0x61c88647];
  const p = [0x01000193, 0x0100019b, 0x01000199, 0x01000187];
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i);
    for (let j = 0; j < 4; j++) h[j] = Math.imul(h[j] ^ c, p[j]) >>> 0;
  }
  return (
    h[0].toString(36) + h[1].toString(36) + h[2].toString(36) + h[3].toString(36)
  );
}

export function canvasFp(): string {
  try {
    const cv = document.createElement("canvas");
    cv.width = 200;
    cv.height = 50;
    const ctx = cv.getContext("2d");
    if (!ctx) return "";
    ctx.textBaseline = "top";
    ctx.font = "14px Arial";
    ctx.fillStyle = "#f60";
    ctx.fillRect(125, 1, 62, 20);
    ctx.fillStyle = "#069";
    ctx.fillText("BmFp,1", 2, 15);
    ctx.fillStyle = "rgba(102,204,0,0.7)";
    ctx.fillText("BmFp,1", 4, 17);
    return cv.toDataURL().slice(-50);
  } catch {
    return "";
  }
}

export function webglFp(): string {
  try {
    const cv = document.createElement("canvas");
    const gl = (cv.getContext("webgl") ||
      cv.getContext("experimental-webgl")) as WebGLRenderingContext | null;
    if (!gl) return "";
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    const v = ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : "";
    const r = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "";
    return v + "~" + r + "~" + gl.getParameter(gl.MAX_TEXTURE_SIZE);
  } catch {
    return "";
  }
}

/**
 * The ordered component list. ORDER AND COUNT ARE PART OF THE CONTRACT —
 * inserting a component shifts every stored fingerprint.
 */
export function fpComponents(): unknown[] {
  const nav = navigator as Navigator & {
    deviceMemory?: number;
    pdfViewerEnabled?: boolean;
    connection?: { effectiveType?: string };
  };
  const c: unknown[] = [];
  c.push(screen.width + "x" + screen.height);
  c.push(screen.availWidth + "x" + screen.availHeight);
  c.push(screen.colorDepth);
  c.push(window.devicePixelRatio || 1);
  c.push(nav.language);
  c.push(nav.platform);
  c.push(nav.hardwareConcurrency || 0);
  c.push(nav.deviceMemory || 0);
  c.push(nav.maxTouchPoints || 0);
  c.push(nav.cookieEnabled ? 1 : 0);
  c.push(nav.doNotTrack || "");
  c.push(nav.pdfViewerEnabled ? 1 : 0);
  try {
    c.push(Intl.DateTimeFormat().resolvedOptions().timeZone);
  } catch {
    c.push("");
  }
  try {
    c.push(nav.connection ? nav.connection.effectiveType : "");
  } catch {
    c.push("");
  }
  c.push(canvasFp());
  c.push(webglFp());
  c.push(Math.tan(-1e300));
  return c;
}

/** `Array.join("|")` — matches tracker.js `c.join("|")` coercion exactly. */
export function fpParts(components: unknown[] = fpComponents()): string {
  return components.join("|");
}

/**
 * The value the pixel stores as `Visitor.fingerprint`.
 *
 * Compute this on a real user gesture (the "catch me" click), NOT lazily
 * inside a poll: a backgrounded tab can perturb the canvas probe and produce
 * a different hash than the one the pixel recorded.
 */
export function beamFingerprint(): string {
  return "fp2_" + hash128(fpParts());
}
