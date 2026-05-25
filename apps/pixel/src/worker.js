export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === "/t.js" || url.pathname === "/pixel/t.js") {
      const trackerCode = TRACKER_JS;
      return new Response(trackerCode, {
        headers: {
          "Content-Type": "application/javascript",
          "Cache-Control": "public, max-age=3600",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }

    return new Response("Not found", { status: 404 });
  },
};
