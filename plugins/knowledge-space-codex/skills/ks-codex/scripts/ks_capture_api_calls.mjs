#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import readline from "node:readline/promises";

const SENSITIVE_KEYS = [
  "authorization",
  "cookie",
  "set-cookie",
  "csrf",
  "xsrf",
  "token",
  "password",
  "secret",
  "key"
];

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    if (!item.startsWith("--")) continue;
    const key = item.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      args[key] = true;
    } else {
      args[key] = next;
      i += 1;
    }
  }
  return args;
}

function isSensitiveKey(key) {
  const lowered = String(key).toLowerCase();
  return SENSITIVE_KEYS.some((part) => lowered.includes(part));
}

function redactObject(value) {
  if (Array.isArray(value)) return value.map(redactObject);
  if (!value || typeof value !== "object") return value;

  const result = {};
  for (const [key, nested] of Object.entries(value)) {
    result[key] = isSensitiveKey(key) ? "<redacted>" : redactObject(nested);
  }
  return result;
}

function redactHeaders(headers) {
  const result = {};
  for (const [key, value] of Object.entries(headers || {})) {
    result[key] = isSensitiveKey(key) ? "<redacted>" : value;
  }
  return result;
}

function redactText(text) {
  if (!text) return text;
  return String(text)
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer <redacted>")
    .replace(/("?(?:password|token|secret|authorization|cookie)"?\s*:\s*)"[^"]*"/gi, "$1\"<redacted>\"");
}

function redactBody(postData) {
  if (!postData) return null;
  try {
    return redactObject(JSON.parse(postData));
  } catch {
    return redactText(postData);
  }
}

function writeJsonl(stream, event) {
  stream.write(`${JSON.stringify(event)}\n`);
}

function usage() {
  console.log(`Usage:
  node scripts/ks_capture_api_calls.mjs --url https://<ks-host>/ --out captures/ks-api.jsonl

Options:
  --url       KS UI URL to open. Also accepts KS_UI_URL env var.
  --out       JSONL output path. Default: captures/ks-api-capture.jsonl
  --pattern   URL substring to capture. Default: /api/

The script opens a headed browser. Log in, perform one or more UI actions,
then press Enter in the terminal to stop. Output is redacted but should still
be reviewed before sharing or committing.`);
}

const args = parseArgs(process.argv.slice(2));
const startUrl = args.url || process.env.KS_UI_URL;
const outPath = args.out || "captures/ks-api-capture.jsonl";
const pattern = args.pattern || "/api/";

if (!startUrl || args.help) {
  usage();
  process.exit(startUrl ? 0 : 2);
}

let playwright;
try {
  playwright = await import("playwright");
} catch {
  console.error("Playwright is not installed. Install it in a disposable/local environment before using this script:");
  console.error("  npm install --save-dev playwright");
  console.error("  npx playwright install chromium");
  process.exit(2);
}

fs.mkdirSync(path.dirname(outPath), { recursive: true });
const stream = fs.createWriteStream(outPath, { flags: "a" });
const browser = await playwright.chromium.launch({ headless: false });
const context = await browser.newContext({ ignoreHTTPSErrors: true });
const page = await context.newPage();

page.on("request", (request) => {
  const url = request.url();
  if (!url.includes(pattern)) return;
  writeJsonl(stream, {
    type: "request",
    ts: new Date().toISOString(),
    method: request.method(),
    url,
    headers: redactHeaders(request.headers()),
    postData: redactBody(request.postData())
  });
});

page.on("response", async (response) => {
  const url = response.url();
  if (!url.includes(pattern)) return;

  const headers = response.headers();
  const contentType = headers["content-type"] || "";
  let bodyPreview = null;

  if (contentType.includes("application/json")) {
    try {
      const text = await response.text();
      bodyPreview = redactText(text.slice(0, 6000));
    } catch {
      bodyPreview = "<unavailable>";
    }
  }

  writeJsonl(stream, {
    type: "response",
    ts: new Date().toISOString(),
    status: response.status(),
    method: response.request().method(),
    url,
    headers: redactHeaders(headers),
    bodyPreview
  });
});

await page.goto(startUrl, { waitUntil: "domcontentloaded" });
console.log(`Capturing API calls matching ${pattern}`);
console.log(`Output: ${outPath}`);
console.log("Use the browser normally, then press Enter here to stop.");

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
await rl.question("");
rl.close();

await browser.close();
stream.end();
console.log("Capture stopped.");
