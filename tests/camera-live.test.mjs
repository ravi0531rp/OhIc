import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const api = await readFile(new URL("../app/lib/api.ts", import.meta.url), "utf8");
const picker = await readFile(new URL("../app/components/SourcePicker.tsx", import.meta.url), "utf8");
const app = await readFile(new URL("../app/OhIcApp.tsx", import.meta.url), "utf8");
const phone = await readFile(new URL("../backend/app/services/phone_camera_page.py", import.meta.url), "utf8");

test("phone camera sends retryable ordered media chunks", () => {
  assert.match(phone, /new MediaRecorder/);
  assert.match(phone, /recorder\.start\(2000\)/);
  assert.match(phone, /X-OhIc-Sequence/);
  assert.match(phone, /attempt <= 5/);
  assert.match(phone, /audio: true/);
});

test("a live camera checkpoint can enter enhancement or Pro", () => {
  assert.match(api, /checkpointCameraSession/);
  assert.match(picker, /Enhance current buffer/);
  assert.match(picker, /Analyze current buffer/);
  assert.match(picker, /onCameraCheckpoint/);
  assert.match(app, /onCameraCheckpoint=\{sourceLoaded\}/);
  assert.match(app, /destination === "pro"/);
});
