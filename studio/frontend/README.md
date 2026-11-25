# Studio frontend

`apps/web` is the Next.js application. Shared React components and the Tailwind theme live in `packages/ui`; `packages/typescript-config` contains the shared compiler settings.

## Local development

From `studio/frontend`, use Node.js 24.15+ and Corepack. Corepack reads `packageManager` in `package.json` and runs the pinned pnpm 11.25.0.

```sh
corepack pnpm install --frozen-lockfile
corepack pnpm build
```

Start Studio from the repository root (`STUDIO_DATA_DIR=./studio-data uvicorn studio.app:create_app --factory`). Open the ASGI URL: it serves both the browser documents and `/api/v1`. The default export is `studio/frontend/apps/web/out`; point `STUDIO_FRONTEND_DIR` at a different built export before startup if needed. Build once before running `tests/studio` locally; rebuild after editing React source.

## Adding a feature document

Keep the existing browser route and its ASGI route name. After checking project scope in its GET handler, return `studio.frontend_routes.document(request, "feature.html")` for a literal export from `apps/web/app/feature/page.tsx`. Keep downloads and mutations in their own handlers. Use ordinary same-origin `<a href>` links so deep links and built or unmigrated pages work alike. The route adapter reads the ID from the browser pathname after hydration and passes it to the renderer (for example, `<ProjectOverview projectId={id} />`). Add future features as sibling documents, rather than extending the overview with pathname switches.

Read `/api/v1/projects` for the library and `/api/v1/projects/{id}` for `{project, groups, gitlab}`. Create with `POST /api/v1/projects`; check saved remote credentials with `POST /api/v1/projects/{id}/check`. The JSON client in `apps/web/lib/studio-api.ts` takes paths relative to `/api/v1`; author-facing errors have `detail: {code, message}`. No Git transport secret is part of a response model.

| Command | Purpose |
| --- | --- |
| `corepack pnpm lint` | Check workspace formatting and type-aware lint rules. |
| `corepack pnpm format` | Apply Ultracite's formatting and automatic lint fixes. |
| `corepack pnpm typecheck` | Check TypeScript across the app and shared packages. |
| `corepack pnpm build` | Build the application for production. |

Use semantic Tailwind utilities such as `bg-primary` so components follow the light and dark themes in `packages/ui/src/styles/globals.css`. Import shared components through the package exports, for example `import { Button } from "@workspace/ui/components/button"`.
