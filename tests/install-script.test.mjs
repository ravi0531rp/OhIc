import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const installer = fileURLToPath(new URL("../install.sh", import.meta.url));

test("one-command installer is valid Bash and documents recovery options", () => {
  execFileSync("bash", ["-n", installer], { stdio: "pipe" });
  const help = execFileSync("bash", [installer, "--help"], { encoding: "utf8" });

  assert.match(help, /--install-only/);
  assert.match(help, /--update/);
  assert.match(help, /--doctor/);
  assert.match(help, /OHIC_HOME/);
});
