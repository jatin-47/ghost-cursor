/**
 * @ghost-cursor/sdk – Context Provider
 *
 * Scans registered targets and declarative DOM annotations on the current page
 * to build a GhostContext snapshot. Uses MutationObserver for reactive tracking
 * and enforces a ~5 KB output budget.
 */

import type { GhostContext, Target } from '../types.js';
import { isSafeTarget } from './target-resolver.js';

/** Maximum serialised context payload size (~5 KB) */
const MAX_CONTEXT_BYTES = 5 * 1024;

/** Maximum interactable targets per snapshot (matches orchestrator schema ceiling) */
const MAX_TARGETS_LIMIT = 100;

/** Input types that are never observed for security/privacy. */
const EXCLUDED_INPUT_TYPES = new Set(['password', 'file', 'hidden']);

/** Logical ID format: 1-120 characters, matching ^[a-zA-Z0-9_.:-]+$ */
const LOGICAL_ID_REGEX = /^[a-zA-Z0-9_.:-]+$/;

/**
 * Context provider that observes registered and declarative targets and produces snapshots.
 */
export class ContextProvider {
  private targets: Record<string, Target>;
  private observer: MutationObserver | null = null;
  private onChangeCallback: (() => void) | null = null;

  constructor(targets: Record<string, Target> = {}) {
    this.targets = targets;
  }

  /**
   * Update the targets registry (e.g. when targets change at runtime).
   */
  setTargets(targets: Record<string, Target>): void {
    this.targets = targets;
  }

  /**
   * Scan all registered targets and declarative DOM annotations for the current page
   * and build a GhostContext snapshot.
   *
   * @param currentPage - The active logical page identifier or URL path
   * @returns A context snapshot bounded to ~5 KB and max 100 targets
   */
  scanContext(currentPage: string): GhostContext {
    const page = currentPage || (typeof window !== 'undefined' ? window.location.pathname : '/');
    const values: Record<string, string | number | boolean> = {};
    const availableTargets: string[] = [];
    const seenElements = new Set<Element>();

    // 1. Declarative DOM Auto-Discovery via data-ghost-id
    if (typeof document !== 'undefined') {
      try {
        const ghostElements = document.querySelectorAll<HTMLElement>('[data-ghost-id]');
        for (const el of ghostElements) {
          if (availableTargets.length >= MAX_TARGETS_LIMIT) break;
          const id = el.getAttribute('data-ghost-id')?.trim();
          if (!id || !this.isValidLogicalId(id)) continue;
          if (!isSafeTarget(el)) continue;

          seenElements.add(el);
          if (!availableTargets.includes(id)) {
            availableTargets.push(id);
          }

          if (values[id] === undefined) {
            const autoVal = this.autoObserve(el);
            if (autoVal !== undefined) {
              values[id] = autoVal;
            }
          }
        }
      } catch {
        // Silently skip if DOM querying fails in restricted environments
      }
    }

    // 2. Programmatically registered targets in config
    for (const [id, target] of Object.entries(this.targets)) {
      if (!this.isValidLogicalId(id)) continue;
      // Only include targets that belong to the current page
      if (!this.isOnPage(target, page)) continue;

      // Check if the element is resolvable
      const el = this.tryResolveElement(id, target);
      if (el && isSafeTarget(el)) {
        seenElements.add(el);
        if (!availableTargets.includes(id) && availableTargets.length < MAX_TARGETS_LIMIT) {
          availableTargets.push(id);
        }
      }

      // Observe value if a custom observer is registered
      if (target.observe) {
        try {
          const val = target.observe();
          if (val !== undefined) {
            values[id] = val;
          }
        } catch {
          // Silently skip targets whose observe() throws
        }
      } else if (el && values[id] === undefined) {
        // Auto-observe common form elements
        const autoVal = this.autoObserve(el);
        if (autoVal !== undefined) {
          values[id] = autoVal;
        }
      }
    }

    // 3. Fallback Auto-Discovery: data-testid and common interactive form controls
    if (typeof document !== 'undefined' && availableTargets.length < MAX_TARGETS_LIMIT) {
      try {
        // Elements with data-testid (if not already discovered via data-ghost-id)
        const testElements = document.querySelectorAll<HTMLElement>('[data-testid]');
        for (const el of testElements) {
          if (availableTargets.length >= MAX_TARGETS_LIMIT) break;
          if (seenElements.has(el) || el.hasAttribute('data-ghost-id')) continue;
          const testId = el.getAttribute('data-testid')?.trim();
          if (!testId || !this.isValidLogicalId(testId)) continue;
          if (!isSafeTarget(el)) continue;

          seenElements.add(el);
          if (!availableTargets.includes(testId)) {
            availableTargets.push(testId);
          }

          if (values[testId] === undefined) {
            const autoVal = this.autoObserve(el);
            if (autoVal !== undefined) {
              values[testId] = autoVal;
            }
          }
        }

        // Standard interactive form controls (inputs, selects, textareas with id or name)
        const formControls = document.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
          'input, select, textarea',
        );
        for (const el of formControls) {
          if (availableTargets.length >= MAX_TARGETS_LIMIT) break;
          if (seenElements.has(el) || el.hasAttribute('data-ghost-id') || el.hasAttribute('data-testid')) continue;
          const id = el.id?.trim() || el.name?.trim();
          if (!id || !this.isValidLogicalId(id)) continue;
          if (!isSafeTarget(el)) continue;

          seenElements.add(el);
          if (!availableTargets.includes(id)) {
            availableTargets.push(id);
          }

          if (values[id] === undefined) {
            const autoVal = this.autoObserve(el);
            if (autoVal !== undefined) {
              values[id] = autoVal;
            }
          }
        }
      } catch {
        // Silently skip
      }
    }

