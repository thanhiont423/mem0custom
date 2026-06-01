/**
 * @name chat-logger.js
 * @version 0.6.1
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
      console.log("[chat-logger v0.6.1] attached (event-driven + result feedback)");
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
        const action = ChatLogger.matchKeyword(text);
        if (!action) return;
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        console.log(`[chat-logger] keyword '${text}' -> '${action}'`);
        ChatLogger.triggerAction(action);
        if (ta.value !== undefined) {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
          setter.call(ta, "");
          ta.dispatchEvent(new InputEvent("input", { bubbles: true }));
        } else {
          ta.innerText = "";
          ta.dispatchEvent(new InputEvent("input", { bubbles: true }));
        }
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
    ChatLogger.btns = { summarize: bSum, compact: bFull };
    box.appendChild(bSum);
    box.appendChild(bFull);
    document.body.appendChild(box);
  }

  static listenResult() {
    if (ChatLogger._resultBound) return;
    ChatLogger._resultBound = true;
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
