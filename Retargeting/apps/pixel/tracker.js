/**
 * ReTargetAgent Pixel — tracker.js
 * Tracks pageviews, scroll depth, time on page, clicks.
 * < 5KB. Drop-in: <script src="https://pixel.retargetagent.com/tracker.js" data-pixel-id="YOUR_ID"></script>
 */
(function () {
  var PIXEL_ID = (document.currentScript || {}).getAttribute("data-pixel-id") || "";
  var API_BASE = (document.currentScript || {}).getAttribute("data-api") || "http://localhost:8000";
  var ENDPOINT = API_BASE + "/api/v1/events/ingest";
  var FLUSH_INTERVAL = 10000; // 10s
  var queue = [];

  // Anonymous ID (persisted in localStorage)
  function getAnonId() {
    var key = "rta_aid";
    var id = localStorage.getItem(key);
    if (!id) {
      id = "anon_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(key, id);
    }
    return id;
  }

  var anonId = getAnonId();
  var pageStart = Date.now();
  var maxScroll = 0;

  // Track scroll depth
  function onScroll() {
    var scrolled = window.scrollY + window.innerHeight;
    var total = document.documentElement.scrollHeight || 1;
    var pct = Math.min(100, Math.round((scrolled / total) * 100));
    if (pct > maxScroll) maxScroll = pct;
  }
  window.addEventListener("scroll", onScroll, { passive: true });

  function track(eventType, extra) {
    var payload = Object.assign({
      pixel_id: PIXEL_ID,
      anonymous_id: anonId,
      event_type: eventType,
      page_url: location.href,
      page_title: document.title,
      referrer: document.referrer,
      scroll_depth: maxScroll,
      time_on_page: Math.round((Date.now() - pageStart) / 1000),
      timestamp: new Date().toISOString(),
    }, extra || {});
    queue.push(payload);
  }

  // Track clicks on links / buttons
  document.addEventListener("click", function (e) {
    var el = e.target;
    if (el.tagName === "A" || el.tagName === "BUTTON") {
      track("click", { properties: JSON.stringify({ tag: el.tagName, text: el.innerText.slice(0, 80) }) });
    }
  });

  // Flush queue
  function flush() {
    if (!queue.length) return;
    var batch = queue.splice(0);
    var payload = JSON.stringify({ events: batch });
    if (navigator.sendBeacon) {
      navigator.sendBeacon(ENDPOINT, new Blob([payload], { type: "application/json" }));
    } else {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", ENDPOINT, true);
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.send(payload);
    }
  }

  setInterval(flush, FLUSH_INTERVAL);
  window.addEventListener("beforeunload", flush);
  window.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") flush();
  });

  // Fire initial pageview
  track("pageview");
})();
