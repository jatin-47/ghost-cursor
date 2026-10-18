/**
 * Ghost Cursor Chat Widget — Shadow DOM encapsulated UI.
 *
 * Custom element that renders the chat interface inside a shadow root
 * for complete CSS isolation from the host application.
 */

import { getWidgetStyles } from './styles';
import { GHOST_CURSOR_ICON } from './ghost-icon';
import type { ActionItem, QuestionItem } from '../types';

export interface WidgetCallbacks {
  onSendMessage: (message: string) => void;
  onApproveActions: () => void;
  onRejectActions: () => void;
  onAnswerQuestion: (answer: string) => void;
  onStop: () => void;
}

export class GhostCursorWidget {
  private hostEl: HTMLElement;
  private shadow: ShadowRoot;
  private toggleBtn!: HTMLElement;
  private panel!: HTMLElement;
  private messagesEl!: HTMLElement;
  private textareaEl!: HTMLTextAreaElement;
  private sendBtn!: HTMLElement;
  private suggestionsEl!: HTMLElement;
  private isOpen = false;
  private callbacks: WidgetCallbacks;
  private disabled = false;
  private iconUrl: string;

  constructor(
    mountPoint: HTMLElement | null,
    primaryColor: string = '#6366f1',
    callbacks: WidgetCallbacks,
    iconUrl: string = GHOST_CURSOR_ICON,
  ) {
    this.callbacks = callbacks;
    this.iconUrl = iconUrl;

    // Create custom element host
    this.hostEl = document.createElement('ghost-cursor-widget');
    this.hostEl.style.cssText = 'all: initial; position: fixed; z-index: 999996;';
    (mountPoint || document.body).appendChild(this.hostEl);

    // Shadow root for CSS isolation
    this.shadow = this.hostEl.attachShadow({ mode: 'open' });

    // Inject styles
    const styleEl = document.createElement('style');
    styleEl.textContent = getWidgetStyles(primaryColor);
    this.shadow.appendChild(styleEl);

    // Build UI
    this.buildUI();
  }

  private renderIconHtml(): string {
    const icon = (this.iconUrl || '').trim();
    if (icon.startsWith('<svg')) {
      return icon;
    }
    return `<img src="${icon}" class="gc-toggle-img" alt="Ghost Cursor" />`;
  }

