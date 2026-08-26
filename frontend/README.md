# romgi-web frontend

The SvelteKit (Svelte 5, CSR-only) frontend for
[romgi-web](../README.md), styled with FlowbiteSvelte and Tailwind CSS v4.

It talks to the Django backend over REST and a Channels WebSocket, so it needs
that backend running — it isn't useful standalone. The usual way to run
everything is `docker compose up --build` from the repo root.

To run just this against a backend on the host:

```bash
npm install
cp .env.example .env   # points at localhost:8001
npm run dev
```

See [docs/development.md](../docs/development.md) for the full local setup,
including the VS Code debug configs and `npm run check`.
