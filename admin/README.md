<img src="public/favicon.svg" alt="Hoodora" width="64">

# Hoodora admin

The moderation dashboard, for staff (moderators and admins), over the API's
`/v1/admin` (decisions D.1 to D.6). React, TypeScript and Vite, with Refine and
Ant Design 5.

## Run it

With the backend running (`docker compose up` in the repository root), and
`ADMIN_CORS_ORIGINS=http://localhost:5174` in its `.env`:

```sh
npm ci
npm run dev        # http://localhost:5174, against http://localhost:8000
```

A staff account comes from `scripts/create_admin.py`, then the Staff screen.

## Check it

```sh
npm run typecheck
npm test           # Vitest and Testing Library, against a mocked API
npm run build      # dist/, with VITE_API_BASE_URL set to the API it should call
```

On Windows, run the tests from a path with an upper-case drive letter
(`C:\Users\...`, as PowerShell's `Set-Location "C:\..."` gives). From a
lower-case one (`c:\...`, as VS Code's terminal often starts), Vitest loads the
setup file twice and reports "failed to find the current suite".

## Build settings

Read at build time (`.env.example`):

| Setting | Default | What |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | The API the dashboard calls. |
| `VITE_IDLE_TIMEOUT_MINUTES` | `15` | Sign out after this long without activity. |

## How it holds together

| Where | What |
| --- | --- |
| `src/api.ts` | The only way to the API. The staff token lives here, in memory only. |
| `src/session.ts` | Signing in and out, and the idle timer. |
| `src/providers.ts` | Refine's auth, data and access providers over the admin API. |
| `src/pages/` | One file per screen. |
| `src/components.tsx` | Loading, empty and error states, and the one dialog every action goes through. |
| `src/pages/GodsView.tsx` | God's view (decision D.8): Leaflet with no map tiles, drawing our own data. |
| `src/kenya.json` | Kenya's outline: Natural Earth 1:50m admin-0 countries, public domain. |

- **No storage:** nothing goes in web storage, cookies or URLs. A reload signs
  the person out.
- **One dialog for every action:** it asks for the reason where the API takes
  one, and sends nothing until its own button is pressed.

## Shipping

The deploy builds this directory on the server, from the commit being deployed,
with `Dockerfile` (decision D.6). See `docs/DEPLOYMENT.md`, "Admin dashboard".
