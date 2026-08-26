import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("macOS artifact waits for both quality gates and is smoke-tested", async () => {
  const [workflow, readme] = await Promise.all([
    read(".github/workflows/ci.yml"),
    read("README.md"),
  ]);

  assert.match(workflow, /package-macos:[\s\S]*permissions:\n      contents: write/);
  assert.match(workflow, /needs: \[backend, frontend\]/);
  assert.match(workflow, /scripts\/smoke-dmg\.sh release\/\*\.dmg/);
  assert.match(workflow, /actions\/upload-artifact@v4/);
  assert.match(workflow, /OhIc-macos-0\.1\.1\.\$\{\{ github\.run_number \}\}/);
  assert.match(workflow, /RELEASE_TAG: native-macos-preview/);
  assert.match(workflow, /release\/OhIc-macOS-Apple-Silicon\.dmg/);
  assert.match(workflow, /gh release upload/);
  assert.match(workflow, /gh release create/);
  assert.match(
    readme.slice(0, 1_000),
    /releases\/download\/native-macos-preview\/OhIc-macOS-Apple-Silicon\.dmg/,
  );
});

test("DMG bundles relocatable runtimes and verifies the mounted app", async () => {
  const [build, nativeHost, info, smoke] = await Promise.all([
    read("scripts/build-dmg.sh"),
    read("packaging/OhIcApp.swift"),
    read("packaging/Info.plist"),
    read("scripts/smoke-dmg.sh"),
  ]);

  assert.match(build, /dylibbundler/);
  assert.match(build, /cp "\$UV_BIN"/);
  assert.match(build, /react react-dom scheduler/);
  assert.match(build, /xcrun swiftc/);
  assert.match(build, /-framework AppKit -framework WebKit/);
  assert.match(build, /generate_app_icon\.swift/);
  assert.match(build, /iconutil -c icns/);
  assert.match(build, /codesign --force --deep --sign/);
  assert.match(smoke, /PYTHONPYCACHEPREFIX/);
  assert.match(smoke, /ditto "\$MOUNTED_APP_DIR"/);
  assert.match(smoke, /hdiutil verify/);
  assert.match(smoke, /backend-runtime-ok/);
  assert.match(smoke, /frontend-runtime-ok/);
  assert.match(smoke, /OHIC_SMOKE_TEST=1/);
  assert.match(smoke, /native-application-runtime-ok/);
  assert.match(smoke, /left local services running/);
  assert.match(nativeHost, /NSApplication\.shared/);
  assert.match(nativeHost, /WKWebView/);
  assert.match(nativeHost, /http:\/\/127\.0\.0\.1:3000/);
  assert.match(nativeHost, /runOpenPanelWith parameters/);
  assert.match(nativeHost, /runJavaScriptConfirmPanelWithMessage/);
  assert.match(nativeHost, /WKDownloadDelegate/);
  assert.match(nativeHost, /applicationWillTerminate/);
  assert.doesNotMatch(nativeHost, /\/usr\/bin\/open/);
  assert.match(info, /<key>CFBundleIconFile<\/key><string>AppIcon<\/string>/);
  assert.match(info, /<key>NSCameraUsageDescription<\/key>/);
});
