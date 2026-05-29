// Chat history module — WAL + per-session JSON export với AUTO-PORTABLE detection
//
// Auto-portable logic:
//   - Nếu exe nằm trong "Program Files" (cài qua installer) -> lưu vào %APPDATA%
//   - Nếu exe nằm chỗ khác (USB, Downloads, portable run) -> lưu cạnh exe trong ./data/
//   - User có thể ép portable mode bằng cách tạo file `portable.flag` cạnh exe
//   - User có thể ép appdata mode bằng cách tạo file `use-appdata.flag` cạnh exe
//
// Log: mọi hành vi (init, log_message, compact, recovery) đều log qua `log` crate
// (output qua tauri-plugin-log -> file app.log + console)

use chrono::Local;
use log::{debug, error, info, warn};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    sync::Mutex,
    time::{SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Manager};

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct LoggedMessage {
    pub id: String,
    pub conversation_id: String,
    pub role: String,
    pub content: String,
    pub captured_at: u64,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct SessionMeta {
    pub session_id: String,
    pub started_at: u64,
    pub started_at_iso: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct SessionFile {
    pub session_id: String,
    pub started_at: u64,
    pub started_at_iso: String,
    pub exported_at: u64,
    pub exported_at_iso: String,
    pub exported_via: String,
    pub message_count: usize,
    pub messages: Vec<LoggedMessage>,
}

#[derive(Default)]
pub struct HistoryState {
    pub buffer: Mutex<Vec<LoggedMessage>>,
    pub session: Mutex<Option<SessionMeta>>,
}

// ---------- Path helpers (AUTO-PORTABLE) ----------

fn detect_portable_mode() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let exe_dir = exe.parent()?.to_path_buf();

    // 1. Explicit override files
    if exe_dir.join("use-appdata.flag").exists() {
        info!("[portable] use-appdata.flag found -> AppData mode");
        return None;
    }
    if exe_dir.join("portable.flag").exists() {
        info!("[portable] portable.flag found -> portable mode (data cạnh exe)");
        return Some(exe_dir.join("data"));
    }

    // 2. Auto-detect: KHÔNG Program Files = portable
    let exe_str = exe_dir.to_string_lossy().to_lowercase();
    let in_program_files = exe_str.contains("program files")
        || exe_str.contains("programfiles")
        || exe_str.contains("\\windows\\")
        || exe_str.contains("/applications/")
        || exe_str.contains("/usr/")
        || exe_str.contains("/opt/");

    if in_program_files {
        info!("[portable] exe in system install dir ({}) -> AppData mode", exe_str);
        return None;
    }

    // 3. Verify can write
    let data_dir = exe_dir.join("data");
    if fs::create_dir_all(&data_dir).is_err() {
        warn!("[portable] cannot create ./data cạnh exe -> fallback AppData");
        return None;
    }
    let test_file = data_dir.join(".write_test");
    match fs::write(&test_file, b"x") {
        Ok(_) => {
            let _ = fs::remove_file(&test_file);
            info!("[portable] auto-detected portable mode -> {}", data_dir.display());
            Some(data_dir)
        }
        Err(e) => {
            warn!("[portable] write test failed ({}) -> fallback AppData", e);
            None
        }
    }
}

fn root_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = if let Some(portable) = detect_portable_mode() {
        portable.join("com.nofwl.chatgpt")
    } else {
        app.path()
            .app_data_dir()
            .map_err(|e| e.to_string())?
            .join("com.nofwl.chatgpt")
    };
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    debug!("[history] root_dir resolved: {}", dir.display());
    Ok(dir)
}

fn wal_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(root_dir(app)?.join("current.wal"))
}

fn session_meta_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(root_dir(app)?.join("current.session"))
}

fn sessions_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = root_dir(app)?.join("sessions");
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir)
}

fn recovered_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = sessions_dir(app)?.join("recovered");
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir)
}

fn now_ts() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn now_iso() -> String {
    Local::now().to_rfc3339()
}

fn now_filename_stamp() -> String {
    Local::now().format("%Y%m%d-%H%M%S").to_string()
}

fn make_session_id(seed: u64) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.subsec_nanos())
        .unwrap_or(0);
    let mix = seed.wrapping_mul(0x9E3779B97F4A7C15).wrapping_add(nanos as u64);
    format!("s{:07x}", mix & 0xFFFFFFF)
}

