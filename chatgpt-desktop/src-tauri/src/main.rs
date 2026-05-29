#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod core;
use core::{cmd, history::{HistoryState, LoggedMessage}, setup, window};
use simplelog::{ColorChoice, CombinedLogger, ConfigBuilder, LevelFilter, TermLogger, TerminalMode, WriteLogger};
use std::fs::OpenOptions;
use tauri::{Listener, Manager};

fn init_logger() {
    let log_dir = {
        let exe = std::env::current_exe().ok();
        let exe_dir = exe.as_ref().and_then(|p| p.parent()).map(|p| p.to_path_buf());

        let portable_data = exe_dir
            .as_ref()
            .map(|d| d.join("data").join("com.nofwl.chatgpt").join("logs"));
        let portable_works = portable_data
            .as_ref()
            .map(|d| std::fs::create_dir_all(d).is_ok())
            .unwrap_or(false);

        if portable_works {
            portable_data.unwrap()
        } else {
            let base = std::env::var("APPDATA")
                .ok()
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|| std::path::PathBuf::from("."));
            let p = base.join("com.nofwl.chatgpt").join("logs");
            let _ = std::fs::create_dir_all(&p);
            p
        }
    };

    let log_file = log_dir.join("app.log");
    let cfg = ConfigBuilder::new()
        .set_time_format_rfc3339()
        .set_target_level(LevelFilter::Error)
        .build();

    let mut loggers: Vec<Box<dyn simplelog::SharedLogger>> = vec![
        TermLogger::new(LevelFilter::Info, cfg.clone(), TerminalMode::Mixed, ColorChoice::Auto),
    ];
    if let Ok(file) = OpenOptions::new().create(true).append(true).open(&log_file) {
        loggers.push(WriteLogger::new(LevelFilter::Debug, cfg, file));
    }
    let _ = CombinedLogger::init(loggers);
    log::info!("===== ChatGPT Desktop starting =====");
    log::info!("[logger] file = {}", log_file.display());
}

fn main() {
    init_logger();

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
            cmd::get_instruction,
            cmd::get_keywords,
            window::open_settings,
        ])
        .setup(|app| {
            log::info!("[app] exe = {:?}", std::env::current_exe().ok());
            log::info!("[app] version = {}", env!("CARGO_PKG_VERSION"));

            let handle = app.handle().clone();
            let state = handle.state::<HistoryState>();
            match core::history::init_session(&handle, &state) {
                Ok(meta) => log::info!("[app] init_session OK: {}", meta.session_id),
                Err(e) => log::error!("[app] init_session failed: {}", e),
            }

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
