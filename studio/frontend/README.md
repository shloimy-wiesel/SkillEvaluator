# Studio frontend

`apps/web` is the Next.js application. Shared React components and the Tailwind theme live in `packages/ui`; `packages/typescript-config` contains the shared compiler settings.

## Local development

From `studio/frontend`, use Node.js 24.15+ and Corepack. Corepack reads `packageManager` in `package.json` and runs the pinned pnpm 11.25.0.

```sh
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

Open the local URL printed by Next.js (normally `http://localhost:3000`).

| Command | Purpose |
| --- | --- |
| `corepack pnpm lint` | Check workspace formatting and type-aware lint rules. |
| `corepack pnpm format` | Apply Ultracite's formatting and automatic lint fixes. |
| `corepack pnpm typecheck` | Check TypeScript across the app and shared packages. |
| `corepack pnpm build` | Build the application for production. |

Use semantic Tailwind utilities such as `bg-primary` so components follow the light and dark themes in `packages/ui/src/styles/globals.css`. Import shared components through the package exports, for example `import { Button } from "@workspace/ui/components/button"`.
