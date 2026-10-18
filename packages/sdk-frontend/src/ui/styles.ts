/**
 * Shadow DOM CSS styles for the Ghost Cursor chat widget.
 * Injected into the shadow root for complete style isolation.
 */

export function getWidgetStyles(primaryColor: string = '#6366f1'): string {
  return `
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

    :host {
      --gc-primary: ${primaryColor};
      --gc-primary-light: ${primaryColor}22;
      --gc-primary-hover: ${primaryColor}dd;
      --gc-bg: #ffffff;
      --gc-bg-secondary: #f8fafc;
      --gc-text: #1e293b;
      --gc-text-secondary: #64748b;
      --gc-border: #e2e8f0;
      --gc-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
      --gc-radius: 16px;
      --gc-font: 'Plus Jakarta Sans', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      font-family: var(--gc-font);
      font-size: 14px;
      line-height: 1.5;
      color: var(--gc-text);
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }

    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: var(--gc-font);
    }


    /* ── Toggle Button ─────────────────── */
    .gc-toggle {
      position: fixed; bottom: 24px; right: 24px;
      width: 60px; height: 60px; border-radius: 50%;
      background: var(--gc-primary);
      border: none; cursor: pointer; z-index: 999999;
      display: flex; align-items: center; justify-content: center;
      box-shadow: 0 8px 32px rgba(99, 102, 241, 0.4);
      transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
      padding: 0;
      overflow: hidden;
    }
    .gc-toggle:hover {
      transform: scale(1.08);
      box-shadow: 0 12px 40px rgba(99, 102, 241, 0.55);
    }
    .gc-toggle:active { transform: scale(0.95); }
    .gc-toggle.open {
      border-radius: 50%;
    }
    .gc-toggle-icon,
    .gc-toggle-img {
      width: 38px;
      height: 38px;
      display: flex;
      align-items: center;
      justify-content: center;
      object-fit: contain;
      pointer-events: none;
      transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
      filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.25));
    }
    .gc-toggle-icon svg {
      width: 100%;
      height: 100%;
      display: block;
    }
    .gc-solid-cursor {
      transition: opacity 0.35s cubic-bezier(0.34, 1.56, 0.64, 1), transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
      transform-origin: 325px 152px;
    }
    .gc-toggle.undocked .gc-solid-cursor {
      opacity: 0;
      transform: scale(0.2) translate(-100px, -100px);
    }
    .gc-dotted-boundary {
      transition: opacity 0.3s ease;
    }
    .gc-toggle.undocked .gc-dotted-boundary {
      opacity: 0.9;
      animation: gc-dock-pulse 2s infinite ease-in-out;
    }
    @keyframes gc-dock-pulse {
      0%, 100% { opacity: 0.7; }
      50% { opacity: 1; filter: drop-shadow(0 0 4px rgba(255, 107, 53, 0.6)); }
    }
    .gc-toggle-close {
      font-size: 24px;
      color: white;
      font-weight: 400;
      line-height: 1;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    /* ── Chat Panel ─────────────────── */
    .gc-panel {
      position: fixed; bottom: 100px; right: 24px;
      width: 400px; height: 600px; max-height: 80vh;
      background: var(--gc-bg);
      border-radius: var(--gc-radius);
      box-shadow: var(--gc-shadow);
      display: flex; flex-direction: column;
      overflow: hidden; z-index: 999998;
      opacity: 0; transform: translateY(20px) scale(0.95);
      transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
      pointer-events: none;
      border: 1px solid var(--gc-border);
    }
    .gc-panel.visible {
      opacity: 1; transform: translateY(0) scale(1);
      pointer-events: auto;
    }

    /* ── Header ─────────────────── */
    .gc-header {
      display: flex; align-items: center; gap: 12px;
      padding: 16px 20px;
      background: #3730a3;
      background: linear-gradient(135deg, rgba(15, 23, 42, 0.28) 0%, rgba(15, 23, 42, 0.42) 100%), var(--gc-primary);
      color: white;
      border-bottom: 1px solid rgba(0, 0, 0, 0.15);
    }
    .gc-header-avatar {
      width: 36px; height: 36px; border-radius: 10px;
      background: rgba(255,255,255,0.2);
      display: flex; align-items: center; justify-content: center;
      overflow: hidden;
      padding: 3px;
    }
    .gc-header-avatar img,
    .gc-header-avatar svg {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
      filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.2));
    }
    .gc-header-info h3 {
      font-size: 15px; font-weight: 600;
      margin: 0; line-height: 1.3;
    }
    .gc-header-info p {
      font-size: 12px; opacity: 0.8;
      margin: 0; line-height: 1.3;
    }
    .gc-close-btn {
      margin-left: auto;
      background: rgba(255,255,255,0.15);
      border: none; color: white; width: 32px; height: 32px;
      border-radius: 8px; cursor: pointer; font-size: 18px;
      display: flex; align-items: center; justify-content: center;
      transition: background 0.2s;
    }
    .gc-close-btn:hover { background: rgba(255,255,255,0.25); }

    /* ── Messages ─────────────────── */
    .gc-messages {
      flex: 1; overflow-y: auto; padding: 16px;
      display: flex; flex-direction: column; gap: 12px;
      scroll-behavior: smooth;
    }
    .gc-messages::-webkit-scrollbar { width: 6px; }
    .gc-messages::-webkit-scrollbar-track { background: transparent; }
    .gc-messages::-webkit-scrollbar-thumb { background: var(--gc-border); border-radius: 3px; }

    .gc-msg {
      max-width: 88%; padding: 12px 16px;
      border-radius: 16px; font-size: 14px; line-height: 1.55;
      animation: gc-fadeIn 0.25s ease;
      word-break: break-word;
      font-family: var(--gc-font);
    }
    .gc-msg.user {
      align-self: flex-end;
      background: var(--gc-primary); color: white;
      border-bottom-right-radius: 4px;
      box-shadow: 0 2px 6px rgba(99, 102, 241, 0.2);
    }
    .gc-msg.assistant {
      align-self: flex-start;
      background: var(--gc-bg-secondary); color: var(--gc-text);
      border-bottom-left-radius: 4px;
      border: 1px solid var(--gc-border);
    }
    .gc-msg.assistant p {
      margin-bottom: 8px;
    }
    .gc-msg.assistant p:last-child {
      margin-bottom: 0;
    }
    .gc-msg strong {
      font-weight: 600;
      color: inherit;
    }
    .gc-msg em {
      font-style: italic;
    }
    .gc-msg code.gc-inline-code {
      background: rgba(0, 0, 0, 0.06);
      padding: 2px 6px;
      border-radius: 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      color: #e11d48;
    }
    .gc-msg pre.gc-code-block {
      background: #0f172a;
      color: #f8fafc;
      padding: 10px 12px;
      border-radius: 8px;
      overflow-x: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      margin: 8px 0;
    }
    .gc-msg ol.gc-list, .gc-msg ul.gc-list {
      margin: 6px 0 6px 20px;
      padding: 0;
    }
    .gc-msg li {
      margin-bottom: 4px;
      padding-left: 2px;
    }
    .gc-msg li:last-child {
      margin-bottom: 0;
    }
    .gc-msg.system {
      align-self: center; text-align: center;
      background: transparent; color: var(--gc-text-secondary);
      font-size: 12px; padding: 4px 12px;
    }


    /* ── Action Plan Card ─────────────────── */
    .gc-action-plan {
      align-self: flex-start; width: 100%;
      background: var(--gc-bg-secondary);
      border: 1px solid var(--gc-border);
      border-radius: 12px; padding: 16px;
      animation: gc-fadeIn 0.3s ease;
    }
    .gc-action-plan h4 {
      font-size: 13px; font-weight: 600;
      color: var(--gc-primary); margin-bottom: 12px;
      display: flex; align-items: center; gap: 6px;
    }
    .gc-action-step {
      display: flex; align-items: flex-start; gap: 10px;
      padding: 8px 0; font-size: 13px;
      border-bottom: 1px solid var(--gc-border);
    }
    .gc-action-step:last-child { border-bottom: none; }
    .gc-step-icon {
      width: 24px; height: 24px; border-radius: 50%;
      background: var(--gc-primary-light);
      color: var(--gc-primary); font-size: 12px; font-weight: 600;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
    }
    .gc-step-icon.done { background: #dcfce7; color: #16a34a; }
    .gc-step-icon.failed { background: #fef2f2; color: #dc2626; }
    .gc-step-icon.running { animation: gc-pulse 1s infinite; }

    .gc-action-buttons {
      display: flex; gap: 8px; margin-top: 12px;
    }
    .gc-btn {
      padding: 10px 20px; border-radius: 10px;
      font-size: 13px; font-weight: 500;
      cursor: pointer; border: none;
      transition: all 0.2s;
    }
    .gc-btn-primary {
      background: var(--gc-primary); color: white;
      box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
    }
    .gc-btn-primary:hover {
      background: var(--gc-primary-hover);
      box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
      transform: translateY(-1px);
    }
    .gc-btn-secondary {
      background: white; color: var(--gc-text-secondary);
      border: 1px solid var(--gc-border);
    }
    .gc-btn-secondary:hover { background: var(--gc-bg-secondary); }
    .gc-btn:disabled {
      opacity: 0.5; cursor: not-allowed; transform: none;
    }

    /* ── Question Options ─────────────────── */
    .gc-question { align-self: flex-start; width: 100%; }
    .gc-question p {
      font-size: 14px; margin-bottom: 10px;
      color: var(--gc-text);
    }
    .gc-option-btn {
      display: block; width: 100%;
      padding: 10px 14px; margin-bottom: 6px;
      background: white; border: 1px solid var(--gc-border);
      border-radius: 10px; cursor: pointer;
      font-size: 13px; text-align: left;
      transition: all 0.2s; color: var(--gc-text);
    }
    .gc-option-btn:hover {
      border-color: var(--gc-primary);
      background: var(--gc-primary-light);
      color: var(--gc-primary);
    }

    /* ── Suggested Quick Prompts ─────── */
    .gc-suggestions {
      padding: 8px 14px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      background: var(--gc-bg);
      border-top: 1px solid var(--gc-border);
      animation: gc-fadeIn 0.2s ease-out;
    }
    .gc-suggestion-chip {
      background: var(--gc-card-bg, #f8fafc);
      border: 1px solid var(--gc-border);
      color: var(--gc-text);
      font-size: 12px;
      line-height: 1.3;
      padding: 6px 11px;
      border-radius: 14px;
      cursor: pointer;
      transition: all 0.2s ease;
      text-align: left;
      font-family: var(--gc-font);
      display: inline-flex;
      align-items: center;
      box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    .gc-suggestion-chip:hover {
      background: var(--gc-primary-light);
      border-color: var(--gc-primary);
      color: var(--gc-primary);
      transform: translateY(-1px);
      box-shadow: 0 2px 4px rgba(0,0,0,0.06);
    }

    /* ── Input Area ─────────────────── */
    .gc-input-area {
      padding: 12px 16px;
      border-top: 1px solid var(--gc-border);
      display: flex; gap: 8px; align-items: flex-end;
      background: var(--gc-bg);
    }
    .gc-textarea {
      flex: 1; resize: none; border: 1px solid var(--gc-border);
      border-radius: 12px; padding: 10px 14px;
      font-family: var(--gc-font); font-size: 14px;
      outline: none; min-height: 42px; max-height: 120px;
      transition: border-color 0.2s;
      color: var(--gc-text); background: var(--gc-bg);
      line-height: 1.4;
    }
    .gc-textarea:focus { border-color: var(--gc-primary); }
    .gc-textarea::placeholder { color: var(--gc-text-secondary); }
    .gc-send-btn {
      width: 42px; height: 42px; border-radius: 12px;
      background: var(--gc-primary); border: none;
      color: white; cursor: pointer; font-size: 18px;
      display: flex; align-items: center; justify-content: center;
      transition: all 0.2s; flex-shrink: 0;
    }
    .gc-send-btn:hover { background: var(--gc-primary-hover); transform: scale(1.05); }
    .gc-send-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

    /* ── Loading ─────────────────── */
    .gc-loading {
      align-self: flex-start; padding: 12px 16px;
      display: flex; gap: 6px; align-items: center;
    }
    .gc-dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--gc-text-secondary);
      animation: gc-bounce 1.4s infinite ease-in-out;
    }
    .gc-dot:nth-child(1) { animation-delay: 0s; }
    .gc-dot:nth-child(2) { animation-delay: 0.2s; }
    .gc-dot:nth-child(3) { animation-delay: 0.4s; }

    /* ── Animations ─────────────────── */
    @keyframes gc-fadeIn {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes gc-bounce {
      0%, 80%, 100% { transform: scale(0); }
      40% { transform: scale(1); }
    }
    @keyframes gc-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.5; }
    }

    /* ── Responsive ─────────────────── */
    @media (max-width: 480px) {
      .gc-panel {
        width: calc(100vw - 16px); right: 8px; bottom: 80px;
        height: 70vh; border-radius: 12px;
      }
      .gc-toggle { width: 52px; height: 52px; bottom: 16px; right: 16px; }
    }

    /* ── Reduced Motion ─────────────────── */
    @media (prefers-reduced-motion: reduce) {
      .gc-panel { transition: opacity 0.1s; }
      .gc-msg { animation: none; }
      .gc-toggle { transition: none; }
      .gc-dot { animation: none; opacity: 0.5; }
    }
  `;
}

