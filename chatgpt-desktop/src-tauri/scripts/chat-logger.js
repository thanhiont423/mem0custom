/**
 * @name chat-logger.js
 * @version 0.8.1
 * @url https://github.com/thanhiont423/mem0custom
 *
 * v0.6.0 — NHE TOI DA (fix lag) + nut noi:
 *   - BO MutationObserver characterData (nguon lag: fire moi token khi stream).
 *   - Quan sat CHI childList + subtree + debounce 500ms -> quet gon khi co tin moi/xong.
 *   - Giu hook Enter bat keyword tai DOM (theo yeu cau).
 *   - Them hop nut noi: [Luu summary] (summarize_current) + [Luu full session] (compact).
 *
 * v0.5.0: doc keywords tu window.__INJECTED_KEYWORDS__ (CSP-safe), emit qua event.
 */

const DEFAULT_KEYWORDS = {
  "compact": "compact_session",
  "lưu": "compact_session",
  "luu": "compact_session",
  "/compact": "compact_session",
  "/lưu": "compact_session",
};

// Lệnh prefix (gõ kèm điều kiện phía sau): "/lichsu deploy VPS" -> tìm theo "deploy VPS".
const PREFIX_COMMANDS = ["lichsu", "lịch sử", "lich su", "history"];
const DETAIL_COMMANDS = ["xemphien", "xem phiên", "xem phien", "chitiet"];

class ChatLogger {
  static loggedIds = new Set();
  static observer = null;
  static emitMethod = null;
  static scanTimer = null;
  static keywords = (typeof window !== "undefined" && window.__INJECTED_KEYWORDS__)
    ? window.__INJECTED_KEYWORDS__
    : DEFAULT_KEYWORDS;

  static start() {
    const tryAttach = () => {
      const target = document.querySelector("main");
      if (!target) {
        setTimeout(tryAttach, 1000);
        return;
      }
      if (ChatLogger.observer) ChatLogger.observer.disconnect();
      // NHE: chi childList + subtree, KHONG characterData (khong fire moi token).
      // Gop cac thay doi bang debounce 500ms -> quet toi da ~2 lan/giay khi co node moi.
      ChatLogger.observer = new MutationObserver(() => ChatLogger.scheduleScan());
      ChatLogger.observer.observe(target, { childList: true, subtree: true });
      ChatLogger.scan();              // quet 1 lan luc gan
      ChatLogger.hookKeywordTrigger();
      ChatLogger.detectEmitMethod();
      ChatLogger.mountFloatingButtons();
      ChatLogger.listenResult();
      ChatLogger.checkOAuth();
      console.log("[chat-logger v0.8.0] attached (+ kiểm tra/gia hạn OAuth token)");
    };
    tryAttach();
  }

  // Debounce: gom nhieu mutation thanh 1 lan quet -> tranh quet lien tuc luc stream.
  static scheduleScan() {
    if (ChatLogger.scanTimer) clearTimeout(ChatLogger.scanTimer);
    ChatLogger.scanTimer = setTimeout(() => {
      ChatLogger.scan();
      ChatLogger.hookKeywordTrigger();
    }, 500);
  }

  static detectEmitMethod() {
    if (window.__TAURI__?.event?.emit) {
      ChatLogger.emitMethod = "event";
    } else if (window.__TAURI_INTERNALS__?.postMessage) {
      ChatLogger.emitMethod = "internals";
    } else if (window.__TAURI__?.core?.invoke) {
      ChatLogger.emitMethod = "invoke";
    } else {
      console.error("[chat-logger] NO Tauri bridge found");
    }
  }

