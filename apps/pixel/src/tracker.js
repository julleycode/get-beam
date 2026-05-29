(function() {
  "use strict";

  // Abort if this is a bot/automated browser
  if (navigator.webdriver === true) return;

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

  // --- Identity Graph: Multi-provider pixel stacking ---
  // Stack multiple identity resolution pixels for maximum match rate.
  // Each provider uses a different identity graph, so stacking is additive.
  //
  // Default providers (always injected unless overridden by data-identity-providers).
  // These are Beam's system-level identity graph integrations.
  var DEFAULT_PROVIDERS = [
    {"type": "leadpipe", "id": "95247db8-8d49-4213-8ea7-ee0a6dd0ae78"},
  ];

  var PIXEL_URLS = {
    "leadpipe": function(id) { return "https://leadpipe.aws53.cloud/p/" + id + ".js"; },
    "capturify": function(id) { return "https://app.capturify.io/pixel/" + id + ".js"; },
    "fullcontact": function(id) { return "https://app.fullcontact.com/tag/" + id + ".js"; },
    "customers_ai": function(id) { return "https://app.customers.ai/pixel/" + id + "/xray.js"; },
  };

  // Use explicit providers from attribute, or fall back to defaults
  var providersAttr = script.getAttribute("data-identity-providers");
  var providers = DEFAULT_PROVIDERS;
  if (providersAttr) {
    try { providers = JSON.parse(providersAttr); } catch(e) {}
  }
  for (var i = 0; i < providers.length; i++) {
    var prov = providers[i];
    var urlFn = PIXEL_URLS[prov.type];
    if (urlFn && prov.id) {
      var s = document.createElement("script");
      s.src = urlFn(prov.id);
      s.async = true;
      document.head.appendChild(s);
    }
  }

  // Backward compatibility: legacy data-lp attribute for existing installations
  var LP_PIXEL_ID = script.getAttribute("data-lp");
  if (LP_PIXEL_ID) {
    // Only inject if not already handled via data-identity-providers
    var alreadyInjectedLp = false;
    if (providersAttr) {
      try {
        var existingProviders = JSON.parse(providersAttr);
        for (var j = 0; j < existingProviders.length; j++) {
          if (existingProviders[j].type === "leadpipe") {
            alreadyInjectedLp = true;
            break;
          }
        }
      } catch(e) {}
    }
    if (!alreadyInjectedLp) {
      var lpScript = document.createElement("script");
      lpScript.src = "https://leadpipe.aws53.cloud/p/" + LP_PIXEL_ID + ".js";
      lpScript.async = true;
      document.head.appendChild(lpScript);
    }
  }
})();
