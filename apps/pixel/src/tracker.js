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

  // --- Utilities ---

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

  // --- State ---

  var visitorId = getVisitorId();
  var fingerprint = getFingerprint();
  var QUEUE_KEY = "_rta_q";
  var queue = [];

  // Honor GPC (CCPA opt-out) + DNT → server marks visitor do_not_resolve.
  var OPTOUT = (function(){try{if(navigator.globalPrivacyControl===true)return true;var d=navigator.doNotTrack||window.doNotTrack||navigator.msDoNotTrack;return d==="1"||d==="yes"||d===true;}catch(e){return false;}})();

  // Recover unflushed events from previous page load
  try {
    var saved = lsGet(QUEUE_KEY);
    if (saved) { queue = JSON.parse(saved); lsDel(QUEUE_KEY); }
  } catch(e) { queue = []; }

  // --- Event Queueing ---

  function pushEvent(evt) {
    evt._fp = fingerprint;
    evt.optout = OPTOUT;
    // Idempotency key: the server drops duplicate event_ids, so a re-sent
    // batch (flush retry, beacon replay) can't double-count events.
    evt.event_id = uuid();
    queue.push(evt);
    lsSet(QUEUE_KEY, JSON.stringify(queue));
  }

  // Drop the first n queued events only AFTER the transport confirmed them.
  // Events queued while a send was in flight survive for the next flush.
  function confirmSent(n) {
    queue = queue.slice(n);
    if (queue.length === 0) lsDel(QUEUE_KEY);
    else lsSet(QUEUE_KEY, JSON.stringify(queue));
  }

  var xhrInFlight = false;

  function flush() {
    if (queue.length === 0) return;

    var batch = queue.slice(0);
    var payload = JSON.stringify({
      site_id: SITE_ID,
      visitor_id: visitorId,
      events: batch
    });

    // sendBeacon returns true only when the browser accepted the payload for
    // delivery — that's the strongest confirmation it offers, so clear then.
    // false (payload too large / too many in-flight beacons) falls through to
    // XHR. The old code cleared queue + localStorage BEFORE sending, which
    // silently and permanently lost events on any failure.
    if (navigator.sendBeacon &&
        navigator.sendBeacon(ENDPOINT, new Blob([payload], { type: "text/plain" }))) {
      confirmSent(batch.length);
      return;
    }

    if (xhrInFlight) return; // one XHR at a time; retry on next interval
    xhrInFlight = true;
    var xhr = new XMLHttpRequest();
    xhr.open("POST", ENDPOINT, true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onload = function() {
      xhrInFlight = false;
      if (xhr.status >= 200 && xhr.status < 300) confirmSent(batch.length);
      // non-2xx: keep queue + localStorage and retry on the next interval
    };
    xhr.onerror = xhr.ontimeout = function() { xhrInFlight = false; };
    xhr.send(payload);
  }

  // --- Pageview ---

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

  // --- UTM _bid identification ---
  // If this page was visited via a Beam-decorated link (?_bid=...), send an
  // utm_identify event so the backend can link the encrypted email to this
  // visitor cookie.
  (function() {
    try {
      var bidParam = new URLSearchParams(window.location.search).get("_bid");
      if (bidParam) {
        pushEvent({type: "utm_identify", bid: bidParam, url: window.location.href, ts: now()});
      }
    } catch(e) {}
  })();

  // Form email capture → links the email to this visitor cookie. Skipped on
  // GPC/DNT opt-out (visitor asked not to be tracked — never transmit the PII).
  document.addEventListener("submit", function(e) {
    try {
      if (OPTOUT) return;
      var form = e.target;
      if (!form || form.nodeName !== "FORM") return;
      var emailInput = form.querySelector(
        "input[type='email'], input[name*='email'], input[name*='Email']"
      );
      if (emailInput && emailInput.value) {
        pushEvent({
          type: "form_email_capture",
          email: emailInput.value,
          url: window.location.href,
          ts: now()
        });
        // Flush immediately so we don't lose the email if the page navigates
        flush();
      }
    } catch(e) {}
  }, true); // capture phase to run before potential SPA navigation

  // Track initial pageview
  trackPageview();

  // --- Engagement signals: scroll depth, time on page, clicks ---
  // Intent scoring awards points for scroll>=75 and time>60s; without these
  // emitters those columns stay 0 and single-session visitors can never
  // reach the identity-resolution threshold.

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

  // Emit accumulated scroll + time for the page being left (SPA nav, tab
  // hide, unload). Counters reset after emit, so repeated hide/show cycles
  // produce additive time chunks instead of double-counting.
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

  // --- SPA Navigation Tracking ---

  var lastUrl = window.location.href;

  function onNavigation() {
    var currentUrl = window.location.href;
    if (currentUrl !== lastUrl) {
      emitPageSignals(lastUrl); // close out the page we're leaving
      lastUrl = currentUrl;
      trackPageview();
    }
  }

  // Intercept History API for SPA frameworks
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

  // --- Flush on interval and unload ---

  setInterval(flush, BATCH_INTERVAL);

  function leavePage() {
    emitPageSignals(window.location.href);
    flush();
  }

  window.addEventListener("beforeunload", leavePage);
  window.addEventListener("pagehide", leavePage);
  document.addEventListener("visibilitychange", function() {
    if (document.visibilityState === "hidden") leavePage();
  });

  // --- Identity-vendor pixel stacking (STRICTLY OPT-IN, default OFF) ---
  // Loads a third-party identity script ONLY when the install snippet sets
  // data-stack="1" AND supplies that vendor's id via data-stack-<vendor>,
  // e.g. data-stack-leadpipe="<account-id>". Vendors without an id are
  // skipped. No vendor account id ships in this file.
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
        var vs = document.createElement("script");
        vs.src = vendorUrls[vk](encodeURIComponent(vendorId));
        vs.async = true;
        document.head.appendChild(vs);
      }
    }
  }
})();
