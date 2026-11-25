import { defineConfig } from "oxlint";
import antiSlop from "ultracite/oxlint/anti-slop";
import core from "ultracite/oxlint/core";
import { jsPluginSettings, selectJsPlugins } from "ultracite/oxlint/js-plugins";
import landmines from "ultracite/oxlint/landmines";
import next from "ultracite/oxlint/next";
import nextJsPlugins from "ultracite/oxlint/next/js-plugins";
import react from "ultracite/oxlint/react";
import shadcn from "ultracite/oxlint/shadcn";

const jsPlugins = selectJsPlugins([
  "github",
  "jsdoc-js",
  "sonarjs",
  "tsdoc",
  "react-doctor",
]);

export default defineConfig({
  env: core.env,
  extends: [
    core,
    react,
    next,
    jsPlugins,
    nextJsPlugins,
    shadcn,
    landmines,
    antiSlop,
  ],
  ignorePatterns: core.ignorePatterns,
  jsPlugins: [
    ...jsPlugins.jsPlugins,
    ...shadcn.jsPlugins,
    ...landmines.jsPlugins,
  ],
  settings: jsPluginSettings,
  options: { typeAware: true },
});
