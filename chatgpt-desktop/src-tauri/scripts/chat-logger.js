/**
 * @name chat-logger.js
 * @version 0.4.0
 * @url https://github.com/thanhiont423/mem0custom
 *
 * v0.4.0:
 *   - DYNAMIC KEYWORDS từ file keywords.json (qua Tauri command get_keywords)
 *   - Mỗi keyword map tới 1 action (compact_session / custom event)
 *   - User sửa file -> reload page là active
 *   - Fallback default keywords nếu file không có
 *   - Vẫn giữ CSP-safe via event.emit (postMessage)
 *   - Vẫn hook cả textarea ChatGPT lẫn ô Ask của app
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
  static keywords = DEFAULT_KEYWORDS;
  static keywordRegex = ChatLogger.buildRegex(DEFAULT_KEYWORDS);

  static buildRegex(map) {
    const escaped = Object.keys(map).map((k) =>
      k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    );
    return new RegExp("^\\s*(" + escaped.join("|") + ")\\s*$", "i");
  }

  static async loadKeywords() {
    try {
      const result = await window.__TAURI__?.core?.invoke?.("get_keywords");
      if (result && typeof result === "object") {
        ChatLogger.keywords = result;
        ChatLogger.keywordRegex = ChatLogger.buildRegex(result);
        console.log("[chat-logger] loaded keywords:", Object.keys(result));
      }
    } catch (e) {
      console.warn("[chat-logger] get_keywords failed, using defaults:", e);
    }
  }

  static start() {
    const tryAttach = () => {
      const target = document.querySelector("main");
      if (!target) {
        setTimeout(tryAttach, 1000);
        return;
      }
      if (ChatLogger.observer) ChatLogger.observer.disconnect();
      ChatLogger.observer = new MutationObserver(() => {
        ChatLogger.scan();
        ChatLogger.hookKeywordTrigger();
      });
      ChatLogger.observer.observe(target, {
        childList: true,
        subtree: true,
        characterData: true,
      });
      ChatLogger.scan();
      ChatLogger.hookKeywordTrigger();
      console.log("[chat-logger v0.4.0] attached");
      ChatLogger.detectEmitMethod();
      // Load keywords sau detect emit method
      ChatLogger.loadKeywords();
    };
    tryAttach();
  }

  static detectEmitMethod() {
    if (window.__TAURI__?.event?.emit) {
      ChatLogger.emitMethod = "event";
      console.log("[chat-logger] using event.emit (postMessage, CSP-safe)");
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

  // Lookup keyword -> action. Returns action name or null.
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
      // Skip nếu content là keyword (đã trigger riêng)
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

        console.log(`[chat-logger] keyword '${text}' -> action '${action}'`);
        ChatLogger.triggerAction(action);

        // Clear textarea
        if (ta.value !== undefined) {
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype,
            "value"
          ).set;
          setter.call(ta, "");
          ta.dispatchEvent(new InputEvent("input", { bubbles: true }));
        } else {
          ta.innerText = "";
          ta.dispatchEvent(new InputEvent("input", { bubbles: true }));
        }
      };

      ta.addEventListener(
        "keydown",
        (e) => {
          if (e.key === "Enter" && !e.shiftKey) handler(e);
        },
        true
      );
    });
  }

  // Generic action dispatcher
  static triggerAction(action) {
    try {
      if (action === "compact_session") {
        ChatLogger.triggerCompact();
      } else if (ChatLogger.emitMethod === "event") {
        // Custom action -> emit qua event channel cùng pattern
        window.__TAURI__.event.emit(`chat-logger://${action}`, {});
      } else if (ChatLogger.emitMethod === "invoke") {
        window.__TAURI__.core.invoke(action).catch((e) =>
          console.error(`[chat-logger] invoke '${action}' failed:`, e)
        );
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

  static compact() {
    ChatLogger.triggerCompact();
  }
}

window.addEventListener("DOMContentLoaded", ChatLogger.start);
window.addEventListener("popstate", () => setTimeout(ChatLogger.start, 500));
window.ChatLogger = ChatLogger;
