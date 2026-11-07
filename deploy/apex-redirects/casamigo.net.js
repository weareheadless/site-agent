/**
 * The Casamigo apex redirects to the canonical www site.
 *
 * The site itself is served by the tenant Worker on www.casamigo.net. This
 * Worker only owns the apex hostname so every path, query string and locale
 * prefix lands on the same page at the canonical origin with a 301.
 *
 * Deployed as the Cloudflare Worker `casamigo-apex-redirect` and attached to
 * the `casamigo.net` custom domain. See deploy/README.md, "Apex host redirects".
 */
export default {
  fetch(request) {
    const url = new URL(request.url);
    const target = new URL(url.pathname + url.search, "https://www.casamigo.net");
    return Response.redirect(target.toString(), 301);
  },
};
