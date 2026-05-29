// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod core;
use core::{cmd, history::{HistoryState, LoggedMessage}, setup, window};
use tauri::{Listener, Manager};

fn main() {
    tauri::Builder::default()
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
            // Init chat history session
            let handle = app.handle().clone();
            let state = handle.state::<HistoryState>();
            if let Err(e) = core::history::init_session(&handle, &state) {
                eprintln!("[history] init_session failed: {}", e);
            }

            // CSP-safe IPC: listen events từ chat-logger.js (qua postMessage)
            // Bypass HTTP IPC bị CSP của chatgpt.com chặn
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
                if let Ok(p) = serde_json::from_str::<Payload>(event.payload()) {
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
                    let _ = core::history::log_message(&log_handle, &state, msg);
                }
            });

            // Compact event từ chat-logger.js (alternative trigger)
            let compact_handle = app.handle().clone();
            app.listen_any("chat-logger://compact", move |_event| {
                let state = compact_handle.state::<HistoryState>();
                let _ = core::history::compact_session(&compact_handle, &state, "compact");
            });

            setup::init(app)
        })
        .build(tauri::generate_context!())
        .expect("error while building lencx/ChatGPT application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let state = app_handle.state::<HistoryState>();
                if let Err(e) = core::history::compact_session(app_handle, &state, "app_exit") {
                    eprintln!("[history] auto-compact on exit failed: {}", e);
                }
            }
        });
}