  static getConvId() {
    const m = location.pathname.match(/\/c\/([^/?#]+)/);
    return m ? m[1] : "default";
  }

  static matchKeyword(text) {
    const t = (text || "").trim().toLowerCase();
    for (const [kw, action] of Object.entries(ChatLogger.keywords)) {
      if (t === kw.toLowerCase()) return action;
    }
    return null;
  }

  static scan() {
    const nodes = document.querySelectorAll("[data-message-id]");
    const convId = ChatLogger.getConvId();
    nodes.forEach((node) => {
      const id = node.dataset.messageId;
      const role = node.dataset.messageAuthorRole;
      if (!id || !role) return;
      if (ChatLogger.loggedIds.has(id)) return;
      const content = (node.innerText || "").trim();
      if (!content) return;
      if (ChatLogger.matchKeyword(content)) {
        ChatLogger.loggedIds.add(id);
        return;
      }
      if (role === "user") {
        ChatLogger.send(id, convId, role, content);
      } else if (role === "assistant") {
        const turnContainer =
          node.closest('[data-testid^="conversation-turn-"]') ||
          node.parentElement;
        const done =
          turnContainer &&
          (turnContainer.querySelector('[data-testid*="copy"]') ||
            turnContainer.querySelector('button[aria-label*="Copy" i]'));
        if (done) ChatLogger.send(id, convId, role, content);
      }
    });
  }

  static hookKeywordTrigger() {
    const textareas = document.querySelectorAll('textarea, [contenteditable="true"]');
    textareas.forEach((ta) => {
      if (ta.dataset.kwHooked === "1") return;
      ta.dataset.kwHooked = "1";
      const handler = (e) => {
        const text = (ta.value !== undefined ? ta.value : ta.innerText || "").trim();
        // Lệnh lịch sử dạng prefix: "/lichsu [điều kiện]" -> tìm theo điều kiện (rỗng = 5 gần nhất)
        const low = text.toLowerCase();
        const pref = PREFIX_COMMANDS.find((c) => low === c || low.startsWith(c + " "));
        if (pref) {
          e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
          const query = text.slice(pref.length).trim();
          console.log(`[chat-logger] history query='${query}'`);
          ChatLogger.triggerFetchHistory(query);
          ChatLogger.clearInput(ta);
          return;
        }
        const det = DETAIL_COMMANDS.find((c) => low.startsWith(c + " "));
        if (det) {
          e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
          const id = text.slice(det.length).trim();
          ChatLogger.triggerFetchDetail(id);
          ChatLogger.clearInput(ta);
          return;
        }
        const action = ChatLogger.matchKeyword(text);
        if (!action) return;
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        console.log(`[chat-logger] keyword '${text}' -> '${action}'`);
        ChatLogger.triggerAction(action);
        ChatLogger.clearInput(ta);
      };
      ta.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) handler(e);
      }, true);
    });
  }

  // ===== Nut noi: Luu summary + Luu full session =====
  static mountFloatingButtons() {
    if (document.getElementById("cl-fab")) return;
    if (!document.body) { setTimeout(ChatLogger.mountFloatingButtons, 800); return; }
    const box = document.createElement("div");
    box.id = "cl-fab";
    box.style.cssText =
      "position:fixed;right:18px;bottom:96px;z-index:2147483647;display:flex;" +
      "flex-direction:column;gap:8px;font-family:system-ui,sans-serif;";

    const mkBtn = (label, title, onClick) => {
      const b = document.createElement("button");
      b.textContent = label;
      b.title = title;
      b.style.cssText =
        "padding:8px 12px;border:none;border-radius:18px;cursor:pointer;" +
        "background:#10a37f;color:#fff;font-size:12px;font-weight:600;" +
        "box-shadow:0 2px 8px rgba(0,0,0,.25);white-space:nowrap;opacity:.85;";
      b.onmouseenter = () => (b.style.opacity = "1");
      b.onmouseleave = () => (b.style.opacity = ".85");
      b.dataset.label = label;
      b.onclick = (e) => {
        e.preventDefault();
        b.textContent = "⏳ Đang lưu...";
        b.disabled = true;
        onClick();
        // fallback: nếu 12s không có phản hồi -> coi như timeout
        clearTimeout(b._t);
        b._t = setTimeout(() => ChatLogger.setBtnState(b, false, "Không có phản hồi (timeout)"), 12000);
      };
      return b;
    };

    const bSum = mkBtn("📝 Lưu summary", "Tom tat phien va luu vao mem0",
      () => ChatLogger.triggerAction("summarize_current"));
    const bFull = mkBtn("💾 Lưu full session", "Luu toan bo phien (full transcript)",
      () => ChatLogger.triggerAction("compact_session"));
    const bRefresh = mkBtn("🔄 Gia hạn token", "Token Claude hết hạn — bấm để tự gia hạn",
      () => ChatLogger.triggerRefreshOAuth());
    bRefresh.style.background = "#d9534f";
    bRefresh.style.display = "none";   // chỉ hiện khi token hết hạn
    ChatLogger.btns = { summarize: bSum, compact: bFull, refresh: bRefresh };
    box.appendChild(bSum);
    box.appendChild(bFull);
    box.appendChild(bRefresh);
    document.body.appendChild(box);
  }

