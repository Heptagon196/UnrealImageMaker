import http from "node:http";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const devUrl = "http://127.0.0.1:5173/";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const windowsTargetTriple = "x86_64-pc-windows-msvc";

async function pathExists(value) {
  try {
    await fs.access(value);
    return true;
  } catch {
    return false;
  }
}

async function ensureDevSidecarPlaceholder() {
  if (process.platform !== "win32") return;
  const binaryDir = path.join(root, "src-tauri", "binaries");
  const supportDir = path.join(root, "src-tauri", "uim-backend-support");
  const target = path.join(binaryDir, `uim-backend-${windowsTargetTriple}.exe`);
  await fs.mkdir(binaryDir, { recursive: true });
  await fs.mkdir(supportDir, { recursive: true });
  await fs.writeFile(path.join(supportDir, ".dev-placeholder"), "Development placeholder. Production builds replace this directory.\n");
  if (await pathExists(target)) return;
  const python = path.join(root, ".venv", "Scripts", "python.exe");
  const source = (await pathExists(python)) ? python : process.execPath;
  await fs.copyFile(source, target);
  console.log(`Prepared development Tauri sidecar placeholder at ${target}`);
}

function checkDevServer() {
  return new Promise((resolve) => {
    const request = http.get(devUrl, { timeout: 700 }, (response) => {
      response.resume();
      resolve(response.statusCode && response.statusCode >= 200 && response.statusCode < 500);
    });
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

await ensureDevSidecarPlaceholder();

if (await checkDevServer()) {
  console.log(`Using existing Vite dev server at ${devUrl}`);
  process.exit(0);
}

const child =
  process.platform === "win32"
    ? spawn(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", "npm.cmd run dev -- --host 127.0.0.1"], { stdio: "inherit" })
    : spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1"], { stdio: "inherit" });

const stop = () => {
  if (!child.killed) child.kill();
};

process.on("SIGINT", stop);
process.on("SIGTERM", stop);
child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
