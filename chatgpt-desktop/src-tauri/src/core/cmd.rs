use tauri::{command, AppHandle, LogicalPosition, Manager, PhysicalSize, State};

use crate::core::{
    conf::AppConf,
    constant::{ASK_HEIGHT, TITLEBAR_HEIGHT},
    history::{self, HistoryState, LoggedMessage},
};

#[command]
pub fn view_reload(app: AppHandle) {
    app.get_window("core")
        .unwrap()
        .get_webview("main")
        .unwrap()
        .eval("window.location.reload()")
        .unwrap();
}

#[command]
pub fn view_url(app: AppHandle) -> tauri::Url {
    app.get_window("core")
        .unwrap()
        .get_webview("main")
        .unwrap()
        .url()
        .unwrap()
}

#[command]
pub fn view_go_forward(app: AppHandle) {
    app.get_window("core")
        .unwrap()
        .get_webview("main")
        .unwrap()
        .eval("window.history.forward()")
        .unwrap();
}

#[command]
pub fn view_go_back(app: AppHandle) {
    app.get_window("core")
        .unwrap()
        .get_webview("main")
        .unwrap()
        .eval("window.history.back()")
        .unwrap();
}

#[command]
pub fn window_pin(app: AppHandle, pin: bool) {
    let conf = AppConf::load(&app).unwrap();
    conf.amend(serde_json::json!({"stay_on_top": pin}))
        .unwrap()
        .save(&app)
        .unwrap();

    app.get_window("core")
        .unwrap()
        .set_always_on_top(pin)
        .unwrap();
}

#[command]
pub fn ask_sync(app: AppHandle, message: String) {
    app.get_window("core")
        .unwrap()
        .get_webview("main")
        .unwrap()
        .eval(&format!("ChatAsk.sync({})", message))
        .unwrap();
}

#[command]
pub fn ask_send(app: AppHandle) {
    let win = app.get_window("core").unwrap();

    win.get_webview("main")
        .unwrap()
        .eval(
            r#"
        ChatAsk.submit();
        setTimeout(() => {
            __TAURI__.webview.Webview.getByLabel('ask')?.setFocus();
        }, 500);
        "#,
        )
        .unwrap();
}

#[command]
pub fn set_theme(app: AppHandle, theme: String) {
    let conf = AppConf::load(&app).unwrap();
    conf.amend(serde_json::json!({"theme": theme}))
        .unwrap()
        .save(&app)
        .unwrap();

    app.restart();
}

#[command]
pub fn get_app_conf(app: AppHandle) -> AppConf {
    AppConf::load(&app).unwrap()
}

// ---------- Chat history commands ----------

#[command]
pub fn log_message(
    app: AppHandle,
    state: State<HistoryState>,
    id: String,
    conversation_id: String,
    role: String,
    content: String,
) -> Result<(), String> {
    let captured_at = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    history::log_message(
        &app,
        &state,
        LoggedMessage {
            id,
            conversation_id,
            role,
            content,
            captured_at,
        },
    )
}

#[command]
pub fn compact_session(
    app: AppHandle,
    state: State<HistoryState>,
) -> Result<Option<String>, String> {
    history::compact_session(&app, &state, "compact")
        .map(|opt| opt.map(|p| p.to_string_lossy().to_string()))
}

#[command]
pub fn set_view_ask(app: AppHandle, enabled: bool) {
    let conf = AppConf::load(&app).unwrap();
    conf.amend(serde_json::json!({"ask_mode": enabled}))
        .unwrap()
        .save(&app)
        .unwrap();

    let core_window = app.get_window("core").unwrap();
    let ask_mode_height = if enabled { ASK_HEIGHT } else { 0.0 };
    let scale_factor = core_window.scale_factor().unwrap();
    let titlebar_height = (scale_factor * TITLEBAR_HEIGHT).round() as u32;
    let win_size = core_window.inner_size().unwrap();
    let ask_height = (scale_factor * ask_mode_height).round() as u32;

    let main_view = core_window.get_webview("main").unwrap();
    let titlebar_view = core_window.get_webview("titlebar").unwrap();
    let ask_view = core_window.get_webview("ask").unwrap();

    if enabled {
        ask_view.set_focus().unwrap();
    } else {
        main_view.set_focus().unwrap();
    }

    let set_view_properties =
        |view: &tauri::Webview, position: LogicalPosition<f64>, size: PhysicalSize<u32>| {
            if let Err(e) = view.set_position(position) {
                eprintln!("[cmd:view:position] Failed to set view position: {}", e);
            }
            if let Err(e) = view.set_size(size) {
                eprintln!("[cmd:view:size] Failed to set view size: {}", e);
            }
        };

    #[cfg(target_os = "macos")]
    {
        set_view_properties(
            &main_view,
            LogicalPosition::new(0.0, TITLEBAR_HEIGHT),
            PhysicalSize::new(
                win_size.width,
                win_size.height - (titlebar_height + ask_height),
            ),
        );
        set_view_properties(
            &titlebar_view,
            LogicalPosition::new(0.0, 0.0),
            PhysicalSize::new(win_size.width, titlebar_height),
        );
        set_view_properties(
            &ask_view,
            LogicalPosition::new(
                0.0,
                (win_size.height as f64 / scale_factor) - ask_mode_height,
            ),
            PhysicalSize::new(win_size.width, ask_height),
        );
    }

    #[cfg(not(target_os = "macos"))]
    {
        set_view_properties(
            &main_view,
            LogicalPosition::new(0.0, 0.0),
            PhysicalSize::new(
                win_size.width,
                win_size.height - (ask_height + titlebar_height),
            ),
        );
        set_view_properties(
            &titlebar_view,
            LogicalPosition::new(
                0.0,
                (win_size.height as f64 / scale_factor) - TITLEBAR_HEIGHT,
            ),
            PhysicalSize::new(win_size.width, titlebar_height),
        );
        set_view_properties(
            &ask_view,
            LogicalPosition::new(
                0.0,
                (win_size.height as f64 / scale_factor) - ask_mode_height - TITLEBAR_HEIGHT,
            ),
            PhysicalSize::new(win_size.width, ask_height),
        );
    }
}


// ============= v0.3.0 — instruction + keywords =============

#[command]
pub fn get_instruction(state: State<HistoryState>) -> Option<String> {
    state.session.lock().ok()
        .and_then(|s| s.clone())
        .and_then(|m| m.instruction)
}

#[command]
pub fn get_keywords(app: AppHandle) -> serde_json::Value {
    let path = match app.path().app_data_dir() {
        Ok(p) => p.join("com.nofwl.chatgpt").join("keywords.json"),
        Err(_) => return default_keywords(),
    };
    let alt = std::env::current_exe().ok()
        .and_then(|e| e.parent().map(|p| p.to_path_buf()))
        .map(|d| d.join("data").join("com.nofwl.chatgpt").join("keywords.json"));

    for p in [Some(path), alt].into_iter().flatten() {
        if p.exists() {
            if let Ok(content) = std::fs::read_to_string(&p) {
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(&content) {
                    log::info!("[keywords] loaded from {}", p.display());
                    return v;
                }
            }
        }
    }
    log::debug!("[keywords] no file -> using defaults");
    default_keywords()
}

fn default_keywords() -> serde_json::Value {
    serde_json::json!({
        "compact": "compact_session",
        "lưu": "compact_session",
        "luu": "compact_session",
        "/compact": "compact_session",
        "/lưu": "compact_session"
    })
}
