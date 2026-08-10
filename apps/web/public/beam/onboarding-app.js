/* ════════════════════════════════════════════════════════════════
   beam onboarding — chat engine
   A real back-and-forth conversation: the mascot types on the left,
   the user's replies land on the right. Rich UI (cards, inputs,
   paywall) appears inline as bot messages. Step content lives in
   onboarding-steps.js (window.OB_STEPS) as async sequences.
   ════════════════════════════════════════════════════════════════ */
(function () {
  // Five steps, not thirteen. Everything past the canary now lives behind auth
  // in the React dashboard onboarding, and account creation is Clerk's hosted
  // /sign-up — see the header comment in onboarding-steps.js.
  const STEP_ORDER = ['welcome', 'canary_go', 'canary_listen', 'canary_reveal', 'account'];

  const state = { fp: '', canary: null, landed: false };

  const spark =
    `<svg viewBox="0 0 100 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs><linearGradient id="obSparkGrad" x1="0" y1="0" x2="1" y2="0.35">
        <stop offset="0" stop-color="#FF6B9D"/><stop offset="0.55" stop-color="#FF3366"/><stop offset="1" stop-color="#FF7FA8"/>
      </linearGradient></defs>
      <path d="M26,15 Q26,32 90,32 Q26,32 26,49 Q26,32 9,32 Q26,32 26,15 Z" fill="url(#obSparkGrad)"/>
      <circle cx="26" cy="32" r="3.4" fill="#fff" opacity="0.92"/>
      <path d="M82,21 Q84,25 88,25 Q84,25 82,29 Q80,25 76,25 Q80,25 82,21 Z" fill="url(#obSparkGrad)" opacity="0.85"/>
    </svg>`;

  let chatEl, progressEl, scrollEl, currentStep = null, reduce = false;

  const wait = (ms) => new Promise(r => setTimeout(r, ms));

  function scrollToEnd() {
    if (!scrollEl) return;
    const pin = () => { scrollEl.scrollTop = scrollEl.scrollHeight; };
    pin();                               // immediate (layout is already settled)
    requestAnimationFrame(pin);          // after paint, for late-loading content
    setTimeout(pin, 70);                 // fallback if rAF is throttled (bg tab)
  }

  function avatar() {
    return `<div class="ob-av">${window.beamMascot()}</div>`;
  }

  // bot message: optional typing indicator, then bubble reveal
  async function bot(html, opts) {
    opts = opts || {};
    const row = document.createElement('div');
    row.className = 'ob-msg bot';
    row.innerHTML = `${avatar()}<div class="ob-bubble"></div>`;
    chatEl.appendChild(row);
    const bub = row.querySelector('.ob-bubble');

    if (!reduce && opts.typing !== false) {
      bub.classList.add('typing');
      bub.innerHTML = `<span class="dots"><span></span><span></span><span></span></span>`;
      scrollToEnd();
      const len = String(html).replace(/<[^>]+>/g, '').length;
      const t = opts.delay != null ? opts.delay : Math.min(1300, Math.max(480, len * 22));
      await wait(t);
    }
    bub.classList.remove('typing');
    bub.classList.add('reveal');
    if (opts.cls) bub.className += ' ' + opts.cls;
    bub.innerHTML = html;
    scrollToEnd();
    await wait(reduce ? 0 : 160);
    return bub;
  }

  // user reply: right-aligned bubble
  function user(html) {
    const row = document.createElement('div');
    row.className = 'ob-msg user';
    row.innerHTML = `<div class="ob-bubble reveal">${html}</div>`;
    chatEl.appendChild(row);
    scrollToEnd();
    return row;
  }

  // interactive block (inputs / cards / buttons) — appended under the conversation,
  // tagged so it can be cleared once the user acts
  function controls(html, wide) {
    clearControls();
    const row = document.createElement('div');
    row.className = 'ob-msg controls' + (wide ? ' wide' : '');
    row.id = 'ob-controls';
    row.innerHTML = `<div class="ob-actionwrap">${html}</div>`;
    chatEl.appendChild(row);
    scrollToEnd();
    return row.querySelector('.ob-actionwrap');
  }
  function clearControls() {
    const c = document.getElementById('ob-controls');
    if (c) c.remove();
  }

  // convenience: user picked something → echo + clear + advance
  function answer(text, nextId) {
    clearControls();
    if (text) user(text);
    if (nextId) go(nextId);
  }

  function renderProgress(id) {
    const idx = STEP_ORDER.indexOf(id);
    if (!progressEl) return;
    if (idx < 0) { progressEl.innerHTML = ''; return; }
    progressEl.innerHTML = STEP_ORDER.map((s, i) =>
      `<span class="ob-dot ${i < idx ? 'done' : ''} ${i === idx ? 'active' : ''}"></span>`
    ).join('');
  }

  function go(id) {
    const fn = window.OB_STEPS && window.OB_STEPS[id];
    if (!fn) { console.warn('no step', id); return; }
    currentStep = id;
    try { localStorage.setItem('beam_ob_step', id); } catch (e) {}
    renderProgress(id);
    Promise.resolve(fn(ob)).catch(e => console.error('step error', id, e));
  }

  function reset() {
    if (chatEl) chatEl.innerHTML = '';
    state.fp = ''; state.canary = null; state.landed = false;
    go('welcome');
  }

  function modal(html) {
    closeModal();
    const back = document.createElement('div');
    back.className = 'ob-modal-back'; back.id = 'ob-modal-back';
    back.innerHTML = `<div class="ob-modal">${html}</div>`;
    back.addEventListener('click', (e) => { if (e.target === back) closeModal(); });
    document.body.appendChild(back);
    return back;
  }
  function closeModal() { const m = document.getElementById('ob-modal-back'); if (m) m.remove(); }

  function celebrate() {
    if (reduce) return;
    const wrap = document.createElement('div');
    wrap.className = 'ob-celebrate';
    const colors = ['#FF3366', '#FF6B9D', '#FFD86B', '#3ECF8E', '#C9B6E4', '#FFF4E0'];
    for (let i = 0; i < 56; i++) {
      const c = document.createElement('div');
      c.className = 'ob-confetti';
      const size = 6 + Math.random() * 7;
      c.style.left = (Math.random() * 100) + '%';
      c.style.top = '-20px';
      c.style.width = size + 'px';
      c.style.height = size * (0.5 + Math.random()) + 'px';
      c.style.background = colors[i % colors.length];
      c.style.borderRadius = Math.random() > 0.5 ? '50%' : '1px';
      const dx = (Math.random() - 0.5) * 240, rot = (Math.random() - 0.5) * 720;
      c.animate([
        { transform: 'translate(0,0) rotate(0deg)', opacity: 1 },
        { transform: `translate(${dx}px, ${window.innerHeight + 80}px) rotate(${rot}deg)`, opacity: 1, offset: 0.9 },
        { transform: `translate(${dx}px, ${window.innerHeight + 120}px) rotate(${rot}deg)`, opacity: 0 },
      ], { duration: 1400 + Math.random() * 1400, easing: 'cubic-bezier(0.2,0.6,0.4,1)', delay: Math.random() * 250 });
      wrap.appendChild(c);
    }
    document.body.appendChild(wrap);
    setTimeout(() => wrap.remove(), 3200);
  }

  const ob = {
    state, spark, wait,
    bot, user, controls, clearControls, answer,
    go, reset, modal, closeModal, celebrate, scrollToEnd,
    STEP_ORDER,
  };
  window.ob = ob;

  function init() {
    reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    chatEl = document.getElementById('ob-chat');
    scrollEl = document.getElementById('ob-scroll');
    progressEl = document.getElementById('ob-progress');
    const logo = document.getElementById('ob-logo');
    if (logo) logo.innerHTML = spark + ' beam';
    go('welcome');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
