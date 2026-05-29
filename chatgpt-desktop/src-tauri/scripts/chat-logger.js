/**
 * @name chat-logger.js
 * @version 0.3.0
 * @url https://github.com/thanhiont423/mem0custom
 *
 * v0.3.0:
 *   - BYPASS CSP via event.emit() (postMessage) — invoke bị chatgpt.com chặn
 *   - HOOK textarea chatgpt.com: nếu user gõ 'luu'/'compact'/'lưu' rồi Enter
 *     -> chặn submit lên OpenAI + emit compact event -> file JSON ra ngay
 *   - Detect cả ô Ask của app lẫn textarea chính của ChatGPT
 */

const COMPACT_KW = /^\s*\/?(compact|lưu|luu)\s*$/i;

class ChatLogger {
  static loggedIds = new Set();
  static observer = null;
  static emitMethod = null;
  static keywordHooked = false;

  static start() {
    const tryAttach = () => {
      const target = document.querySelector('main');
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
      console.log('[chat-logger v0.3.0] attached');
      ChatLogger.detectEmitMethod();
    };
    tryAttach();
  }

  static detectEmitMethod() {
    if (window.__TAURI__?.event?.emit) {
      ChatLogger.emitMethod = 'event';
      console.log('[chat-logger] using event.emit (postMessage, CSP-safe)');
    } else if (window.__TAURI_INTERNALS__?.postMessage) {
      ChatLogger.emitMethod = 'internals';
    } else if (window.__TAURI__?.core?.invoke) {
      ChatLogger.emitMethod = 'invoke';
    } else {
      console.error('[chat-logger] NO Tauri bridge found');
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
      // BỎ qua nếu content match keyword (đã bị handle riêng)
      if (COMPACT_KW.test(content)) {
        ChatLogger.loggedIds.add(id);
        return;
      }
      if (role === 'user') {
        ChatLogger.send(id, convId, role, content);
      } else if (role === 'assistant') {
        const turnContainer = node.closest('[data-testid^="conversation-turn-"]') || node.parentElement;
        const done = turnContainer && (
          turnContainer.querySelector('[data-testid*="copy"]') ||
          turnContainer.querySelector('button[aria-label*="Copy" i]')
        );
        if (done) ChatLogger.send(id, convId, role, content);
      }
    });
  }

  // MỚI v0.3.0: hook textarea chatgpt.com, intercept Enter khi gõ keyword
  static hookKeywordTrigger() {
    const textareas = document.querySelectorAll('textarea, [contenteditable="true"]');
    textareas.forEach((ta) => {
      if (ta.dataset.compactHooked === '1') return;
      ta.dataset.compactHooked = '1';

      const handler = (e) => {
        // Lấy text từ textarea HOẶC contenteditable
        const text = (ta.value !== undefined ? ta.value : ta.innerText || '').trim();
        if (!COMPACT_KW.test(text)) return;

        // Chặn submit / send lên ChatGPT
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();

        console.log('[chat-logger] COMPACT keyword detected, triggering...');
        ChatLogger.triggerCompact();

        // Clear textarea
        if (ta.value !== undefined) {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
          setter.call(ta, '');
          ta.dispatchEvent(new InputEvent('input', { bubbles: true }));
        } else {
          ta.innerText = '';
          ta.dispatchEvent(new InputEvent('input', { bubbles: true }));
        }
      };

      // Bắt Enter (không Shift+Enter)
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          handler(e);
        }
      }, true); // capture phase để chặn trước handler khác
    });
  }

  static triggerCompact() {
    try {
      if (ChatLogger.emitMethod === 'event') {
        window.__TAURI__.event.emit('chat-logger://compact', {});
      } else if (ChatLogger.emitMethod === 'internals') {
        window.__TAURI_INTERNALS__.postMessage({ cmd: 'compact_session' });
      } else if (ChatLogger.emitMethod === 'invoke') {
        window.__TAURI__.core.invoke('compact_session');
      }
    } catch (err) {
      console.error('[chat-logger] compact trigger failed:', err);
    }
  }

  static send(id, conversationId, role, content) {
    ChatLogger.loggedIds.add(id);
    const payload = { id, conversationId, role, content };
    try {
      if (ChatLogger.emitMethod === 'event') {
        window.__TAURI__.event.emit('chat-logger://log-message', payload);
      } else if (ChatLogger.emitMethod === 'internals') {
        window.__TAURI_INTERNALS__.postMessage({ cmd: 'log_message', ...payload });
      } else if (ChatLogger.emitMethod === 'invoke') {
        window.__TAURI__.core.invoke('log_message', payload);
      }
    } catch (err) {
      ChatLogger.loggedIds.delete(id);
      console.error('[chat-logger] send failed:', err);
    }
  }

  static compact() {
    ChatLogger.triggerCompact();
  }
}

window.addEventListener('DOMContentLoaded', ChatLogger.start);
window.addEventListener('popstate', () => setTimeout(ChatLogger.start, 500));
window.ChatLogger = ChatLogger;
