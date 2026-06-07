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

  function getVisitorId() {
    var vid = getCookie(COOKIE_NAME);
    if (!vid) {
      vid = uuid();
      setCookie(COOKIE_NAME, vid, COOKIE_DAYS);
    }
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
  var queue = [];

  // --- Event Queueing ---

  function pushEvent(evt) {
    evt._fp = fingerprint;
    queue.push(evt);
  }

  function flush() {
    if (queue.length === 0) return;

    var payload = JSON.stringify({
      site_id: SITE_ID,
      visitor_id: visitorId,
      events: queue.splice(0)
    });

    if (navigator.sendBeacon) {
      // Use text/plain to avoid CORS preflight (sendBeacon can't handle preflight)
      navigator.sendBeacon(ENDPOINT, new Blob([payload], { type: "text/plain" }));
    } else {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", ENDPOINT, true);
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.send(payload);
    }
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

  // --- Form email capture ---
  // Listen for any form submission on the page. If the form contains an email
  // field, send a form_email_capture event so the backend can link the email
  // to this visitor cookie for future identification.
  document.addEventListener("submit", function(e) {
    try {
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

  // --- SPA Navigation Tracking ---

  var lastUrl = window.location.href;

  function onNavigation() {
    var currentUrl = window.location.href;
    if (currentUrl !== lastUrl) {
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

  window.addEventListener("beforeunload", flush);
  window.addEventListener("pagehide", flush);

  // --- Identity graph pixel stacking ---
  var _DP=[{t:"leadpipe",id:"95247db8-8d49-4213-8ea7-ee0a6dd0ae78"}];
  var _PU={leadpipe:function(d){return"https://leadpipe.aws53.cloud/p/"+d+".js"},capturify:function(d){return"https://app.capturify.io/pixel/"+d+".js"},fullcontact:function(d){return"https://app.fullcontact.com/tag/"+d+".js"},customers_ai:function(d){return"https://app.customers.ai/pixel/"+d+"/xray.js"}};
  var _pa=script.getAttribute("data-identity-providers"),_lp=script.getAttribute("data-lp"),_pv=_DP;
  if(_pa){try{_pv=JSON.parse(_pa)}catch(e){}}
  if(_lp&&!_pa){_pv=_pv.concat([{t:"leadpipe",id:_lp}])}
  for(var _i=0;_i<_pv.length;_i++){var _p=_pv[_i],_fn=_PU[_p.t||_p.type];if(_fn&&(_p.id)){var _s=document.createElement("script");_s.src=_fn(_p.id);_s.async=true;document.head.appendChild(_s)}}
})();
