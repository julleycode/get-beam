// The pixel-art "beam girl" mascot, ported from the landing/onboarding hero
// sprite at public/beam/onboarding-mascot.js so it can render inside React
// (the dashboard) without a window global or a binary image asset. Front-facing
// standing pose; render at any size — shapeRendering="crispEdges" +
// imageRendering:pixelated keep the pixels sharp.
//
// Palette recolored to the pink-hair / navy-uniform variant for the onboarding
// tour (matches the mascot reference). The landing/onboarding hero keeps its own
// palette in public/beam/onboarding-mascot.js — this recolor is tour-only.
const PAL: Record<string, string> = {
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

// Run-length encode the grid into horizontal rects once at module load.
const RECTS: Px[] = (() => {
  const rows = GRID.split("\n").filter((r) => r.length);
  const out: Px[] = [];
  for (let y = 0; y < rows.length; y++) {
    const row = rows[y];
    let x = 0;
    while (x < row.length) {
      const c = row[x];
      if (c === "." || c === " " || !PAL[c]) {
        x++;
        continue;
      }
      let run = 1;
      while (x + run < row.length && row[x + run] === c) run++;
      out.push({ x, y, w: run, fill: PAL[c] });
      x += run;
    }
  }
  return out;
})();

export function BeamMascot({ className }: { className?: string }) {
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
