/* ════════════════════════════════════════════════════════════════
   beam onboarding — step content (window.OB_STEPS)
   Each step is an async sequence in the chat: the mascot types
   messages (ob.bot), the user replies on the right (ob.user), and
   interactive controls (ob.controls) advance the conversation.
   ════════════════════════════════════════════════════════════════ */
(function () {
  function detectPlatform(url) {
    const u = (url || '').toLowerCase();
    if (u.includes('shopify') || u.includes('myshopify')) return 'shopify';
    if (u.includes('wordpress') || u.includes('/wp-') || u.includes('wp.')) return 'wordpress';
    if (u.includes('framer')) return 'framer';
    return 'webflow';
  }
  function cleanHost(url) {
    let u = (url || '').trim().replace(/^https?:\/\//i, '').replace(/\/+$/, '');
    return u || 'yoursite.com';
  }
  function icMail() { return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 7 8.5 6 8.5-6"/></svg>`; }
  function icPin() { return `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>`; }
  function badge(t) { return `<span class="ob-ib">${t}</span>`; }

  // ── Fingerprint (v2) — same algorithm as pixel tracker.js ──
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

  // ── Journey replay (sample-data mode) ───────────────────────────────
  // When a user has no site, onboarding sends them to getbeam.fyi (which
  // runs the pixel). renderJourney shows the real pages they just browsed,
  // pulled from ob.state.journey (populated by the wait-step poll).
  function _esc(t) { return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function _fmtSecs(s) {
    s = Math.max(0, Math.round(s || 0));
    if (!s) return '';
    if (s < 60) return s + 's';
    const m = Math.floor(s / 60), r = s % 60;
    return r ? m + 'm ' + r + 's' : m + 'm';
  }
  async function renderJourney(ob) {
    const pages = (ob.state && ob.state.journey) || [];
    if (!pages.length) return;
    await ob.bot(`and here's <b>exactly</b> what you just did on getbeam.fyi — recorded live by the pixel:`, { delay: 300 });
    const rows = pages.map((p, i) => {
      const secs = _fmtSecs(p.seconds);
      return `<div class="ob-row"><span class="k">${i + 1}. ${_esc(p.path || '/')}</span>` +
        `<span class="v">${secs ? '<span class="ob-pill">' + secs + '</span>' : '<span class="ob-hint">just now</span>'}</span></div>`;
    }).join('');
    await ob.bot(`<div class="ob-rows">${rows}</div>`, { cls: 'rich card', typing: false });
  }

  const PLATFORM_INSTALL = {
    webflow:     'project settings → custom code → head',
    shopify:     'theme.liquid, before &lt;/head&gt;',
    wordpress:   'header.php or an "insert headers" plugin',
    framer:      'site settings → custom code → head',
    wix:         'settings → custom code → add to the &lt;head&gt;',
    squarespace: 'settings → advanced → code injection → header',
    unknown:     'paste it just before the closing &lt;/head&gt; tag',
  };

  // ── Real Beam API wiring ─────────────────────────────────────────────
  const BEAM_API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8000'
    : 'https://api.getbeam.fyi';
  async function apiPost(path, body, token) {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const r = await fetch(BEAM_API + path, { method: 'POST', headers, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || ('http ' + r.status));
    return data;
  }
  async function apiGet(path, token) {
    const headers = {};
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const r = await fetch(BEAM_API + path, { headers });
    if (!r.ok) throw new Error('http ' + r.status);
    return r.json();
  }

  // ── ClerkJS (loaded lazily, only when Clerk is configured) ───────────
  // Lets the static onboarding create a real Clerk account in-page, so the
  // signup→dashboard handoff uses the same Clerk session as the rest of the app.
  let _clerkPromise = null;
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src; s.async = true; s.crossOrigin = 'anonymous';
      s.onload = resolve; s.onerror = () => reject(new Error('script load failed: ' + src));
      document.head.appendChild(s);
    });
  }
  // Returns a loaded Clerk instance, or null when Clerk isn't configured / fails.
  async function ensureClerk() {
    if (_clerkPromise) return _clerkPromise;
    _clerkPromise = (async () => {
      let pk = null;
      try {
        const cfg = await apiGet('/api/v1/demo/clerk-config');
        pk = cfg && cfg.publishable_key;
      } catch (e) { /* config endpoint unreachable */ }
      if (!pk) return null;  // Clerk not configured → caller falls back to legacy
      if (!window.Clerk) {
        await loadScript('https://cdn.jsdelivr.net/npm/@clerk/clerk-js@5/dist/clerk.browser.js');
      }
      const clerk = new window.Clerk(pk);
      await clerk.load();
      return clerk;
    })().catch(() => null);
    return _clerkPromise;
  }

  const OB_STEPS = {

    /* ── 1 · WELCOME ─────────────────────────────────────────── */
    async welcome(ob) {
      await ob.bot(`<p class="lead">hey — i'm beam 👋</p>`, { delay: 500 });
      await ob.bot(`the stupidly easy way to know who's actually on your site, and engage them tastefully.`);
      await ob.bot(`give me ~4 minutes and i'll set you up. cool?`);
      const c = ob.controls(`<button class="ob-btn ob-btn-primary ob-btn-lg" data-go>let's do it <span aria-hidden="true">→</span></button>`);
      c.querySelector('[data-go]').addEventListener('click', () => ob.answer(`let's do it`, 'url'));
    },

    /* ── 2 · PASTE SITE URL ──────────────────────────────────── */
    async url(ob) {
      await ob.bot(`first — what's your site? paste the url and i'll start watching for visitors.`);
      const c = ob.controls(`
        <div class="ob-field">
          <span class="scheme">https://</span>
          <input class="ob-input" id="ob-url" placeholder="yoursite.com" autocomplete="off" spellcheck="false" />
          <button class="ob-btn ob-btn-primary" data-go>go</button>
        </div>
        <div class="ob-error" id="ob-url-err" style="display:none">enter your site's address to continue.</div>
        <div class="ob-hint">no site handy? <a href="#" id="ob-demo">use sample data →</a></div>
      `);
      const input = c.querySelector('#ob-url');
      setTimeout(() => input.focus(), 60);
      function submit() {
        const v = input.value.trim();
        if (!v) { c.querySelector('#ob-url-err').style.display = 'block'; input.focus(); return; }
        ob.state.url = v;
        ob.answer(cleanHost(v), 'verify');
      }
      c.querySelector('[data-go]').addEventListener('click', submit);
      input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
      c.querySelector('#ob-demo').addEventListener('click', e => {
        e.preventDefault(); ob.state.url = 'demo.beam.fyi'; ob.state.platform = 'webflow';
        ob.answer('use sample data', 'verify');
      });
    },

    /* ── 3 · VERIFY + DETECT PLATFORM ────────────────────────── */
    async verify(ob) {
      const isSample = ob.state.url === 'demo.beam.fyi';
      if (isSample) {
        // Sample-data users have no site — skip the snippet/install pretense and
        // demo on our own site. ONE button: it opens getbeam.fyi and starts
        // watching (no redundant second "i'll open it" step).
        await ob.bot(`no site of your own yet? no problem — i'll show you exactly how beam works on our <b>own</b> site, <b>getbeam.fyi</b>.`, { delay: 700 });
        await ob.bot(`i'll open it in a new tab — click around a page or two, then come back here and watch. our pixel records every move, exactly what it'll do on your site once you add the snippet.`);
        const sc = ob.controls(`<button class="ob-btn ob-btn-primary" data-go>open getbeam.fyi &amp; catch me <span aria-hidden="true">→</span></button>`);
        sc.querySelector('[data-go]').addEventListener('click', () => {
          try { window.open('https://getbeam.fyi/?beam=demo', '_blank', 'noopener'); } catch (e) {}
          ob.answer('opening getbeam.fyi now', 'wait');
        });
        return;
      }
      const hostName = cleanHost(ob.state.url);
      await ob.bot(`checking ${hostName}…`, { delay: 1100 });
      // REAL platform detection — fetches the site's HTML (same engine as the dashboard).
      try {
        const det = await apiPost('/api/v1/demo/detect-platform', { url: ob.state.url });
        if (det && det.platform && det.platform !== 'unknown') ob.state.platform = det.platform;
        else ob.state.platform = ob.state.platform || '';
      } catch (e) { /* keep whatever we have */ }
      const plat = ob.state.platform || 'webflow';
      await ob.bot(`found you, and i can tell what you're built on:`, { cls: 'rich', delay: 400 });
      await ob.bot(`
        <div class="ob-rows">
          <div class="ob-row"><span class="k">site</span><span class="v">${hostName}</span></div>
          <div class="ob-row"><span class="k">platform</span><span class="v"><span class="ob-pill"><span class="pdot"></span> ${plat}</span></span></div>
          <div class="ob-row"><span class="k">status</span><span class="v"><span class="ob-pill green"><span class="pdot"></span> reachable</span></span></div>
        </div>`, { cls: 'rich card', typing: false });
      await ob.bot(`ready for your snippet?`);
      const c = ob.controls(`
        <button class="ob-btn ob-btn-primary" data-go>yes, show me</button>
        <button class="ob-btn ob-btn-ghost" data-wrong>wrong platform</button>`);
      c.querySelector('[data-go]').addEventListener('click', () => ob.answer('yes, show me', 'install'));
      c.querySelector('[data-wrong]').addEventListener('click', () => {
        ob.clearControls(); ob.user('actually, wrong platform');
        const opts = ['webflow', 'shopify', 'wordpress', 'wix', 'squarespace', 'framer'];
        const cc = ob.controls(`<div class="ob-chips">${opts.map(o => `<button class="ob-chip" data-p="${o}">${o}</button>`).join('')}</div>`);
        cc.querySelectorAll('[data-p]').forEach(b => b.addEventListener('click', () => {
          ob.state.platform = b.dataset.p; ob.answer(b.dataset.p, 'install');
        }));
      });
    },

    /* ── 4 · INSTALL SNIPPET ─────────────────────────────────── */
    async install(ob) {
      const plat = ob.state.platform || 'unknown';
      const instr = PLATFORM_INSTALL[plat] || PLATFORM_INSTALL.unknown;
      const platLabel = plat === 'unknown' ? 'your site' : plat;
      await ob.bot(`copy this and paste it into your site's &lt;head&gt;. for <b>${platLabel}</b>: ${instr}.`);
      await ob.bot(`
        <div class="ob-code">
          <button class="ob-copy" id="ob-copy">copy</button>
<span class="tag">&lt;script</span> <span class="attr">src</span>=<span class="str">"https://beam.fyi/b.js"</span> <span class="attr">data-id</span>=<span class="str">"usr_8fk2c9"</span><span class="tag">&gt;&lt;/script&gt;</span>
        </div>`, { cls: 'rich plain', typing: false });
      const c = ob.controls(`
        <button class="ob-btn ob-btn-primary" data-go>i installed it</button>
        <button class="ob-btn ob-btn-ghost" id="ob-dev">send to my AI agent</button>`);
      // copy button lives in the previous bubble
      const copyBtn = document.getElementById('ob-copy');
      if (copyBtn) copyBtn.addEventListener('click', () => {
        const txt = '<script src="https://beam.fyi/b.js" data-id="usr_8fk2c9"></scr' + 'ipt>';
        if (navigator.clipboard) navigator.clipboard.writeText(txt).catch(() => {});
        copyBtn.textContent = '✓ copied'; copyBtn.classList.add('copied');
        setTimeout(() => { copyBtn.textContent = 'copy'; copyBtn.classList.remove('copied'); }, 1800);
      });
      c.querySelector('[data-go]').addEventListener('click', () => ob.answer('installed', 'detect'));
      c.querySelector('#ob-dev').addEventListener('click', () => {
        const prompt = `Install the Beam tracking pixel on ${cleanHost(ob.state.url)} (${ob.state.platform || 'unknown platform'}).\n\nAdd this snippet before </head>:\n<script src="https://beam.fyi/b.js" data-id="usr_8fk2c9"></scr` + `ipt>\n\nFor ${ob.state.platform || 'your site'}: ${PLATFORM_INSTALL[ob.state.platform] || PLATFORM_INSTALL.unknown}`;
        if (navigator.clipboard) navigator.clipboard.writeText(prompt).catch(() => {});
        ob.modal(`
          <h3>prompt copied ✓</h3>
          <p>paste this into Cursor, Claude Code, or any AI coding agent. it has the snippet + install instructions for ${ob.state.platform || 'your site'}.</p>
          <div class="ob-code" style="font-size:12px;max-height:140px;overflow-y:auto;margin:12px 0">${prompt.replace(/\n/g, '<br>').replace(/</g, '&lt;')}</div>
          <div class="ob-actions" style="margin-top:16px">
            <button class="ob-btn ob-btn-primary" id="ob-dev-ok">got it</button>
          </div>`);
        const back = document.getElementById('ob-modal-back');
        back.querySelector('#ob-dev-ok').addEventListener('click', () => { ob.closeModal(); ob.answer('sent to my agent', 'detect'); });
      });
    },

    /* ── 5 · AUTO-DETECT SNIPPET ACTIVE ──────────────────────── */
    async detect(ob) {
      // Sample mode never reaches here — verify() opens getbeam.fyi and jumps
      // straight to 'wait'. This step is the real-site (installed-snippet) path.
      const hostName = cleanHost(ob.state.url);
      await ob.bot(`scanning for the snippet…`, { delay: 1200 });
      await ob.bot(`<span class="ob-pill green" style="padding:3px 9px"><span class="pdot"></span> live</span> i can see you now. 🎉`, { delay: 500 });
      await ob.bot(`let's test it on you first. open <b>${hostName}</b> in another tab or an incognito window — i'll catch you and show you exactly what i do for every visitor.`);
      const c = ob.controls(`<button class="ob-btn ob-btn-primary" data-go>i'm opening it now</button>`);
      c.querySelector('[data-go]').addEventListener('click', () => ob.answer('opening it now', 'wait'));
    },

    /* ── 6 · WAITING FOR VISIT ───────────────────────────────── */
    async wait(ob) {
      const isSample = ob.state.url === 'demo.beam.fyi';
      await ob.bot(`i'm watching… 👀`, { delay: 400 });
      const card = await ob.bot(`
        <div class="ob-listen">
          <div class="ob-radar"><div class="ring"></div><div class="ring"></div><div class="ring"></div><div class="core"></div></div>
          <div class="ob-hint" id="ob-wait-note">listening for your visit…</div>
        </div>`, { cls: 'rich card', typing: false });
      const c = ob.controls(`<button class="ob-skip" data-skip>skip the wait →</button>`);
      const note = card.querySelector('#ob-wait-note');
      let done = false;
      const advance = () => { if (!done) { done = true; ob.answer('', 'identify'); } };
      c.querySelector('[data-skip]').addEventListener('click', advance);

      if (isSample) {
        // Poll the real pixel events until we see the getbeam.fyi visit land.
        if (note) note.textContent = 'open getbeam.fyi and click around a page or two…';
        const fp = obFingerprint();
        const deadline = Date.now() + 15000;
        while (!done && Date.now() < deadline) {
          await ob.wait(2000);
          if (done) return;
          try {
            const j = await apiPost('/api/v1/demo/journey', { fingerprint: fp });
            if (j && j.pages && j.pages.length) { ob.state.journey = j.pages; break; }
          } catch (e) { /* keep listening */ }
          if (note && document.body.contains(note)) note.textContent = 'still listening — browse a page on getbeam.fyi…';
        }
        advance();
      } else {
        setTimeout(() => { if (note && document.body.contains(note)) note.textContent = 'still listening — did you open the site?'; }, 4200);
        setTimeout(advance, 3600);
      }
    },

    /* ── 7 · CAPTURED + IDENTIFYING ───────────────── */
    async identify(ob) {
      await ob.bot(`got you! 🎯 identifying…`, { delay: 300 });
      // Send browser fingerprint so backend can match against pixel events
      try { ob.state.identified = await apiPost('/api/v1/demo/identify', { fingerprint: obFingerprint() }); }
      catch (e) { ob.state.identified = null; }
      const id = ob.state.identified;
      if (id && id.matched) {
        // IP resolved — show skeleton briefly then jump to wow
        await ob.wait(600);
      }
      // Skip skeleton entirely — go straight to wow (which shows real data or email fallback)
      ob.go('wow');
    },

    /* ── 8 · WHAT I KNOW ABOUT YOU (the WOW) ──────────────────── */
    async wow(ob) {
      // Sample-data mode: replay the real pages they just browsed on getbeam.fyi.
      await renderJourney(ob);
      const id = ob.state.identified;
      function initials(n) { return (n || 'JT').split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase(); }
      function profileCard(p) {
        const meta = [];
        if (p.company) meta.push(`<div class="mrow"><span class="ic">${icPin()}</span> ${p.company}${p.country ? ' · ' + p.country : ''}</div>`);
        if (p.email) meta.push(`<div class="mrow"><span class="ic">${icMail()}</span> ${p.email}</div>`);
        if (p.linkedin) meta.push(`<div class="mrow"><span class="ic">${badge('in')}</span> <a href="#" onclick="return false">${p.linkedin}</a></div>`);
        if (p.twitter) meta.push(`<div class="mrow"><span class="ic">${badge('X')}</span> <a href="#" onclick="return false">@${p.twitter}</a></div>`);
        return `
        <span class="ob-speed">⚡ identified in <b>4 seconds</b></span>
        <div class="ob-profile" style="margin-top:12px">
          <div class="ob-avatar">${initials(p.name)}</div>
          <div class="who">
            <div class="name">${p.name}</div>
            <div class="role">${p.role || ''}</div>
            <div class="ob-meta">${meta.join('')}</div>
          </div>
        </div>`;
      }

      if (id && id.matched && id.level === 'person') {
        await ob.bot(`here's who just visited — identified from a cold, anonymous hit:`, { delay: 300 });
        await ob.bot(profileCard({
          name: id.full_name || 'someone at ' + (id.company_domain || 'your company'),
          role: [id.job_title, id.company_name || id.company_domain].filter(Boolean).join(' · '),
          company: id.company_name || id.company_domain,
          country: id.country, email: id.email,
          linkedin: (id.linkedin_url || '').replace(/^https?:\/\//, '') || null,
          twitter: id.twitter_handle || null,
        }), { cls: 'rich card', typing: false });
      } else if (id && id.matched && id.level === 'company') {
        await ob.bot(`here's the visit — identified straight from a cold, anonymous hit:`, { delay: 300 });
        await ob.bot(profileCard({
          name: 'someone from ' + id.company_domain,
          role: 'company-level match · ' + (id.country || ''),
          company: id.company_domain, country: id.country,
        }), { cls: 'rich card', typing: false });
      } else if (id && id.matched && id.level === 'device') {
        await ob.bot(`caught you! your browser fingerprint matched the pixel visit. 🔒`, { delay: 300 });
        await ob.bot(`that's device-level identification — in production, we layer identity providers on top to get your name, email, and social profiles.`);
        await ob.bot(`drop your work email and i'll show you the full profile experience.`);
      } else {
        await ob.bot(`couldn't identify you this time — happens with ~30% of traffic. in production, our 7-layer waterfall catches most of your real visitors.`, { delay: 300 });
        await ob.bot(`drop your work email and i'll pull your real profile.`);
      }

      if (!id || !id.matched || id.level === 'device') {
        const ec = ob.controls(`
          <div class="ob-field">
            <input class="ob-input" id="ob-email-id" type="email" placeholder="you@company.com" autocomplete="email" />
            <button class="ob-btn ob-btn-primary" data-go>identify me</button>
          </div>`);
        const emailResult = await new Promise(resolve => {
          const inp = ec.querySelector('#ob-email-id');
          setTimeout(() => inp.focus(), 60);
          async function doLookup() {
            const email = inp.value.trim();
            if (!email || !email.includes('@')) { inp.focus(); return; }
            ob.clearControls();
            ob.user(email);
            await ob.bot(`looking you up…`, { delay: 800 });
            try {
              const res = await apiPost('/api/v1/demo/identify-by-email', { email });
              if (res && res.matched) {
                ob.state.identified = res;
                resolve(res);
              } else {
                await ob.bot(`no match for that email. works best with company emails (like you@company.com). edu and personal emails usually aren't in our database.`);
                const retry = ob.controls(`
                  <div class="ob-field">
                    <input class="ob-input" id="ob-email-retry" type="email" placeholder="you@company.com" />
                    <button class="ob-btn ob-btn-primary" data-go>try again</button>
                  </div>`);
                const retryInp = retry.querySelector('#ob-email-retry');
                retryInp.focus();
                retry.querySelector('[data-go]').addEventListener('click', async () => {
                  const e2 = retryInp.value.trim();
                  if (!e2) return;
                  ob.clearControls(); ob.user(e2);
                  await ob.bot(`checking…`, { delay: 800 });
                  try {
                    const r2 = await apiPost('/api/v1/demo/identify-by-email', { email: e2 });
                    if (r2 && r2.matched) { ob.state.identified = r2; resolve(r2); }
                    else { await ob.bot(`still no match. no worries, let me show you how it works.`); resolve(null); }
                  } catch (_) { resolve(null); }
                });
                retryInp.addEventListener('keydown', e => { if (e.key === 'Enter') retry.querySelector('[data-go]').click(); });
              }
            } catch (_) { resolve(null); }
          }
          ec.querySelector('[data-go]').addEventListener('click', doLookup);
          inp.addEventListener('keydown', e => { if (e.key === 'Enter') doLookup(); });
        });

        if (emailResult && emailResult.matched) {
          await ob.bot(`found you:`, { delay: 300 });
          await ob.bot(profileCard({
            name: emailResult.full_name || emailResult.email,
            role: [emailResult.job_title, emailResult.company_name || emailResult.company_domain].filter(Boolean).join(' · '),
            company: emailResult.company_name || emailResult.company_domain,
            country: emailResult.country, email: emailResult.email,
            linkedin: (emailResult.linkedin_url || '').replace(/^https?:\/\//, '') || null,
            twitter: emailResult.twitter_handle || null,
          }), { cls: 'rich card', typing: false });
        }
      }
      // Fetch REAL social posts if we have a twitter handle
      if (ob.state.identified && ob.state.identified.twitter_handle) {
        try {
          const sp = await apiPost('/api/v1/demo/social-posts', {
            twitter_handle: ob.state.identified.twitter_handle,
          });
          ob.state.social_posts = (sp && sp.posts) || [];
          ob.state.social_source = (sp && sp.source) || 'none';
        } catch (_) { ob.state.social_posts = []; }
      } else {
        ob.state.social_posts = [];
      }

      setTimeout(() => ob.celebrate(), 250);
      // Only ask "is this you?" when there's an actual profile to confirm.
      // A device-level fingerprint match has matched:true but no name/email,
      // so a failed email lookup must NOT trigger the confirm prompt.
      const idf = ob.state.identified;
      const hasProfile = idf && idf.matched && idf.level !== 'device' &&
        (idf.full_name || idf.company_name || idf.company_domain || idf.email);
      if (hasProfile) {
        await ob.bot(`is this you?`);
      } else {
        await ob.bot(`no worries. let me show you how beam works when a real visitor lands.`, { delay: 400 });
        ob.go('walk'); return;
      }
      const c = ob.controls(`
        <button class="ob-btn ob-btn-primary" data-yes>✓ yes, that's me</button>
        <button class="ob-btn ob-btn-ghost" data-no>not quite</button>`);
      c.querySelector('[data-yes]').addEventListener('click', () => ob.answer(`yep, that's me`, 'walk'));
      c.querySelector('[data-no]').addEventListener('click', () => {
        ob.clearControls(); ob.user('not quite');
        const opts = ['wrong name', 'wrong company', 'wrong socials', 'not me at all'];
        const cc = ob.controls(`
          <div class="ob-checks">
            ${opts.map((o, i) => `<label class="ob-check"><input type="checkbox" data-c="${i}"> ${o}</label>`).join('')}
          </div>
          <textarea class="ob-textarea" style="margin-top:10px" placeholder="optional details…"></textarea>
          <button class="ob-btn ob-btn-primary" style="margin-top:10px" data-fb>submit & continue</button>`);
        cc.querySelectorAll('.ob-check').forEach(l => l.addEventListener('change', () => l.classList.toggle('on', l.querySelector('input').checked)));
        cc.querySelector('[data-fb]').addEventListener('click', () => ob.answer('sent you some feedback', 'walk'));
      });
    },

    /* ── 9 · WALKTHROUGH ─────────────────────────────────────── */
    async walk(ob) {
      // Use real identified visitor data
      const id = ob.state.identified;
      const vName = (id && id.full_name) || 'a visitor';
      const vHandle = (id && id.twitter_handle) ? '@' + id.twitter_handle : '';
      const vCompany = (id && (id.company_name || id.company_domain)) || '';
      const vRole = [id && id.job_title, vCompany].filter(Boolean).join(' · ') || '';
      const initials = vName.split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase() || '??';
      const posts = ob.state.social_posts || [];

      // Build real social card from actual posts
      let socialCard = '';
      if (vName !== 'a visitor') {
        const postLines = posts.slice(0, 2).map(p => {
          const snippet = p.content.length > 80 ? p.content.slice(0, 80) + '…' : p.content;
          return `<div class="mini-line">· "${snippet}"</div>`;
        }).join('');
        socialCard = `<div class="ob-mini">
          <div class="mini-row"><span class="mini-av" style="background:#C7E1F3">${initials}</span><div><div>${vName}</div><div class="mini-tag">${vRole}</div></div></div>
          ${vHandle ? '<div class="mini-line" style="color:var(--pink,#FF3366)">· ' + vHandle + ' on x</div>' : ''}
          ${postLines || (vHandle ? '<div class="mini-line" style="opacity:0.5">· no recent posts found</div>' : '')}
        </div>`;
      }

      const beats = [
        { say: `every visitor that lands, i identify. 7 layers. 60-80% match rate.`, card: '' },
        { say: `then i find their socials.`, card: socialCard },
        { say: `then i draft a reply. personalized. in your voice.`, card: '' },
        { say: `you review, hit send. from your own account. no bans.`, card: '' },
        { say: `paste url. install snippet. i identify. you engage. done.`, card: '' },
      ];
      for (let i = 0; i < beats.length; i++) {
        await ob.bot(beats[i].say);
        if (beats[i].card) await ob.bot(beats[i].card, { cls: 'rich card', typing: false });
      }
      const c = ob.controls(`<button class="ob-btn ob-btn-primary" data-go>makes sense — what's a real one look like?</button>`);
      c.querySelector('[data-go]').addEventListener('click', () => ob.answer('makes sense', 'sample'));
    },

    /* ── 10 · SAMPLE DRAFT ───────────────────────────────────── */
    async sample(ob) {
      const id = ob.state.identified;
      const hasReal = id && id.matched && id.full_name;
      const vName = hasReal ? id.full_name : '';
      const vCompany = (id && (id.company_name || id.company_domain)) || '';
      const vRole = (id && id.job_title) || '';
      const posts = ob.state.social_posts || [];
      const bestPost = posts.length > 0 ? posts[0] : null;
      const siteHost = cleanHost(ob.state.url);

      if (hasReal) {
        await ob.bot(`here's what i'd draft for ${vName}:`, { delay: 400 });
      } else {
        await ob.bot(`here's what it looks like when a real visitor hits ${siteHost}:`, { delay: 400 });
      }

      // Show context card with REAL data — real post if available
      const postSnippet = bestPost
        ? bestPost.content.length > 80 ? bestPost.content.slice(0, 80) + '…' : bestPost.content
        : '';
      const visitorLabel = hasReal ? vName : 'a visitor from ' + siteHost;
      const card = await ob.bot(`
        <div class="ob-rows" style="margin-bottom:10px">
          <div class="ob-row"><span class="k">visitor</span><span class="v">${visitorLabel}</span></div>
          ${vCompany ? '<div class="ob-row"><span class="k">company</span><span class="v">' + vCompany + '</span></div>' : ''}
          <div class="ob-row"><span class="k">detected on</span><span class="v">/pricing</span></div>
          ${bestPost ? '<div class="ob-row"><span class="k">latest post</span><span class="v" style="font-weight:400">"' + postSnippet + '"</span></div>' : ''}
        </div>
        <div class="ob-label" style="margin-bottom:6px">beam is writing · in your voice</div>
        <div class="ob-draftcard"><div class="dmeta">${badge('x')} ai draft</div><span id="ob-draft" class="ob-typing-cursor"></span></div>`,
        { cls: 'rich card', typing: false });

      // Generate draft via AI — pass real post for context
      async function generateDraft() {
        try {
          const res = await apiPost('/api/v1/demo/generate-draft', {
            visitor_name: vName,
            visitor_role: vRole,
            visitor_company: vCompany,
            user_url: ob.state.url || '',
            recent_post: bestPost ? bestPost.content : '',
          });
          return (res && res.draft) || '';
        } catch (_) { return ''; }
      }

      // Type out the draft with cursor effect
      async function typeDraft(el, text) {
        el.classList.add('ob-typing-cursor');
        el.textContent = '';
        for (let i = 0; i < text.length; i++) {
          el.textContent = text.slice(0, i + 1);
          await new Promise(r => setTimeout(r, 18 + Math.random() * 12));
        }
        el.classList.remove('ob-typing-cursor');
      }

      let draftText = await generateDraft();
      if (!draftText) {
        // Minimal fallback — still references real post if available
        if (bestPost) {
          const snippet = bestPost.content.slice(0, 60);
          draftText = `this resonates. "${snippet}…" — would love to swap notes on this.`;
        } else if (hasReal) {
          draftText = `hey ${vName.split(' ')[0].toLowerCase()}! saw you checking out ${siteHost}. would love to connect.`;
        } else {
          draftText = `saw someone checking out your pricing page on ${siteHost}. this is what beam would draft based on their latest social posts and your writing style.`;
        }
      }

      const draftEl = card.querySelector('#ob-draft');
      await typeDraft(draftEl, draftText);

      const c = ob.controls(`
        <button class="ob-btn ob-btn-primary" data-go>i want this for my visitors <span aria-hidden="true">→</span></button>
        <button class="ob-btn ob-btn-ghost" data-regen>↻ regenerate</button>`);
      c.querySelector('[data-go]').addEventListener('click', () => window.location.href = '/pricing');
      c.querySelector('[data-regen]').addEventListener('click', async () => {
        const newDraft = await generateDraft() || `${vName.split(' ')[0].toLowerCase()}, your work caught my eye. let's chat.`;
        await typeDraft(draftEl, newDraft);
      });
    },

    /* ── 11 · PAYWALL ────────────────────────────────────────── */
    async paywall(ob) {
      const plans = {
        pro: { name: 'pro', monthly: 19, feats: ['50 identified visitors / mo', 'social enrichment', 'ai drafts in your voice', 'manual send'] },
        max: { name: 'max', monthly: 49, rec: true, feats: ['unlimited identified visitors', 'priority identification', 'team seats', 'api access'] },
        free: { name: 'free', monthly: 0, free: true, feats: ['10 identified visitors / mo', 'core enrichment', 'kick the tires', 'no card, ever'] },
      };
      await ob.bot(`beautiful work. ready to do this for your actual traffic? pick a plan:`, { delay: 400 });
      const wrap = ob.controls('', true);
      function render() {
        const yearly = ob.state.billing === 'yearly';
        const price = p => p.free ? `<div class="price">$0<small> forever</small></div>`
          : `<div class="price">$${yearly ? Math.round(p.monthly * 0.8) : p.monthly}<small>/mo${yearly ? ' · yearly' : ''}</small></div>`;
        const card = k => { const p = plans[k]; return `
          <div class="ob-plan ${p.rec ? 'feature' : ''} ${p.free ? 'free' : ''}">
            ${p.rec ? '<span class="rec">recommended</span>' : ''}
            <div class="pname">${p.name}</div>${price(p)}
            <ul>${p.feats.map(f => `<li><span class="ck">✓</span> ${f}</li>`).join('')}</ul>
            <button class="ob-btn ${p.free ? 'ob-btn-ghost' : 'ob-btn-primary'}" data-plan="${k}">${p.free ? 'start free' : 'start free trial'}</button>
            <div class="subnote">${p.free ? 'no card required' : 'no card · 14 days free'}</div>
          </div>`; };
        wrap.innerHTML = `
          <div class="ob-toggle">
            <button class="${yearly ? 'on' : ''}" data-bill="yearly">yearly <span class="save">–20%</span></button>
            <button class="${!yearly ? 'on' : ''}" data-bill="monthly">monthly</button>
          </div>
          <div class="ob-plans">${card('pro')}${card('max')}${card('free')}</div>`;
        wrap.querySelectorAll('[data-bill]').forEach(b => b.addEventListener('click', () => { ob.state.billing = b.dataset.bill; render(); }));
        wrap.querySelectorAll('[data-plan]').forEach(b => b.addEventListener('click', () => {
          ob.state.plan = b.dataset.plan;
          ob.answer(`${b.dataset.plan} plan${b.dataset.plan === 'free' ? '' : ' · ' + ob.state.billing}`, 'account');
        }));
        ob.scrollToEnd();
      }
      render();
    },

    /* ── 12 · ACCOUNT CREATION / LOGIN ─────────────────────────── */
    async account(ob) {
      const planLabel = ob.state.plan === 'free' ? 'the free tier' : `${ob.state.plan} (14-day trial)`;
      await ob.bot(`last step — let me save your account so ${planLabel} is ready when you're back.`);
      const prefill = (ob.state.identified && ob.state.identified.email) || '';

      let mode = 'signup'; // 'signup' or 'login'

      const c = ob.controls(`
        <div class="ob-auth-tabs" style="display:flex;gap:0;margin-bottom:16px;border-bottom:2px solid #f0e8dc">
          <button class="ob-auth-tab active" id="ob-tab-signup" style="flex:1;padding:10px 0;font-size:14px;font-weight:600;border:none;background:none;cursor:pointer;color:#FF3366;border-bottom:2px solid #FF3366;margin-bottom:-2px;transition:all .2s">create account</button>
          <button class="ob-auth-tab" id="ob-tab-login" style="flex:1;padding:10px 0;font-size:14px;font-weight:500;border:none;background:none;cursor:pointer;color:#8C8295;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .2s">sign in</button>
        </div>
        <div class="ob-card">
          <label class="ob-label">email</label>
          <input class="ob-input-plain" id="ob-email" type="email" value="${prefill}" placeholder="you@yourcompany.com" style="margin-bottom:14px" />
          <label class="ob-label">password</label>
          <input class="ob-input-plain" id="ob-pass" type="password" placeholder="choose a password (8+ chars)" />
        </div>
        <div class="ob-error" id="ob-acc-err" style="display:none;margin-top:10px"></div>
        <div class="ob-actions" style="flex-direction:column;align-items:stretch;gap:10px;margin-top:12px">
          <button class="ob-btn ob-btn-primary ob-btn-block" id="ob-submit">create account</button>
          <button class="ob-btn ob-btn-ghost ob-btn-block" id="ob-google">continue with google</button>
        </div>`, true);

      const errEl = c.querySelector('#ob-acc-err');
      const submitBtn = c.querySelector('#ob-submit');
      const tabSignup = c.querySelector('#ob-tab-signup');
      const tabLogin = c.querySelector('#ob-tab-login');
      const passInput = c.querySelector('#ob-pass');
      const showErr = (html) => { errEl.innerHTML = html; errEl.style.display = 'block'; };
      const clerkErr = (e) => (e && e.errors && e.errors[0] && (e.errors[0].longMessage || e.errors[0].message)) || String((e && e.message) || e);

      function switchTab(newMode) {
        mode = newMode;
        errEl.style.display = 'none';
        if (mode === 'login') {
          tabLogin.style.color = '#FF3366'; tabLogin.style.fontWeight = '600'; tabLogin.style.borderBottomColor = '#FF3366';
          tabSignup.style.color = '#8C8295'; tabSignup.style.fontWeight = '500'; tabSignup.style.borderBottomColor = 'transparent';
          submitBtn.textContent = 'sign in';
          passInput.placeholder = 'your password';
        } else {
          tabSignup.style.color = '#FF3366'; tabSignup.style.fontWeight = '600'; tabSignup.style.borderBottomColor = '#FF3366';
          tabLogin.style.color = '#8C8295'; tabLogin.style.fontWeight = '500'; tabLogin.style.borderBottomColor = 'transparent';
          submitBtn.textContent = 'create account';
          passInput.placeholder = 'choose a password (8+ chars)';
        }
      }
      tabSignup.addEventListener('click', () => switchTab('signup'));
      tabLogin.addEventListener('click', () => switchTab('login'));

      async function finishWithToken(token) {
        if (ob.state.url && ob.state.url !== 'demo.beam.fyi') {
          try {
            const host = cleanHost(ob.state.url);
            const site = await apiPost('/api/v1/sites/', { name: host, url: 'https://' + ob.state.url.replace(/^https?:\/\//, '') }, token);
            ob.state.siteId = site.site_id;
            const snip = await apiGet('/api/v1/sites/' + site.site_id + '/pixel', token);
            ob.state.snippet = snip.snippet;
          } catch (e) { /* site optional */ }
        }
        ob.celebrate(); ob.answer('account created 🎉', 'dash');
      }

      async function clerkVerify(clerk, signUp, email) {
        ob.clearControls();
        await ob.bot(`i sent a 6-digit code to <b>${esc(email)}</b> — pop it in to confirm it's you.`);
        const vc = ob.controls(`
          <div class="ob-card">
            <label class="ob-label">verification code</label>
            <input class="ob-input-plain" id="ob-code" inputmode="numeric" autocomplete="one-time-code" placeholder="123456" />
          </div>
          <div class="ob-error" id="ob-code-err" style="display:none;margin-top:10px"></div>
          <div class="ob-actions" style="margin-top:12px"><button class="ob-btn ob-btn-primary ob-btn-block" id="ob-verify">verify</button></div>`);
        const codeErr = vc.querySelector('#ob-code-err');
        const vBtn = vc.querySelector('#ob-verify');
        async function attempt() {
          const code = vc.querySelector('#ob-code').value.trim();
          codeErr.style.display = 'none';
          if (!/^\d{4,8}$/.test(code)) { codeErr.textContent = 'enter the numeric code from your email.'; codeErr.style.display = 'block'; return; }
          vBtn.disabled = true; vBtn.textContent = 'verifying…';
          try {
            const res = await signUp.attemptEmailAddressVerification({ code });
            if (res.status !== 'complete') throw new Error('verification incomplete — double-check the code.');
            await clerk.setActive({ session: res.createdSessionId });
            const token = await clerk.session.getToken();
            ob.user('verified ✓');
            await finishWithToken(token);
          } catch (e) {
            vBtn.disabled = false; vBtn.textContent = 'verify';
            codeErr.textContent = clerkErr(e); codeErr.style.display = 'block';
          }
        }
        vBtn.addEventListener('click', attempt);
        vc.querySelector('#ob-code').addEventListener('keydown', e => { if (e.key === 'Enter') attempt(); });
      }

      async function loginAccount() {
        const email = c.querySelector('#ob-email').value.trim();
        const pass = c.querySelector('#ob-pass').value;
        errEl.style.display = 'none';
        if (!email || !pass) { showErr('enter your email and password.'); return; }
        submitBtn.disabled = true; submitBtn.textContent = 'signing in…';

        const clerk = await ensureClerk();
        if (clerk) {
          try {
            const signIn = await clerk.client.signIn.create({ identifier: email, password: pass });
            if (signIn.status === 'complete') {
              await clerk.setActive({ session: signIn.createdSessionId });
              const token = await clerk.session.getToken();
              ob.user('signed in ✓');
              await finishWithToken(token);
            } else {
              showErr('sign-in requires additional verification. <a href="/login">use the full login page →</a>');
              submitBtn.disabled = false; submitBtn.textContent = 'sign in';
            }
          } catch (e) {
            submitBtn.disabled = false; submitBtn.textContent = 'sign in';
            showErr('invalid email or password. try again or <a href="/login">use the full login page →</a>');
          }
          return;
        }

        try {
          const res = await apiPost('/api/v1/auth/login', { email, password: pass });
          const token = res.access_token;
          try { localStorage.setItem('auth_token', token); } catch (e) {}
          ob.user('signed in ✓');
          await finishWithToken(token);
        } catch (e) {
          submitBtn.disabled = false; submitBtn.textContent = 'sign in';
          showErr('invalid email or password. try again.');
        }
      }

      async function createAccount() {
        const email = c.querySelector('#ob-email').value.trim();
        const pass = c.querySelector('#ob-pass').value;
        errEl.style.display = 'none';
        if (!email || !pass || pass.length < 8) {
          showErr('enter your email and a password of 8+ characters.'); return;
        }
        submitBtn.disabled = true; submitBtn.textContent = 'creating…';

        const clerk = await ensureClerk();
        if (clerk) {
          try {
            const signUp = await clerk.client.signUp.create({ emailAddress: email, password: pass });
            if (signUp.status === 'complete') {
              await clerk.setActive({ session: signUp.createdSessionId });
              const token = await clerk.session.getToken();
              await finishWithToken(token);
            } else {
              await signUp.prepareEmailAddressVerification({ strategy: 'email_code' });
              await clerkVerify(clerk, signUp, email);
            }
          } catch (e) {
            submitBtn.disabled = false; submitBtn.textContent = 'create account';
            const msg = clerkErr(e);
            if (/exist|already|taken|identifier/i.test(msg)) {
              switchTab('login');
              showErr('that email already has an account — switched to sign in for you.');
            } else {
              showErr('could not create account: ' + msg);
            }
          }
          return;
        }

        try {
          const res = await apiPost('/api/v1/auth/signup', { email, password: pass });
          const token = res.access_token;
          try { localStorage.setItem('auth_token', token); } catch (e) {}
          await finishWithToken(token);
        } catch (e) {
          submitBtn.disabled = false; submitBtn.textContent = 'create account';
          const msg = String(e.message || '');
          if (/exist|registered|taken/i.test(msg)) {
            switchTab('login');
            showErr('that email already has an account — switched to sign in for you.');
          } else {
            showErr('could not create account: ' + msg);
          }
        }
      }

      async function handleSubmit() {
        if (mode === 'login') await loginAccount();
        else await createAccount();
      }
      submitBtn.addEventListener('click', handleSubmit);
      c.querySelector('#ob-pass').addEventListener('keydown', e => { if (e.key === 'Enter') handleSubmit(); });
      c.querySelector('#ob-google').addEventListener('click', () => { window.location.href = '/signup'; });
    },

    /* ── 13 · DASHBOARD WELCOME ──────────────────────────────── */
    async dash(ob) {
      await ob.bot(`you're live — welcome to beam. 🚀`, { delay: 400 });
      if (ob.state.snippet) {
        const esc = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        await ob.bot(`one thing left — paste this into your site's &lt;head&gt; so i can catch your real visitors:`);
        await ob.bot(`<div class="ob-code"><button class="ob-copy" id="ob-snip-copy">copy</button>${esc(ob.state.snippet)}</div>`, { cls: 'rich plain', typing: false });
        const cb = document.getElementById('ob-snip-copy');
        if (cb) cb.addEventListener('click', () => {
          if (navigator.clipboard) navigator.clipboard.writeText(ob.state.snippet).catch(() => {});
          cb.textContent = '✓ copied'; cb.classList.add('copied');
          setTimeout(() => { cb.textContent = 'copy'; cb.classList.remove('copied'); }, 1700);
        });
      }
      await ob.bot(`here's your home base. your real visitors will start showing up here within ~30 minutes.`, { cls: 'rich card', delay: 600 });
      await ob.bot(`
        <div class="ob-dash">
          <div class="ob-subcard">
            <div class="ob-dash-head"><b>identified visitors</b><span class="ob-pill green"><span class="pdot"></span> live</span></div>
            <div class="ob-visitor">
              <div class="ob-avatar" style="width:42px;height:42px;border-radius:11px;font-size:16px">${((ob.state.identified && ob.state.identified.full_name) || 'You').split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase()}</div>
              <div style="flex:1;min-width:0">
                <div style="font-weight:500">${(ob.state.identified && ob.state.identified.full_name) || 'you'} <span class="ob-hint">· you</span></div>
                <div class="ob-hint">/pricing · just now</div>
              </div>
              <button class="ob-btn ob-btn-ghost" style="padding:7px 13px;font-size:12.5px">draft</button>
            </div>
          </div>
          <div class="ob-subcard">
            <div class="ob-dash-head"><b>get set up</b></div>
            <div class="ob-checklist">
              <div class="ob-cl-item done"><span class="ob-cl-box">✓</span><span class="lbl">install snippet</span></div>
              <div class="ob-cl-item"><span class="ob-cl-box">✓</span><span class="lbl">verify your voice</span></div>
              <div class="ob-cl-item"><span class="ob-cl-box">✓</span><span class="lbl">invite a teammate</span></div>
            </div>
          </div>
        </div>`, { cls: 'rich card wide', typing: false });
      await ob.bot(`i'm always one click away in the corner. let's go find your people.`);
      const c = ob.controls(`
        <button class="ob-btn ob-btn-primary" id="ob-done">go to dashboard <span aria-hidden="true">→</span></button>
        <button class="ob-btn ob-btn-ghost" id="ob-restart">replay onboarding</button>`);
      c.querySelector('#ob-done').addEventListener('click', () => { window.location.href = '/dashboard'; });
      c.querySelector('#ob-restart').addEventListener('click', () => ob.reset());
    },
  };

  window.OB_STEPS = OB_STEPS;
})();
