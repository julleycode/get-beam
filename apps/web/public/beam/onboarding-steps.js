/* ════════════════════════════════════════════════════════════════
   beam onboarding (public / logged-out) — step content (window.OB_STEPS)

   TRUNCATED FUNNEL. This used to be a 13-step simulation of the whole
   product (paste url → fake platform detect → fake snippet install →
   FAKE detection → profile card → walkthrough → AI draft → paywall →
   hand-rolled ClerkJS signup → fake dashboard). Everything after the
   canary now lives behind auth in the React dashboard onboarding, and
   account creation is Clerk's hosted /sign-up, which does it properly.

   What is left is the one thing this surface can do that the authed
   flow structurally cannot: prove Beam works to someone with no
   account, using their own visit.

     welcome → canary_go → canary_listen → canary_reveal → account

   Three defects were removed rather than carried over:
     · the hard-coded data-site="YOUR_SITE_ID" snippet (dead `install` step)
     · `setTimeout(advance, 3600)` — a FAKED detection. canary_listen
       polls a real endpoint and, when nothing lands, says so.
     · "is this you?" feedback that was collected and thrown away. It now
       POSTs to /api/v1/demo/identity-feedback.

   Mirrors the React implementation (src/components/onboarding/*,
   src/lib/canary-*.ts) in behaviour and copy. Where a rule is duplicated
   here it is because this file has no build step and cannot import it —
   keep the two in sync.
   ════════════════════════════════════════════════════════════════ */
