// Chat history module — WAL (write-ahead log) + per-session JSON export
//
// Flow:
//   1. App start  -> init_session()    : check WAL recovery, create fresh session
//   2. Every msg  -> log_message()     : append NDJSON line to current.wal + push RAM buffer
//   3. Compact    -> compact_session() : read WAL, write session_*.json, clear WAL, start new session
//   4. App exit   -> compact_session() : auto-flush remaining buffer
//
// File layout under {app_data_dir}/com.nofwl.chatgpt/:
//   - current.session  (metadata of active session)
//   - current.wal      (NDJSON, append-only)
//   - sessions/        (final per-session JSON files)
//   - sessions/recovered/ (files restored from WAL after crash)

use chrono::Local;
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
    pub exported_via: String, // "compact" | "app_exit" | "crash_recovery"
    pub message_count: usize,
    pub messages: Vec<LoggedMessage>,
}

#[derive(Default)]
pub struct HistoryState {
    pub buffer: Mutex<Vec<LoggedMessage>>,
    pub session: Mutex<Option<SessionMeta>>,
}

// ---------- Path helpers ----------

fn root_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("com.nofwl.chatgpt");
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
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

// ---------- Time helpers ----------

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
    // Short hex id derived from timestamp + nanos — collision-resistant for human use.
    // Prefix `s` so it's obvious in filenames.
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.subsec_nanos())
        .unwrap_or(0);
    let mix = seed.wrapping_mul(0x9E3779B97F4A7C15).wrapping_add(nanos as u64);
    format!("s{:07x}", mix & 0xFFFFFFF)
}

// ---------- Core operations ----------

/// Called at app startup. Recovers any WAL from previous crash, then creates a fresh session.
pub fn init_session(app: &AppHandle, state: &HistoryState) -> Result<SessionMeta, String> {
    // 1. Check if there's a stale session from previous run
    let meta_path = session_meta_path(app)?;
    let wal = wal_path(app)?;

    if meta_path.exists() {
        // Previous session exists — try to recover WAL into a recovered/ file
        let old_meta_raw = fs::read_to_string(&meta_path).map_err(|e| e.to_string())?;
        let old_meta: SessionMeta =
            serde_json::from_str(&old_meta_raw).map_err(|e| e.to_string())?;

        if wal.exists() {
            let msgs = read_wal(&wal)?;
            if !msgs.is_empty() {
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
                fs::write(dir.join(&fname), pretty).map_err(|e| e.to_string())?;
            }
            let _ = fs::remove_file(&wal);
        }
        let _ = fs::remove_file(&meta_path);
    }

    // 2. Create fresh session
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

    // Create empty WAL
    File::create(&wal).map_err(|e| e.to_string())?;

    *state.session.lock().unwrap() = Some(meta.clone());
    state.buffer.lock().unwrap().clear();
    Ok(meta)
}

/// Append a message to WAL (durable) and RAM buffer (fast read).
pub fn log_message(
    app: &AppHandle,
    state: &HistoryState,
    msg: LoggedMessage,
) -> Result<(), String> {
    // 1. Append NDJSON line to WAL (atomic at OS level for small writes)
    let wal = wal_path(app)?;
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&wal)
        .map_err(|e| e.to_string())?;
    let line = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
    writeln!(f, "{}", line).map_err(|e| e.to_string())?;
    // Best-effort fsync — survives kernel-level crashes too
    let _ = f.sync_data();

    // 2. Push to RAM buffer
    state.buffer.lock().unwrap().push(msg);
    Ok(())
}

