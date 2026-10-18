/**
 * Guided Tour Engine — multi-step spotlight walkthroughs.
 * 
 * Highlights elements sequentially with explanatory tooltips,
 * dark overlay with cutout, and next/prev/skip navigation.
 * Supports cross-page navigation between tour steps.
 */

import { resolveTarget } from './target-resolver';

export interface TourStep {
  target_id: string;
  message: string;
  page?: string;
  route?: string;
  spotlight?: boolean;
}

export class TourEngine {
  private overlay: HTMLElement | null = null;
  private tooltip: HTMLElement | null = null;
  private steps: TourStep[] = [];
  private currentStep = 0;
  private onComplete?: () => void;
  private active = false;

  /**
   * Start a guided tour with multiple steps.
   */
  async startTour(steps: TourStep[], onComplete?: () => void): Promise<void> {
    this.steps = steps;
    this.currentStep = 0;
    this.onComplete = onComplete;
    this.active = true;

    this.createOverlay();
    await this.showStep(0);
  }

  private createOverlay(): void {
    // Dark overlay with cutout
    this.overlay = document.createElement('div');
    this.overlay.id = 'ghost-tour-overlay';
    this.overlay.style.cssText = `
      position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
      background: rgba(0, 0, 0, 0.55); z-index: 999990;
      transition: clip-path 0.3s ease, opacity 0.3s ease;
      pointer-events: auto;
    `;

    // Tooltip container
    this.tooltip = document.createElement('div');
    this.tooltip.id = 'ghost-tour-tooltip';
    this.tooltip.style.cssText = `
      position: fixed; z-index: 999995; max-width: 380px; width: 90vw;
      background: white; border-radius: 14px; padding: 22px;
      box-shadow: 0 25px 65px rgba(0,0,0,0.35), 0 0 0 1px rgba(0,0,0,0.06);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    `;

    document.body.appendChild(this.overlay);
    document.body.appendChild(this.tooltip);
  }

  private inferPageFromTarget(targetId: string): string | null {
    if (targetId.startsWith('orders.')) return '/orders';
    if (targetId.startsWith('settings.')) return '/settings';
    if (targetId.startsWith('cart.')) return '/cart';
    if (targetId.startsWith('checkout.')) return '/checkout';
    if (targetId.startsWith('catalog.')) return '/';
    return null;
  }

