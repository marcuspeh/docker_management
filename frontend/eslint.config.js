import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["**/dist/**", "**/coverage/**", "**/node_modules/**"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    // Neither app may import from the other: each one has to build, run and
    // deploy on its own.
    files: ["apps/deployment/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@portal/containers-app", "@portal/containers-app/*"],
              message:
                "The Deployment app must not import from the Containers app. Move shared code into @portal/shared.",
            },
            {
              group: ["../../containers/*", "../containers/*"],
              message:
                "The Deployment app must not import from the Containers app. Move shared code into @portal/shared.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["apps/containers/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@portal/deployment-app", "@portal/deployment-app/*"],
              message:
                "The Containers app must not import from the Deployment app. Move shared code into @portal/shared.",
            },
            {
              group: ["../../deployment/*", "../deployment/*"],
              message:
                "The Containers app must not import from the Deployment app. Move shared code into @portal/shared.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["**/*.test.{ts,tsx}", "**/vitest.config.ts"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
);