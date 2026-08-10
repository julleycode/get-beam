// The pixel-art "beam girl" mascot, ported from the landing/onboarding hero
// sprite at public/beam/onboarding-mascot.js so it can render inside React
// (the dashboard) without a window global or a binary image asset. Front-facing
// standing pose; render at any size — shapeRendering="crispEdges" +
// imageRendering:pixelated keep the pixels sharp.
//
// Two palettes on one grid:
//   "tour" — pink-hair / navy-uniform recolor used by the dashboard tour
//   "chat" — the original auburn-hair / lilac-uniform hero palette, used by the
//            onboarding chat so it matches the marketing funnel's mascot
//
// ⚠️ GRID SYNC: public/beam/onboarding-mascot.js holds a THIRD copy of this
// sprite grid. It must stay a plain <script> because the static landing page
// calls window.beamMascot() and cannot import from src/. If you change GRID
// here, change it there too — see the matching note at the top of that file.
const PAL_TOUR: Record<string, string> = {
  H: "#D98CC0", // hair — pink shadow / outline
  h: "#F6B8DD", // hair — pink fill
  s: "#FBE2D2", // face skin
  S: "#2B2540", // shoes
  e: "#2B2530", // eyes
  m: "#C75F75", // mouth
  B: "#F49DAE", // cheek blush
  c: "#FBF6EE", // sailor collar (white)
  b: "#42548A", // uniform top — navy
  o: "#2C3A63", // uniform top — navy shadow
  l: "#3A4C80", // skirt — navy
  L: "#283457", // skirt — navy shadow
  k: "#FBE2D2", // legs skin
};

// Byte-for-byte the palette from public/beam/onboarding-mascot.js.
const PAL_CHAT: Record<string, string> = {
  H: "#C9785A", h: "#E89A7B", s: "#FBE2D2", S: "#3D2F4F",
  e: "#2B2530", m: "#C75F75", B: "#F49DAE", c: "#FBF6EE",
  b: "#C9B6E4", o: "#A691CF", l: "#9B7FCB", L: "#7A5BB0", k: "#FBE2D2",
};

export type MascotPalette = "tour" | "chat";

const PALETTES: Record<MascotPalette, Record<string, string>> = {
  tour: PAL_TOUR,
  chat: PAL_CHAT,
};

const GRID = `
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

type Px = { x: number; y: number; w: number; fill: string };

// Run-length encode the grid into horizontal rects once per palette, at module
// load. Both palettes share the grid, so only the fills differ.
function encode(pal: Record<string, string>): Px[] {
  const rows = GRID.split("\n").filter((r) => r.length);
  const out: Px[] = [];
  for (let y = 0; y < rows.length; y++) {
    const row = rows[y];
    let x = 0;
    while (x < row.length) {
      const c = row[x];
      if (c === "." || c === " " || !pal[c]) {
        x++;
        continue;
      }
      let run = 1;
      while (x + run < row.length && row[x + run] === c) run++;
      out.push({ x, y, w: run, fill: pal[c] });
      x += run;
    }
  }
  return out;
}

const RECTS_BY_PALETTE: Record<MascotPalette, Px[]> = {
  tour: encode(PALETTES.tour),
  chat: encode(PALETTES.chat),
};

export function BeamMascot({
  className,
  palette = "tour",
}: {
  className?: string;
  palette?: MascotPalette;
}) {
  const RECTS = RECTS_BY_PALETTE[palette] ?? RECTS_BY_PALETTE.tour;
  return (
    <svg
      className={className}
      viewBox="0 0 18 26"
      shapeRendering="crispEdges"
      preserveAspectRatio="xMidYMax meet"
      style={{ imageRendering: "pixelated" }}
      aria-hidden="true"
    >
      {RECTS.map((r, i) => (
        <rect key={i} x={r.x} y={r.y} width={r.w} height={1} fill={r.fill} />
      ))}
    </svg>
  );
}
