import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const output = path.join(root, "_site");
const pages = ["index.html", "features.html", "install.html", "privacy.html"];
const downloadUrl =
  "https://github.com/ravi0531rp/OhIc/releases/download/native-macos-preview/OhIc-macOS-Apple-Silicon.dmg";

test("marketing pages build with complete metadata and downloads", async () => {
  for (const page of pages) {
    const html = await readFile(path.join(output, page), "utf8");
    assert.match(html, /<title>[^<]+<\/title>/);
    assert.match(html, /<meta\s+name="description"\s+content="[^"]+"/);
    assert.match(html, /<link rel="canonical" href="https:\/\/ravi0531rp\.github\.io\/OhIc\//);
    assert.match(html, new RegExp(downloadUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    assert.match(html, /<a class="skip-link" href="#main">/);
    assert.match(html, /<main id="main">/);
  }
});

test("every internal page and published asset resolves", async () => {
  const requiredFiles = [
    ...pages,
    "assets/site.css",
    "assets/site.js",
    "assets/ui1.png",
    "assets/ui2.png",
    "assets/pro-ai-workflow.gif",
    "og.png",
    "robots.txt",
    "sitemap.xml",
    ".nojekyll",
  ];
  await Promise.all(requiredFiles.map((file) => access(path.join(output, file))));

  for (const page of pages) {
    const html = await readFile(path.join(output, page), "utf8");
    const localLinks = [...html.matchAll(/href="([^"#:]+\.html(?:#[^"]*)?)"/g)];
    for (const [, link] of localLinks) {
      await access(path.join(output, link.split("#")[0]));
    }
  }
});

test("GitHub Pages deploys only a validated website artifact", async () => {
  const workflow = await readFile(path.join(root, ".github/workflows/pages.yml"), "utf8");
  assert.match(workflow, /node --test tests\/website\.test\.mjs/);
  assert.match(workflow, /actions\/configure-pages@v5/);
  assert.match(workflow, /actions\/upload-pages-artifact@v4/);
  assert.match(workflow, /actions\/deploy-pages@v4/);
  assert.match(workflow, /path: _site/);
});
