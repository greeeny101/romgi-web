// CSR-only: this is a private, authenticated app talking to the Django API,
// so there's no benefit to SSR and it keeps JWT token handling simple
// (no server-side cookie/session juggling). See the plan's frontend design.
export const ssr = false;
