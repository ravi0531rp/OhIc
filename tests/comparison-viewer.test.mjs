import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../app/components/ComparisonViewer.tsx", import.meta.url), "utf8");

test("comparison wipe does not expose misleading native controls", () => {
  assert.doesNotMatch(source, /<video[^>]*\scontrols(?:\s|=|>)/);
  assert.match(source, /aria-label="Comparison playback position"/);
  assert.match(source, /aria-label=\{playing \? "Pause comparison" : "Play comparison"\}/);
});

test("comparison slider and playback timeline are separate controls", () => {
  assert.match(source, /aria-label="Before and after comparison position"/);
  assert.match(source, /className="comparison-transport"/);
});
