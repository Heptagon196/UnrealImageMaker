import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const distDir = path.join(root, "dist");
const outDir = path.join(root, "playwright-screenshots");

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".svg", "image/svg+xml; charset=utf-8"],
  [".webp", "image/webp"],
]);

function safeJoin(base, requestPath) {
  const decoded = decodeURIComponent(requestPath.split("?")[0]);
  const requested = decoded === "/" ? "/index.html" : decoded;
  const resolved = path.resolve(base, `.${requested}`);
  if (!resolved.startsWith(base)) return path.join(base, "index.html");
  return resolved;
}

async function serveDist() {
  const server = http.createServer(async (request, response) => {
    try {
      const filePath = safeJoin(distDir, request.url || "/");
      const bytes = await fs.readFile(filePath);
      response.writeHead(200, {
        "Content-Type": contentTypes.get(path.extname(filePath)) || "application/octet-stream",
      });
      response.end(bytes);
    } catch {
      const fallback = await fs.readFile(path.join(distDir, "index.html"));
      response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      response.end(fallback);
    }
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });

  return server;
}

async function launchBrowser() {
  const attempts = [
    () => chromium.launch({ channel: "msedge", headless: true }),
    () => chromium.launch({ channel: "chrome", headless: true }),
    () => chromium.launch({ headless: true }),
  ];

  let lastError;
  for (const attempt of attempts) {
    try {
      return await attempt();
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

await fs.mkdir(outDir, { recursive: true });

const server = await serveDist();
const address = server.address();
const url = `http://127.0.0.1:${address.port}/`;
const browser = await launchBrowser();
const viewports = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
  { width: 390, height: 844 },
];
const report = [];

try {
  for (const viewport of viewports) {
    const page = await browser.newPage({ viewport });
    await page.goto(url, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);

    const metrics = await page.evaluate(() => {
      const rectOf = (element) => {
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        return {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      };
      const selectors = {
        app: ".app-shell",
        leftRail: ".left-rail",
        workbench: ".workbench-shell",
        body: ".workbench-body",
        main: ".main-workspace",
        rightRail: ".right-rail",
        tabs: ".top-tabs",
        preview: ".preview-panel",
        formPanel: ".form-panel",
        console: ".console-panel",
        queue: ".queue-panel",
      };
      const rects = Object.fromEntries(
        Object.entries(selectors).map(([key, selector]) => [key, rectOf(document.querySelector(selector))]),
      );
      const body = document.body;
      const root = document.documentElement;
      return {
        viewport: { width: window.innerWidth, height: window.innerHeight },
        scroll: {
          bodyWidth: body.scrollWidth,
          bodyHeight: body.scrollHeight,
          rootWidth: root.scrollWidth,
          rootHeight: root.scrollHeight,
          horizontalOverflow: Math.max(body.scrollWidth, root.scrollWidth) > window.innerWidth + 1,
          verticalOverflow: Math.max(body.scrollHeight, root.scrollHeight) > window.innerHeight + 1,
        },
        rects,
        topTabs: [...document.querySelectorAll(".top-tabs button")].map((button) => button.textContent?.trim()),
        visibleHeadings: [...document.querySelectorAll("h1,h2,h3,.section-kicker")]
          .map((item) => item.textContent?.trim())
          .filter(Boolean)
          .slice(0, 24),
      };
    });

    const screenshotPath = path.join(outDir, `ui-${viewport.width}x${viewport.height}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    report.push({ screenshotPath, ...metrics });
    await page.close();
  }
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}

await fs.writeFile(path.join(outDir, "ui-smoke-report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ url, reportPath: path.join(outDir, "ui-smoke-report.json"), screenshots: report.map((item) => item.screenshotPath) }, null, 2));
