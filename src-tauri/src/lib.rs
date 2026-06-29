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
}

const EXPECTED_API_CONTRACT_VERSION: &str = "uim-api-2026-06-29-ui-import-assets";

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

fn python_executable(project_root: Option<&Path>, resource_root: Option<&Path>) -> PathBuf {
    let candidates = [
        project_root.map(|root| root.join(".venv").join("Scripts").join("python.exe")),
        resource_root.map(|root| root.join(".venv").join("Scripts").join("python.exe")),
    ];
    first_existing(candidates.into_iter().flatten()).unwrap_or_else(|| PathBuf::from("python"))
}

fn backend_dir(project_root: Option<&Path>, resource_root: Option<&Path>) -> Option<PathBuf> {
    let candidates = [
        project_root.map(|root| root.join("backend")),
        resource_root.map(|root| root.join("backend")),
    ];
    first_existing(candidates.into_iter().flatten())
}

fn app_root(project_root: Option<&Path>, resource_root: Option<&Path>) -> PathBuf {
    project_root
        .or(resource_root)
        .map(Path::to_path_buf)
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

    let project_root = project_root_from_current_dir();
    let resource_root = bundled_root(app);
    let backend = backend_dir(project_root.as_deref(), resource_root.as_deref())?;
    let python = python_executable(project_root.as_deref(), resource_root.as_deref());
    let root = app_root(project_root.as_deref(), resource_root.as_deref());
    let (stdout_log, stderr_log) = backend_logs(&root);
    let stdout = File::create(stdout_log).ok()?;
    let stderr = File::create(stderr_log).ok()?;

    let mut command = Command::new(python);
    command
        .arg("-m")
        .arg("uim_core.api")
        .env("PYTHONPATH", &backend)
        .env("NO_PROXY", "127.0.0.1,localhost")
        .env("no_proxy", "127.0.0.1,localhost")
        .current_dir(&root)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }

    command.spawn().ok()
}

fn backend_status_for(app: &tauri::AppHandle) -> BackendStatus {
    let project_root = project_root_from_current_dir();
    let resource_root = bundled_root(app);
    let root = app_root(project_root.as_deref(), resource_root.as_deref());
    let (stdout_log, stderr_log) = backend_logs(&root);
    BackendStatus {
        online: backend_online(),
        stdout_log: Some(stdout_log.to_string_lossy().to_string()),
        stderr_log: Some(stderr_log.to_string_lossy().to_string()),
    }
}

fn mcp_runtime_paths_for(app: &tauri::AppHandle) -> McpRuntimePaths {
    let project_root = project_root_from_current_dir();
    let resource_root = bundled_root(app);
    let backend = backend_dir(project_root.as_deref(), resource_root.as_deref());
    let python = python_executable(project_root.as_deref(), resource_root.as_deref());
    let root = app_root(project_root.as_deref(), resource_root.as_deref());
    let available = backend.as_ref().is_some_and(|path| path.exists()) && python.exists();

    McpRuntimePaths {
        root: root.to_string_lossy().to_string(),
        python: python.to_string_lossy().to_string(),
        backend: backend
            .unwrap_or_else(|| root.join("backend"))
            .to_string_lossy()
            .to_string(),
        available,
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