  static listenResult() {
    if (ChatLogger._resultBound) return;
    ChatLogger._resultBound = true;
    try {
      if (window.__TAURI__?.event?.listen) {
        window.__TAURI__.event.listen("chat-logger://history-result",
          (e) => ChatLogger.renderHistory(e.payload));
        window.__TAURI__.event.listen("chat-logger://oauth-status",
          (e) => ChatLogger.onOAuthStatus(e.payload));
        window.__TAURI__.event.listen("chat-logger://session-detail-result",
          (e) => ChatLogger.renderDetail(e.payload));
      }
    } catch (err) { console.error("[chat-logger] listen extra failed:", err); }
    const handle = (payload) => {
      const p = payload || {};
      const btn = p.action === "summarize" ? (ChatLogger.btns && ChatLogger.btns.summarize)
                : p.action === "compact"   ? (ChatLogger.btns && ChatLogger.btns.compact)
                : null;
      if (btn) ChatLogger.setBtnState(btn, !!p.ok, p.msg || "");
      ChatLogger.toast(p.ok, p.msg || (p.ok ? "Thành công" : "Thất bại"));
    };
    try {
      if (window.__TAURI__?.event?.listen) {
        window.__TAURI__.event.listen("chat-logger://result", (e) => handle(e.payload));
      }
    } catch (err) { console.error("[chat-logger] listenResult failed:", err); }
  }

  static setBtnState(btn, ok, msg) {
    if (!btn) return;
    clearTimeout(btn._t);
    btn.disabled = false;
    btn.title = msg || btn.title;
    btn.textContent = ok ? "✓ " + (btn.dataset.label || "Đã lưu") : "✗ Lỗi";
    btn.style.background = ok ? "#10a37f" : "#d9534f";
    setTimeout(() => {
      btn.textContent = btn.dataset.label || btn.textContent;
      btn.style.background = "#10a37f";
    }, 2500);
  }

