import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("macOS artifact waits for both quality gates and is smoke-tested", async () => {
  const workflow = await read(".github/workflows/ci.yml");

  assert.match(workflow, /needs: \[backend, frontend\]/);
  assert.match(workflow, /scripts\/smoke-dmg\.sh release\/\*\.dmg/);
  assert.match(workflow, /actions\/upload-artifact@v4/);
  assert.match(workflow, /OhIc-macos-0\.1\.0\.\$\{\{ github\.run_number \}\}/);
});

test("DMG bundles relocatable runtimes and verifies the mounted app", async () => {
  const [build, smoke] = await Promise.all([
    read("scripts/build-dmg.sh"),
    read("scripts/smoke-dmg.sh"),
  ]);

  assert.match(build, /dylibbundler/);
  assert.match(build, /cp "\$UV_BIN"/);
  assert.match(build, /react react-dom scheduler/);
  assert.match(build, /codesign --force --deep --sign/);
  assert.match(smoke, /hdiutil verify/);
  assert.match(smoke, /backend-runtime-ok/);
  assert.match(smoke, /frontend-runtime-ok/);
});
