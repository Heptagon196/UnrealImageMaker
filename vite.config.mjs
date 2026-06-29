import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";

const API_CONTRACT_VERSION = "uim-api-2026-06-28-game-ui-mcp";
const API_HEALTH_URL = "http://127.0.0.1:8765/health";

let backendProcess = null;

function checkBackendHealth() {
  return new Promise((resolve) => {
    const request = http.get(API_HEALTH_URL, { timeout: 700 }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        try {
          const parsed = JSON.parse(body);
          resolve({
            online: response.statusCode === 200 && parsed.status === "ok",
            contractMatches: parsed.apiContractVersion === API_CONTRACT_VERSION,
            detail: parsed
          });
        } catch {
          resolve({ online: false, contractMatches: false, detail: body || response.statusMessage });
        }
      });
    });
    request.on("timeout", () => {
      request.destroy();
      resolve({ online: false, contractMatches: false, detail: "timeout" });
    });
    request.on("error", (error) => resolve({ online: false, contractMatches: false, detail: error.message }));
  });
}

async function waitForBackendReady(timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  let last = await checkBackendHealth();
  while ((!last.online || !last.contractMatches) && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 350));
    last = await checkBackendHealth();
  }
  return last;
}

function startDevBackend(rootDir) {
  if (backendProcess && !backendProcess.killed) return { started: false, reason: "already-started" };
  const python = path.join(rootDir, ".venv", "Scripts", "python.exe");
  const backend = path.join(rootDir, "backend");
  const logDir = path.join(rootDir, "logs");
  fs.mkdirSync(logDir, { recursive: true });
  const stdoutLog = path.join(logDir, "dev-backend-worker.out.log");
  const stderrLog = path.join(logDir, "dev-backend-worker.err.log");
  const stdout = fs.openSync(stdoutLog, "w");
  const stderr = fs.openSync(stderrLog, "w");
  backendProcess = spawn(python, ["-m", "uim_core.api"], {
    cwd: rootDir,
    env: {
      ...process.env,
      PYTHONPATH: backend,
      NO_PROXY: "127.0.0.1,localhost",
      no_proxy: "127.0.0.1,localhost"
    },
    stdio: ["ignore", stdout, stderr],
    windowsHide: true
  });
  backendProcess.on("exit", () => {
    backendProcess = null;
  });
  return { started: true, stdout_log: stdoutLog, stderr_log: stderrLog };
}

function stopDevBackendPort() {
  if (process.platform !== "win32") return;
  spawnSync(
    "powershell",
    [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-Command",
      "$connections = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue; foreach ($connection in $connections) { Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue }"
    ],
    { stdio: "ignore", windowsHide: true }
  );
}

function uimBackendDevPlugin() {
  return {
    name: "uim-backend-dev",
    configureServer(server) {
      const rootDir = server.config.root;
      server.middlewares.use("/__uim/restart-backend", async (request, response) => {
        if (request.method !== "POST") {
          response.statusCode = 405;
          response.end("Method Not Allowed");
          return;
        }
        try {
          const before = await checkBackendHealth();
          let startResult = { started: false, reason: "already-online" };
          if (!before.online || !before.contractMatches) {
            if (before.online && !before.contractMatches) {
              stopDevBackendPort();
              await new Promise((resolve) => setTimeout(resolve, 300));
            }
            startResult = startDevBackend(rootDir);
          }
          const health = await waitForBackendReady();
          response.setHeader("Content-Type", "application/json");
          response.end(JSON.stringify({
            online: health.online && health.contractMatches,
            health,
            ...startResult
          }));
        } catch (error) {
          response.statusCode = 500;
          response.setHeader("Content-Type", "application/json");
          response.end(JSON.stringify({
            online: false,
            error: error instanceof Error ? error.message : String(error)
          }));
        }
      });
      server.httpServer?.once("close", () => {
        if (backendProcess && !backendProcess.killed) {
          backendProcess.kill();
          backendProcess = null;
        }
      });
    }
  };
}

export default defineConfig({
  base: "./",
  plugins: [react(), uimBackendDevPlugin()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ["**/.venv/**", "**/backend/**/__pycache__/**", "**/src-tauri/target/**", "**/dist/**"]
    }
  },
  build: {
    target: "es2022"
  }
});
