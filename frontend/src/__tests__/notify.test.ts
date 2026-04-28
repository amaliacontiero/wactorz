import { describe, it, expect, vi, beforeEach } from "vitest";

// We need a fresh module for each test group so the _isTauri constant
// and _permissionGranted cache reset properly.

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
});

// ── Helper: install a Tauri stub ──────────────────────────────────────────────

function installTauri(invokeImpl?: (cmd: string) => Promise<unknown>) {
  const defaultImpl = async (cmd: string) => {
    if (cmd === "plugin:notification|is_permission_granted") return false;
    if (cmd === "plugin:notification|request_permission") return "granted";
    return undefined;
  };
  (globalThis as any).window = globalThis;
  (window as any).__TAURI_INTERNALS__ = {
    invoke: vi.fn(invokeImpl ?? defaultImpl),
  };
}

function removeTauri() {
  delete (window as any).__TAURI_INTERNALS__;
}

async function freshNotify() {
  return import("../io/DesktopNotify");
}

// ── Non-Tauri (browser) mode ──────────────────────────────────────────────────

describe("DesktopNotify — browser mode (no Tauri)", () => {
  beforeEach(removeTauri);

  it("initNotifications() is a no-op in browser mode", async () => {
    const { initNotifications } = await freshNotify();
    expect(() => initNotifications()).not.toThrow();
  });

  it("desktopNotify() is a no-op in browser mode", async () => {
    const { desktopNotify } = await freshNotify();
    expect(() => desktopNotify("Title", "Body")).not.toThrow();
  });

  it("desktopNotifyBackground() is a no-op in browser mode", async () => {
    const { desktopNotifyBackground } = await freshNotify();
    expect(() => desktopNotifyBackground("Title", "Body")).not.toThrow();
  });

  it("clearUnreadBadge() is a no-op in browser mode", async () => {
    const { clearUnreadBadge } = await freshNotify();
    expect(() => clearUnreadBadge()).not.toThrow();
  });
});

// ── Tauri mode ────────────────────────────────────────────────────────────────

describe("DesktopNotify — Tauri mode", () => {
  beforeEach(() => installTauri());
  afterEach(removeTauri);

  it("initNotifications() calls is_permission_granted", async () => {
    const { initNotifications } = await freshNotify();
    initNotifications();
    // Allow microtask queue to flush
    await new Promise((r) => setTimeout(r, 0));
    const invoke = (window as any).__TAURI_INTERNALS__.invoke;
    expect(invoke).toHaveBeenCalledWith("plugin:notification|is_permission_granted", {});
  });

  it("desktopNotify() calls notify and add_unread after permission granted", async () => {
    installTauri(async (cmd: string) => {
      if (cmd === "plugin:notification|is_permission_granted") return true;
      return undefined;
    });
    const { desktopNotify } = await freshNotify();
    desktopNotify("Hello", "World");
    await new Promise((r) => setTimeout(r, 0));
    const invoke = (window as any).__TAURI_INTERNALS__.invoke as ReturnType<typeof vi.fn>;
    const cmds = invoke.mock.calls.map((c: unknown[]) => c[0]);
    expect(cmds).toContain("notify");
    expect(cmds).toContain("add_unread");
  });

  it("desktopNotify() does not call notify when permission denied", async () => {
    installTauri(async (cmd: string) => {
      if (cmd === "plugin:notification|is_permission_granted") return false;
      if (cmd === "plugin:notification|request_permission") return "denied";
      return undefined;
    });
    const { desktopNotify } = await freshNotify();
    desktopNotify("Hi", "there");
    await new Promise((r) => setTimeout(r, 0));
    const invoke = (window as any).__TAURI_INTERNALS__.invoke as ReturnType<typeof vi.fn>;
    const cmds = invoke.mock.calls.map((c: unknown[]) => c[0]);
    expect(cmds).not.toContain("notify");
  });

  it("desktopNotifyBackground() skips notification when window has focus", async () => {
    // happy-dom: document.hasFocus() returns false by default
    // Override to return true
    Object.defineProperty(document, "hasFocus", { value: () => true, configurable: true });
    installTauri(async () => true);
    const { desktopNotifyBackground } = await freshNotify();
    desktopNotifyBackground("Hi", "there");
    await new Promise((r) => setTimeout(r, 0));
    const invoke = (window as any).__TAURI_INTERNALS__?.invoke as ReturnType<typeof vi.fn> | undefined;
    const cmds = invoke?.mock.calls.map((c: unknown[]) => c[0]) ?? [];
    expect(cmds).not.toContain("notify");
    Object.defineProperty(document, "hasFocus", { value: () => false, configurable: true });
  });

  it("desktopNotifyBackground() sends notification when window unfocused", async () => {
    Object.defineProperty(document, "hasFocus", { value: () => false, configurable: true });
    installTauri(async (cmd: string) => {
      if (cmd === "plugin:notification|is_permission_granted") return true;
      return undefined;
    });
    const { desktopNotifyBackground } = await freshNotify();
    desktopNotifyBackground("Hi", "there");
    await new Promise((r) => setTimeout(r, 0));
    const invoke = (window as any).__TAURI_INTERNALS__.invoke as ReturnType<typeof vi.fn>;
    const cmds = invoke.mock.calls.map((c: unknown[]) => c[0]);
    expect(cmds).toContain("notify");
  });

  it("clearUnreadBadge() invokes clear_unread", async () => {
    const { clearUnreadBadge } = await freshNotify();
    clearUnreadBadge();
    await new Promise((r) => setTimeout(r, 0));
    const invoke = (window as any).__TAURI_INTERNALS__.invoke as ReturnType<typeof vi.fn>;
    expect(invoke).toHaveBeenCalledWith("clear_unread", {});
  });

  it("invoke failure in clearUnreadBadge does not throw", async () => {
    installTauri(async () => { throw new Error("IPC error"); });
    const { clearUnreadBadge } = await freshNotify();
    expect(() => clearUnreadBadge()).not.toThrow();
  });

  it("ensurePermission caches result (only calls is_permission_granted once)", async () => {
    installTauri(async (cmd: string) => {
      if (cmd === "plugin:notification|is_permission_granted") return true;
      return undefined;
    });
    const { desktopNotify } = await freshNotify();
    // First call — resolves permission and caches it
    desktopNotify("A", "1");
    await new Promise((r) => setTimeout(r, 10));
    // Second call — should use cached _permissionGranted=true, not call again
    desktopNotify("B", "2");
    await new Promise((r) => setTimeout(r, 10));
    const invoke = (window as any).__TAURI_INTERNALS__.invoke as ReturnType<typeof vi.fn>;
    const permCalls = invoke.mock.calls.filter(
      (c: unknown[]) => c[0] === "plugin:notification|is_permission_granted",
    );
    expect(permCalls.length).toBe(1);
  });

  it("handles invoke throwing during permission check", async () => {
    installTauri(async () => { throw new Error("permission error"); });
    const { initNotifications } = await freshNotify();
    expect(() => initNotifications()).not.toThrow();
    await new Promise((r) => setTimeout(r, 0));
  });

  it("desktopNotify() warns when notify invoke fails after permission granted", async () => {
    installTauri(async (cmd: string) => {
      if (cmd === "plugin:notification|is_permission_granted") return true;
      if (cmd === "notify") throw new Error("notification blocked");
      return undefined;
    });
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { desktopNotify } = await freshNotify();
    desktopNotify("Hi", "there");
    await new Promise((r) => setTimeout(r, 20));
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("[DesktopNotify]"),
      expect.any(Error),
    );
    warnSpy.mockRestore();
  });
});
