"use client";

import { useEffect, useRef } from "react";

/**
 * Post-login welcome, ported from the pre-signup chat at /beam/onboarding.html
 * so the first-run experience matches that conversational, mascot-driven feel
 * instead of a static card. Reuses the exact markup + /beam/onboarding.css the
 * static flow uses (injected while mounted, removed on unmount so the cream
 * chat theme never bleeds into the Tailwind dashboard). This is only the
 * welcome intro — "let's do it" hands off to the real Clerk-authed add-site
 * form via onDone; it does NOT re-run the pre-signup demo/paywall funnel.
 */

// ── beam mascot (ported from /beam/onboarding-mascot.js) ──────────────────
const MASCOT_PAL: Record<string, string> = {
  H: "#C9785A", h: "#E89A7B", s: "#FBE2D2", S: "#3D2F4F",
  e: "#2B2530", m: "#C75F75", B: "#F49DAE", c: "#FBF6EE",
  b: "#C9B6E4", o: "#A691CF", l: "#9B7FCB", L: "#7A5BB0", k: "#FBE2D2",
};
const MASCOT_GRID = `
....HHHHHHHH......
...HHhhhhhhHH.....
..HhhhhhhhhhhH....
..Hhhsssssshhh....
..Hhssssssssshh...
..Hhseesseessh....
..Hhssssssssshh...
..HhssssBBssshh...
..Hhshssmmsshhh...
..HhhssssssshhH...
...Hhhhsssshhh....
....HccccccH......
...obbbbbbbbo.....
..obbbBbbbBbbbo...
..obbBbbbbbBbbb...
..obbbbbbbbbbb....
..obbbbbbbbbb.....
...lLlLlLlLl......
..llllllllll......
..llllllllll......
....kk...kk.......
....kk...kk.......
....kk...kk.......
...SSS..SSS.......
...SSS..SSS.......
`;
function mascotSvg(): string {
  const rows = MASCOT_GRID.split("\n").filter((r) => r.length);
  let rects = "";
  for (let y = 0; y < rows.length; y++) {
    const row = rows[y];
    let x = 0;
    while (x < row.length) {
      const c = row[x];
      if (c === "." || c === " " || !MASCOT_PAL[c]) {
        x++;
        continue;
      }
      let run = 1;
      while (x + run < row.length && row[x + run] === c) run++;
      rects += `<rect x="${x}" y="${y}" width="${run}" height="1" fill="${MASCOT_PAL[c]}"/>`;
      x += run;
    }
  }
  return `<svg class="beam-mascot-svg" viewBox="0 0 18 26" shape-rendering="crispEdges" preserveAspectRatio="xMidYMax meet" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${rects}</svg>`;
}

const SPARK = `<svg viewBox="0 0 100 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><defs><linearGradient id="obSparkGrad" x1="0" y1="0" x2="1" y2="0.35"><stop offset="0" stop-color="#FF6B9D"/><stop offset="0.55" stop-color="#FF3366"/><stop offset="1" stop-color="#FF7FA8"/></linearGradient></defs><path d="M26,15 Q26,32 90,32 Q26,32 26,49 Q26,32 9,32 Q26,32 26,15 Z" fill="url(#obSparkGrad)"/><circle cx="26" cy="32" r="3.4" fill="#fff" opacity="0.92"/><path d="M82,21 Q84,25 88,25 Q84,25 82,29 Q80,25 76,25 Q80,25 82,21 Z" fill="url(#obSparkGrad)" opacity="0.85"/></svg>`;

// The scripted welcome, matching onboarding-steps.js §WELCOME copy but ending
// in the add-site handoff instead of the demo.
const LINES = [
  { html: `<p class="lead">hey, i'm beam 👋</p>`, delay: 500 },
  { html: `the stupidly easy way to know who's on your site, and engage them tastefully.` },
  { html: `let's get your first site connected. takes about a minute, ready?` },
];

export function OnboardingWelcomeChat({
  onDone,
  onExit,
}: {
  onDone: () => void;
  onExit: () => void;
}) {
  const chatRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Inject the static flow's fonts + stylesheet only while mounted.
  useEffect(() => {
    const links: HTMLLinkElement[] = [];
    const add = (href: string, crossOrigin?: boolean) => {
      const l = document.createElement("link");
      l.rel = "stylesheet";
      l.href = href;
      if (crossOrigin) l.crossOrigin = "anonymous";
      l.dataset.obWelcome = "1";
      document.head.appendChild(l);
      links.push(l);
    };
    add(
      "https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600&display=swap",
      true,
    );
    add("/beam/onboarding.css");
    return () => links.forEach((l) => l.remove());
  }, []);

  // Run the scripted conversation. Clears first so React 18 StrictMode's
  // double-invoke (mount → cleanup → mount) replays cleanly instead of
  // stalling on a cancelled first pass.
  useEffect(() => {
    if (chatRef.current) chatRef.current.innerHTML = "";

    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
    let cancelled = false;

    const scrollEnd = () => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    };

    async function bot(html: string, delay?: number) {
      const chat = chatRef.current;
      if (!chat) return;
      const row = document.createElement("div");
      row.className = "ob-msg bot";
      row.innerHTML = `<div class="ob-av">${mascotSvg()}</div><div class="ob-bubble"></div>`;
      chat.appendChild(row);
      const bub = row.querySelector(".ob-bubble") as HTMLElement;
      if (!reduce) {
        bub.classList.add("typing");
        bub.innerHTML = `<span class="dots"><span></span><span></span><span></span></span>`;
        scrollEnd();
        const len = html.replace(/<[^>]+>/g, "").length;
        await wait(delay != null ? delay : Math.min(1300, Math.max(480, len * 22)));
        if (cancelled) return;
      }
      bub.classList.remove("typing");
      bub.classList.add("reveal");
      bub.innerHTML = html;
      scrollEnd();
      await wait(reduce ? 0 : 160);
    }

    (async () => {
      for (const line of LINES) {
        if (cancelled) return;
        await bot(line.html, line.delay);
      }
      if (cancelled) return;
      // "let's do it" control — clicking hands off to the add-site form.
      const chat = chatRef.current;
      if (!chat) return;
      const row = document.createElement("div");
      row.className = "ob-msg controls";
      row.innerHTML = `<div class="ob-actionwrap"><button class="ob-btn ob-btn-primary ob-btn-lg" type="button">let's do it <span aria-hidden="true">→</span></button></div>`;
      chat.appendChild(row);
      row.querySelector("button")?.addEventListener("click", onDone);
      scrollEnd();
    })();

    return () => {
      cancelled = true;
    };
  }, [onDone]);

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 60 }}>
      <div className="ob-root">
        <div className="ob-bg" />
        <header className="ob-top">
          <span
            className="ob-logo"
            dangerouslySetInnerHTML={{ __html: `${SPARK} beam` }}
          />
          <div className="ob-progress" />
          <button type="button" className="ob-exit" onClick={onExit}>
            exit
          </button>
        </header>
        <main className="ob-stage">
          <div className="ob-scroll" ref={scrollRef}>
            <div className="ob-chat" ref={chatRef} />
          </div>
        </main>
      </div>
    </div>
  );
}
