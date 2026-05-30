/* beam-scene.js — PIXEL-ART hero scene (polished).
   A pixel schoolgirl walks, fires an eye-laser at an anonymous visitor who is
   "charmed" and floats up to join a conga line of lovestruck followers already
   trailing behind her. Polished pixel school-hallway background. Loops cleanly.
   Exposes window.__BEAM_SVG for the standalone export. */
(function () {
  const VB_W = 320, VB_H = 180;
  const PX = 2;            // one "pixel"
  const LOOP = 4.0;        // seconds per cycle (matches the "calm" pace default)
  const FLOOR_Y = 138;

  // ── palette (soft pixel aesthetic) ──
  const C = {
    bg:'#FAF6F0', floor:'#EFE4D0', floorLine:'#E0D1B4', floorGloss:'#FBF7EE',
    wallTop:'#F7F1E6', wallBot:'#F2E8DC', wainscot:'#ECDFCB', rail:'#D7C6A6', railHi:'#FBF5E9',
    frameBd:'#CBB596', frameMat:'#F5EEDF',
    // protagonist
    hair:'#E89A7B', hairDk:'#C9785A', skin:'#FBE2D2', skinSh:'#EBC9B4',
    eye:'#2B2530', blush:'#F49DAE', mouth:'#C75F75',
    body:'#C9B6E4', bodyDk:'#A691CF', skirt:'#9B7FCB', skirtDk:'#7A5BB0',
    shoe:'#3D2F4F', sock:'#FBF6EE',
    // silhouette
    sil:'#C9C2B5', silDk:'#A8A192', silQ:'#6B6358',
    // charmed follower skin
    cskin:'#FBE2D2',
    // accents
    heart:'#FF3366', heartHi:'#FF6B9D', sparkleY:'#FFD86B', sparkleP:'#FF6B9D', sparkleW:'#FFF4E0',
    bhairDk:'#4A3F4E', bhairHi:'#6E6172', bshoe:'#2E2636',
  };

  // ── sprite renderer: grid string → run-length <rect>s ──
  function sprite(grid, palette) {
    const rows = grid.split('\n').filter(r => r.length);
    let out = '';
    for (let y = 0; y < rows.length; y++) {
      const row = rows[y];
      let x = 0;
      while (x < row.length) {
        const c = row[x];
        if (c === '.' || c === ' ' || !palette[c]) { x++; continue; }
        let run = 1;
        while (x + run < row.length && row[x + run] === c) run++;
        out += `<rect x="${x*PX}" y="${y*PX}" width="${run*PX}" height="${PX}" fill="${palette[c]}"/>`;
        x += run;
      }
    }
    return out;
  }

  // ── PROTAGONIST (girl) — 18×26, arm extended, no wand (fires eye laser) ──
  const PROTAG = sprite(`
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
...llllllllll.....
...lll.ll.lll.....
...ll...l...l.....
....k...k...k.....
....k...k...k.....
....k...k.........
....SS.SS.........
....SS.SS.........
`, {
    H:C.hairDk, h:C.hair, s:C.skin, S:C.shoe,
    e:C.eye, m:C.mouth, B:C.blush, c:C.sock,
    b:C.body, o:C.bodyDk, l:C.skirt, L:C.skirtDk, k:C.skin,
  });

  // ── Anonymous visitor silhouette — 14×26 ──
  const SIL = sprite(`
....SSSSSS....
...SssssssS...
..SsssssssS...
..SsssssssS...
..Ssss..ssS...
..SsssssssS...
..SssssssS....
...SsssssS....
.....ss.......
....SSSSS.....
...SSSSSSS....
..SSSSSSSSS...
..SSSSSSSSS...
..SSSSSSSSS...
..SSSSSSSSS...
..SSSSSSSSS...
...SSSSSSS....
...SS...SS....
...SS...SS....
...SS...SS....
...SS...SS....
..SSS...SSS...
..SSS...SSS...
`, { S:C.silDk, s:C.sil });

  const QMARK = sprite(`
..qqqq..
.qq..qq.
.qq..qq.
.....qq.
....qq..
...qq...
..qq....
..qq....
........
..qq....
`, { q:C.silQ });

  // ── Lovestruck FLOATER (hunched, hovering). 14×24. CSS-rotated to lean. ──
  function makeFloater(shirt, shirtDk, pants, pantsDk) {
    return sprite(`
......hhhh....
....hhhhhhhh..
...hhhhhhhhhh.
..hhhhhHHHhhh.
..hhhHHHHHfff.
..hhHHHHffeef.
..hHHHHfffeef.
..hHHffffffff.
...ffffffmff..
...fffffffff..
....ddddddd...
...bbbbbbbbb..
..bbbbbBBbbbb.
..bbbbbbbbbbb.
..bbbbbbbbbbb.
..ffbbbbbbbff.
...nnnnnnnnn..
...nnnNNNnnn..
...nnnnnnnnn..
...nnn..nnn...
..nnn....nn...
..nn.....nnn..
.SSS.....nn...
.SS.......SS..
`, {
      h:C.bhairDk, H:C.bhairHi, f:C.cskin, e:C.heart, m:C.mouth,
      d:shirtDk, b:shirt, B:shirtDk, n:pants, N:pantsDk, S:C.bshoe,
    });
  }
  const FLOATER_PINK  = makeFloater('#F2BFCD', '#DC9CB0', '#E7E1EC', '#CCC4D7');
  const FLOATER_BLUE  = makeFloater('#5A6A93', '#414D6E', '#3A4358', '#2B3242');
  const FLOATER_SLATE = makeFloater('#8B93A8', '#6D758B', '#565C70', '#444A5C');
  const FLOATER_NEW   = makeFloater('#7AB8A1', '#4E8F77', '#6BA0C2', '#4F82A2');

  const HEART = sprite(`
.hh.hh.
hHHhHHh
hHHHHHh
.hHHHh.
..hHh..
...h...
`, { h:C.heart, H:C.heartHi });
  const HEART_SM = sprite(`
hh.hh
hHHHh
.HHh.
..h..
`, { h:C.heart, H:C.heartHi });

  const SPARK = sprite(`
..s..
.sSs.
sSWSs
.sSs.
..s..
`, { s:C.sparkleP, S:C.sparkleY, W:C.sparkleW });
  const SPARK_Y = sprite(`
..s..
.sSs.
sSWSs
.sSs.
..s..
`, { s:C.sparkleY, S:C.sparkleY, W:C.sparkleW });

  // ────────────────────────────────────────────────────────────────
  // POLISHED HALLWAY BACKGROUND
  // ────────────────────────────────────────────────────────────────
  // framed picture on the wall
  function frame(x, y, w, h, artBg, motif = '') {
    return `
      <rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${C.frameBd}"/>
      <rect x="${x+2}" y="${y+2}" width="${w-4}" height="${h-4}" fill="${C.frameMat}"/>
      <rect x="${x+4}" y="${y+4}" width="${w-8}" height="${h-8}" fill="${artBg}"/>
      ${motif}`;
  }

  const frames = (() => {
    const FY = 18, FW = 34, FH = 42;
    const tiles = [
      { x:16,  bg:'#DCE7E0', motif:(x,y)=>`<rect x="${x+6}" y="${y+26}" width="${FW-12}" height="8" fill="#B7CBC0"/><rect x="${x+12}" y="${y+16}" width="8" height="14" fill="#C9D8CF"/>` }, // hill
      { x:78,  bg:'#EAD9DE', motif:(x,y)=>HEART ? `<g transform="translate(${x+FW/2-3},${y+FH/2-3})">${HEART}</g>` : '' },                                  // heart
      { x:140, bg:'#E7E0D0', motif:(x,y)=>`<rect x="${x+8}" y="${y+10}" width="${FW-16}" height="${FH-22}" fill="#D3C6A8"/>` },                            // abstract
      { x:236, bg:'#DCDDEA', motif:(x,y)=>`<circle cx="${x+FW/2}" cy="${y+14}" r="5" fill="#C7C9DD"/><rect x="${x+6}" y="${y+24}" width="${FW-12}" height="9" fill="#C7C9DD"/>` }, // moon+sea
      { x:288, bg:'#E8E1D2', motif:(x,y)=>`<rect x="${x+9}" y="${y+9}" width="${FW-18}" height="${FH-20}" fill="#D6C9AB"/>` },
    ];
    return tiles.map(t => frame(t.x, FY, FW, FH, t.bg, t.motif(t.x, FY))).join('');
  })();

  const background = `
    <!-- wall -->
    <rect width="${VB_W}" height="${FLOOR_Y}" fill="url(#wallGrad)"/>
    <!-- picture frames -->
    ${frames}
    <!-- wainscot / dado -->
    <rect x="0" y="98" width="${VB_W}" height="${FLOOR_Y-98}" fill="${C.wainscot}"/>
    <rect x="0" y="96" width="${VB_W}" height="2" fill="${C.rail}"/>
    <rect x="0" y="95" width="${VB_W}" height="1" fill="${C.railHi}" opacity="0.7"/>
    <!-- vertical wainscot panel seams -->
    <g stroke="${C.rail}" stroke-width="1" opacity="0.35">
      ${[40,100,160,220,280].map(x=>`<line x1="${x}" y1="100" x2="${x}" y2="${FLOOR_Y-2}"/>`).join('')}
    </g>
    <!-- floor -->
    <rect x="0" y="${FLOOR_Y}" width="${VB_W}" height="${VB_H-FLOOR_Y}" fill="${C.floor}"/>
    <rect x="0" y="${FLOOR_Y}" width="${VB_W}" height="2" fill="#D8C7A8"/>
    <rect x="0" y="${FLOOR_Y+1}" width="${VB_W}" height="1" fill="${C.railHi}" opacity="0.6"/>
    <!-- floor perspective lines fanning to a vanishing point -->
    <g stroke="${C.floorLine}" stroke-width="1" opacity="0.5">
      ${[ -40, 40, 120, 200, 280, 360 ].map(x0=>`<line x1="${x0}" y1="${VB_H}" x2="160" y2="${FLOOR_Y}"/>`).join('')}
      <line x1="0" y1="160" x2="${VB_W}" y2="160" opacity="0.6"/>
    </g>
    <!-- soft floor reflection streaks -->
    <g opacity="0.4">
      <rect x="54"  y="${FLOOR_Y+3}" width="8"  height="${VB_H-FLOOR_Y-5}" fill="${C.floorGloss}"/>
      <rect x="150" y="${FLOOR_Y+3}" width="12" height="${VB_H-FLOOR_Y-5}" fill="${C.floorGloss}"/>
      <rect x="250" y="${FLOOR_Y+3}" width="9"  height="${VB_H-FLOOR_Y-5}" fill="${C.floorGloss}"/>
    </g>`;

  const shadow = (cx, cy, w = 28, op = 0.18, cls = '') =>
    `<ellipse class="${cls}" cx="${cx}" cy="${cy}" rx="${w/2}" ry="${w/7}" fill="#6B5C52" opacity="${op}" filter="url(#soft)"/>`;

  // ────────────────────────────────────────────────────────────────
  // LAYOUT
  // ────────────────────────────────────────────────────────────────
  const PROT_X = 196, PROT_Y = 86;
  const SIL_X = 262,  SIL_Y = 86;
  const SLOTS = [44, 92, 140];          // 3 followers (near→far)
  const FLOAT_Y = 80;                   // hover (feet ≈126)
  const FSHADOW_Y = 140;

  const beamX = PROT_X + 9 * PX, beamY = PROT_Y + 5 * PX + 1;
  const beamLen = (SIL_X + 4 * PX) - beamX;

  const sparkleBurst = [[-6,-8],[6,-10],[-10,2],[10,0],[-2,-14],[4,8],[-8,10],[8,-2]]
    .map(([dx,dy],i)=>`<g class="spark spark-${i}" transform="translate(${dx},${dy})">${SPARK}</g>`).join('');

  // ────────────────────────────────────────────────────────────────
  // ASSEMBLE
  // ────────────────────────────────────────────────────────────────
  const svg = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${VB_W} ${VB_H}" shape-rendering="crispEdges" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="wallGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${C.wallTop}"/>
      <stop offset="1" stop-color="${C.wallBot}"/>
    </linearGradient>
    <linearGradient id="beamGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#FF6B9D"/>
      <stop offset="0.5" stop-color="#FF3366"/>
      <stop offset="1" stop-color="#FF6B9D"/>
    </linearGradient>
    <radialGradient id="bloom" cx="50%" cy="34%" r="75%">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.0"/>
      <stop offset="0.7" stop-color="#FFF6FA" stop-opacity="0.08"/>
      <stop offset="1" stop-color="#FFE6EE" stop-opacity="0.34"/>
    </radialGradient>
    <radialGradient id="vig" cx="50%" cy="48%" r="74%">
      <stop offset="0.66" stop-color="#000" stop-opacity="0"/>
      <stop offset="1" stop-color="#4A3A40" stop-opacity="0.12"/>
    </radialGradient>
    <filter id="soft" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="1.1"/></filter>
    <filter id="beamGlow" x="-20%" y="-120%" width="140%" height="340%"><feGaussianBlur stdDeviation="1.3"/></filter>
    <style><![CDATA[
      #beam-stage svg { background:${C.bg}; }

      .protagonist { animation: protBob 0.5s steps(2) infinite; transform-origin:50% 100%; }
      @keyframes protBob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-1px)} }

      /* eye laser charge glow */
      .eye-glow { opacity:0; animation: eyeGlow ${LOOP}s linear infinite; }
      @keyframes eyeGlow { 0%,14%{opacity:0} 18%{opacity:.7} 22%{opacity:.4} 24%,44%{opacity:1} 48%{opacity:0} 100%{opacity:0} }

      /* eye laser beam */
      .beam-group { opacity:0; transform-origin:0 50%; animation: beamLife ${LOOP}s linear infinite; }
      @keyframes beamLife { 0%,22%{opacity:0;transform:scaleX(0)} 24%{opacity:1;transform:scaleX(.06)} 38%{opacity:1;transform:scaleX(1)} 45%{opacity:1;transform:scaleX(1)} 48%{opacity:0;transform:scaleX(1)} 100%{opacity:0;transform:scaleX(0)} }
      .beam-wobble { animation: beamWobble 0.18s steps(2) infinite; }
      @keyframes beamWobble { 0%,100%{transform:translateY(0)} 50%{transform:translateY(1px)} }
      .beam-trail-dot { opacity:0; animation: trailDot ${LOOP}s linear infinite; }
      .beam-trail-dot:nth-child(1){animation-delay:-${LOOP*0.75}s} .beam-trail-dot:nth-child(2){animation-delay:-${LOOP*0.74}s}
      .beam-trail-dot:nth-child(3){animation-delay:-${LOOP*0.73}s} .beam-trail-dot:nth-child(4){animation-delay:-${LOOP*0.72}s}
      @keyframes trailDot { 0%,22%,50%,100%{opacity:0;transform:translate(0,0)} 26%{opacity:1;transform:translate(0,-2px)} 34%{opacity:.6;transform:translate(0,-4px)} 42%{opacity:0;transform:translate(0,-6px)} }

      /* anonymous visitor */
      .silhouette { animation: silLife ${LOOP}s linear infinite; }
      @keyframes silLife { 0%,44%{opacity:1} 46%,92%{opacity:0} 96%,100%{opacity:1} }
      .qmark { animation: qBob 1s steps(2) infinite, qLife ${LOOP}s linear infinite; transform-origin:50% 100%; }
      @keyframes qBob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-1px)} }
      @keyframes qLife { 0%,42%{opacity:1} 44%,92%{opacity:0} 96%,100%{opacity:1} }

      /* impact sparkle burst */
      .spark { opacity:0; transform-origin:center; animation: sparkBurst ${LOOP}s ease-out infinite; }
      .spark-0{animation-delay:0s}.spark-1{animation-delay:.02s}.spark-2{animation-delay:.04s}.spark-3{animation-delay:.06s}
      .spark-4{animation-delay:.08s}.spark-5{animation-delay:.05s}.spark-6{animation-delay:.03s}.spark-7{animation-delay:.01s}
      @keyframes sparkBurst { 0%,44%{opacity:0;transform:scale(.2)} 46%{opacity:1;transform:scale(1.4)} 52%{opacity:1;transform:scale(1)} 58%{opacity:0;transform:scale(.6) translate(0,-4px)} 100%{opacity:0;transform:scale(.2)} }

      /* three trailing followers: lean + hover-bob, staggered */
      .floater { transform-box:fill-box; transform-origin:50% 92%; animation: floaterBob 1.6s ease-in-out infinite; }
      @keyframes floaterBob { 0%,100%{transform:rotate(13deg) translateY(0)} 50%{transform:rotate(15deg) translateY(-3px)} }
      .f-1{animation-delay:-.53s}.f-2{animation-delay:-1.06s}
      .float-heart { transform-box:fill-box; transform-origin:50% 100%; animation: floatHeart 1.6s ease-in-out infinite; }
      @keyframes floatHeart { 0%,100%{transform:translateY(0);opacity:.85} 50%{transform:translateY(-3px);opacity:1} }
      .fh-1{animation-delay:-.53s}.fh-2{animation-delay:-1.06s}
      .float-shadow { transform-box:fill-box; transform-origin:50% 50%; animation: floatShadow 1.6s ease-in-out infinite; }
      @keyframes floatShadow { 0%,100%{transform:scaleX(1);opacity:1} 50%{transform:scaleX(.85);opacity:.8} }
      .fs-1{animation-delay:-.53s}.fs-2{animation-delay:-1.06s}

      /* incoming joiner: hidden as silhouette, then charmed + flies in to merge */
      .floater-new { opacity:0; transform-box:fill-box; transform-origin:50% 92%; animation: floaterNew ${LOOP}s ease-in-out infinite; }
      @keyframes floaterNew {
        0%,44%{opacity:0; transform:translate(0,4px) scale(1) rotate(0deg)}
        47%   {opacity:1; transform:translate(0,0) scale(1) rotate(4deg)}
        56%   {opacity:1; transform:translate(-44px,-12px) scale(.98) rotate(13deg)}
        70%   {opacity:1; transform:translate(-140px,-8px) scale(.92) rotate(13deg)}
        88%   {opacity:1; transform:translate(-238px,-6px) scale(.9) rotate(13deg)}
        95%   {opacity:.5; transform:translate(-244px,-6px) scale(.9) rotate(13deg)}
        100%  {opacity:0; transform:translate(-244px,-6px) scale(.9) rotate(13deg)}
      }
      .fh-new { opacity:0; animation: fhNew ${LOOP}s ease-in-out infinite; }
      @keyframes fhNew { 0%,46%{opacity:0} 50%{opacity:1} 90%{opacity:1} 96%,100%{opacity:0} }
    ]]></style>
  </defs>

  ${background}

  <!-- ground shadows -->
  ${shadow(PROT_X + 18, FLOOR_Y + 4, 34, 0.17)}
  ${[2,1,0].map(i=>shadow(SLOTS[i] + 14, FSHADOW_Y, 26 - i*3, 0.15 - i*0.02, `float-shadow fs-${i}`)).join('')}

  <!-- incoming joiner (behind everyone) -->
  <g transform="translate(${SIL_X}, ${FLOAT_Y})">
    <g class="floater-new">
      ${FLOATER_NEW}
      <g transform="translate(${5*PX}, ${-6*PX})"><g class="fh-new">${HEART_SM}</g></g>
    </g>
  </g>

  <!-- three trailing followers (far→near draw order) -->
  ${[2,1,0].map(i=>{
    const fx = SLOTS[i];
    const body = [FLOATER_PINK, FLOATER_BLUE, FLOATER_SLATE][i];
    return `
  <g transform="translate(${fx}, ${FLOAT_Y})"><g class="floater f-${i}">${body}</g></g>
  <g transform="translate(${fx + 5*PX}, ${FLOAT_Y - 6*PX})"><g class="float-heart fh-${i}">${HEART_SM}</g></g>`;
  }).join('')}

  <!-- anonymous visitor -->
  <g transform="translate(${SIL_X}, ${SIL_Y})">
    <g class="silhouette">
      ${SIL}
      <g transform="translate(${3*PX}, ${-10*PX})"><g class="qmark">${QMARK}</g></g>
    </g>
  </g>

  <!-- sparkle burst at impact -->
  <g transform="translate(${SIL_X + 7*PX}, ${SIL_Y + 8*PX})"><g>${sparkleBurst}</g></g>

  <!-- protagonist -->
  <g transform="translate(${PROT_X}, ${PROT_Y})"><g class="protagonist">${PROTAG}</g></g>

  <!-- eye glow -->
  <g class="eye-glow" transform="translate(${PROT_X}, ${PROT_Y})">
    <rect x="${4*PX-2}" y="${5*PX-3}" width="${7*PX+4}" height="${PX+6}" rx="4" fill="#FF6B9D" opacity="0.55" filter="url(#beamGlow)"/>
    <rect x="${4*PX}" y="${5*PX-1}" width="${2*PX}" height="${PX+2}" rx="1" fill="#FFF4E0"/>
    <rect x="${8*PX}" y="${5*PX-1}" width="${2*PX}" height="${PX+2}" rx="1" fill="#FFF4E0"/>
  </g>

  <!-- eye laser beam -->
  <g transform="translate(${beamX}, ${beamY})">
    <g class="beam-group">
      <g class="beam-wobble">
        <rect x="0" y="-9" width="${beamLen}" height="18" rx="9" fill="#FF6B9D" opacity="0.32" filter="url(#beamGlow)"/>
        <rect x="0" y="-6" width="${beamLen}" height="12" rx="6" fill="url(#beamGrad)"/>
        <rect x="0" y="-3" width="${beamLen}" height="6" rx="3" fill="#FFE0EC" opacity="0.95"/>
        <rect x="0" y="-1.5" width="${beamLen}" height="3" rx="1.5" fill="#FFFFFF" opacity="0.92"/>
        <g class="beam-trail-dot" transform="translate(18,-7)">${SPARK_Y}</g>
        <g class="beam-trail-dot" transform="translate(36,6)">${SPARK}</g>
        <g class="beam-trail-dot" transform="translate(54,-7)">${SPARK_Y}</g>
        <g class="beam-trail-dot" transform="translate(70,6)">${SPARK}</g>
      </g>
    </g>
  </g>

  <!-- film overlays -->
  <rect width="${VB_W}" height="${VB_H}" fill="url(#bloom)"/>
  <rect width="${VB_W}" height="${VB_H}" fill="url(#vig)"/>
</svg>`;

  const stage = document.getElementById('beam-stage');
  if (stage) stage.innerHTML = svg;
  window.__BEAM_SVG = svg;
})();
