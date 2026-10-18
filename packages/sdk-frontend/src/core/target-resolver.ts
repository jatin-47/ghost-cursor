/**
 * Element Targeting Cascade — resolves DOM elements through 5 fallback levels.
 * 
 * Priority:
 * 1. data-ghost-id (explicit logical ID)
 * 2. data-testid (automated test ID)
 * 3. DOM id attribute
 * 4. ARIA labels (aria-label, role)
 * 5. Semantic text matching (visible text content)
 */

const RESOLVE_TIMEOUT = 8000; // 8 seconds
const POLL_INTERVAL = 200; // ms

/** Safety-check: reject elements that shouldn't be automated. */
export function isSafeTarget(el: Element): boolean {
  if (!el.isConnected) return false;

  const htmlEl = el as HTMLElement;

  // Reject inert elements
  if (htmlEl.inert) return false;

  // Reject explicitly hidden elements
  if (htmlEl.hidden || htmlEl.getAttribute('aria-hidden') === 'true') return false;

  // Reject hidden/invisible elements
  const isFixed = htmlEl.style?.position === 'fixed' ||
    (typeof window !== 'undefined' && typeof window.getComputedStyle === 'function' && window.getComputedStyle(htmlEl).position === 'fixed');
  if (htmlEl.offsetParent === null && !isFixed) {
    if (htmlEl.style?.display === 'none' || htmlEl.style?.visibility === 'hidden') return false;
    if (typeof window !== 'undefined' && typeof window.getComputedStyle === 'function') {
      try {
        const style = window.getComputedStyle(htmlEl);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
      } catch {
        // Ignore style computation errors
      }
    }
  }

  // Reject disabled elements
  if ((el as HTMLInputElement).disabled) return false;

  // Reject sensitive input types
  const inputEl = el as HTMLInputElement;
  if (inputEl.tagName === 'INPUT') {
    const sensitiveTypes = ['password', 'file', 'hidden'];
    if (sensitiveTypes.includes((inputEl.type || '').toLowerCase())) return false;
  }

  return true;
}

/** Level 1: Explicit logical ID via data-ghost-id attribute */
function resolveByGhostId(targetId: string): Element | null {
  return document.querySelector(`[data-ghost-id="${CSS.escape(targetId)}"]`);
}

/** Level 2: Automated test ID via data-testid attribute */
function resolveByTestId(targetId: string): Element | null {
  // Convert dot notation to dash notation for testids
  const testId = targetId.replace(/\./g, '-');
  return document.querySelector(`[data-testid="${CSS.escape(testId)}"]`)
    || document.querySelector(`[data-testid="${CSS.escape(targetId)}"]`);
}

/** Level 3: Standard DOM id attribute */
function resolveById(targetId: string): Element | null {
  const id = targetId.replace(/\./g, '-');
  return document.getElementById(id) || document.getElementById(targetId);
}

/** Level 4: ARIA accessibility labels */
function resolveByAria(targetId: string): Element | null {
  const label = targetId.replace(/[._]/g, ' ');
  return document.querySelector(`[aria-label="${CSS.escape(label)}"]`)
    || document.querySelector(`[aria-label*="${CSS.escape(label)}"]`);
}

/** Level 5: Semantic text / visible value matching */
function resolveByText(targetId: string): Element | null {
  const searchText = targetId.replace(/[._]/g, ' ').toLowerCase();
  
  // Search buttons, links, and labeled elements
  const candidates = document.querySelectorAll('button, a, [role="button"], label, [role="tab"]');
  for (const el of candidates) {
    const text = (el.textContent || '').trim().toLowerCase();
    if (text === searchText || text.includes(searchText)) {
      return el;
    }
  }
  return null;
}

/**
 * Resolve a target element through the 5-level cascade.
 * Polls with bounded timeout.
 */
export async function resolveTarget(targetId: string, timeout: number = RESOLVE_TIMEOUT): Promise<Element> {
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    // Try each level in priority order
    const resolvers = [resolveByGhostId, resolveByTestId, resolveById, resolveByAria, resolveByText];
    
    for (const resolver of resolvers) {
      const el = resolver(targetId);
      if (el && isSafeTarget(el)) {
        return el;
      }
    }

    // Poll wait
    await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL));
  }

  throw new Error(`Target "${targetId}" could not be resolved within ${timeout}ms.`);
}

/**
 * Re-resolve immediately before acting to avoid stale references.
 * Uses only a single attempt (no polling).
 */
export function reResolveTarget(targetId: string): Element | null {
  const resolvers = [resolveByGhostId, resolveByTestId, resolveById, resolveByAria, resolveByText];
  for (const resolver of resolvers) {
    const el = resolver(targetId);
    if (el && isSafeTarget(el)) return el;
  }
  return null;
}

