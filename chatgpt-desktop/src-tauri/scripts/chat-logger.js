/**
 * @name chat-logger.js
 * @version 0.1.0
 * @url https://github.com/lencx/ChatGPT/tree/main/scripts/chat-logger.js
 *
 * Quan sát DOM của chatgpt.com và đẩy mỗi message (user + assistant)
 * về Rust qua Tauri command `log_message`. Chỉ ghi assistant khi đã
 * stop streaming (phát hiện qua nút Copy xuất hiện trong turn đó).
 */

class ChatLogger {
  static loggedIds = new Set();
  static observer = null;

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
      console.log('[chat-logger] attached');
    };
    tryAttach();
  }

  static invoke(cmd, args) {
    try {
      return window.__TAURI__.core.invoke(cmd, args);
    } catch (e) {
      console.error('[chat-logger] invoke failed:', e);
      return Promise.reject(e);
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
        // Chỉ log assistant khi streaming xong — phát hiện qua nút Copy
        const turnContainer = node.closest('[data-testid^="conversation-turn-"]') || node.parentElement;
        const done =
          turnContainer &&
          (turnContainer.querySelector('[data-testid*="copy"]') ||
            turnContainer.querySelector('button[aria-label*="Copy" i]'));
        if (done) {
          ChatLogger.send(id, convId, role, content);
        }
      }
    });
  }

  static send(id, conversationId, role, content) {
    ChatLogger.loggedIds.add(id); // optimistic — tránh gửi lặp
    ChatLogger.invoke('log_message', { id, conversationId, role, content })
      .then(() => {
        // ok
      })
      .catch((err) => {
        ChatLogger.loggedIds.delete(id); // cho retry lần kế tiếp
        console.error('[chat-logger] log failed:', err);
      });
  }
}

window.addEventListener('DOMContentLoaded', ChatLogger.start);
// Một số trang SPA không phát DOMContentLoaded khi route thay đổi
window.addEventListener('popstate', () => setTimeout(ChatLogger.start, 500));
window.ChatLogger = ChatLogger;
