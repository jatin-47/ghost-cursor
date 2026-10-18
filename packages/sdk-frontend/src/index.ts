/**
 * @ghost-cursor/sdk — Main Entry Point
 * 
 * Ghost Cursor Frontend SDK: Application-aware AI co-pilot widget.
 * Provides chat widget, AI cursor animation, action execution,
 * guided tours, and element targeting cascade.
 */

export { createGhostCursor } from './ghost-cursor';
export { ContextProvider } from './core/context-provider';
export { resolveTarget, isSafeTarget } from './core/target-resolver';
export type {
  GhostCursorConfig,
  GhostCursorInstance,
  Target,
  GhostContext,
  ActionItem,
  QuestionItem,
  RunResponse,
  GhostCursorTheme,
} from './types';

