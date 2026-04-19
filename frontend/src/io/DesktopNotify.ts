/**
 * DesktopNotify — thin wrapper around the Tauri `notify` command.
 *
 * Falls back silently in browser mode (non-Tauri).  All callers should treat
 * this as fire-and-forget: send a notification and move on.
 */

const _tauri = (window as any).__TAURI_INTERNALS__;
const _isTauri = _tauri?.invoke != null;

function invoke(cmd: string, args: Record<string, unknown>): void {
  if (_isTauri) _tauri.invoke(cmd, args).catch(() => {});
}

export function desktopNotify(title: string, body: string): void {
  invoke("notify", { title, body });
}

/** Notify only when the window is not focused (avoid interrupting active use). */
export function desktopNotifyBackground(title: string, body: string): void {
  if (!_isTauri) return;
  if (document.hasFocus()) return;
  desktopNotify(title, body);
}
