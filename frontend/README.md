# Web workspace

React 18 / TypeScript / Vite. Run `npm ci`, `npm run dev`, `npm run typecheck`, `npm run build` here. Use `http://localhost:5173` so the exact Origin matches the API default. `/api` is proxied locally; the browser never stores auth tokens.

`src/api.ts` exports the typed same-origin API client and standardized errors. Company selection is kept in the URL for refresh/deep-link support; business data, consents and sessions remain server-owned. The UI uses local system fonts, a responsive dark navigation and warm neutral workspace. Browser checks run with `npm run test:e2e` against an already running seeded stack and installed Chrome; see the root README for Chromium alternatives.
