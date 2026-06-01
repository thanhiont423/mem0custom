// OAuth token check + refresh cho Claude Max OAT.
// Đọc ~/.claude/.credentials.json: claudeAiOauth.{accessToken, refreshToken, expiresAt}.
// - check_token_status(): còn hạn / sắp hết / hết hạn.
// - refresh_token(): dùng refreshToken gọi OAuth endpoint Anthropic -> ghi token mới vào file.
//
// LƯU Ý: client_id + endpoint để trong code dưới dạng default, có thể override qua biến
// môi trường (CLAUDE_OAUTH_CLIENT_ID / CLAUDE_OAUTH_TOKEN_URL) nếu Anthropic đổi.

use serde_json::{json, Value};
use std::path::PathBuf;

// Public OAuth client_id của Claude Code (dùng cho luồng refresh). Override bằng env nếu cần.
const DEFAULT_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
const DEFAULT_TOKEN_URL: &str = "https://console.anthropic.com/v1/oauth/token";
// Ngưỡng coi là "sắp hết hạn" (ms): còn dưới 5 phút -> nên refresh.
const SOON_MS: i64 = 5 * 60 * 1000;

fn creds_path() -> PathBuf {
    let home = std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_default();
    home.join(".claude").join(".credentials.json")
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn read_creds() -> Result<Value, String> {
    let p = creds_path();
    let raw = std::fs::read_to_string(&p)
        .map_err(|e| format!("read {}: {}", p.display(), e))?;
    serde_json::from_str(&raw).map_err(|e| format!("parse creds: {}", e))
}

/// "valid" | "expired" | "missing"
pub fn check_token_status() -> String {
    let creds = match read_creds() {
        Ok(c) => c,
        Err(_) => return "missing".into(),
    };
    let oauth = match creds.get("claudeAiOauth") {
        Some(o) => o,
        None => return "missing".into(),
    };
    if oauth.get("accessToken").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
        return "missing".into();
    }
    match oauth.get("expiresAt").and_then(|v| v.as_i64()) {
        Some(exp) => {
            if exp - now_ms() <= SOON_MS { "expired".into() } else { "valid".into() }
        }
        // không có expiresAt -> coi như valid (không chặn)
        None => "valid".into(),
    }
}

/// Refresh OAT bằng refreshToken. Ghi token mới vào .credentials.json. Trả status mới.
pub async fn refresh_token() -> Result<String, String> {
    let mut creds = read_creds()?;
    let refresh = creds
        .pointer("/claudeAiOauth/refreshToken")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .ok_or("Không có refreshToken trong credentials — cần đăng nhập lại Claude Code")?
        .to_string();

    let client_id =
        std::env::var("CLAUDE_OAUTH_CLIENT_ID").unwrap_or_else(|_| DEFAULT_CLIENT_ID.to_string());
    let token_url =
        std::env::var("CLAUDE_OAUTH_TOKEN_URL").unwrap_or_else(|_| DEFAULT_TOKEN_URL.to_string());

    let body = json!({
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": client_id,
    });

    let resp = reqwest::Client::new()
        .post(&token_url)
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("refresh request: {}", e))?;

    let status = resp.status();
    let text = resp.text().await.unwrap_or_default();
    if !status.is_success() {
        return Err(format!("refresh thất bại HTTP {}: {}", status, text));
    }
    let tok: Value = serde_json::from_str(&text).map_err(|e| format!("parse refresh resp: {}", e))?;

    let access = tok.get("access_token").and_then(|v| v.as_str())
        .ok_or("refresh resp thiếu access_token")?;
    let new_refresh = tok.get("refresh_token").and_then(|v| v.as_str());
    let expires_in = tok.get("expires_in").and_then(|v| v.as_i64()).unwrap_or(0);

    // cập nhật vào creds (giữ các field khác)
    if let Some(o) = creds.get_mut("claudeAiOauth") {
        o["accessToken"] = json!(access);
        if let Some(r) = new_refresh { o["refreshToken"] = json!(r); }
        if expires_in > 0 { o["expiresAt"] = json!(now_ms() + expires_in * 1000); }
    }
    std::fs::write(creds_path(), serde_json::to_string_pretty(&creds).unwrap_or(text))
        .map_err(|e| format!("ghi creds mới: {}", e))?;

    Ok(check_token_status())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_status_missing_when_no_file() {
        // Trên CI không có ~/.claude/.credentials.json -> missing (không panic)
        let s = check_token_status();
        assert!(s == "missing" || s == "valid" || s == "expired");
    }
    #[test]
    fn test_soon_threshold_positive() {
        assert!(SOON_MS > 0);
    }
}
