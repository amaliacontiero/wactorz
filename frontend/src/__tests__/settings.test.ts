import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SettingsPanel } from "../ui/SettingsPanel";

// ── Tauri stub ────────────────────────────────────────────────────────────────

const defaultConfig = {
  api_port: 8888,
  llm_provider: "anthropic",
  llm_model: "claude-sonnet-4-6",
  llm_api_key: "sk-test",
  mqtt_host: "localhost",
  mqtt_port: 1883,
  ha_url: "",
  ha_token: "",
  autostart: false,
};

function installTauri(invokeImpl?: (cmd: string, args?: any) => Promise<unknown>) {
  const impl = invokeImpl ?? (async (cmd: string) => {
    if (cmd === "get_config") return { ...defaultConfig };
    return undefined;
  });
  (window as any).__TAURI_INTERNALS__ = { invoke: vi.fn(impl) };
}

function removeTauri() {
  delete (window as any).__TAURI_INTERNALS__;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function overlay() { return document.getElementById("settings-overlay")!; }
function getInput(id: string) {
  return overlay().querySelector<HTMLInputElement | HTMLSelectElement>(`#${id}`)!;
}

describe("SettingsPanel", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    document.head.innerHTML = "";
    vi.clearAllMocks();
  });
  afterEach(removeTauri);

  // ── construction ──────────────────────────────────────────────────────────

  it("appends overlay to body on construction", () => {
    new SettingsPanel();
    expect(document.getElementById("settings-overlay")).not.toBeNull();
  });

  it("overlay starts hidden", () => {
    new SettingsPanel();
    expect(overlay().style.display).toBe("none");
  });

  it("injects CSS into head on construction", () => {
    new SettingsPanel();
    expect(document.getElementById("settings-styles")).not.toBeNull();
  });

  it("does not inject CSS twice when constructed twice", () => {
    new SettingsPanel();
    new SettingsPanel();
    expect(document.querySelectorAll("#settings-styles").length).toBe(1);
  });

  // ── open / close ──────────────────────────────────────────────────────────

  it("open() shows overlay", () => {
    installTauri();
    const panel = new SettingsPanel();
    panel.open();
    expect(overlay().style.display).toBe("flex");
  });

  it("close() hides overlay", () => {
    const panel = new SettingsPanel();
    panel.open();
    panel.close();
    expect(overlay().style.display).toBe("none");
  });

  it("clicking overlay backdrop closes panel", () => {
    const panel = new SettingsPanel();
    panel.open();
    overlay().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(overlay().style.display).toBe("none");
    void panel;
  });

  it("clicking inside modal does not close panel", () => {
    const panel = new SettingsPanel();
    panel.open();
    const modal = overlay().querySelector(".settings-modal")!;
    modal.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(overlay().style.display).toBe("flex");
    void panel;
  });

  it("close button closes panel", () => {
    const panel = new SettingsPanel();
    panel.open();
    (overlay().querySelector("#settings-close") as HTMLButtonElement).click();
    expect(overlay().style.display).toBe("none");
    void panel;
  });

  it("cancel button closes panel", () => {
    const panel = new SettingsPanel();
    panel.open();
    (overlay().querySelector("#settings-cancel") as HTMLButtonElement).click();
    expect(overlay().style.display).toBe("none");
    void panel;
  });

  // ── populate ─────────────────────────────────────────────────────────────

  it("open() populates fields from get_config", async () => {
    installTauri();
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 10));
    expect(getInput("cfg-llm-provider").value).toBe("anthropic");
    expect(getInput("cfg-llm-model").value).toBe("claude-sonnet-4-6");
    expect(getInput("cfg-mqtt-host").value).toBe("localhost");
    expect(getInput("cfg-mqtt-port").value).toBe("1883");
  });

  it("open() sets autostart checkbox from config", async () => {
    installTauri(async () => ({ ...defaultConfig, autostart: true }));
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 10));
    const cb = overlay().querySelector<HTMLInputElement>("#cfg-autostart")!;
    expect(cb.checked).toBe(true);
  });

  it("open() hides restart note on populate", async () => {
    installTauri();
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 10));
    const note = overlay().querySelector<HTMLElement>("#settings-restart-note")!;
    expect(note.style.display).toBe("none");
  });

  it("open() does not throw when Tauri is unavailable", () => {
    removeTauri();
    const panel = new SettingsPanel();
    expect(() => panel.open()).not.toThrow();
  });

  // ── save ──────────────────────────────────────────────────────────────────

  it("save button calls save_config with collected values", async () => {
    installTauri(async (cmd) => {
      if (cmd === "get_config") return { ...defaultConfig };
      return undefined;
    });
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 10));

    getInput("cfg-llm-model").value = "gpt-4";
    (overlay().querySelector("#settings-save") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 10));

    const invoke = (window as any).__TAURI_INTERNALS__.invoke as ReturnType<typeof vi.fn>;
    const saveCall = invoke.mock.calls.find((c: any[]) => c[0] === "save_config");
    expect(saveCall).toBeDefined();
    expect(saveCall![1].config.llm_model).toBe("gpt-4");
  });

  it("save success shows restart note and toast", async () => {
    installTauri(async (cmd) => {
      if (cmd === "get_config") return { ...defaultConfig };
      if (cmd === "save_config") return undefined;
      return undefined;
    });
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 10));
    (overlay().querySelector("#settings-save") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 20));
    const note = overlay().querySelector<HTMLElement>("#settings-restart-note")!;
    expect(note.style.display).toBe("inline");
    expect(document.querySelector(".settings-toast-success")).not.toBeNull();
    void panel;
  });

  it("save failure shows error toast", async () => {
    installTauri(async (cmd) => {
      if (cmd === "get_config") return { ...defaultConfig };
      if (cmd === "save_config") throw new Error("disk full");
      return undefined;
    });
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 10));
    (overlay().querySelector("#settings-save") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 20));
    expect(document.querySelector(".settings-toast-error")).not.toBeNull();
    void panel;
  });

  it("save re-enables save button after completion", async () => {
    installTauri(async (cmd) => {
      if (cmd === "get_config") return { ...defaultConfig };
      return undefined;
    });
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 10));
    const saveBtn = overlay().querySelector<HTMLButtonElement>("#settings-save")!;
    saveBtn.click();
    await new Promise((r) => setTimeout(r, 20));
    expect(saveBtn.disabled).toBe(false);
    void panel;
  });

  // ── test notification ─────────────────────────────────────────────────────

  it("test button calls notify invoke", async () => {
    installTauri(async () => undefined);
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 5));
    (overlay().querySelector("#settings-test") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 10));
    const invoke = (window as any).__TAURI_INTERNALS__.invoke as ReturnType<typeof vi.fn>;
    const notifyCall = invoke.mock.calls.find((c: any[]) => c[0] === "notify");
    expect(notifyCall).toBeDefined();
    void panel;
  });

  it("test notification success shows success toast", async () => {
    installTauri(async () => undefined);
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 5));
    (overlay().querySelector("#settings-test") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 20));
    expect(document.querySelector(".settings-toast-success")).not.toBeNull();
    void panel;
  });

  it("test notification failure shows error toast", async () => {
    installTauri(async (cmd) => {
      if (cmd === "notify") throw new Error("no permission");
      return undefined;
    });
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 5));
    (overlay().querySelector("#settings-test") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 20));
    expect(document.querySelector(".settings-toast-error")).not.toBeNull();
    void panel;
  });

  // ── _collect helpers ──────────────────────────────────────────────────────

  it("_collect uses default 1883 for invalid mqtt port", async () => {
    installTauri(async (cmd) => {
      if (cmd === "get_config") return { ...defaultConfig };
      if (cmd === "save_config") return undefined;
      return undefined;
    });
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 10));
    getInput("cfg-mqtt-port").value = "not-a-number";
    (overlay().querySelector("#settings-save") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 20));
    const invoke = (window as any).__TAURI_INTERNALS__.invoke as ReturnType<typeof vi.fn>;
    const saveCall = invoke.mock.calls.find((c: any[]) => c[0] === "save_config");
    expect(saveCall![1].config.mqtt_port).toBe(1883);
    void panel;
  });

  it("_showToast replaces previous toast", async () => {
    installTauri(async (cmd) => {
      if (cmd === "get_config") return { ...defaultConfig };
      if (cmd === "save_config") return undefined;
      return undefined;
    });
    const panel = new SettingsPanel();
    panel.open();
    await new Promise((r) => setTimeout(r, 10));
    (overlay().querySelector("#settings-save") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 10));
    (overlay().querySelector("#settings-save") as HTMLButtonElement).click();
    await new Promise((r) => setTimeout(r, 20));
    // Only one toast should be in the DOM at a time
    expect(document.querySelectorAll(".settings-toast").length).toBeLessThanOrEqual(1);
    void panel;
  });
});