(function () {
  function _esc(t) {
    return String(t == null ? '' : t)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Fingerprint (v2) — same algorithm as pixel tracker.js ──
  // Changing ANY component here breaks the join with the pixel's stored
  // fingerprint and the catch silently never lands.
  function _h128(str) {
    var h = [0x811c9dc5, 0xc6a4a793, 0x6c62272e, 0x61c88647];
    var p = [0x01000193, 0x0100019b, 0x01000199, 0x01000187];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      for (var j = 0; j < 4; j++) h[j] = Math.imul(h[j] ^ c, p[j]) >>> 0;
    }
    return h[0].toString(36) + h[1].toString(36) + h[2].toString(36) + h[3].toString(36);
  }
  function _cvfp() {
    try {
      var cv = document.createElement('canvas'); cv.width = 200; cv.height = 50;
      var ctx = cv.getContext('2d'); if (!ctx) return '';
      ctx.textBaseline = 'top'; ctx.font = '14px Arial';
      ctx.fillStyle = '#f60'; ctx.fillRect(125, 1, 62, 20);
      ctx.fillStyle = '#069'; ctx.fillText('BmFp,1', 2, 15);
      ctx.fillStyle = 'rgba(102,204,0,0.7)'; ctx.fillText('BmFp,1', 4, 17);
      return cv.toDataURL().slice(-50);
    } catch(e) { return ''; }
  }
  function _glfp() {
    try {
      var cv = document.createElement('canvas');
      var gl = cv.getContext('webgl') || cv.getContext('experimental-webgl');
      if (!gl) return '';
      var ext = gl.getExtension('WEBGL_debug_renderer_info');
      var v = ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : '';
      var r = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : '';
      return v + '~' + r + '~' + gl.getParameter(gl.MAX_TEXTURE_SIZE);
    } catch(e) { return ''; }
  }
  function obFingerprint() {
    var c = [];
    c.push(screen.width + 'x' + screen.height);
    c.push(screen.availWidth + 'x' + screen.availHeight);
    c.push(screen.colorDepth);
    c.push(window.devicePixelRatio || 1);
    c.push(navigator.language);
    c.push(navigator.platform);
    c.push(navigator.hardwareConcurrency || 0);
    c.push(navigator.deviceMemory || 0);
    c.push(navigator.maxTouchPoints || 0);
    c.push(navigator.cookieEnabled ? 1 : 0);
    c.push(navigator.doNotTrack || '');
    c.push(navigator.pdfViewerEnabled ? 1 : 0);
    try { c.push(Intl.DateTimeFormat().resolvedOptions().timeZone); } catch(e) { c.push(''); }
    try { c.push(navigator.connection ? navigator.connection.effectiveType : ''); } catch(e) { c.push(''); }
    c.push(_cvfp());
    c.push(_glfp());
    c.push(Math.tan(-1e300));
    return 'fp2_' + _h128(c.join('|'));
  }

  // ── Beam API ────────────────────────────────────────────────────────
  const BEAM_API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8000'
    : 'https://api.getbeam.fyi';
  async function apiPost(path, body) {
    const r = await fetch(BEAM_API + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error('http ' + r.status);
    if (r.status === 204) return null;
    return r.json().catch(() => ({}));
  }

  // ── Canary constants — mirror src/lib/canary-listen-status.ts ───────
  const CANARY_URL = 'https://getbeam.fyi/?beam=canary';
  const LISTEN_DEADLINE_MS = 90000;   // not the old 15s: the user has to open a
  const POLL_FAST_MS = 2000;          // tab, actually read, and come back.
  const POLL_SLOW_MS = 4000;
  const POLL_BACKOFF_AFTER_MS = 20000;
  const MAX_CONSECUTIVE_ERRORS = 3;   // dormant endpoint (flag off → 404) in ~6s
  // This page carries the Beam pixel itself (onboarding.html, site_90a488f43eac),
  // so a visit to THIS path is already in the journey before the user opens
  // anything. Treating that as "caught you on getbeam.fyi" would be the same
  // dishonesty as the old fake timeout, so it is excluded from the landed test
  // (it is still shown in the page list — it genuinely happened).
  const SELF_PATH = '/onboarding';

  function pollIntervalFor(ms) { return ms < POLL_BACKOFF_AFTER_MS ? POLL_FAST_MS : POLL_SLOW_MS; }
  function statusFor(ms) {
    if (ms < 8000) return 'listening…';
    if (ms < 25000) return 'open a page on getbeam.fyi…';
    if (ms < 60000) return 'still listening — did the tab actually load?';
    return 'one more moment…';
  }

  // ── Reveal formatting — mirrors src/lib/canary-format.ts ────────────
  // THE FABRICATION GUARD: a datacenter / CDN / privacy-relay org is a hosting
  // provider that happens to own the exit address. It must NEVER be described
  // as the user's company or ISP.
  function formatPlace(geo) {
    if (!geo) return '';
    const city = (geo.city || '').trim();
    const region = (geo.region || '').trim();
    const cc = (geo.country_code || '').trim().toUpperCase();
    const parts = [];
    if (city) parts.push(city);
    if (region && region.toLowerCase() !== city.toLowerCase()) parts.push(region);
    const left = parts.join(', ');
    if (left && cc) return left + ' · ' + cc;
    return left || cc;
  }
  function formatNetwork(net) {
    if (!net) return null;                       // omit the line entirely rather
    const label = (net.label || '').trim();      // than print "Unknown ISP"
    if (!label) return null;
    switch ((net.kind || '').toLowerCase()) {
      case 'relay': case 'cdn':
        return "you're behind a privacy relay — this pin is the relay's exit, not you.";
      case 'datacenter': case 'hosting': case 'vpn':
        return "you're on a VPN — here's where it thinks you are.";
      case 'company':
        return "looks like you're on " + label + "'s network";
      case 'isp': case 'eyeball':
        return label + ' · your ISP';
      default:
        return label;                            // no ownership claim
    }
  }
  function formatPageLine(p) {
    const path = ((p && p.path) || '/').trim() || '/';
    const secs = (p && p.seconds) || 0;
    return secs > 0 ? path + ' · ' + Math.round(secs) + 's' : path;
  }

  /** Null Island: lat==lng==0 is the classic "provider returned nothing" pin. */
  function hasUsableGeo(res) {
    const g = res && res.geo;
    if (!g) return false;
    if (typeof g.lat !== 'number' || typeof g.lng !== 'number') return false;
    if (!isFinite(g.lat) || !isFinite(g.lng)) return false;
    return !(g.lat === 0 && g.lng === 0);
  }
  /** 'map' | 'text' | 'skip' — mirrors src/lib/canary-reveal-mode.ts. */
  function chooseRevealMode(res, tilesFailed) {
    if (!res) return 'skip';
    const geoOk = hasUsableGeo(res);
    const hasPages = !!(res.pages && res.pages.length);
    const hasNetwork = !!(res.network && res.network.label);
    if (!geoOk && !hasPages && !hasNetwork) return 'skip';
    if (geoOk && !tilesFailed) return 'map';
    return 'text';
  }

  // THE HONESTY CAPTION — load-bearing, not polish. Without it a 30km-off pin
  // reads as "your product is broken", the #1 failure mode of a location reveal.
  const HONESTY_CAPTION =
    "that's an IP-level estimate — usually the right city, sometimes the wrong suburb.";

  // ── Leaflet, loaded from CDN (no build step on this page) ───────────
  const LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
  const LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  // ATTRIBUTION IS MANDATORY under the OSM Tile Usage Policy — do not hide the
  // control, and do not proxy these tiles through our own API.
  const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  const TILE_ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  // NEVER go past 13. An IP pin is city-level at best; zooming to street level
  // makes a precision claim the data cannot support.
  const MAP_MIN_ZOOM = 9, MAP_MAX_ZOOM = 13, MAP_ZOOM = 11;
  const TILE_ERROR_THRESHOLD = 4, TILE_ERROR_WINDOW_MS = 2500, TILE_LOAD_DEADLINE_MS = 4000;

  let _leafletPromise = null;
  function ensureLeaflet() {
    if (_leafletPromise) return _leafletPromise;
    _leafletPromise = new Promise((resolve, reject) => {
      if (window.L) { resolve(window.L); return; }
      const css = document.createElement('link');
      css.rel = 'stylesheet'; css.href = LEAFLET_CSS; css.crossOrigin = 'anonymous';
      document.head.appendChild(css);
      const s = document.createElement('script');
      s.src = LEAFLET_JS; s.async = true; s.crossOrigin = 'anonymous';
      s.onload = () => (window.L ? resolve(window.L) : reject(new Error('leaflet missing')));
      s.onerror = () => reject(new Error('leaflet blocked'));
      document.head.appendChild(s);
    }).catch((e) => { _leafletPromise = null; throw e; });
    return _leafletPromise;
  }

  /**
   * Render the map into `host`. Resolves true on a loaded tile, false when the
   * tiles are blocked (corporate firewall / uBlock — the most likely visible
   * field failure). A grey box with a floating pin is worse than no map, so the
   * caller swaps to the text reveal on false.
   */
  function renderMap(host, geo) {
    return ensureLeaflet().then((L) => new Promise((resolve) => {
      let settled = false;
      const done = (ok) => { if (!settled) { settled = true; resolve(ok); } };

      const map = L.map(host, {
        center: [geo.lat, geo.lng],
        zoom: MAP_ZOOM, minZoom: MAP_MIN_ZOOM, maxZoom: MAP_MAX_ZOOM,
        // The map sits inside a scrolling chat transcript; wheel-zoom would
        // hijack the scroll.
        scrollWheelZoom: false, dragging: true,
        zoomControl: false, attributionControl: true, keyboard: false,
      });

      const startedAt = Date.now();
      let errors = 0, loadedAny = false;
      const fail = () => {
        if (loadedAny) return;
        try { map.remove(); } catch (e) {}
        done(false);
      };

      const tiles = L.tileLayer(TILE_URL, {
        attribution: TILE_ATTRIBUTION, maxZoom: MAP_MAX_ZOOM, minZoom: MAP_MIN_ZOOM,
      });
      tiles.on('tileerror', () => {
        errors++;
        if (errors >= TILE_ERROR_THRESHOLD && Date.now() - startedAt <= TILE_ERROR_WINDOW_MS) fail();
      });
      tiles.on('load', () => { if (!loadedAny) { loadedAny = true; done(true); } });
      tiles.addTo(map);
      // A host that black-holes the request (DNS sinkhole) never fires
      // `tileerror` at all, so a plain deadline is required too.
      setTimeout(() => { if (!loadedAny) fail(); }, TILE_LOAD_DEADLINE_MS);

      // The honest radius — the visual half of the caption above.
      L.circle([geo.lat, geo.lng], {
        radius: Math.max(1, geo.accuracy_km || 25) * 1000,
        color: '#FF3366', weight: 1, opacity: 0.45,
        fillColor: '#FF3366', fillOpacity: 0.1, interactive: false,
      }).addTo(map);

      // divIcon, not the default marker: Leaflet resolves that PNG relative to
      // the stylesheet, which is the classic broken-marker bug.
      L.marker([geo.lat, geo.lng], {
        interactive: false, keyboard: false,
        icon: L.divIcon({
          className: 'ob-map-pin-wrap',
          html: '<span class="ob-map-pin"></span>',
          iconSize: [12, 12], iconAnchor: [6, 6],
        }),
      }).addTo(map);
    })).catch(() => false);
  }

  // ── Feedback ────────────────────────────────────────────────────────
  // Must match FEEDBACK_REASONS in apps/api/models/identity_feedback.py; the
  // server drops unknown reasons so the counts stay analysable.
  const FEEDBACK_REASONS = [
    { value: 'wrong_city', label: 'wrong city' },
    { value: 'wrong_network', label: 'wrong network / ISP' },
    { value: 'vpn_or_proxy', label: "i'm on a VPN or proxy" },
    { value: 'not_me', label: "that's not me at all" },
  ];

  const OB_STEPS = {

    /* ── 1 · WELCOME ─────────────────────────────────────────── */
    async welcome(ob) {
      await ob.bot(`<p class="lead">hey — i'm beam 👋</p>`, { delay: 500 });
      await ob.bot(`the stupidly easy way to know who's actually on your site, and engage them tastefully.`);
      await ob.bot(`before you sign up for anything, let me just show you. cool?`);
      const c = ob.controls(`<button class="ob-btn ob-btn-primary ob-btn-lg" data-go>go on then <span aria-hidden="true">→</span></button>`);
      c.querySelector('[data-go]').addEventListener('click', () => ob.answer(`go on then`, 'canary_go'));
    },

    /* ── 2 · GO BROWSE ───────────────────────────────────────── */
    async canary_go(ob) {
      await ob.bot(`i'm going to catch you.`, { delay: 400 });
      await ob.bot(`open <b>getbeam.fyi</b> in a new tab, read a page or two, then come back here.`);
      // `.muted` is styled as `.ob-bubble .muted`, so it has to be a child node,
      // not a class on the bubble itself.
      await ob.bot(`<span class="muted">beam's own pixel runs on that site, so this is a real catch — not a demo.</span>`);
      const c = ob.controls(`
        <button class="ob-btn ob-btn-primary ob-btn-lg" data-go>catch me <span aria-hidden="true">→</span></button>
        <button class="ob-skip" data-skip>skip, just let me sign up</button>`);
      c.querySelector('[data-go]').addEventListener('click', () => {
        // COMPUTE THE FINGERPRINT HERE, ON THE CLICK. Once the new tab takes
        // focus this one is backgrounded, and a backgrounded tab can perturb the
        // canvas probe — producing a hash that does not match what the pixel
        // stored on getbeam.fyi. The join would then miss with no error anywhere.
        try { ob.state.fp = obFingerprint(); } catch (e) { ob.state.fp = ''; }
        try { window.open(CANARY_URL, '_blank', 'noopener,noreferrer'); } catch (e) {}
        ob.answer('opening it now', 'canary_listen');
      });
      c.querySelector('[data-skip]').addEventListener('click', () => ob.answer('skip', 'account'));
    },

    /* ── 3 · LISTENING (real poll, never a fake timer) ───────── */
    async canary_listen(ob) {
      const card = await ob.bot(`
        <div class="ob-listen">
          <div class="ob-radar"><div class="ring"></div><div class="ring"></div><div class="ring"></div><div class="core"></div></div>
          <div class="ob-map-note" id="ob-listen-status" aria-live="polite">listening…</div>
        </div>`, { cls: 'rich card', typing: false });
      // Escape hatch, available the whole time — never trap someone in a
      // 90-second wait for a demo.
      const c = ob.controls(`<button class="ob-skip" data-skip>skip this →</button>`);
      const status = card.querySelector('#ob-listen-status');

      let stopped = false;
      c.querySelector('[data-skip]').addEventListener('click', () => {
        stopped = true;
        ob.answer('skip', 'account');
      });

      const fp = ob.state.fp || '';
      const startedAt = Date.now();
      let errors = 0, last = null, baseline = null;

      // KEY ON path+timestamp, NEVER ON PATH ALONE. The page we send people to
      // is getbeam.fyi's root, and anyone arriving here from the landing page
      // already has `/` in the journey — so a path-keyed baseline marks the very
      // visit we asked for as "already seen" and the catch can never land. Each
      // pageview carries its own `at`, so a repeat visit to the same path is a
      // new key. `at` may be null on old rows; those degrade to path-only.
      const pageKey = (p) => ((p && p.path) || '') + '|' + ((p && p.at) || '');
      const isFresh = (res) => ((res && res.pages) || []).some(
        p => (p && p.path) !== SELF_PATH && !(baseline && baseline.has(pageKey(p)))
      );

      while (!stopped) {
        const elapsed = Date.now() - startedAt;
        if (elapsed >= LISTEN_DEADLINE_MS) break;
        if (status && document.body.contains(status)) status.textContent = statusFor(elapsed);

        try {
          const res = await apiPost('/api/v1/demo/canary', { fingerprint: fp });
          errors = 0;
          last = res;
          if (baseline === null) {
            // Whatever is already in the journey belongs to THIS page, which
            // also runs the pixel. Only something new counts as the catch.
            baseline = new Set(((res && res.pages) || []).map(pageKey));
          } else if (isFresh(res)) {
            ob.state.canary = res;
            ob.state.landed = true;
            if (!stopped) ob.answer('', 'canary_reveal');
            return;
          }
        } catch (e) {
          errors++;
          // A dormant endpoint (location_reveal_enabled off → 404) resolves in
          // ~6s instead of making the user wait out the whole deadline.
          if (errors >= MAX_CONSECUTIVE_ERRORS) break;
        }

        await ob.wait(pollIntervalFor(Date.now() - startedAt));
      }

      if (stopped) return;
      // NEVER fake a detection. Geo comes from the caller's own IP and is not
      // gated on the visit landing, so a VPN / adblocker / DNT user still gets a
      // real reveal instead of nothing.
      ob.state.canary = last;
      ob.state.landed = false;
      ob.answer('', 'canary_reveal');
    },

    /* ── 4 · THE REVEAL ──────────────────────────────────────── */
    async canary_reveal(ob) {
      const res = ob.state.canary;
      const landed = !!ob.state.landed;
      const mode0 = chooseRevealMode(res, false);

      if (mode0 === 'skip') {
        // Nothing honest to show at all.
        await ob.bot(`couldn't catch you this time — an adblocker, a privacy setting (we honor DNT and GPC), or the tab just never loaded.`, { delay: 300 });
        await ob.bot(`no matter. it works the same on your own site, where you control the page.`);
        ob.go('account');
        return;
      }

      if (landed) {
        await ob.bot(`got you.`, { delay: 300 });
      } else {
        await ob.bot(`didn't catch your visit — adblocker, DNT/GPC (we honor both), or the tab never loaded.`, { delay: 300 });
        await ob.bot(`but here's what your IP alone says:`);
      }

      const place = formatPlace(res.geo);
      const network = formatNetwork(res.network);
      const pages = (res.pages || []);
      const pagesHtml = pages.length
        ? `<div class="mrow"><span class="ic" aria-hidden="true">↗</span><span class="ob-path">` +
          pages.map((p, i) => (i ? '<span class="arr"> → </span>' : '') + '<code>' + _esc(formatPageLine(p)) + '</code>').join('') +
          `</span></div>`
        : '';

      const wantsMap = chooseRevealMode(res, false) === 'map';
      const card = await ob.bot(`
        ${wantsMap ? '<div class="ob-map" id="ob-map" role="img" aria-label="Approximate location on a map"></div>' : ''}
        <div class="ob-meta">
          ${place ? '<div class="mrow"><span class="ic" aria-hidden="true">◎</span><span>' + _esc(place) + '</span></div>' : ''}
          ${network ? '<div class="mrow"><span class="ic" aria-hidden="true">⌁</span><span>' + _esc(network) + '</span></div>' : ''}
          ${pagesHtml}
        </div>
        <p class="ob-map-note" id="ob-map-note">${_esc(HONESTY_CAPTION)}</p>`,
        { cls: 'rich card', typing: false });

      if (wantsMap) {
        const host = card.querySelector('#ob-map');
        const ok = await renderMap(host, res.geo);
        if (!ok) {
          // Tiles blocked or Leaflet itself unreachable → text reveal.
          if (host) host.remove();
          const note = card.querySelector('#ob-map-note');
          if (note) note.textContent =
            HONESTY_CAPTION + " (couldn't load the map here — something is blocking the tiles.)";
        }
        ob.scrollToEnd();
      }

      await ob.bot(`is this you?`);
      const c = ob.controls(`
        <button class="ob-btn ob-btn-primary" data-yes>✓ yes, that's me</button>
        <button class="ob-btn ob-btn-ghost" data-no>not quite</button>`);
      c.querySelector('[data-yes]').addEventListener('click', () => ob.answer(`yep, that's me`, 'account'));
      c.querySelector('[data-no]').addEventListener('click', () => {
        ob.clearControls(); ob.user('not quite');
        const cc = ob.controls(`
          <div class="ob-checks">
            ${FEEDBACK_REASONS.map(r => `<label class="ob-check"><input type="checkbox" value="${r.value}"> <span>${r.label}</span></label>`).join('')}
          </div>
          <textarea class="ob-textarea" style="margin-top:10px" maxlength="500" placeholder="anything else? (optional)" aria-label="Additional feedback"></textarea>
          <button class="ob-btn ob-btn-primary" style="margin-top:10px" data-fb>send it</button>`, true);
        cc.querySelectorAll('.ob-check').forEach(l =>
          l.addEventListener('change', () => l.classList.toggle('on', l.querySelector('input').checked)));
        cc.querySelector('[data-fb]').addEventListener('click', () => {
          const reasons = Array.from(cc.querySelectorAll('.ob-check input:checked')).map(i => i.value);
          const note = (cc.querySelector('.ob-textarea').value || '').trim();
          const geo = (res && res.geo) || null;
          const net = (res && res.network) || null;
          // OPTIMISTIC: fire and advance in the same tick. A feedback write must
          // never block the funnel, so failures are swallowed deliberately.
          apiPost('/api/v1/demo/identity-feedback', {
            reasons: reasons,
            note: note || null,
            fingerprint: ob.state.fp || null,
            shown: {
              city: geo ? geo.city : null,
              region: geo ? geo.region : null,
              country_code: geo ? geo.country_code : null,
              // Rounded: this is a feedback record, not a location store.
              lat: geo ? Math.round(geo.lat * 100) / 100 : null,
              lng: geo ? Math.round(geo.lng * 100) / 100 : null,
              org: net ? net.label : null,
              kind: net ? net.kind : null,
            },
          }).catch(() => {});
          ob.answer('sent you some feedback', 'account');
        });
      });
    },

    /* ── 5 · CREATE YOUR ACCOUNT → Clerk's hosted /sign-up ───── */
    async account(ob) {
      // No in-page auth here any more. The old step hand-rolled ClerkJS signup,
      // email-code verification, a login tab, and a legacy JWT fallback — ~230
      // lines duplicating what Clerk's hosted page does correctly.
      await ob.bot(`that's beam, on you, before you installed anything.`, { delay: 400 });
      await ob.bot(`create your account and i'll do it for your visitors — you paste one snippet, i take it from there.`);
      const c = ob.controls(`
        <button class="ob-btn ob-btn-primary ob-btn-lg" data-go>create your account <span aria-hidden="true">→</span></button>
        <div class="ob-hint" style="margin-top:10px">already have one? <a href="/sign-in">sign in →</a></div>`);
      c.querySelector('[data-go]').addEventListener('click', () => { window.location.href = '/sign-up'; });
    },
  };

  window.OB_STEPS = OB_STEPS;
})();