  static toast(ok, msg) {
    if (!document.body) return;
    const t = document.createElement("div");
    t.textContent = (ok ? "✓ " : "✗ ") + msg;
    t.style.cssText =
      "position:fixed;right:18px;bottom:150px;z-index:2147483647;max-width:280px;" +
      "padding:10px 14px;border-radius:8px;color:#fff;font-size:13px;font-family:system-ui,sans-serif;" +
      "box-shadow:0 4px 12px rgba(0,0,0,.3);opacity:0;transition:opacity .2s;" +
      "background:" + (ok ? "#10a37f" : "#d9534f") + ";";
    document.body.appendChild(t);
    const raf = (typeof requestAnimationFrame !== "undefined") ? requestAnimationFrame : (cb)=>setTimeout(cb,16);
    raf(() => (t.style.opacity = "1"));
    setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 300); }, 3500);
  }

  static triggerAction(action) {
    try {
      if (action === "fetch_history") {
        ChatLogger.triggerFetchHistory("");
        return;
      }
      if (action === "compact_session") {
        ChatLogger.triggerCompact();
      } else if (ChatLogger.emitMethod === "event") {
        window.__TAURI__.event.emit(`chat-logger://${action}`, {});
      } else if (ChatLogger.emitMethod === "internals") {
        window.__TAURI_INTERNALS__.postMessage({ cmd: action });
      } else if (ChatLogger.emitMethod === "invoke") {
        window.__TAURI__.core.invoke(action).catch((e) =>
          console.error(`[chat-logger] invoke '${action}' failed:`, e));
      }
    } catch (err) {
      console.error(`[chat-logger] triggerAction '${action}' failed:`, err);
    }
  }

  static renderHistory(payload) {
    const p = payload || {};
    if (!p.ok) {
      ChatLogger.insertIntoChat("⚠️ Không lấy được lịch sử: " + (p.msg || "lỗi không rõ"));
      return;
    }
    let sessions = p.sessions;
    if (sessions && !Array.isArray(sessions) && Array.isArray(sessions.sessions)) sessions = sessions.sessions;
    if (!Array.isArray(sessions)) sessions = [];
    if (sessions.length === 0) {
      ChatLogger.insertIntoChat("📜 Lịch sử trống — chưa có phiên nào được lưu.");
      return;
    }
    const lines = ["📜 **" + sessions.length + " phiên gần nhất:**", ""];
    sessions.forEach((snap, i) => {
      const id = snap.id || "?";
      const when = snap.started_at || snap.created_at || "";
      const sum = (snap.summary || snap.llm_summary || "(chưa có tóm tắt)").toString().slice(0, 160);
      const cnt = snap.message_count != null ? ` · ${snap.message_count} tin` : "";
      lines.push(`${i + 1}. [${when}]${cnt}\n   ${sum}\n   id: ${id}`);
    });
    ChatLogger.insertIntoChat(lines.join("\n"));
  }

  // Chèn text vào ô nhập ChatGPT (để hiện trong khung chat / làm ngữ cảnh).
  static insertIntoChat(text) {
    const ta = document.querySelector('textarea, [contenteditable="true"]');
    if (!ta) { ChatLogger.toast(true, text.slice(0, 80)); return; }
    if (ta.value !== undefined) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      setter.call(ta, text);
      ta.dispatchEvent(new InputEvent("input", { bubbles: true }));
    } else {
      ta.innerText = text;
      ta.dispatchEvent(new InputEvent("input", { bubbles: true }));
    }
    ta.focus();
    ChatLogger.toast(true, "Đã chèn lịch sử vào ô chat — Enter để gửi/đọc");
  }

  static triggerFetchDetail(id) {
    if (!id) { ChatLogger.toast(false, "Thiếu id phiên (vd: xemphien <id>)"); return; }
    ChatLogger.toast(true, "Đang lấy chi tiết phiên...");
    try {
      if (ChatLogger.emitMethod === "event") {
        window.__TAURI__.event.emit("chat-logger://fetch-session-detail", { id });
      } else if (ChatLogger.emitMethod === "internals") {
        window.__TAURI_INTERNALS__.postMessage({ cmd: "fetch_session_detail", id });
      }
    } catch (err) { console.error("[chat-logger] fetchDetail failed:", err); }
  }

  static renderDetail(payload) {
    const p = payload || {};
    if (!p.ok) { ChatLogger.insertIntoChat("⚠️ Không lấy được chi tiết: " + (p.msg || "lỗi")); return; }
    const sn = p.session || {};
    let tr = sn.transcript;
    if (typeof tr === "string") { try { tr = JSON.parse(tr); } catch (e) {} }
    if (!Array.isArray(tr)) tr = [];
    const head = `📄 Phiên ${sn.id || ""} — ${sn.started_at || ""} · ${tr.length} tin\n`;
    const body = tr.map((m) => {
      const role = m.role || m.author || "?";
      const content = (m.content || m.text || "").toString().slice(0, 2000);
      return `[${role}] ${content}`;
    }).join("\n\n");
    ChatLogger.insertIntoChat(head + "\n" + body);
  }

  static clearInput(ta) {
    if (ta.value !== undefined) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      setter.call(ta, "");
      ta.dispatchEvent(new InputEvent("input", { bubbles: true }));
    } else {
      ta.innerText = "";
      ta.dispatchEvent(new InputEvent("input", { bubbles: true }));
    }
  }

  // Lấy lịch sử: query rỗng = 5 phiên gần nhất; có query = tìm theo điều kiện.
  static triggerFetchHistory(query) {
    ChatLogger.toast(true, query ? `Đang tìm lịch sử: ${query}` : "Đang lấy 5 phiên gần nhất...");
    const payload = { query: query || "" };
    try {
      if (ChatLogger.emitMethod === "event") {
        window.__TAURI__.event.emit("chat-logger://fetch-history", payload);
      } else if (ChatLogger.emitMethod === "internals") {
        window.__TAURI_INTERNALS__.postMessage({ cmd: "fetch_history", ...payload });
      }
    } catch (err) { console.error("[chat-logger] fetchHistory failed:", err); }
  }

  static checkOAuth() {
    try {
      if (window.__TAURI__?.event?.emit) {
        window.__TAURI__.event.emit("chat-logger://check-oauth", {});
      }
    } catch (err) { console.error("[chat-logger] checkOAuth failed:", err); }
  }

  static triggerRefreshOAuth() {
    const b = ChatLogger.btns && ChatLogger.btns.refresh;
    if (b) { b.textContent = "⏳ Đang gia hạn..."; b.disabled = true; }
    try {
      if (window.__TAURI__?.event?.emit) {
        window.__TAURI__.event.emit("chat-logger://refresh-oauth", {});
      }
    } catch (err) { console.error("[chat-logger] refresh failed:", err); }
  }

  // Xử lý trạng thái token: valid | expired | missing
  static onOAuthStatus(payload) {
    const p = payload || {};
    const st = p.status || "valid";
    const bSum = ChatLogger.btns && ChatLogger.btns.summarize;
    const bRef = ChatLogger.btns && ChatLogger.btns.refresh;
    if (st === "valid") {
      if (bSum) { bSum.style.background = "#10a37f"; bSum.title = "Tóm tắt phiên và lưu vào mem0"; bSum.disabled = false; }
      if (bRef) { bRef.style.display = "none"; bRef.disabled = false; bRef.textContent = "🔄 Gia hạn token"; }
      if (p.refreshed) ChatLogger.toast(true, p.msg || "Token còn hạn");
      return;
    }
    // expired hoặc missing -> báo đỏ nút summary + hiện nút gia hạn
    if (bSum) {
      bSum.style.background = "#d9534f";
      bSum.title = st === "missing"
        ? "Chưa có credentials.json — sẽ thử provider OpenAI khi tóm tắt"
        : "Token Claude hết hạn — bấm 'Gia hạn token'";
    }
    if (bRef) { bRef.style.display = "block"; bRef.disabled = false; bRef.textContent = "🔄 Gia hạn token"; }
    if (p.refreshed === false) ChatLogger.toast(false, p.msg || "Token hết hạn");
  }

  static triggerCompact() {
    try {
      if (ChatLogger.emitMethod === "event") {
        window.__TAURI__.event.emit("chat-logger://compact", {});
      } else if (ChatLogger.emitMethod === "internals") {
        window.__TAURI_INTERNALS__.postMessage({ cmd: "compact_session" });
      } else if (ChatLogger.emitMethod === "invoke") {
        window.__TAURI__.core.invoke("compact_session");
      }
    } catch (err) {
      console.error("[chat-logger] compact trigger failed:", err);
    }
  }

  static send(id, conversationId, role, content) {
    ChatLogger.loggedIds.add(id);
    const payload = { id, conversationId, role, content };
    try {
      if (ChatLogger.emitMethod === "event") {
        window.__TAURI__.event.emit("chat-logger://log-message", payload);
      } else if (ChatLogger.emitMethod === "internals") {
        window.__TAURI_INTERNALS__.postMessage({ cmd: "log_message", ...payload });
      } else if (ChatLogger.emitMethod === "invoke") {
        window.__TAURI__.core.invoke("log_message", payload);
      }
    } catch (err) {
      ChatLogger.loggedIds.delete(id);
      console.error("[chat-logger] send failed:", err);
    }
  }

  static compact() { ChatLogger.triggerCompact(); }
}

window.addEventListener("DOMContentLoaded", ChatLogger.start);
window.addEventListener("popstate", () => setTimeout(ChatLogger.start, 500));
window.ChatLogger = ChatLogger;
