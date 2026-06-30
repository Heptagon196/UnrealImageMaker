import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const distDir = path.join(root, "dist");
const outDir = path.join(root, "docs", "readme-assets");
const apiBase = "http://127.0.0.1:8765";

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

async function ensureBackendHealth(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${apiBase}/health`);
      if (response.ok) {
        const health = await response.json();
        if (health.status === "ok") return;
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`README screenshots require the backend at ${apiBase}. Start it with "npm.cmd run backend:api". ${lastError}`);
}

async function tryLaunchHeaded() {
  const attempts = [
    () => chromium.launch({ channel: "msedge", headless: false, args: ["--start-maximized"] }),
    () => chromium.launch({ channel: "chrome", headless: false, args: ["--start-maximized"] }),
    () => chromium.launch({ headless: false, args: ["--start-maximized"] }),
  ];

  let lastError;
  for (const attempt of attempts) {
    try {
      return { browser: await attempt(), maximized: true };
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

async function launchBrowser() {
  try {
    return await tryLaunchHeaded();
  } catch {
    const attempts = [
      () => chromium.launch({ channel: "msedge", headless: true }),
      () => chromium.launch({ channel: "chrome", headless: true }),
      () => chromium.launch({ headless: true }),
    ];

    let lastError;
    for (const attempt of attempts) {
      try {
        return { browser: await attempt(), maximized: false };
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError;
  }
}

async function clickTab(page, name) {
  await page
    .locator(".top-tabs button")
    .filter({ hasText: name })
    .first()
    .click();
  await page.waitForTimeout(600);
}

async function screenshot(page, fileName) {
  const filePath = path.join(outDir, fileName);
  await page.screenshot({ path: filePath, fullPage: false });
  return path.relative(root, filePath).replaceAll(path.sep, "/");
}

await fs.mkdir(outDir, { recursive: true });
await ensureBackendHealth();

const server = await serveDist();
const address = server.address();
const url = `http://127.0.0.1:${address.port}/`;
const { browser, maximized } = await launchBrowser();
const context = await browser.newContext(
  maximized
    ? { viewport: null }
    : {
        viewport: { width: 1920, height: 1080 },
      },
);
const screenshots = [];
let metrics = null;

async function openAppPage() {
  const page = await context.newPage();
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForSelector(".app-shell", { timeout: 10000 });
  await page.waitForSelector(".project-status-pill.online", { timeout: 20000 });
  await page.waitForTimeout(1200);
  return page;
}

async function capture(fileName, steps = []) {
  const page = await openAppPage();
  try {
    for (const step of steps) {
      await step(page);
    }
    const filePath = await screenshot(page, fileName);
    metrics = await page.evaluate(() => ({
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      outerWidth: window.outerWidth,
      outerHeight: window.outerHeight,
    }));
    return filePath;
  } finally {
    await page.close();
  }
}

try {
  screenshots.push(await capture("01-pixel-workbench.png"));
  screenshots.push(await capture("02-game-ui-structure.png", [async (page) => clickTab(page, "游戏 UI")]));
  screenshots.push(
    await capture("03-game-ui-texture-kit.png", [
      async (page) => clickTab(page, "游戏 UI"),
      async (page) => {
        await page
          .locator(".module-switcher button")
          .filter({ hasText: "UI 贴图组" })
          .first()
          .click();
        await page.waitForTimeout(600);
      },
    ]),
  );

  await fs.writeFile(
    path.join(outDir, "screenshot-report.json"),
    `${JSON.stringify({ url, maximized, metrics, screenshots }, null, 2)}\n`,
  );
  console.log(JSON.stringify({ url, maximized, metrics, screenshots }, null, 2));
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
