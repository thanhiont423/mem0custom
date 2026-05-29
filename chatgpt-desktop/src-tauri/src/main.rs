// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod core;
use core::{cmd, history::HistoryState, setup, window};
use tauri::Manager;

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
            // Init chat history session (handles crash recovery from previous run)
            let handle = app.handle().clone();
            let state = handle.state::<HistoryState>();
            if let Err(e) = core::history::init_session(&handle, &state) {
                eprintln!("[history] init_session failed: {}", e);
            }
            setup::init(app)
        })
        .build(tauri::generate_context!())
        .expect("error while building lencx/ChatGPT application")
        .run(|app_handle, event| {
            // Auto-flush remaining session when app exits
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let state = app_handle.state::<HistoryState>();
                if let Err(e) = core::history::compact_session(app_handle, &state, "app_exit") {
                    eprintln!("[history] auto-compact on exit failed: {}", e);
                }
            }
        });
}
