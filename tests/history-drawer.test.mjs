import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const drawer = await readFile(new URL("../app/components/HistoryDrawer.tsx", import.meta.url), "utf8");
const api = await readFile(new URL("../app/lib/api.ts", import.meta.url), "utf8");
const app = await readFile(new URL("../app/OhIcApp.tsx", import.meta.url), "utf8");

test("history includes enhancements, camera captures, and Pro analyses", () => {
  assert.match(api, /request<HistoryEntry\[]>\("\/api\/history"\)/);
  assert.match(drawer, /Enhancements, camera captures, and Pro analyses/);
  assert.match(drawer, /entry\.kind === "pro"/);
  assert.match(drawer, /entry\.kind === "camera"/);
});

test("history entries reopen their matching workspace", () => {
  assert.match(app, /selected\.kind === "pro"/);
  assert.match(app, /selected\.kind === "camera"/);
  assert.match(app, /api\.analysis\(selected\.reference_id\)/);
  assert.match(app, /api\.video\(selected\.video_id\)/);
});