  private buildUI(): void {
    // Toggle button
    this.toggleBtn = document.createElement('button');
    this.toggleBtn.className = 'gc-toggle';
    this.toggleBtn.innerHTML = `<div class="gc-toggle-icon">${this.renderIconHtml()}</div>`;
    this.toggleBtn.setAttribute('aria-label', 'Open Ghost Cursor AI assistant');
    this.toggleBtn.addEventListener('click', () => this.toggle());
    this.shadow.appendChild(this.toggleBtn);

    // Chat panel
    this.panel = document.createElement('div');
    this.panel.className = 'gc-panel';
    this.panel.setAttribute('role', 'dialog');
    this.panel.setAttribute('aria-label', 'Ghost Cursor AI Assistant');
    this.panel.innerHTML = `
      <div class="gc-header">
        <div class="gc-header-avatar">${this.renderIconHtml()}</div>
        <div class="gc-header-info">
          <h3>Ghost Cursor</h3>
          <p>AI Co-pilot • Ready to help</p>
        </div>
        <button class="gc-close-btn" aria-label="Close">✕</button>
      </div>
      <div class="gc-messages" role="log" aria-live="polite">
        <div class="gc-msg assistant">
          Hi! I'm Ghost Cursor, your AI co-pilot. I can navigate the app, fill forms, run guided tours, and answer questions for you. What would you like to do? 🚀
        </div>
      </div>
      <div class="gc-suggestions" style="display: none;"></div>
      <div class="gc-input-area">
        <textarea class="gc-textarea" placeholder="Ask me anything..." rows="1" aria-label="Type your message"></textarea>
        <button class="gc-send-btn" aria-label="Send message">↑</button>
      </div>
    `;
    this.shadow.appendChild(this.panel);

    // Cache elements
    this.messagesEl = this.panel.querySelector('.gc-messages')!;
    this.suggestionsEl = this.panel.querySelector('.gc-suggestions')!;
    this.textareaEl = this.panel.querySelector('.gc-textarea')!;
    this.sendBtn = this.panel.querySelector('.gc-send-btn')!;

    // Event listeners
    this.panel.querySelector('.gc-close-btn')!.addEventListener('click', () => this.toggle());

    this.sendBtn.addEventListener('click', () => this.handleSend());

    this.textareaEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.handleSend();
      }
    });

    // Auto-resize textarea
    this.textareaEl.addEventListener('input', () => {
      this.textareaEl.style.height = 'auto';
      this.textareaEl.style.height = Math.min(this.textareaEl.scrollHeight, 120) + 'px';
    });
  }

  private toggle(): void {
    this.isOpen = !this.isOpen;
    this.panel.classList.toggle('visible', this.isOpen);
    this.toggleBtn.classList.toggle('open', this.isOpen);
    this.toggleBtn.innerHTML = this.isOpen
      ? '<span class="gc-toggle-close">✕</span>'
      : `<div class="gc-toggle-icon">${this.renderIconHtml()}</div>`;
    if (this.isOpen) {
      this.textareaEl.focus();
    }
  }

  private handleSend(): void {
    if (this.disabled) return;
    const msg = this.textareaEl.value.trim();
    if (!msg) return;
    this.clearSuggestions();
    this.textareaEl.value = '';
    this.textareaEl.style.height = 'auto';
    this.callbacks.onSendMessage(msg);
  }

  // ── Public API ──

  /** Set suggested questions quick prompts. */
  setSuggestions(suggestions: string[]): void {
    if (!this.suggestionsEl) return;
    if (!suggestions || suggestions.length === 0) {
      this.clearSuggestions();
      return;
    }

    this.suggestionsEl.innerHTML = '';
    suggestions.slice(0, 3).forEach(text => {
      const chip = document.createElement('button');
      chip.className = 'gc-suggestion-chip';
      chip.textContent = text;
      chip.addEventListener('click', () => {
        this.clearSuggestions();
        this.callbacks.onSendMessage(text);
      });
      this.suggestionsEl.appendChild(chip);
    });

    this.suggestionsEl.style.display = 'flex';
  }

  /** Clear and hide suggested questions chips. */
  clearSuggestions(): void {
    if (this.suggestionsEl) {
      this.suggestionsEl.innerHTML = '';
      this.suggestionsEl.style.display = 'none';
    }
  }


  /** Add a user message bubble. */
  addUserMessage(text: string): void {
    const div = document.createElement('div');
    div.className = 'gc-msg user';
    div.textContent = text;
    this.messagesEl.appendChild(div);
    this.scrollToBottom();
  }

  /** Add an assistant text reply. */
  addAssistantMessage(text: string): void {
    this.removeLoading();
    const div = document.createElement('div');
    div.className = 'gc-msg assistant';
    div.innerHTML = this.renderMarkdown(text);
    this.messagesEl.appendChild(div);
    this.scrollToBottom();
  }

  /** Add a system message. */
  addSystemMessage(text: string): void {
    const div = document.createElement('div');
    div.className = 'gc-msg system';
    div.textContent = text;
    this.messagesEl.appendChild(div);
    this.scrollToBottom();
  }

  /** Show the action plan with approve/reject buttons. */
  showActionPlan(actions: ActionItem[], reply?: string): void {
    this.removeLoading();

    if (reply) {
      this.addAssistantMessage(reply);
    }

    const card = document.createElement('div');
    card.className = 'gc-action-plan';

    const stepsHtml = actions.map((a, i) => {
      const p = a.parameters || {};
      const rawExp = p.explanation ?? `${a.tool}(${p.target_id ?? p.target_page ?? ''})`;
      const explanation = String(rawExp);
      return `
        <div class="gc-action-step" data-step-id="${a.id}">
          <div class="gc-step-icon">${i + 1}</div>
          <div>
            <strong>${this.escapeHtml(a.tool)}</strong>
            <div style="color: var(--gc-text-secondary); font-size: 12px;">${this.escapeHtml(explanation)}</div>
          </div>
        </div>
      `;
    }).join('');

    card.innerHTML = `
      <h4>🎯 Planned Actions</h4>
      ${stepsHtml}
      <div class="gc-action-buttons">
        <button class="gc-btn gc-btn-primary gc-approve-btn">✓ Approve and Run</button>
        <button class="gc-btn gc-btn-secondary gc-reject-btn">✕ Cancel</button>
      </div>
    `;

    card.querySelector('.gc-approve-btn')!.addEventListener('click', () => {
      this.setActionsDisabled(card, true);
      this.callbacks.onApproveActions();
    });
    card.querySelector('.gc-reject-btn')!.addEventListener('click', () => {
      this.setActionsDisabled(card, true);
      this.callbacks.onRejectActions();
    });

    this.messagesEl.appendChild(card);
    this.scrollToBottom();
  }

  /** Update a step's visual status during execution. */
  updateStepStatus(stepId: string, status: 'running' | 'done' | 'failed'): void {
    const step = this.messagesEl.querySelector(`[data-step-id="${CSS.escape(stepId)}"]`);
    if (!step) return;
    const icon = step.querySelector('.gc-step-icon') as HTMLElement;
    if (!icon) return;

    icon.className = `gc-step-icon ${status}`;
    if (status === 'done') icon.textContent = '✓';
    else if (status === 'failed') icon.textContent = '✕';
  }

  /** Show clarification question with option buttons. */
  showQuestion(question: QuestionItem): void {
    this.removeLoading();

    const div = document.createElement('div');
    div.className = 'gc-question';

    const opts = question.options || [];
    const optionsHtml = opts.map(opt =>
      `<button class="gc-option-btn">${this.escapeHtml(opt)}</button>`
    ).join('');


    div.innerHTML = `
      <div class="gc-msg assistant">${this.renderMarkdown(question.question)}</div>
      ${optionsHtml}
    `;

    div.querySelectorAll('.gc-option-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.callbacks.onAnswerQuestion(btn.textContent || '');
        // Disable all option buttons
        div.querySelectorAll('.gc-option-btn').forEach(b => {
          (b as HTMLButtonElement).disabled = true;
          (b as HTMLElement).style.opacity = '0.5';
        });
        (btn as HTMLElement).style.opacity = '1';
        (btn as HTMLElement).style.borderColor = 'var(--gc-primary)';
        (btn as HTMLElement).style.color = 'var(--gc-primary)';
      });
    });

    this.messagesEl.appendChild(div);
    this.scrollToBottom();
  }

  /** Show loading dots. */
  showLoading(): void {
    this.removeLoading();
    const div = document.createElement('div');
    div.className = 'gc-loading';
    div.id = 'gc-loading';
    div.innerHTML = '<div class="gc-dot"></div><div class="gc-dot"></div><div class="gc-dot"></div>';
    this.messagesEl.appendChild(div);
    this.scrollToBottom();
  }

  /** Remove loading indicator. */
  removeLoading(): void {
    this.shadow.getElementById('gc-loading')?.remove();
  }

  /** Disable/enable the input. */
  setInputDisabled(disabled: boolean): void {
    this.disabled = disabled;
    this.textareaEl.disabled = disabled;
    (this.sendBtn as HTMLButtonElement).disabled = disabled;
  }

  private setActionsDisabled(card: HTMLElement, disabled: boolean): void {
    card.querySelectorAll('button').forEach(btn => {
      (btn as HTMLButtonElement).disabled = disabled;
    });
  }

  private scrollToBottom(): void {
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /** Convert markdown into sanitized, formatted HTML */
  private renderMarkdown(raw: string): string {
    if (!raw) return '';

    // HTML-escape to ensure XSS safety
    const escaped = this.escapeHtml(raw);

    const lines = escaped.split('\n');
    const result: string[] = [];
    let inList: 'ul' | 'ol' | null = null;
    let inCodeBlock = false;
    let codeBlockContent: string[] = [];

    const closeList = () => {
      if (inList === 'ul') {
        result.push('</ul>');
        inList = null;
      } else if (inList === 'ol') {
        result.push('</ol>');
        inList = null;
      }
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Code blocks ```
      if (line.trim().startsWith('```')) {
        if (inCodeBlock) {
          result.push(`<pre class="gc-code-block"><code>${codeBlockContent.join('\n')}</code></pre>`);
          codeBlockContent = [];
          inCodeBlock = false;
        } else {
          closeList();
          inCodeBlock = true;
        }
        continue;
      }

      if (inCodeBlock) {
        codeBlockContent.push(line);
        continue;
      }

      // Check unordered list item (- item or * item)
      const ulMatch = line.match(/^(\s*)[-*]\s+(.+)$/);
      if (ulMatch) {
        if (inList !== 'ul') {
          closeList();
          result.push('<ul class="gc-list">');
          inList = 'ul';
        }
        result.push(`<li>${this.formatInlineMarkdown(ulMatch[2])}</li>`);
        continue;
      }

      // Check ordered list item (1. item)
      const olMatch = line.match(/^(\s*)\d+\.\s+(.+)$/);
      if (olMatch) {
        if (inList !== 'ol') {
          closeList();
          result.push('<ol class="gc-list">');
          inList = 'ol';
        }
        result.push(`<li>${this.formatInlineMarkdown(olMatch[2])}</li>`);
        continue;
      }

      // Regular line: close any open list
      closeList();

      if (line.trim() === '') {
        result.push('<div style="height: 6px;"></div>');
      } else {
        result.push(`<p>${this.formatInlineMarkdown(line)}</p>`);
      }
    }

    if (inCodeBlock && codeBlockContent.length > 0) {
      result.push(`<pre class="gc-code-block"><code>${codeBlockContent.join('\n')}</code></pre>`);
    }
    closeList();

    return result.join('');
  }

  private formatInlineMarkdown(text: string): string {
    return text
      // Inline code: `code`
      .replace(/`([^`]+)`/g, '<code class="gc-inline-code">$1</code>')
      // Bold + Italic: ***text***
      .replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>')
      // Bold: **text** or __text__
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/__([^_]+)__/g, '<strong>$1</strong>')
      // Italic: *text* or _text_
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/_([^_]+)_/g, '<em>$1</em>');
  }

  /** Open the chat panel. */
  open(): void {
    if (!this.isOpen) this.toggle();
  }

  /** Close the chat panel. */
  close(): void {
    if (this.isOpen) this.toggle();
  }

  /** Set docking state (undocked hides the solid cursor inside the toggle button). */
  setDocked(docked: boolean): void {
    if (this.toggleBtn) {
      this.toggleBtn.classList.toggle('undocked', !docked);
    }
  }

  /** Get the bounding rectangle of the floating toggle button. */
  getToggleRect(): DOMRect {
    return this.toggleBtn.getBoundingClientRect();
  }

  /** Remove widget from DOM. */
  dispose(): void {
    this.hostEl.remove();
  }
}