    const context: GhostContext = {
      page,
      values,
      availableTargets,
    };

    // Enforce size budget
    return this.enforceLimit(context);
  }

  /**
   * Start observing the DOM for mutations. Calls `onChange` when elements
   * that could affect context are added/removed/changed.
   */
  startObserving(onChange: () => void): void {
    this.stopObserving();
    this.onChangeCallback = onChange;

    if (typeof MutationObserver === 'undefined' || typeof document === 'undefined') return;

    this.observer = new MutationObserver((mutations) => {
      // Only fire for relevant mutations (attributes, child list)
      const isRelevant = mutations.some(
        (m) =>
          m.type === 'childList' ||
          (m.type === 'attributes' &&
            ['value', 'checked', 'disabled', 'aria-label', 'data-ghost-id', 'data-testid'].includes(
              m.attributeName ?? '',
            )),
      );
      if (isRelevant && this.onChangeCallback) {
        this.onChangeCallback();
      }
    });

    try {
      this.observer.observe(document.body || document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['value', 'checked', 'disabled', 'aria-label', 'data-ghost-id', 'data-testid'],
      });
    } catch {
      // Ignore observation failure if body is not ready
    }
  }

  /**
   * Stop the MutationObserver.
   */
  stopObserving(): void {
    if (this.observer) {
      this.observer.disconnect();
      this.observer = null;
    }
    this.onChangeCallback = null;
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  /** Validate a logical ID against the Ghost protocol specification. */
  private isValidLogicalId(id: string): boolean {
    return id.length >= 1 && id.length <= 120 && LOGICAL_ID_REGEX.test(id);
  }

  /** Check if a target belongs to the given page with path normalization. */
  private isOnPage(target: Target, page: string): boolean {
    const normalize = (p: string) => {
      const trimmed = p.replace(/^\/+|\/+$/g, '').toLowerCase();
      if (!trimmed || trimmed === 'dashboard' || trimmed === 'catalog' || trimmed === 'index') return 'home';
      return trimmed;
    };

    const normPage = normalize(page);
    const pages = Array.isArray(target.page) ? target.page : [target.page];

    return pages.some((p) => {
      if (p === '*') return true;
      if (p === page) return true;
      return normalize(p) === normPage;
    });
  }

  /**
   * Try to resolve an element for a target. Returns null if not found
   * or if it's a forbidden input type.
   */
  private tryResolveElement(id: string, target: Target): HTMLElement | null {
    let el: HTMLElement | null = null;

    // Use custom resolver first
    if (target.resolve) {
      try {
        el = target.resolve();
      } catch {
        return null;
      }
    }

    // Fall back to data-ghost-id attribute
    if (!el && typeof document !== 'undefined') {
      try {
        el = document.querySelector<HTMLElement>(`[data-ghost-id="${CSS.escape(id)}"]`);
      } catch {
        el = document.querySelector<HTMLElement>(`[data-ghost-id="${id}"]`);
      }
    }

    if (!el) return null;

    // Reject excluded input types
    const tagName = el.tagName?.toUpperCase();
    if (tagName === 'INPUT') {
      const inputEl = el as HTMLInputElement;
      if (EXCLUDED_INPUT_TYPES.has((inputEl.type || '').toLowerCase())) {
        return null;
      }
    }

    return el;
  }

  /**
   * Auto-observe value from common form elements and state nodes.
   */
  private autoObserve(el: HTMLElement): string | number | boolean | undefined {
    // Action triggers (buttons and links) do not hold UI state values unless annotated
    const tagName = el.tagName?.toUpperCase();
    if (tagName === 'BUTTON' || tagName === 'A' || el.getAttribute('role') === 'button') {
      if (!el.hasAttribute('data-ghost-value')) {
        return undefined;
      }
    }

    // Explicit data-ghost-value attribute takes precedence
    if (el.hasAttribute('data-ghost-value')) {
      const v = el.getAttribute('data-ghost-value');
      return v ?? undefined;
    }

    // Standard form elements
    if (tagName === 'INPUT') {
      const inputEl = el as HTMLInputElement;
      const type = (inputEl.type || 'text').toLowerCase();
      if (EXCLUDED_INPUT_TYPES.has(type)) return undefined;
      if (type === 'checkbox' || type === 'radio') return inputEl.checked;
      if (type === 'number' || type === 'range') {
        return inputEl.value !== '' ? Number(inputEl.value) : undefined;
      }
      return inputEl.value !== '' ? inputEl.value : undefined;
    }
    if (tagName === 'TEXTAREA') {
      const textEl = el as HTMLTextAreaElement;
      return textEl.value !== '' ? textEl.value : undefined;
    }
    if (tagName === 'SELECT') {
      const selEl = el as HTMLSelectElement;
      return selEl.value !== '' ? selEl.value : undefined;
    }

    // Generic data-value attribute
    if (el.hasAttribute('data-value')) {
      return el.getAttribute('data-value') ?? undefined;
    }

    // ARIA value (e.g. custom sliders, switches)
    if (el.hasAttribute('aria-valuenow')) {
      const v = el.getAttribute('aria-valuenow');
      const n = Number(v);
      return !isNaN(n) ? n : (v ?? undefined);
    }

    // Leaf elements with brief text content (e.g. confirmation badges, IDs)
    if (el.children.length === 0 && el.textContent) {
      const text = el.textContent.trim();
      if (text.length > 0 && text.length <= 100) {
        return text;
      }
    }

    return undefined;
  }

  /**
   * Enforce the ~5 KB output budget by truncating values if needed.
   */
  private enforceLimit(context: GhostContext): GhostContext {
    let json = JSON.stringify(context);
    const byteLength = new TextEncoder().encode(json).byteLength;

    if (byteLength <= MAX_CONTEXT_BYTES) return context;

    // Trim values to fit within budget — remove least-important entries
    const trimmed = {
      ...context,
      values: { ...context.values },
      availableTargets: [...context.availableTargets],
    };
    const keys = Object.keys(trimmed.values);

    while (keys.length > 0) {
      const key = keys.pop()!;
      const val = trimmed.values[key];
      // Truncate long string values first
      if (typeof val === 'string' && val.length > 100) {
        trimmed.values[key] = val.slice(0, 100) + '…';
      } else {
        delete trimmed.values[key];
      }

      json = JSON.stringify(trimmed);
      if (new TextEncoder().encode(json).byteLength <= MAX_CONTEXT_BYTES) return trimmed;
    }

    // If still over budget, cap availableTargets
    while (trimmed.availableTargets.length > 10) {
      trimmed.availableTargets.pop();
      json = JSON.stringify(trimmed);
      if (new TextEncoder().encode(json).byteLength <= MAX_CONTEXT_BYTES) break;
    }

    return trimmed;
  }
}
