// SPA mode: no SSR, no prerender — the static app-shell is hydrated client-side and the SSE bus +
// leaderboard fetch run only in the browser (REWRITE-ARCHITECTURE §3, "Frontend stack").
export const ssr = false;
export const prerender = false;
export const trailingSlash = 'never';