  private async navigateTo(targetPage: string): Promise<void> {
    const clean = targetPage.startsWith('/') ? targetPage : `/${targetPage}`;
    const navName = clean.replace('/', '');
    const navLink = (document.querySelector(`[data-ghost-nav="${CSS.escape(clean)}"]`) ||
      document.querySelector(`[data-ghost-nav="${CSS.escape(navName)}"]`) ||
      document.querySelector(`[data-ghost-id="nav.${CSS.escape(navName)}"]`)) as HTMLElement | null;

    if (navLink) {
      navLink.click();
    } else {
      window.history.pushState({}, '', clean);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
    await new Promise(r => setTimeout(r, 450));
  }

  private async showStep(index: number): Promise<void> {
    if (!this.active || index >= this.steps.length || !this.tooltip) return;

    const step = this.steps[index];
    this.currentStep = index;

    // Auto-navigate if step belongs to another page
    const targetPage = step.page || step.route || this.inferPageFromTarget(step.target_id);
    if (targetPage && window.location.pathname !== targetPage) {
      await this.navigateTo(targetPage);
    }

    try {
      let el: Element | null = null;
      try {
        el = await resolveTarget(step.target_id, 3500);
      } catch (err) {
        // If resolution failed, try navigating if target implies another page
        const inferred = this.inferPageFromTarget(step.target_id);
        if (inferred && window.location.pathname !== inferred) {
          await this.navigateTo(inferred);
          el = await resolveTarget(step.target_id, 3500);
        } else {
          throw err;
        }
      }

      const htmlEl = el as HTMLElement;

      // Scroll smoothly into view
      htmlEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await new Promise(r => setTimeout(r, 320));

      // Position spotlight cutout around target
      const rect = htmlEl.getBoundingClientRect();
      const pad = 8;
      if (this.overlay) {
        this.overlay.style.clipPath = `polygon(
          0% 0%, 0% 100%, 
          ${rect.left - pad}px 100%, ${rect.left - pad}px ${rect.top - pad}px,
          ${rect.right + pad}px ${rect.top - pad}px, ${rect.right + pad}px ${rect.bottom + pad}px,
          ${rect.left - pad}px ${rect.bottom + pad}px, ${rect.left - pad}px 100%,
          100% 100%, 100% 0%
        )`;
      }

      // Highlight target element
      htmlEl.style.outline = '3px solid #6366f1';
      htmlEl.style.outlineOffset = '4px';
      htmlEl.style.borderRadius = '6px';
      htmlEl.style.position = 'relative';
      htmlEl.style.zIndex = '999993';

      // Update tooltip content
      this.tooltip.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
          <span style="font-size: 12px; color: #6366f1; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">
            🎬 Step ${index + 1} of ${this.steps.length}
          </span>
          <span style="font-size: 11px; color: #94a3b8; font-weight: 500;">
            Guided Tour
          </span>
        </div>
        <div style="font-size: 15px; line-height: 1.55; color: #1e293b; margin-bottom: 18px; font-weight: 450;">
          ${this.escapeHtml(step.message)}
        </div>
        <div style="display: flex; gap: 8px; justify-content: flex-end; align-items: center;">
          ${index > 0 ? '<button id="ghost-tour-prev" style="padding: 7px 14px; border: 1px solid #cbd5e1; border-radius: 8px; background: white; cursor: pointer; font-size: 13px; font-weight: 500; color: #475569;">← Back</button>' : ''}
          <button id="ghost-tour-skip" style="padding: 7px 14px; border: 1px solid #cbd5e1; border-radius: 8px; background: white; cursor: pointer; font-size: 13px; font-weight: 500; color: #64748b;">Skip</button>
          <button id="ghost-tour-next" style="padding: 7px 18px; border: none; border-radius: 8px; background: #6366f1; color: white; cursor: pointer; font-size: 13px; font-weight: 600; box-shadow: 0 2px 6px rgba(99,102,241,0.35);">
            ${index === this.steps.length - 1 ? 'Finish ✓' : 'Next →'}
          </button>
        </div>
      `;

      // Position tooltip near element
      const tooltipRect = this.tooltip.getBoundingClientRect();
      const tooltipHeight = tooltipRect.height || 180;
      const tooltipWidth = tooltipRect.width || 340;

      let top = rect.bottom + pad + 14;
      let left = rect.left;

      // Flip above if not enough bottom clearance
      if (top + tooltipHeight > window.innerHeight - 20) {
        top = Math.max(16, rect.top - pad - tooltipHeight - 14);
      }
      // Keep inside horizontal boundaries
      if (left + tooltipWidth > window.innerWidth - 20) {
        left = window.innerWidth - tooltipWidth - 20;
      }
      left = Math.max(16, left);

      this.tooltip.style.top = `${top}px`;
      this.tooltip.style.left = `${left}px`;

      // Event listeners
      this.tooltip.querySelector('#ghost-tour-next')?.addEventListener('click', () => {
        this.cleanupStepHighlight(htmlEl);
        if (index === this.steps.length - 1) {
          this.endTour();
        } else {
          this.showStep(index + 1);
        }
      });

      this.tooltip.querySelector('#ghost-tour-prev')?.addEventListener('click', () => {
        this.cleanupStepHighlight(htmlEl);
        this.showStep(index - 1);
      });

      this.tooltip.querySelector('#ghost-tour-skip')?.addEventListener('click', () => {
        this.cleanupStepHighlight(htmlEl);
        this.endTour();
      });
    } catch {
      // Skip unreachable step
      if (index < this.steps.length - 1) {
        this.showStep(index + 1);
      } else {
        this.endTour();
      }
    }
  }

  private cleanupStepHighlight(el: HTMLElement): void {
    try {
      el.style.outline = '';
      el.style.outlineOffset = '';
      el.style.zIndex = '';
    } catch { /* ignore if already disconnected */ }
  }

  private endTour(): void {
    this.active = false;
    this.overlay?.remove();
    this.tooltip?.remove();
    this.overlay = null;
    this.tooltip = null;
    this.onComplete?.();
  }

  /** Stop the tour immediately. */
  dispose(): void {
    this.active = false;
    this.overlay?.remove();
    this.tooltip?.remove();
    this.overlay = null;
    this.tooltip = null;
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}
