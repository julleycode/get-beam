(function() {
  "use strict";

  if (navigator.webdriver === true) return;
  var script = document.currentScript;
  if (!script) return;

  var SITE_ID = script.getAttribute("data-site");
  if (!SITE_ID) {
    try { SITE_ID = new URL(script.src).searchParams.get("site"); } catch(e) {}
  }
  if (!SITE_ID) return;

  var API_URL = script.getAttribute("data-api");
  if (!API_URL) {
    try { API_URL = new URL(script.src).origin; } catch(e) { API_URL = "http://localhost:8000"; }
  }
  var ENDPOINT = API_URL + "/api/v1/events/ingest";
  var BATCH_INTERVAL = 5000;
  var COOKIE_NAME = "_rta_vid";
  var COOKIE_DAYS = 365;

  function uuid() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function(c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function getCookie(name) {
    var match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? match[2] : null;
  }

  function setCookie(name, value, days) {
    var d = new Date();
    d.setTime(d.getTime() + days * 86400000);
    document.cookie = name + "=" + value + ";path=/;expires=" + d.toUTCString() + ";SameSite=Lax";
  }

  function delCookie(name) {
    document.cookie = name + "=;path=/;expires=Thu, 01 Jan 1970 00:00:00 GMT;SameSite=Lax";
  }

  function lsGet(k) { try { return localStorage.getItem(k); } catch(e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch(e) {} }
  function lsDel(k) { try { localStorage.removeItem(k); } catch(e) {} }

  function getVisitorId() {
    var vid = getCookie(COOKIE_NAME) || lsGet(COOKIE_NAME);
    if (!vid) {
      vid = uuid();
    }
    setCookie(COOKIE_NAME, vid, COOKIE_DAYS);
    lsSet(COOKIE_NAME, vid);
    return vid;
  }

  function getUTM() {
    var params = new URLSearchParams(window.location.search);
    var utm = {};
    var keys = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];
    var found = false;
    for (var i = 0; i < keys.length; i++) {
      var val = params.get(keys[i]);
      if (val) {
        utm[keys[i].replace("utm_", "")] = val;
        found = true;
      }
    }
    return found ? utm : null;
  }

  function getDevice() {
    var w = window.innerWidth;
    if (w < 768) return "mobile";
    if (w < 1024) return "tablet";
    return "desktop";
  }

  function now() {
    return new Date().toISOString();
  }

  // --- Fingerprint (v2: 17 signals, 128-bit hash) ---

  function hash128(str) {
    var h = [0x811c9dc5, 0xc6a4a793, 0x6c62272e, 0x61c88647];
    var p = [0x01000193, 0x0100019b, 0x01000199, 0x01000187];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      for (var j = 0; j < 4; j++) h[j] = Math.imul(h[j] ^ c, p[j]) >>> 0;
    }
    return h[0].toString(36) + h[1].toString(36) + h[2].toString(36) + h[3].toString(36);
  }

  function canvasFp() {
    try {
      var cv = document.createElement("canvas");
      cv.width = 200; cv.height = 50;
      var ctx = cv.getContext("2d");
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
    } catch(e) { return ""; }
  }

  function webglFp() {
    try {
      var cv = document.createElement("canvas");
      var gl = cv.getContext("webgl") || cv.getContext("experimental-webgl");
      if (!gl) return "";
      var ext = gl.getExtension("WEBGL_debug_renderer_info");
      var v = ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : "";
      var r = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "";
      return v + "~" + r + "~" + gl.getParameter(gl.MAX_TEXTURE_SIZE);
    } catch(e) { return ""; }
  }

  function getFingerprint() {
    var c = [];
    c.push(screen.width + "x" + screen.height);
    c.push(screen.availWidth + "x" + screen.availHeight);
    c.push(screen.colorDepth);
    c.push(window.devicePixelRatio || 1);
    c.push(navigator.language);
    c.push(navigator.platform);
    c.push(navigator.hardwareConcurrency || 0);
    c.push(navigator.deviceMemory || 0);
    c.push(navigator.maxTouchPoints || 0);
    c.push(navigator.cookieEnabled ? 1 : 0);
    c.push(navigator.doNotTrack || "");
    c.push(navigator.pdfViewerEnabled ? 1 : 0);
    try { c.push(Intl.DateTimeFormat().resolvedOptions().timeZone); } catch(e) { c.push(""); }
    try { c.push(navigator.connection ? navigator.connection.effectiveType : ""); } catch(e) { c.push(""); }
    c.push(canvasFp());
    c.push(webglFp());
    c.push(Math.tan(-1e300));
    return "fp2_" + hash128(c.join("|"));
  }

  var visitorId = getVisitorId();
  // Phantom-visitor guard: in an embedded subframe with unwritable storage
  // (third-party cookies blocked + partitioned/blocked localStorage) every
  // tracker instance mints a fresh visitor_id and usually delivers only its
  // pagehide beacon — creating zero-pageview ghost visitors. No durable id is
  // possible there, so do not track at all. Top-level pages keep tracking
  // even with storage blocked: their pageviews are real.
  var inSubframe = false;
  try { inSubframe = window.self !== window.top; } catch (e) { inSubframe = true; }
  if (inSubframe && !getCookie(COOKIE_NAME) && !lsGet(COOKIE_NAME)) return;
  var fingerprint = getFingerprint();
  var QUEUE_KEY = "_rta_q";
  var queue = [];

  // Honor GPC (CCPA opt-out) + DNT → server marks visitor do_not_resolve.
  var OPTOUT = (function(){try{if(navigator.globalPrivacyControl===true)return true;var d=navigator.doNotTrack||window.doNotTrack||navigator.msDoNotTrack;return d==="1"||d==="yes"||d===true;}catch(e){return false;}})();

  try {
    var saved = lsGet(QUEUE_KEY);
    if (saved) { queue = JSON.parse(saved); lsDel(QUEUE_KEY); }
  } catch(e) { queue = []; }

  function pushEvent(evt) {
    if (DEAD) return; // site deleted — stop collecting
    evt._fp = fingerprint;
    evt.optout = OPTOUT;
    // Idempotency key — server drops duplicate event_ids (retry/replay safe).
    evt.event_id = uuid();
    queue.push(evt);
    lsSet(QUEUE_KEY, JSON.stringify(queue));
  }

  // Drop the first n events only after the transport confirmed them.
  function confirmSent(n) {
    queue = queue.slice(n);
    if (queue.length === 0) lsDel(QUEUE_KEY);
    else lsSet(QUEUE_KEY, JSON.stringify(queue));
  }

  var xhrInFlight = false;
  // Site-deleted self-destruct. The ingest endpoint returns 403 (site gone) /
  // 410 for a deleted site; when the readable XHR flush sees that, we wipe every
  // cookie/localStorage key this pixel owns and stop tracking. (A PAUSED site
  // returns 204, so it never trips this.) flushTimer is cleared so the interval
  // stops; DEAD short-circuits pushEvent/flush against any late listeners.
  var DEAD = false;
  var flushTimer = null;
  var firstFlush = true; // first flush goes via readable XHR to catch 403/410

  function selfDestruct() {
    DEAD = true;
    try { delCookie(COOKIE_NAME); delCookie(CONSENT_KEY); } catch (e) {}
    lsDel(COOKIE_NAME);
    lsDel(QUEUE_KEY);
    lsDel(CONSENT_KEY);
    queue = [];
    if (flushTimer) { clearInterval(flushTimer); flushTimer = null; }
  }

  function flush(onUnload) {
    if (DEAD) return; // site deleted — stop sending
    if (consentBlocked()) return; // EU: hold events until visitor decides
    if (queue.length === 0) return;

    var batch = queue.slice(0);
    var payload = JSON.stringify({
      site_id: SITE_ID,
      visitor_id: visitorId,
      events: batch
    });

    // Prefer sendBeacon (survives unload) EXCEPT the first flush of the session,
    // which goes via readable XHR so a deleted-site 403/410 is visible and can
    // trigger selfDestruct(). On unload always beacon. sendBeacon returns true
    // once the browser accepts the payload; false (too large / too many beacons)
    // falls through to XHR.
    if ((onUnload || !firstFlush) && navigator.sendBeacon &&
        navigator.sendBeacon(ENDPOINT, new Blob([payload], { type: "text/plain" }))) {
      confirmSent(batch.length);
      return;
    }

    if (xhrInFlight) return; // one XHR at a time; retry on next interval
    xhrInFlight = true;
    var xhr = new XMLHttpRequest();
    xhr.open("POST", ENDPOINT, true);
    // Cross-origin Set-Cookie (_rta_svid HttpOnly) is ignored unless the XHR
    // opts into credentials AND the API echoes Origin + Allow-Credentials.
    // sendBeacon still used on unload; once the cookie is set, beacons include it.
    xhr.withCredentials = true;
    // text/plain is CORS-safelisted → no preflight (matches the beacon); the
    // server parses text/plain the same as JSON.
    xhr.setRequestHeader("Content-Type", "text/plain");
    xhr.onload = function() {
      xhrInFlight = false;
      firstFlush = false;
      // Site deleted → server answers 403 (gone) / 410. Wipe our cookies + stop.
      if (xhr.status === 403 || xhr.status === 410) { selfDestruct(); return; }
      if (xhr.status >= 200 && xhr.status < 300) confirmSent(batch.length);
      // other non-2xx: keep queue + localStorage and retry on the next interval
    };
    xhr.onerror = xhr.ontimeout = function() { xhrInFlight = false; };
    xhr.send(payload);
  }

  function trackPageview() {
    pushEvent({
      type: "pageview",
      url: window.location.href,
      page_path: window.location.pathname,
      page_title: document.title,
      referrer: document.referrer || null,
      utm: getUTM(),
      device: getDevice(),
      lang: navigator.language || null,
      user_agent: navigator.userAgent || null,
      ts: now()
    });
  }

  // _bid: arrived via a Beam-decorated link (?_bid=...) → link the encrypted
  // email to this visitor cookie.
  (function() {
    try {
      if (OPTOUT) return;
      var bidParam = new URLSearchParams(window.location.search).get("_bid");
      if (bidParam) {
        pushEvent({type: "utm_identify", bid: bidParam, url: window.location.href, ts: now()});
      }
    } catch(e) {}
  })();

  // Deterministic email capture: form submit, email-field blur/change (SPA
  // logins/checkouts that never submit a <form>), and window.beamIdentify().
  // Every path is OPTOUT-gated and deduped (same email sent at most once).
  var _sent = {};
  // Fields the visitor actively interacted with this session (input/change/blur).
  // The NEW value-based submit scan only reads a field's value if it's here — a
  // prefilled/hydrated field the visitor never touched is never scraped (G6/AC8).
  var _touched = (typeof WeakSet!=="undefined")?new WeakSet():null;
  function looksEmail(s){return typeof s==="string"&&s.length>=5&&/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s);}
  function captureEmail(raw, source){
    try{
      if(OPTOUT||typeof raw!=="string")return;
      var email=raw.trim().toLowerCase();
      if(!looksEmail(email)||_sent[email])return;
      _sent[email]=1;
      pushEvent({type:"form_email_capture",email:email,source:source||"form",url:window.location.href,ts:now()});
      flush();
    }catch(e){}
  }
  function emailSource(el){
    try{
      var f=el&&(el.form||(el.closest&&el.closest("form")));
      var h=(f?f.id+" "+f.className+" "+(f.getAttribute("action")||""):"").toLowerCase();
      if(/login|signin|sign-in|log-in/.test(h))return "login";
      if(/checkout|payment|billing|order/.test(h))return "checkout";
      if(/newsletter|subscribe|sign-?up/.test(h))return "newsletter";
    }catch(e){}
    return "input";
  }
  function isEmailField(el){
    if(!el||el.nodeName!=="INPUT")return false;
    var t=(el.type||"").toLowerCase();
    if(t==="hidden")return false; // G6/AC8: hidden values are never visitor-provided
    return t==="email"||/email/i.test((el.name||"")+" "+(el.id||""));
  }
  // Value-based matcher (SPEC AC1): a field whose *value* is a valid email but
  // whose name/id/type contains no "email" hint (e.g. name="username" on a login
  // form). Only text-shaped inputs the visitor can type into — type="hidden" and
  // non-text controls are structurally excluded (G6: never scrape a value the
  // visitor didn't provide). Additive to isEmailField, never a replacement.
  function isTextShapedField(el){
    if(!el||el.nodeName!=="INPUT")return false;
    var t=(el.type||"").toLowerCase();
    return t===""||t==="text"||t==="email"||t==="search";
  }
  // True originating element. For an open shadow-DOM widget, event.target is
  // retargeted to the shadow host; composedPath()[0] is the real inner field
  // (SPEC AC6). Only pierced when shadow capture is enabled (CAP_SHADOW); a
  // closed shadow root has an empty composedPath and falls back to e.target.
  function realTarget(e){try{if(CAP_SHADOW&&e.composedPath){var p=e.composedPath();if(p&&p.length)return p[0];}}catch(_){}return e.target;}
  function onSubmit(e){
    try{
      var f=realTarget(e);
      if(!f||f.nodeName!=="FORM")return;
      // Fast-path first: literal email-named/typed field (AC2). Excludes
      // type="hidden" — a hidden field's value is site-injected, never visitor-
      // provided (G6/AC8), even when its name contains "email".
      var i=f.querySelector("input[type='email']:not([type='hidden']), input[name*='email']:not([type='hidden']), input[name*='Email']:not([type='hidden'])");
      if(i&&i.value&&(i.type||"").toLowerCase()!=="hidden")captureEmail(i.value,emailSource(i));
      // Value-based fallback (AC1): any OTHER text-shaped field holding an email,
      // but ONLY if the visitor actually touched it this session (G6/AC8 — never
      // scrape a prefilled/hydrated field). Dedup prevents a double-capture of the
      // email-named field handled above.
      var all=f.querySelectorAll("input");
      for(var k=0;k<all.length;k++){
        var el=all[k];
        if(!isEmailField(el)&&isTextShapedField(el)&&_touched&&_touched.has(el)&&looksEmail(el.value))captureEmail(el.value,emailSource(el));
      }
    }catch(e){}
  }
  function onFieldDone(e){try{
    var el=realTarget(e);
    if(_touched&&el)_touched.add(el); // this event IS the interaction on el
    if(isEmailField(el)&&el.value){captureEmail(el.value,emailSource(el));return;}
    // Value-based (AC1): text-shaped field whose value looks like an email.
    if(isTextShapedField(el)&&looksEmail(el.value))captureEmail(el.value,emailSource(el));
  }catch(e){}}
  // Autofill (AC5) + open-shadow-DOM typing (AC6): the `input` event is
  // composed:true, so it both fires on browser autofill (where `change` is
  // unreliable across WebKit/Firefox — D2) and crosses open shadow boundaries.
  // G6 (no keystroke logging): ONLY a fully-formed email (looksEmail) is ever
  // captured — partial/interim keystrokes are a silent no-op, never logged or
  // queued, and dedup means a value already captured on submit/blur won't refire.
  function onInputMaybe(e){try{var el=realTarget(e);if(_touched&&el)_touched.add(el);if(isTextShapedField(el)&&el.value&&looksEmail(el.value))captureEmail(el.value,emailSource(el));}catch(e){}}
  // Attach the email-capture listener set to a document — the main document or a
  // same-origin iframe's contentDocument (AC7). All capture-phase (blur/submit
  // don't bubble).
  function attachCapture(doc){
    try{
      doc.addEventListener("submit",onSubmit,true);
      doc.addEventListener("blur",onFieldDone,true);
      doc.addEventListener("change",onFieldDone,true);
      doc.addEventListener("input",onInputMaybe,true);
    }catch(e){}
  }
  attachCapture(document);
  try{window.beamIdentify=function(email){captureEmail(email,"identify");};}catch(e){}

  // Conversion signal: site code calls window.beamConvert("purchase",{value:49.99})
  // on a success page/action. Goal must exist (by name) in the Beam dashboard.
  // Same consent path as everything else: pushEvent queues, flush() holds until
  // consent; OPTOUT drops it entirely.
  try{window.beamConvert=function(goal,opts){
    try{
      if(OPTOUT||typeof goal!=="string"||!goal)return;
      var v=opts&&typeof opts.value==="number"&&isFinite(opts.value)?opts.value:null;
      pushEvent({type:"conversion",goal:goal.slice(0,100),value:v,url:window.location.href,ts:now()});
      flush();
    }catch(e){}
  };}catch(e){}

  // --- Cookie consent (EU-gated, opt-in). data-consent: off|eu|all|cmp ---
  // "off" (default) = today's behavior. "eu" = banner + hold events only for
  // EU/EEA visitors (timezone heuristic); non-EU keep firing immediately +
  // GPC/DNT opt-out. "all" = banner for everyone. "cmp" = no Beam banner, the
  // site's own consent tool calls window.beamConsent(granted). A declined
  // visitor reuses the existing OPTOUT path → backend sets do_not_resolve.
  var CONSENT_MODE = script.getAttribute("data-consent") || "off";
  var CONSENT_KEY = "_rta_c";

  function isEU() {
    try {
      var tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      if (tz.indexOf("Europe/") === 0) return true;
      return /^(Atlantic\/(Canary|Azores|Madeira|Faroe|Reykjavik)|Asia\/(Nicosia|Famagusta))$/.test(tz);
    } catch (e) { return false; }
  }

  var GATED = CONSENT_MODE === "all" || CONSENT_MODE === "cmp" ||
              (CONSENT_MODE === "eu" && isEU());
  var consentDecision = GATED ? (getCookie(CONSENT_KEY) || lsGet(CONSENT_KEY)) : "g";
  if (GATED && consentDecision === "d") OPTOUT = true; // persisted decline

  // --- Per-site capture config (Phase 3, SPEC AC12) ---
  // The more consent-sensitive mechanisms (mailto, URL-param) are opt-OUT-able
  // per site. DEFAULT is "on" for every flag so current installs keep their
  // always-on behavior unchanged (opt-out, not opt-in). Value-based matching,
  // autofill, and shadow-DOM are lower-sensitivity and stay non-configurable.
  function capOn(attr){ return script.getAttribute(attr) !== "off"; }
  var CAP_MAILTO = capOn("data-capture-mailto");
  var CAP_URLPARAM = capOn("data-capture-url-param");
  var CAP_SHADOW = capOn("data-capture-shadow-dom");
  var URLPARAM_NAME = script.getAttribute("data-capture-url-param-name") || "email";

  // URL-param email capture (SPEC AC3/AC4). Placed AFTER GATED/consentDecision
  // are assigned (Hard Guardrail G7): captureEmail() calls flush() synchronously,
  // and flush()'s consentBlocked() guard reads GATED/consentDecision — running
  // this before they're set would bypass the EU consent-hold on GATED sites.
  // Per Decision D1, no client-side crypto: the raw value is read once and handed
  // straight to captureEmail() (server dual-writes ciphertext + logs domain only);
  // never console.log'd, never written to storage, never re-echoed to the URL.
  (function(){
    try{
      if(OPTOUT||!CAP_URLPARAM)return;
      var pv=new URLSearchParams(window.location.search).get(URLPARAM_NAME);
      if(pv&&looksEmail(pv))captureEmail(pv,"url_param");
    }catch(e){}
  })();

  // Same-origin iframe capture (SPEC AC6/AC7). Attach the same capture listeners
  // to any iframe whose contentDocument is reachable. A CROSS-origin iframe throws
  // SecurityError on contentDocument access — caught + no-op'd; that catch IS the
  // same-origin boundary enforcement (AC7: cross-origin content stays silent), not
  // a workaround. Re-scans on each iframe `load` for late/replaced frames.
  function scanIframes(){
    try{
      var frames=document.querySelectorAll("iframe");
      for(var i=0;i<frames.length;i++){
        (function(fr){
          function tryAttach(){try{var d=fr.contentDocument;if(d)attachCapture(d);}catch(e){}}
          tryAttach();
          try{fr.addEventListener("load",tryAttach);}catch(e){}
        })(frames[i]);
      }
    }catch(e){}
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",scanIframes);
  else scanIframes();
  try{window.addEventListener("load",scanIframes);}catch(e){}

  // Referenced by flush() (hoisted). Blocks sending while a gated visitor has
  // not decided yet — the pageview still queues in _rta_q, just isn't flushed.
  function consentBlocked() { return GATED && consentDecision == null; }

  function decideConsent(v) {
    setCookie(CONSENT_KEY, v, COOKIE_DAYS);
    lsSet(CONSENT_KEY, v);
    consentDecision = v;
    if (v === "g") { flush(); }           // accept → send everything queued
    else { OPTOUT = true; lsDel(QUEUE_KEY); queue = []; } // decline → drop, send nothing
  }

  // CMP hook (mirrors window.beamIdentify): customer's consent tool calls this.
  try {
    window.beamConsent = function(granted) {
      if (consentDecision != null) return;
      decideConsent(granted ? "g" : "d");
      var el = document.getElementById("_rtaC");
      if (el && el.parentNode) el.parentNode.removeChild(el);
    };
  } catch (e) {}

  function showConsentBanner() {
    if (CONSENT_MODE === "cmp" || !consentBlocked()) return;
    if (document.getElementById("_rtaC")) return;
    var host = document.body || document.documentElement;
    if (!host) return;
    var b = document.createElement("div");
    b.id = "_rtaC";
    b.setAttribute("role", "dialog");
    b.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:#111;color:#fff;font:14px/1.4 system-ui,sans-serif;padding:14px 16px;display:flex;gap:12px;align-items:center;justify-content:center;flex-wrap:wrap;box-shadow:0 -1px 8px rgba(0,0,0,.3)";
    var pol = script.getAttribute("data-consent-policy");
    b.innerHTML = '<span style="max-width:640px">We use cookies to understand site traffic.' +
      (pol ? ' <a href="' + pol + '" style="color:#8ab4ff">Learn more</a>.' : '') + '</span>';
    function mk(t, bg) {
      var e = document.createElement("button");
      e.textContent = t;
      e.style.cssText = "border:0;border-radius:6px;padding:8px 16px;cursor:pointer;font:inherit;font-weight:600;background:" + bg + ";color:" + (bg === "#fff" ? "#111" : "#fff");
      return e;
    }
    var no = mk("Decline", "#333"), yes = mk("Accept", "#fff");
    yes.onclick = function() { decideConsent("g"); if (b.parentNode) b.parentNode.removeChild(b); };
    no.onclick = function() { decideConsent("d"); if (b.parentNode) b.parentNode.removeChild(b); };
    b.appendChild(no);
    b.appendChild(yes);
    host.appendChild(b);
  }

  if (consentBlocked()) showConsentBanner();

  trackPageview();

  // --- Engagement signals: scroll depth, time on page, clicks ---
  // Feed intent scoring (scroll>=75, time>60s); without these those stay 0.

  var pageStart = Date.now();
  var maxDepth = 0;
  var clickCount = 0;

  function scrollDepth() {
    try {
      var doc = document.documentElement;
      var total = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0);
      if (!total) return 0;
      var seen = (window.pageYOffset || doc.scrollTop || 0) + window.innerHeight;
      var pct = Math.round((seen / total) * 100);
      return pct > 100 ? 100 : pct;
    } catch (e) { return 0; }
  }

  window.addEventListener("scroll", function() {
    var d = scrollDepth();
    if (d > maxDepth) maxDepth = d;
  }, { passive: true });

  document.addEventListener("click", function(e) {
    try {
      if (clickCount >= 25) return; // bound payload per page
      var el = e.target && e.target.closest ? e.target.closest("a,button") : null;
      if (!el) return;
      // mailto: click capture (SPEC AC3). The visitor initiated this click, so
      // it's a real interaction — reuse the same captureEmail() funnel (OPTOUT +
      // dedup + validate). Address is the part before any "?" query suffix.
      if (CAP_MAILTO && el.href && el.href.indexOf("mailto:") === 0) {
        var addr = el.href.slice(7).split("?")[0];
        try { addr = decodeURIComponent(addr); } catch (e2) {}
        if (looksEmail(addr)) captureEmail(addr, "mailto_click");
      }
      clickCount++;
      pushEvent({
        type: "click",
        element_text: (el.textContent || "").trim().slice(0, 80),
        element_href: el.href || "",
        url: window.location.href,
        ts: now()
      });
    } catch (err) {}
  }, true);

  // Emit accumulated scroll + time for the page being left (SPA nav / hide /
  // unload). Counters reset after emit → additive chunks, no double-count.
  function emitPageSignals(url) {
    var secs = Math.round((Date.now() - pageStart) / 1000);
    if (secs > 0) {
      pushEvent({ type: "time_on_page", seconds: secs > 7200 ? 7200 : secs, url: url, ts: now() });
    }
    var d = scrollDepth();
    if (d > maxDepth) maxDepth = d;
    if (maxDepth > 0) {
      pushEvent({ type: "scroll", depth: maxDepth, url: url, ts: now() });
    }
    pageStart = Date.now();
    maxDepth = 0;
    clickCount = 0;
  }

  var lastUrl = window.location.href;

  function onNavigation() {
    var currentUrl = window.location.href;
    if (currentUrl !== lastUrl) {
      emitPageSignals(lastUrl); // close out the page we're leaving
      lastUrl = currentUrl;
      trackPageview();
    }
  }

  var origPushState = history.pushState;
  if (origPushState) {
    history.pushState = function() {
      origPushState.apply(this, arguments);
      onNavigation();
    };
  }

  var origReplaceState = history.replaceState;
  if (origReplaceState) {
    history.replaceState = function() {
      origReplaceState.apply(this, arguments);
      onNavigation();
    };
  }

  window.addEventListener("popstate", onNavigation);

  flushTimer = setInterval(function () { flush(false); }, BATCH_INTERVAL);

  function leavePage() {
    emitPageSignals(window.location.href);
    flush(true); // unload → beacon (survives), never the readable XHR path
  }

  window.addEventListener("beforeunload", leavePage);
  window.addEventListener("pagehide", leavePage);
  document.addEventListener("visibilitychange", function() {
    if (document.visibilityState === "hidden") leavePage();
  });

  // --- Identity-vendor pixel stacking (STRICTLY OPT-IN, default OFF) ---
  // Loads a vendor identity script only when data-stack="1" AND its id is given
  // via data-stack-<vendor> (e.g. data-stack-leadpipe). No vendor id ships here.
  if (script.getAttribute("data-stack") === "1") {
    var vendorUrls = {
      "leadpipe": function(d) { return "https://leadpipe.aws53.cloud/p/" + d + ".js"; },
      "capturify": function(d) { return "https://app.capturify.io/pixel/" + d + ".js"; },
      "fullcontact": function(d) { return "https://app.fullcontact.com/tag/" + d + ".js"; },
      "customers-ai": function(d) { return "https://app.customers.ai/pixel/" + d + "/xray.js"; }
    };
    for (var vk in vendorUrls) {
      var vendorId = script.getAttribute("data-stack-" + vk);
      if (vendorId) {
        // Leadpipe only: hand the vendor SDK our visitor id so its webhook can
        // name the visitor instead of us guessing by IP + time. The SDK reads
        // this JSON block at init and spread-merges globalParams (no key
        // whitelist), so the id rides along on every event it sends. Whether
        // Leadpipe echoes it back on the webhook is unverified — if it does not,
        // the server-side match simply falls through to the email tier.
        // Written BEFORE the vendor script is appended: the SDK reads the config
        // during its own init, so a block added afterwards would be missed.
        if (vk === "leadpipe" && visitorId) {
          try {
            var cfg = document.createElement("script");
            cfg.type = "application/json";
            cfg.id = "pixelsdk-config-" + vendorId + "-config";
            cfg.text = JSON.stringify({ globalParams: { beam_visitor_id: visitorId } });
            document.head.appendChild(cfg);
          } catch (e) {}
        }
        var vs = document.createElement("script");
        vs.src = vendorUrls[vk](encodeURIComponent(vendorId));
        vs.async = true;
        document.head.appendChild(vs);
      }
    }
  }
})();
