use std::{
    fs::{self, File},
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Duration,
};

use tauri::Manager;

struct BackendWorker(Mutex<Option<Child>>);

#[derive(serde::Serialize)]
struct BackendStatus {
    online: bool,
    stdout_log: Option<String>,
    stderr_log: Option<String>,
}

#[derive(serde::Serialize)]
struct McpRuntimePaths {
    root: String,
    python: String,
    backend: String,
    available: bool,
    #[serde(rename = "runtimeKind")]
    runtime_kind: String,
    #[serde(rename = "mcpArgs")]
    mcp_args: Vec<String>,
}

const EXPECTED_API_CONTRACT_VERSION: &str = "uim-api-2026-06-29-ui-import-assets";
const WINDOWS_TARGET_TRIPLE: &str = "x86_64-pc-windows-msvc";
const SIDECAR_BASE_NAME: &str = "uim-backend";
const SIDECAR_SUPPORT_DIR: &str = "uim-backend-support";

struct BackendRuntime {
    root: PathBuf,
    command: PathBuf,
    args: Vec<String>,
    backend: Option<PathBuf>,
    kind: &'static str,
    mcp_args: Vec<String>,
}

fn backend_online() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], 8765));
    TcpStream::connect_timeout(&addr, Duration::from_millis(150)).is_ok()
}

fn backend_has_current_routes() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], 8765));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(250)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let request = b"GET /health HTTP/1.1\r\nHost: 127.0.0.1:8765\r\nConnection: close\r\n\r\n";
    if stream.write_all(request).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    let Some(body) = response.split("\r\n\r\n").nth(1) else {
        return false;
    };
    let Ok(json) = serde_json::from_str::<serde_json::Value>(body) else {
        return false;
    };
    json.get("status").and_then(|value| value.as_str()) == Some("ok")
        && json.get("apiContractVersion").and_then(|value| value.as_str()) == Some(EXPECTED_API_CONTRACT_VERSION)
}

