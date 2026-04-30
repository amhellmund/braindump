use std::fs;
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::time::Duration;

use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

// ---------------------------------------------------------------------------
// Workspace helpers
// ---------------------------------------------------------------------------

/// Returns the workspace directory.
/// Falls back to ~/braindump-workspace.
/// Override with BRAINDUMP_TAURI_WORKSPACE env var.
fn resolve_workspace() -> PathBuf {
    if let Ok(env_ws) = std::env::var("BRAINDUMP_TAURI_WORKSPACE") {
        return PathBuf::from(env_ws);
    }
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("braindump-workspace")
}

/// Polls TCP port 8000 until it accepts connections or retries are exhausted.
/// Called from a blocking thread; each retry sleeps 500 ms → max wait = retries × 0.5 s.
fn wait_for_port(port: u16, max_retries: u32) -> bool {
    for _ in 0..max_retries {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

/// Write a default llm.json so `braindump run` works on first launch without
/// requiring the user to go through the interactive `braindump init` wizard.
fn ensure_llm_config(config_dir: &Path) -> std::io::Result<()> {
    let llm_json = config_dir.join("llm.json");
    if !llm_json.exists() {
        let default_config = serde_json::json!({
            "model": "claude-sonnet-4-6",
            "health_check_interval_minutes": 60,
            "env_file": null
        });
        fs::write(llm_json, serde_json::to_string_pretty(&default_config).unwrap())?;
    }
    Ok(())
}

/// Create the minimum workspace layout that `braindump run` expects.
/// The FastAPI lifespan handler (wiki.init_wiki) creates the wiki/ tree at startup.
fn bootstrap_workspace(workspace: &Path) -> std::io::Result<()> {
    fs::create_dir_all(workspace.join("spikes"))?;
    let config_dir = workspace.join(".config");
    fs::create_dir_all(&config_dir)?;
    ensure_llm_config(&config_dir)
}

// ---------------------------------------------------------------------------
// Tauri entry point
// ---------------------------------------------------------------------------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let handle = app.handle().clone();
            let workspace = resolve_workspace();

            tauri::async_runtime::spawn(async move {
                let workspace_str = workspace.to_string_lossy().to_string();

                // Ensure the workspace and default config exist before starting the backend.
                if let Err(e) = bootstrap_workspace(&workspace) {
                    eprintln!("[tauri] Failed to bootstrap workspace at {workspace_str}: {e}");
                    return;
                }

                eprintln!("[tauri] Using workspace: {workspace_str}");

                // Spawn the backend (long-running — do NOT await its completion).
                let spawn_result = handle
                    .shell()
                    .sidecar("braindump")
                    .expect("braindump sidecar not registered — check bundle.externalBin in tauri.conf.json")
                    .args(["run", &workspace_str])
                    .spawn();

                let (mut rx, child) = match spawn_result {
                    Ok(pair) => pair,
                    Err(e) => {
                        eprintln!("[tauri] Failed to spawn braindump backend: {e}");
                        return;
                    }
                };

                eprintln!("[tauri] Waiting for backend on port 8000…");

                // Poll in a blocking thread so we don't block the async runtime.
                // max wait: 120 retries × 500 ms = 60 s.
                let ready = tauri::async_runtime::spawn_blocking(|| wait_for_port(8000, 120))
                    .await
                    .unwrap_or(false);

                if ready {
                    eprintln!("[tauri] Backend ready — opening UI");
                    if let Some(window) = handle.get_webview_window("main") {
                        let _ = window
                            .navigate("http://localhost:8000".parse().expect("valid URL"));
                        let _ = window.show();
                    }
                } else {
                    eprintln!("[tauri] Backend did not become ready within 60 s — giving up");
                }

                // Keep child alive and forward stderr for diagnostics.
                // This loop runs for the lifetime of the app process.
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stderr(line) => {
                            eprintln!("[braindump] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stdout(line) => {
                            eprintln!("[braindump] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[braindump] process terminated: code={:?}", payload.code);
                            break;
                        }
                        _ => {}
                    }
                }

                // Explicit drop makes it clear we own the child for the full lifetime above.
                drop(child);
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application")
}
