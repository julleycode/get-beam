(function() {
  "use strict";
  // Beam on-site company greeting. Lazy-loaded by tracker.js ONLY when
  // data-greeting="on" AND consent granted AND no GPC/DNT. The server decides
  // everything; this file renders owner copy via textContent (never innerHTML),
  // sends no cookies, ignores any non-200, and remembers a dismiss for 30 days.
  var me = document.currentScript;
  if (!me || document.getElementById("_rtaG")) return;
  var KEY = "_rta_gd";
  var DAYS30 = 2592000000;
  try {
    var at = +localStorage.getItem(KEY);
    if (at && Date.now() - at < DAYS30) return;
  } catch (e) {}
  var u;
  try { u = new URL(me.src); } catch (e) { return; }
  var site = u.searchParams.get("s");
  if (!site) return;
  var q = new URLSearchParams({ site_id: site });
  var vid = u.searchParams.get("v");
  if (vid) q.set("v", vid);
  if (typeof fetch !== "function") return;

  fetch(u.origin + "/api/v1/greeting?" + q, { credentials: "omit", cache: "no-store" })
    .then(function(r) { return r.status === 200 ? r.json() : null; })
    .then(function(d) {
      if (!d || d.show !== true || typeof d.text !== "string" || !d.text) return;
      render(d.text, typeof d.cta_url === "string" && d.cta_url.indexOf("https://") === 0 ? d.cta_url : null);
    })
    .catch(function() {});

  function render(text, cta) {
    if (document.getElementById("_rtaG")) return;
    var host = document.body || document.documentElement;
    if (!host) return;
    var b = document.createElement("div");
    b.id = "_rtaG";
    b.setAttribute("role", "status");
    b.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483646;max-width:320px;background:#111;color:#fff;font:14px/1.4 system-ui,sans-serif;padding:12px 36px 12px 14px;border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.25)";
    var t = document.createElement("span");
    t.className = "_rtaGt";
    t.textContent = text;
    b.appendChild(t);
    if (cta) {
      var a = document.createElement("a");
      a.className = "_rtaGc";
      a.href = cta;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "Learn more";
      a.style.cssText = "display:block;margin-top:6px;color:#8ab4ff";
      b.appendChild(a);
    }
    var x = document.createElement("button");
    x.className = "_rtaGx";
    x.setAttribute("aria-label", "Dismiss");
    x.textContent = "×";
    x.style.cssText = "position:absolute;top:6px;right:8px;border:0;background:none;color:#fff;font-size:18px;cursor:pointer";
    x.onclick = function() {
      try { localStorage.setItem(KEY, String(Date.now())); } catch (e) {}
      if (b.parentNode) b.parentNode.removeChild(b);
    };
    b.appendChild(x);
    host.appendChild(b);
  }
})();