pub fn init_session(app: &AppHandle, state: &HistoryState) -> Result<SessionMeta, String> {
    info!("[history] init_session starting");
    let meta_path = session_meta_path(app)?;
    let wal = wal_path(app)?;

    if meta_path.exists() {
        info!("[history] found stale session from previous run -> checking WAL");
        let old_meta_raw = fs::read_to_string(&meta_path).map_err(|e| e.to_string())?;
        let old_meta: SessionMeta =
            serde_json::from_str(&old_meta_raw).map_err(|e| e.to_string())?;

        if wal.exists() {
            let msgs = read_wal(&wal)?;
            if !msgs.is_empty() {
                info!("[history] CRASH RECOVERY: {} messages in WAL, dumping to recovered/", msgs.len());
                let dir = recovered_dir(app)?;
                let fname = format!(
                    "session_recovered_{}_{}.json",
                    old_meta.session_id,
                    now_filename_stamp()
                );
                let now = now_ts();
                let session_file = SessionFile {
                    session_id: old_meta.session_id.clone(),
                    started_at: old_meta.started_at,
                    started_at_iso: old_meta.started_at_iso.clone(),
                    exported_at: now,
                    exported_at_iso: now_iso(),
                    exported_via: "crash_recovery".to_string(),
                    message_count: msgs.len(),
                    messages: msgs,
                };
                let pretty =
                    serde_json::to_string_pretty(&session_file).map_err(|e| e.to_string())?;
                let recovery_path = dir.join(&fname);
                fs::write(&recovery_path, pretty).map_err(|e| e.to_string())?;
                info!("[history] recovery file written: {}", recovery_path.display());
            } else {
                debug!("[history] WAL exists but empty, skipping recovery");
            }
            let _ = fs::remove_file(&wal);
        }
        let _ = fs::remove_file(&meta_path);
    }

    let ts = now_ts();
    let meta = SessionMeta {
        session_id: make_session_id(ts),
        started_at: ts,
        started_at_iso: now_iso(),
    };
    fs::write(
        &meta_path,
        serde_json::to_string_pretty(&meta).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    File::create(&wal).map_err(|e| e.to_string())?;

    *state.session.lock().unwrap() = Some(meta.clone());
    state.buffer.lock().unwrap().clear();
    info!("[history] new session created: id={}", meta.session_id);
    Ok(meta)
}

pub fn log_message(
    app: &AppHandle,
    state: &HistoryState,
    msg: LoggedMessage,
) -> Result<(), String> {
    let wal = wal_path(app)?;
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&wal)
        .map_err(|e| e.to_string())?;
    let line = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
    writeln!(f, "{}", line).map_err(|e| e.to_string())?;
    let _ = f.sync_data();
    debug!(
        "[history] log_message: role={} id={} content_len={}",
        msg.role,
        msg.id,
        msg.content.len()
    );
    state.buffer.lock().unwrap().push(msg);
    Ok(())
}

pub fn compact_session(
    app: &AppHandle,
    state: &HistoryState,
    via: &str,
) -> Result<Option<PathBuf>, String> {
    info!("[history] compact_session triggered via='{}'", via);
    let wal = wal_path(app)?;
    let msgs = if wal.exists() { read_wal(&wal)? } else { vec![] };

    let meta = state.session.lock().unwrap().clone();
    let meta = match meta {
        Some(m) => m,
        None => {
            error!("[history] compact failed: no active session");
            return Err("No active session — call init_session first".into());
        }
    };

    if msgs.is_empty() {
        warn!("[history] compact: buffer empty, only rotating session");
        rotate_session(app, state)?;
        return Ok(None);
    }

    let now = now_ts();
    let session_file = SessionFile {
        session_id: meta.session_id.clone(),
        started_at: meta.started_at,
        started_at_iso: meta.started_at_iso.clone(),
        exported_at: now,
        exported_at_iso: now_iso(),
        exported_via: via.to_string(),
        message_count: msgs.len(),
        messages: msgs,
    };

    let dir = sessions_dir(app)?;
    let fname = format!(
        "session_{}_{}.json",
        meta.session_id,
        now_filename_stamp()
    );
    let path = dir.join(&fname);
    let pretty = serde_json::to_string_pretty(&session_file).map_err(|e| e.to_string())?;
    fs::write(&path, pretty).map_err(|e| e.to_string())?;
    info!(
        "[history] compact OK: {} messages -> {}",
        session_file.message_count,
        path.display()
    );

    let _ = fs::remove_file(&wal);
    rotate_session(app, state)?;
    Ok(Some(path))
}

fn rotate_session(app: &AppHandle, state: &HistoryState) -> Result<(), String> {
    let ts = now_ts();
    let meta = SessionMeta {
        session_id: make_session_id(ts),
        started_at: ts,
        started_at_iso: now_iso(),
    };
    fs::write(
        session_meta_path(app)?,
        serde_json::to_string_pretty(&meta).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    File::create(wal_path(app)?).map_err(|e| e.to_string())?;
    debug!("[history] session rotated: new id={}", meta.session_id);
    *state.session.lock().unwrap() = Some(meta);
    state.buffer.lock().unwrap().clear();
    Ok(())
}

fn read_wal(path: &PathBuf) -> Result<Vec<LoggedMessage>, String> {
    let f = File::open(path).map_err(|e| e.to_string())?;
    let reader = BufReader::new(f);
    let mut out = Vec::new();
    let mut corrupt = 0;
    for line in reader.lines() {
        let line = line.map_err(|e| e.to_string())?;
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        match serde_json::from_str::<LoggedMessage>(trimmed) {
            Ok(m) => out.push(m),
            Err(_) => {
                corrupt += 1;
                continue;
            }
        }
    }
    if corrupt > 0 {
        warn!("[history] read_wal: {} corrupt lines skipped", corrupt);
    }
    Ok(out)
}

// ===========================================================================
// Unit tests — chỉ test logic không cần AppHandle
// ===========================================================================
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_session_id_format() {
        for i in 0..50 {
            let id = make_session_id(now_ts().wrapping_add(i));
            assert!(id.starts_with('s'));
            assert_eq!(id.len(), 8);
        }
    }

    #[test]
    fn test_filename_stamp_format() {
        let stamp = now_filename_stamp();
        assert_eq!(stamp.len(), 15);
        assert_eq!(&stamp[8..9], "-");
    }

    #[test]
    fn test_session_serialize() {
        let sf = SessionFile {
            session_id: "s1234567".into(),
            started_at: 100,
            started_at_iso: "2026-01-01T00:00:00Z".into(),
            exported_at: 200,
            exported_at_iso: "2026-01-01T00:01:00Z".into(),
            exported_via: "compact".into(),
            message_count: 1,
            messages: vec![LoggedMessage {
                id: "m1".into(),
                conversation_id: "c1".into(),
                role: "user".into(),
                content: "hi".into(),
                captured_at: 150,
            }],
        };
        let json = serde_json::to_string(&sf).unwrap();
        assert!(json.contains("\"session_id\":\"s1234567\""));
        assert!(json.contains("\"role\":\"user\""));
    }
}
