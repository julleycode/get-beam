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

  // --- State ---

  var visitorId = getVisitorId();
  var queue = [];

  // --- Event Queueing ---

  function pushEvent(evt) {
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
