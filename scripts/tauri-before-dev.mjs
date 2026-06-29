import http from "node:http";
import { spawn } from "node:child_process";

const devUrl = "http://127.0.0.1:5173/";

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
