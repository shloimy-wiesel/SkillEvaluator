/* oxlint-disable shadcn/no-unknown-classes, next/no-html-link-for-pages, react-doctor/nextjs-no-a-element, next/no-css-tags, react-doctor/nextjs-no-css-link -- Studio classes come from the shared same-origin stylesheet. Browser routes are owned by ASGI. */
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "SkillEvaluator Studio" };

/** @returns The frame shared by exported Studio documents. */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="stylesheet" href="/static/studio.css" />
      </head>
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <header>
          <nav aria-label="Workspace">
            <a className="brand" href="/">
              <b aria-hidden="true">S/</b> SkillEvaluator <span>Studio</span>
            </a>
            <a className="workspace-link" href="/">
              Projects
            </a>
          </nav>
        </header>
        <main id="main" tabIndex={-1}>
          {children}
        </main>
        <footer>
          SkillEvaluator Studio <span>/</span> Self-hosted workspace
        </footer>
      </body>
    </html>
  );
}
