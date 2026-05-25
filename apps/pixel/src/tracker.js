(function() {
  "use strict";

  var script = document.currentScript;
  if (!script) return;

  // Support both data-site attribute and ?site= query param (for Shopify ScriptTag)
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
  var BATCH_INTERVAL = 10000;
  var TIME_PING_INTERVAL = 15000;
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
  var scrollThresholds = { 25: false, 50: false, 75: false, 100: false };
  var pageStartTime = Date.now();
  var isVisible = true;

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
      navigator.sendBeacon(ENDPOINT, new Blob([payload], { type: "application/json" }));
    } else {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", ENDPOINT, true);
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.send(payload);
    }
  }

  // --- Pageview ---

  pushEvent({
    type: "pageview",
    url: window.location.href,
    referrer: document.referrer || null,
    utm: getUTM(),
    viewport: { w: window.innerWidth, h: window.innerHeight },
    device: getDevice(),
    lang: navigator.language || null,
    ts: now()
  });

  // --- Scroll Tracking ---

  function getScrollPercent() {
    var docHeight = Math.max(
      document.body.scrollHeight,
      document.documentElement.scrollHeight
    );
    var winHeight = window.innerHeight;
    if (docHeight <= winHeight) return 100;
    return Math.round((window.scrollY / (docHeight - winHeight)) * 100);
  }

  function onScroll() {
    var pct = getScrollPercent();
    var thresholds = [25, 50, 75, 100];
    for (var i = 0; i < thresholds.length; i++) {
      var t = thresholds[i];
      if (pct >= t && !scrollThresholds[t]) {
        scrollThresholds[t] = true;
        pushEvent({
          type: "scroll",
          depth: t,
          url: window.location.href,
          ts: now()
        });
      }
    }
  }

  window.addEventListener("scroll", onScroll, { passive: true });

  // --- Time on Page ---

  setInterval(function() {
    if (!isVisible) return;
    var seconds = Math.round((Date.now() - pageStartTime) / 1000);
    pushEvent({
      type: "time_on_page",
      seconds: seconds,
      url: window.location.href,
      ts: now()
    });
  }, TIME_PING_INTERVAL);

  // --- Click Tracking ---

  document.addEventListener("click", function(e) {
    var target = e.target;
    var el = target.closest("a, button, [role='button']");
    if (!el) return;

    pushEvent({
      type: "click",
      element_text: (el.textContent || "").trim().substring(0, 200),
      element_href: el.href || null,
      url: window.location.href,
      ts: now()
    });
  }, true);

  // --- Visibility ---

  document.addEventListener("visibilitychange", function() {
    isVisible = !document.hidden;
    pushEvent({
      type: "visibility",
      visible: isVisible,
      url: window.location.href,
      ts: now()
    });
  });

  // --- Flush on interval and unload ---

  setInterval(flush, BATCH_INTERVAL);

  window.addEventListener("beforeunload", flush);
  window.addEventListener("pagehide", flush);
})();