/// Compact: write current session out as a single JSON file, clear WAL, start new session.
/// `via` = "compact" | "app_exit"
pub fn compact_session(
    app: &AppHandle,
    state: &HistoryState,
    via: &str,
) -> Result<Option<PathBuf>, String> {
    // Read source of truth from WAL (covers race where caller logged just before compact)
    let wal = wal_path(app)?;
    let msgs = if wal.exists() { read_wal(&wal)? } else { vec![] };

    let meta = state.session.lock().unwrap().clone();
    let meta = match meta {
        Some(m) => m,
        None => return Err("No active session — call init_session first".into()),
    };

    if msgs.is_empty() {
        // Nothing to export; still rotate session id so next batch is fresh
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

    // Clear WAL + buffer, then rotate session
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
    *state.session.lock().unwrap() = Some(meta);
    state.buffer.lock().unwrap().clear();
    Ok(())
}

fn read_wal(path: &PathBuf) -> Result<Vec<LoggedMessage>, String> {
    let f = File::open(path).map_err(|e| e.to_string())?;
    let reader = BufReader::new(f);
    let mut out = Vec::new();
    for line in reader.lines() {
        let line = line.map_err(|e| e.to_string())?;
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        // Tolerate corrupt last line (crash mid-write)
        match serde_json::from_str::<LoggedMessage>(trimmed) {
            Ok(m) => out.push(m),
            Err(_) => continue,
        }
    }
    Ok(out)
}

// ===========================================================================
// Pure-function unit tests (no AppHandle required) — verify logic
// independently of Tauri. Run with: cargo test --lib core::history
// ===========================================================================
#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use tempfile::TempDir;

    /// Mini-runtime mimicking what AppHandle gives us in production.
    struct TestEnv {
        _tmp: TempDir,
        root: PathBuf,
    }

    impl TestEnv {
        fn new() -> Self {
            let tmp = TempDir::new().unwrap();
            let root = tmp.path().join("com.nofwl.chatgpt");
            std::fs::create_dir_all(&root).unwrap();
            std::fs::create_dir_all(root.join("sessions")).unwrap();
            std::fs::create_dir_all(root.join("sessions").join("recovered")).unwrap();
            TestEnv { _tmp: tmp, root }
        }
        fn wal(&self) -> PathBuf { self.root.join("current.wal") }
        fn meta(&self) -> PathBuf { self.root.join("current.session") }
        fn sessions(&self) -> PathBuf { self.root.join("sessions") }
        fn recovered(&self) -> PathBuf { self.root.join("sessions").join("recovered") }
    }

    /// Test variants of init/log/compact that take explicit paths instead of AppHandle.
    fn t_init(env: &TestEnv) -> SessionMeta {
        let ts = now_ts();
        let meta = SessionMeta {
            session_id: make_session_id(ts),
            started_at: ts,
            started_at_iso: now_iso(),
        };
        std::fs::write(env.meta(), serde_json::to_string_pretty(&meta).unwrap()).unwrap();
        File::create(env.wal()).unwrap();
        meta
    }

    fn t_log(env: &TestEnv, msg: &LoggedMessage) {
        let mut f = OpenOptions::new().create(true).append(true).open(env.wal()).unwrap();
        writeln!(f, "{}", serde_json::to_string(msg).unwrap()).unwrap();
    }

    fn t_compact(env: &TestEnv, meta: &SessionMeta, via: &str) -> Option<PathBuf> {
        let msgs = if env.wal().exists() { read_wal(&env.wal()).unwrap() } else { vec![] };
        if msgs.is_empty() { return None; }
        let now = now_ts();
        let sf = SessionFile {
            session_id: meta.session_id.clone(),
            started_at: meta.started_at,
            started_at_iso: meta.started_at_iso.clone(),
            exported_at: now,
            exported_at_iso: now_iso(),
            exported_via: via.to_string(),
            message_count: msgs.len(),
            messages: msgs,
        };
        let fname = format!("session_{}_{}.json", meta.session_id, now_filename_stamp());
        let path = env.sessions().join(fname);
        std::fs::write(&path, serde_json::to_string_pretty(&sf).unwrap()).unwrap();
        let _ = std::fs::remove_file(env.wal());
        Some(path)
    }

    fn mkmsg(id: &str, role: &str, content: &str) -> LoggedMessage {
        LoggedMessage {
            id: id.into(),
            conversation_id: "conv-1".into(),
            role: role.into(),
            content: content.into(),
            captured_at: now_ts(),
        }
    }

    #[test]
    fn test_init_creates_meta_and_empty_wal() {
        let env = TestEnv::new();
        let meta = t_init(&env);
        assert!(env.meta().exists());
        assert!(env.wal().exists());
        assert!(meta.session_id.starts_with('s'));
        assert_eq!(std::fs::read_to_string(env.wal()).unwrap(), "");
    }

    #[test]
    fn test_log_appends_ndjson() {
        let env = TestEnv::new();
        t_init(&env);
        t_log(&env, &mkmsg("m1", "user", "hello"));
        t_log(&env, &mkmsg("m2", "assistant", "hi there"));

        let content = std::fs::read_to_string(env.wal()).unwrap();
        let lines: Vec<&str> = content.trim().split('\n').collect();
        assert_eq!(lines.len(), 2);
        let m1: LoggedMessage = serde_json::from_str(lines[0]).unwrap();
        assert_eq!(m1.id, "m1");
        assert_eq!(m1.role, "user");
        assert_eq!(m1.content, "hello");
    }

    #[test]
    fn test_compact_produces_valid_json_file() {
        let env = TestEnv::new();
        let meta = t_init(&env);
        t_log(&env, &mkmsg("u1", "user", "Q1"));
        t_log(&env, &mkmsg("a1", "assistant", "A1"));

        let out = t_compact(&env, &meta, "compact").unwrap();
        assert!(out.exists());
        assert!(out.file_name().unwrap().to_string_lossy()
            .starts_with(&format!("session_{}_", meta.session_id)));
        assert!(!env.wal().exists(), "WAL should be removed after compact");

        let raw = std::fs::read_to_string(&out).unwrap();
        let sf: SessionFile = serde_json::from_str(&raw).unwrap();
        assert_eq!(sf.message_count, 2);
        assert_eq!(sf.exported_via, "compact");
        assert_eq!(sf.session_id, meta.session_id);
        assert_eq!(sf.messages[0].content, "Q1");
    }

    #[test]
    fn test_compact_empty_buffer_returns_none() {
        let env = TestEnv::new();
        let meta = t_init(&env);
        let out = t_compact(&env, &meta, "compact");
        assert!(out.is_none());
    }

    #[test]
    fn test_crash_recovery_from_wal() {
        let env = TestEnv::new();
        let old_meta = t_init(&env);
        t_log(&env, &mkmsg("m1", "user", "before crash"));
        t_log(&env, &mkmsg("m2", "assistant", "answer"));

        // Simulate crash: meta + wal still on disk, no compact happened.
        // Now boot scenario: read old meta, dump WAL into recovered/
        assert!(env.meta().exists());
        assert!(env.wal().exists());

        let old_meta_raw = std::fs::read_to_string(env.meta()).unwrap();
        let old_meta_parsed: SessionMeta = serde_json::from_str(&old_meta_raw).unwrap();
        assert_eq!(old_meta_parsed.session_id, old_meta.session_id);

        let msgs = read_wal(&env.wal()).unwrap();
        assert_eq!(msgs.len(), 2);

        let now = now_ts();
        let sf = SessionFile {
            session_id: old_meta_parsed.session_id.clone(),
            started_at: old_meta_parsed.started_at,
            started_at_iso: old_meta_parsed.started_at_iso.clone(),
            exported_at: now,
            exported_at_iso: now_iso(),
            exported_via: "crash_recovery".into(),
            message_count: msgs.len(),
            messages: msgs,
        };
        let fname = format!("session_recovered_{}_{}.json", sf.session_id, now_filename_stamp());
        let path = env.recovered().join(&fname);
        std::fs::write(&path, serde_json::to_string_pretty(&sf).unwrap()).unwrap();

        let raw = std::fs::read_to_string(&path).unwrap();
        let restored: SessionFile = serde_json::from_str(&raw).unwrap();
        assert_eq!(restored.exported_via, "crash_recovery");
        assert_eq!(restored.message_count, 2);
        assert_eq!(restored.messages[0].content, "before crash");
    }

    #[test]
    fn test_wal_tolerates_corrupt_last_line() {
        let env = TestEnv::new();
        t_init(&env);
        t_log(&env, &mkmsg("m1", "user", "good line"));

        // Append a torn / corrupt line at end (simulate crash mid-write)
        let mut f = OpenOptions::new().append(true).open(env.wal()).unwrap();
        writeln!(f, "{{\"id\":\"m2\",\"role\":\"user\",\"con").unwrap();
        drop(f);

        let msgs = read_wal(&env.wal()).unwrap();
        assert_eq!(msgs.len(), 1, "Corrupt line must be skipped, good line kept");
        assert_eq!(msgs[0].id, "m1");
    }

    #[test]
    fn test_session_id_is_unique_per_call() {
        let mut seen = std::collections::HashSet::new();
        for i in 0..50 {
            let id = make_session_id(now_ts().wrapping_add(i));
            assert!(id.starts_with('s'));
            assert!(seen.insert(id.clone()), "Duplicate session id: {}", id);
        }
    }

    #[test]
    fn test_session_filename_contains_session_id_and_time() {
        let env = TestEnv::new();
        let meta = t_init(&env);
        t_log(&env, &mkmsg("x1", "user", "hello"));
        let out = t_compact(&env, &meta, "compact").unwrap();
        let fname = out.file_name().unwrap().to_string_lossy().to_string();
        // session_{id}_{YYYYMMDD-HHMMSS}.json
        assert!(fname.contains(&meta.session_id), "filename missing session_id");
        assert!(fname.ends_with(".json"));
        // Time stamp portion has 8 digits + '-' + 6 digits
        let re = regex::Regex::new(r"_\d{8}-\d{6}\.json$").unwrap();
        assert!(re.is_match(&fname), "filename '{}' missing time stamp", fname);
    }

    #[test]
    fn test_full_flow_init_log_compact_rotate() {
        let env = TestEnv::new();

        // Phiên 1
        let meta1 = t_init(&env);
        t_log(&env, &mkmsg("u1", "user", "first Q"));
        t_log(&env, &mkmsg("a1", "assistant", "first A"));
        let out1 = t_compact(&env, &meta1, "compact").unwrap();
        assert!(out1.exists());

        // Sau compact: WAL bị xoá → tạo phiên 2 mới
        assert!(!env.wal().exists());
        let meta2 = t_init(&env);
        assert_ne!(meta1.session_id, meta2.session_id);

        t_log(&env, &mkmsg("u2", "user", "second Q"));
        let out2 = t_compact(&env, &meta2, "compact").unwrap();
        assert!(out2.exists());
        assert_ne!(out1, out2);

        // Mỗi phiên 1 file riêng
        let entries: Vec<_> = std::fs::read_dir(env.sessions())
            .unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().unwrap().is_file())
            .collect();
        assert_eq!(entries.len(), 2);
    }
}
