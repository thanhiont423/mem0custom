#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod core;
use core::{cmd, history::{HistoryState, LoggedMessage}, setup, window};
use tauri::{Listener, Manager};
use tauri_plugin_log::{Target, TargetKind};

fn main() {
    tauri::Builder::default()
        // LOG plugin: ghi mọi log ra file app.log + stdout
        .plugin(
            tauri_plugin_log::Builder::default()
                .targets([
                    Target::new(TargetKind::Stdout),
                    Target::new(TargetKind::LogDir { file_name: Some("app".into()) }),
                    Target::new(TargetKind::Webview),
                ])
                .level(log::LevelFilter::Info)
                .level_for("chatgpt::core::history", log::LevelFilter::Debug)
                .max_file_size(10_000_000) // 10 MB rotate
                .rotation_strategy(tauri_plugin_log::RotationStrategy::KeepAll)
                .timezone_strategy(tauri_plugin_log::TimezoneStrategy::UseLocal)
                .build(),
        )
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(HistoryState::default())
        .invoke_handler(tauri::generate_handler![
            cmd::view_reload,
            cmd::view_url,
            cmd::view_go_forward,
            cmd::view_go_back,
            cmd::set_view_ask,
            cmd::get_app_conf,
            cmd::window_pin,
            cmd::ask_sync,
            cmd::ask_send,
            cmd::set_theme,
            cmd::log_message,
            cmd::compact_session,
            window::open_settings,
        ])
        .setup(|app| {
            log::info!("[app] starting ChatGPT Desktop");
            log::info!("[app] exe = {:?}", std::env::current_exe().ok());
            log::info!("[app] version = {}", env!("CARGO_PKG_VERSION"));

            let handle = app.handle().clone();
            let state = handle.state::<HistoryState>();
            match core::history::init_session(&handle, &state) {
                Ok(meta) => log::info!("[app] init_session OK: {}", meta.session_id),
                Err(e) => log::error!("[app] init_session failed: {}", e),
            }

            // Event listeners (CSP-safe via postMessage)
            let log_handle = app.handle().clone();
            app.listen_any("chat-logger://log-message", move |event| {
                #[derive(serde::Deserialize)]
                struct Payload {
                    id: String,
                    #[serde(rename = "conversationId")]
                    conversation_id: String,
                    role: String,
                    content: String,
                }
                match serde_json::from_str::<Payload>(event.payload()) {
                    Ok(p) => {
                        let captured_at = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)
                            .map(|d| d.as_secs())
                            .unwrap_or(0);
                        let msg = LoggedMessage {
                            id: p.id,
                            conversation_id: p.conversation_id,
                            role: p.role,
                            content: p.content,
                            captured_at,
                        };
                        let state = log_handle.state::<HistoryState>();
                        if let Err(e) = core::history::log_message(&log_handle, &state, msg) {
                            log::error!("[event] log_message failed: {}", e);
                        }
                    }
                    Err(e) => log::error!("[event] log-message payload parse failed: {}", e),
                }
            });

            let compact_handle = app.handle().clone();
            app.listen_any("chat-logger://compact", move |_event| {
                log::info!("[event] compact triggered from frontend");
                let state = compact_handle.state::<HistoryState>();
                match core::history::compact_session(&compact_handle, &state, "compact") {
                    Ok(Some(p)) => log::info!("[event] compact OK: {}", p.display()),
                    Ok(None) => log::info!("[event] compact: empty buffer, only rotated"),
                    Err(e) => log::error!("[event] compact failed: {}", e),
                }
            });

            setup::init(app)
        })
        .build(tauri::generate_context!())
        .expect("error while building lencx/ChatGPT application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                log::info!("[app] exit requested, auto-compacting");
                let state = app_handle.state::<HistoryState>();
                match core::history::compact_session(app_handle, &state, "app_exit") {
                    Ok(Some(p)) => log::info!("[app] auto-compact OK: {}", p.display()),
                    Ok(None) => log::info!("[app] auto-compact: empty buffer"),
                    Err(e) => log::error!("[app] auto-compact failed: {}", e),
                }
            }
        });
}