fn stop_stale_backend() {
    #[cfg(target_os = "windows")]
    {
        let _ = Command::new("powershell")
            .arg("-NoProfile")
            .arg("-ExecutionPolicy")
            .arg("Bypass")
            .arg("-Command")
            .arg("$connections = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue; foreach ($connection in $connections) { Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue }")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

fn project_root_from_current_dir() -> Option<PathBuf> {
    let current = std::env::current_dir().ok()?;
    if current.join("backend").exists() {
        return Some(current);
    }
    let parent = current.parent()?;
    if parent.join("backend").exists() {
        return Some(parent.to_path_buf());
    }
    None
}

fn bundled_root(app: &tauri::AppHandle) -> Option<PathBuf> {
    app.path().resource_dir().ok()
}

fn first_existing(paths: impl IntoIterator<Item = PathBuf>) -> Option<PathBuf> {
    paths.into_iter().find(|path| path.exists())
}

fn source_backend_runtime(root: &Path) -> Option<BackendRuntime> {
    let backend = root.join("backend");
    let python = root.join(".venv").join("Scripts").join("python.exe");
    if !backend.exists() || !python.exists() {
        return None;
    }
    Some(BackendRuntime {
        root: root.to_path_buf(),
        command: python,
        args: vec!["-m".to_string(), "uim_core.api".to_string()],
        backend: Some(backend),
        kind: "python-source",
        mcp_args: vec!["-m".to_string(), "uim_core.mcp_server".to_string()],
    })
}

fn legacy_resource_backend_runtime(root: &Path) -> Option<BackendRuntime> {
    let backend = root.join("backend");
    let python = root.join(".venv").join("Scripts").join("python.exe");
    if !backend.exists() || !python.exists() {
        return None;
    }
    Some(BackendRuntime {
        root: root.to_path_buf(),
        command: python,
        args: vec!["-m".to_string(), "uim_core.api".to_string()],
        backend: Some(backend),
        kind: "python-resource",
        mcp_args: vec!["-m".to_string(), "uim_core.mcp_server".to_string()],
    })
}

fn sidecar_executable(resource_root: &Path) -> Option<PathBuf> {
    let exe_name = format!("{SIDECAR_BASE_NAME}-{WINDOWS_TARGET_TRIPLE}.exe");
    first_existing([
        resource_root.join("binaries").join(&exe_name),
        resource_root.join(&exe_name),
        resource_root.join("binaries").join(format!("{SIDECAR_BASE_NAME}.exe")),
        resource_root.join(format!("{SIDECAR_BASE_NAME}.exe")),
    ])
}

fn sidecar_backend_runtime(resource_root: &Path) -> Option<BackendRuntime> {
    let executable = sidecar_executable(resource_root)?;
    let root = executable.parent().unwrap_or(resource_root).to_path_buf();
    let support = root.join(SIDECAR_SUPPORT_DIR);
    Some(BackendRuntime {
        root,
        command: executable,
        args: Vec::new(),
        backend: Some(support),
        kind: "sidecar",
        mcp_args: vec!["--mcp".to_string()],
    })
}

fn backend_runtime(app: &tauri::AppHandle) -> Option<BackendRuntime> {
    if let Some(project_root) = project_root_from_current_dir() {
        if let Some(runtime) = source_backend_runtime(&project_root) {
            return Some(runtime);
        }
    }
    if let Some(resource_root) = bundled_root(app) {
        if let Some(runtime) = sidecar_backend_runtime(&resource_root) {
            return Some(runtime);
        }
        if let Some(runtime) = legacy_resource_backend_runtime(&resource_root) {
            return Some(runtime);
        }
    }
    None
}

fn app_root(app: &tauri::AppHandle) -> PathBuf {
    backend_runtime(app)
        .map(|runtime| runtime.root)
        .or_else(|| project_root_from_current_dir())
        .or_else(|| bundled_root(app))
        .unwrap_or_else(|| PathBuf::from("."))
}

fn backend_logs(root: &Path) -> (PathBuf, PathBuf) {
    let log_dir = root.join("logs");
    let _ = fs::create_dir_all(&log_dir);
    (
        log_dir.join("backend-worker.out.log"),
        log_dir.join("backend-worker.err.log"),
    )
}

fn start_backend(app: &tauri::AppHandle) -> Option<Child> {
    if backend_online() && backend_has_current_routes() {
        return None;
    }
    if backend_online() {
        stop_stale_backend();
        std::thread::sleep(Duration::from_millis(250));
    }

    let runtime = backend_runtime(app)?;
    let root = runtime.root.clone();
    let (stdout_log, stderr_log) = backend_logs(&root);
    let stdout = File::create(stdout_log).ok()?;
    let stderr = File::create(stderr_log).ok()?;

    let mut command = Command::new(&runtime.command);
    command
        .env("NO_PROXY", "127.0.0.1,localhost")
        .env("no_proxy", "127.0.0.1,localhost")
        .current_dir(&root)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    command.args(&runtime.args);
    if let Some(backend) = runtime.backend.as_ref().filter(|path| path.exists()) {
        command.env("PYTHONPATH", backend);
    }

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }

    command.spawn().ok()
}

fn backend_status_for(app: &tauri::AppHandle) -> BackendStatus {
    let root = app_root(app);
    let (stdout_log, stderr_log) = backend_logs(&root);
    BackendStatus {
        online: backend_online(),
        stdout_log: Some(stdout_log.to_string_lossy().to_string()),
        stderr_log: Some(stderr_log.to_string_lossy().to_string()),
    }
}

fn mcp_runtime_paths_for(app: &tauri::AppHandle) -> McpRuntimePaths {
    if let Some(runtime) = backend_runtime(app) {
        let backend = runtime.backend.clone().unwrap_or_else(|| runtime.root.join("backend"));
        let available = runtime.command.exists() && (runtime.kind == "sidecar" || backend.exists());
        return McpRuntimePaths {
            root: runtime.root.to_string_lossy().to_string(),
            python: runtime.command.to_string_lossy().to_string(),
            backend: backend.to_string_lossy().to_string(),
            available,
            runtime_kind: runtime.kind.to_string(),
            mcp_args: runtime.mcp_args,
        };
    }
    let root = app_root(app);
    McpRuntimePaths {
        root: root.to_string_lossy().to_string(),
        python: PathBuf::from("python").to_string_lossy().to_string(),
        backend: root.join("backend").to_string_lossy().to_string(),
        available: false,
        runtime_kind: "missing".to_string(),
        mcp_args: vec!["-m".to_string(), "uim_core.mcp_server".to_string()],
    }
}

#[tauri::command]
fn backend_worker_status(app: tauri::AppHandle) -> BackendStatus {
    backend_status_for(&app)
}

#[tauri::command]
fn mcp_runtime_paths(app: tauri::AppHandle) -> McpRuntimePaths {
    mcp_runtime_paths_for(&app)
}

#[tauri::command]
fn restart_backend_worker(app: tauri::AppHandle, worker: tauri::State<BackendWorker>) -> BackendStatus {
    if backend_online() && backend_has_current_routes() {
        return backend_status_for(&app);
    }
    if let Ok(mut child_guard) = worker.0.lock() {
        if let Some(mut child) = child_guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        *child_guard = start_backend(&app);
    }
    backend_status_for(&app)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            backend_worker_status,
            mcp_runtime_paths,
            restart_backend_worker
        ])
        .setup(|app| {
            let child = start_backend(app.handle());
            app.manage(BackendWorker(Mutex::new(child)));
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                let child = {
                    let worker = window.app_handle().state::<BackendWorker>();
                    let child = match worker.0.lock() {
                        Ok(mut child_guard) => child_guard.take(),
                        Err(_) => None,
                    };
                    child
                };
                if let Some(mut child) = child {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
