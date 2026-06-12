# CLI v2 Sandbox

CLI v2 is self-contained under `opencode/sandbox/cli-v2/`. Its source, tests, fixtures, scenarios, and docs live in this folder and must not depend on the legacy sandbox CLI.

CLI v2 runs directly from TypeScript source with Node v22 via `node sandbox/cli-v2/index.ts`. TypeScript is used for checks only; CLI v2 does not require or produce a `dist/` build output.

## Commands

- `hello` prints `hello world` without starting OpenCode.
- `hello-world` runs the checked-in `hello-world` fixture agent in an isolated sandbox.
- `single-agent` runs one named agent with one prompt source.
- `scenario` runs a saved sandbox recipe from a scenario folder.

Check and test from the package root with:

```sh
npm run check:sandbox:v2
npm run test:sandbox:v2
```
