/**
 * DesktopNotify — native OS notifications via Tauri IPC.
 *
 * Uses the Tauri plugin IPC directly (not window.Notification which is
 * unsupported in WKWebView on macOS).  Falls back silently in browser mode.
 */

const _isTauri =
  typeof window !== "undefined" &&
  (window as any).__TAURI_INTERNALS__ != null;

function invoke<T = void>(cmd: string, args: Record<string, unknown> = {}): Promise<T> {
  return (window as any).__TAURI_INTERNALS__.invoke(cmd, args) as Promise<T>;
}

let _permissionGranted: boolean | null = null;

async function ensurePermission(): Promise<boolean> {
  if (_permissionGranted !== null) return _permissionGranted;
  try {
    const granted = await invoke<boolean>("plugin:notification|is_permission_granted");
    if (granted) {
      _permissionGranted = true;
      return true;
    }
    // Request the native macOS permission dialog via Rust
    const result = await invoke<string>("plugin:notification|request_permission");
    _permissionGranted = result === "granted";
    return _permissionGranted;
  } catch (e) {
    console.warn("[DesktopNotify] permission check failed:", e);
    _permissionGranted = false;
    return false;
  }
}

/** Request permission eagerly — call once on startup so the dialog appears early. */
export function initNotifications(): void {
  if (!_isTauri) return;
  ensurePermission().then((granted) => {
    console.info("[DesktopNotify] permission:", granted ? "granted" : "denied");
  });
}

export function desktopNotify(title: string, body: string): void {
  if (!_isTauri) return;
  ensurePermission().then((granted) => {
    if (!granted) return;
    invoke("notify", { title, body }).catch((e) =>
      console.warn("[DesktopNotify] notify failed:", e),
    );
  });
  invoke("add_unread").catch(() => {});
}

/** Notify only when the window is not focused (avoid interrupting active use). */
export function desktopNotifyBackground(title: string, body: string): void {
  if (!_isTauri) return;
  if (document.hasFocus()) return;
  desktopNotify(title, body);
}

/** Clear the tray badge — call on window focus. */
export function clearUnreadBadge(): void {
  if (!_isTauri) return;
  invoke("clear_unread").catch(() => {});
}
