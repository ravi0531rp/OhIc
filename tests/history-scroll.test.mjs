import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("history keeps rows full-size inside a bounded scroll region", () => {
  assert.match(css, /\.history-drawer \{[^}]*display: flex;[^}]*flex-direction: column;[^}]*max-height: 100dvh;/s);
  assert.match(css, /\.history-list \{[^}]*flex: 1 1 auto;[^}]*min-height: 0;[^}]*overflow-y: auto;/s);
  assert.match(css, /\.history-row \{[^}]*flex: 0 0 auto;[^}]*min-height: 64px;/s);
  assert.doesNotMatch(
    css,
    /\.drawer-footnote \{[^}]*position: absolute;/s,
    "footnote must participate in drawer layout",
  );
});
