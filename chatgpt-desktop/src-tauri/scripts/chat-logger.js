/**
 * @name chat-logger.js
 * @version 0.2.0
 * @url https://github.com/thanhiont423/mem0custom
 *
 * v0.2.0: BYPASS CSP — dùng __TAURI__.event.emit() (postMessage) thay vì invoke()
 * vì chatgpt.com CSP block 'ipc.localhost' (Tauri HTTP IPC endpoint).
 */

class ChatLogger {
  static loggedIds = new Set();
  static observer = null;
  static emitMethod = null;

  static start() {
    const tryAttach = () => {
      const target = document.querySelector('main');
      if (!target) {
        setTimeout(tryAttach, 1000);
        return;
      }
      if (ChatLogger.observer) ChatLogger.observer.disconnect();
      ChatLogger.observer = new MutationObserver(() => ChatLogger.scan());
      ChatLogger.observer.observe(target, {
        childList: true,
        subtree: true,
        characterData: true,
      });
      ChatLogger.scan();
      console.log('[chat-logger v0.2.0] attached');
      ChatLogger.detectEmitMethod();
    };
    tryAttach();
  }

  static detectEmitMethod() {
    // Thử 3 cách emit theo thứ tự ưu tiên:
    // 1. window.__TAURI__.event.emit (Tauri 2 official, postMessage)
    // 2. window.__TAURI_INTERNALS__.postMessage (lower-level)
    // 3. window.__TAURI__.core.invoke (HTTP IPC - bị CSP chặn, fallback cuối)
    if (window.__TAURI__?.event?.emit) {
      ChatLogger.emitMethod = 'event';
      console.log('[chat-logger] using event.emit (postMessage, CSP-safe)');
    } else if (window.__TAURI_INTERNALS__?.postMessage) {
      ChatLogger.emitMethod = 'internals';
      console.log('[chat-logger] using __TAURI_INTERNALS__.postMessage');
    } else if (window.__TAURI__?.core?.invoke) {
      ChatLogger.emitMethod = 'invoke';
      console.log('[chat-logger] using invoke (may fail due to CSP)');
    } else {
      console.error('[chat-logger] NO Tauri bridge found — không gửi được message về Rust');
    }
  }

  static getConvId() {
    const m = location.pathname.match(/\/c\/([^/?#]+)/);
    return m ? m[1] : 'default';
  }

  static scan() {
    const nodes = document.querySelectorAll('[data-message-id]');
    const convId = ChatLogger.getConvId();

    nodes.forEach((node) => {
      const id = node.dataset.messageId;
      const role = node.dataset.messageAuthorRole;
      if (!id || !role) return;
      if (ChatLogger.loggedIds.has(id)) return;

      const content = (node.innerText || '').trim();
      if (!content) return;

      if (role === 'user') {
        ChatLogger.send(id, convId, role, content);
      } else if (role === 'assistant') {
        const turnContainer = node.closest('[data-testid^="conversation-turn-"]') || node.parentElement;
        const done = turnContainer && (
          turnContainer.querySelector('[data-testid*="copy"]') ||
          turnContainer.querySelector('button[aria-label*="Copy" i]')
        );
        if (done) {
          ChatLogger.send(id, convId, role, content);
        }
      }
    });
  }

  static send(id, conversationId, role, content) {
    ChatLogger.loggedIds.add(id);
    const payload = { id, conversationId, role, content };

    try {
      if (ChatLogger.emitMethod === 'event') {
        // postMessage-based, bypass CSP
        window.__TAURI__.event.emit('chat-logger://log-message', payload);
      } else if (ChatLogger.emitMethod === 'internals') {
        window.__TAURI_INTERNALS__.postMessage({
          cmd: 'log_message',
          ...payload,
        });
      } else if (ChatLogger.emitMethod === 'invoke') {
        window.__TAURI__.core.invoke('log_message', payload);
      }
    } catch (err) {
      ChatLogger.loggedIds.delete(id);
      console.error('[chat-logger] send failed:', err);
    }
  }

  // Compact trigger từ Ask.tsx cũng qua event
  static compact() {
    if (window.__TAURI__?.event?.emit) {
      window.__TAURI__.event.emit('chat-logger://compact', {});
    } else if (window.__TAURI__?.core?.invoke) {
      window.__TAURI__.core.invoke('compact_session');
    }
  }
}

window.addEventListener('DOMContentLoaded', ChatLogger.start);
window.addEventListener('popstate', () => setTimeout(ChatLogger.start, 500));
window.ChatLogger = ChatLogger;
