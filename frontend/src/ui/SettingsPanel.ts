/**
 * SettingsPanel — desktop-only configuration modal.
 *
 * Reads and writes config via Tauri commands (get_config / save_config).
 * Only rendered when window.__WACTORZ_API_PORT is set (i.e. inside Tauri).
 */

interface AppConfig {
  api_port: number;
  llm_provider: string;
  llm_model: string;
  llm_api_key: string;
  mqtt_host: string;
  mqtt_port: number;
  ha_url: string;
  ha_token: string;
}

function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const internals = (window as any).__TAURI_INTERNALS__;
  if (!internals?.invoke)
    return Promise.reject(new Error("Tauri internals not available"));
  return internals.invoke(cmd, args ?? {}) as Promise<T>;
}

export class SettingsPanel {
  private overlay: HTMLElement;
  private toast: HTMLElement | null = null;

  constructor() {
    this.overlay = this._build();
    document.body.appendChild(this.overlay);
    this._injectStyles();
  }

  open(): void {
    invoke<AppConfig>("get_config")
      .then((cfg) => this._populate(cfg))
      .catch(() => {});
    this.overlay.style.display = "flex";
  }

  close(): void {
    this.overlay.style.display = "none";
  }

  // ── Private ────────────────────────────────────────────────────────────────

  private _build(): HTMLElement {
    const overlay = document.createElement("div");
    overlay.id = "settings-overlay";
    overlay.style.display = "none";

    overlay.innerHTML = `
      <div class="settings-modal glass">
        <div class="settings-header">
          <span class="settings-title">⚙ Settings</span>
          <button class="settings-close" id="settings-close">✕</button>
        </div>

        <div class="settings-body">
          <section class="settings-section">
            <div class="settings-section-title">LLM</div>

            <label class="settings-label">Provider
              <select id="cfg-llm-provider" class="settings-input">
                <option value="anthropic">Anthropic</option>
                <option value="openai">OpenAI</option>
                <option value="ollama">Ollama</option>
                <option value="gemini">Gemini</option>
                <option value="nim">NVIDIA NIM</option>
              </select>
            </label>

            <label class="settings-label">Model
              <input id="cfg-llm-model" class="settings-input" type="text"
                     placeholder="claude-sonnet-4-6" />
            </label>

            <label class="settings-label">API Key
              <input id="cfg-llm-api-key" class="settings-input" type="password"
                     placeholder="sk-…" autocomplete="off" />
            </label>
          </section>

          <section class="settings-section">
            <div class="settings-section-title">MQTT <span class="settings-optional">(optional)</span></div>

            <label class="settings-label">Host
              <input id="cfg-mqtt-host" class="settings-input" type="text"
                     placeholder="localhost" />
            </label>

            <label class="settings-label">Port
              <input id="cfg-mqtt-port" class="settings-input" type="number"
                     min="1" max="65535" placeholder="1883" />
            </label>
          </section>

          <section class="settings-section">
            <div class="settings-section-title">Home Assistant <span class="settings-optional">(optional)</span></div>

            <label class="settings-label">URL
              <input id="cfg-ha-url" class="settings-input" type="url"
                     placeholder="http://homeassistant.local:8123" />
            </label>

            <label class="settings-label">Long-lived token
              <input id="cfg-ha-token" class="settings-input" type="password"
                     placeholder="ey…" autocomplete="off" />
            </label>
          </section>
        </div>

        <div class="settings-footer">
          <span class="settings-restart-note" id="settings-restart-note" style="display:none">
            ↺ Restart to apply changes
          </span>
          <button class="settings-btn-cancel" id="settings-cancel">Cancel</button>
          <button class="settings-btn-save"   id="settings-save">Save</button>
        </div>
      </div>
    `;

    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) this.close();
    });
    overlay.querySelector("#settings-close")!.addEventListener("click", () => this.close());
    overlay.querySelector("#settings-cancel")!.addEventListener("click", () => this.close());
    overlay.querySelector("#settings-save")!.addEventListener("click", () => this._save());

    return overlay;
  }

  private _populate(cfg: AppConfig): void {
    this._val("cfg-llm-provider", cfg.llm_provider);
    this._val("cfg-llm-model", cfg.llm_model);
    this._val("cfg-llm-api-key", cfg.llm_api_key);
    this._val("cfg-mqtt-host", cfg.mqtt_host);
    this._val("cfg-mqtt-port", String(cfg.mqtt_port));
    this._val("cfg-ha-url", cfg.ha_url);
    this._val("cfg-ha-token", cfg.ha_token);
    const note = this.overlay.querySelector<HTMLElement>("#settings-restart-note");
    if (note) note.style.display = "none";
  }

  private _collect(): AppConfig {
    return {
      api_port: 8888,
      llm_provider: this._get("cfg-llm-provider"),
      llm_model: this._get("cfg-llm-model"),
      llm_api_key: this._get("cfg-llm-api-key"),
      mqtt_host: this._get("cfg-mqtt-host"),
      mqtt_port: parseInt(this._get("cfg-mqtt-port"), 10) || 1883,
      ha_url: this._get("cfg-ha-url"),
      ha_token: this._get("cfg-ha-token"),
    };
  }

  private _save(): void {
    const config = this._collect();
    const saveBtn = this.overlay.querySelector<HTMLButtonElement>("#settings-save");
    if (saveBtn) saveBtn.disabled = true;

    invoke("save_config", { config })
      .then(() => {
        const note = this.overlay.querySelector<HTMLElement>("#settings-restart-note");
        if (note) note.style.display = "inline";
        this._showToast("Settings saved — restart to apply", "success");
      })
      .catch((err: unknown) => {
        this._showToast(`Save failed: ${err}`, "error");
      })
      .finally(() => {
        if (saveBtn) saveBtn.disabled = false;
      });
  }

  private _showToast(msg: string, kind: "success" | "error"): void {
    if (this.toast) this.toast.remove();
    const t = document.createElement("div");
    t.className = `settings-toast settings-toast-${kind}`;
    t.textContent = msg;
    document.body.appendChild(t);
    this.toast = t;
    setTimeout(() => t.remove(), 3500);
  }

  private _val(id: string, value: string): void {
    const el = this.overlay.querySelector<
      HTMLInputElement | HTMLSelectElement
    >(`#${id}`);
    if (el) el.value = value;
  }

  private _get(id: string): string {
    return (
      this.overlay.querySelector<HTMLInputElement | HTMLSelectElement>(
        `#${id}`,
      )?.value ?? ""
    );
  }

  private _injectStyles(): void {
    if (document.getElementById("settings-styles")) return;
    const s = document.createElement("style");
    s.id = "settings-styles";
    s.textContent = `
      #settings-overlay {
        position: fixed; inset: 0; z-index: 9999;
        background: rgba(0,0,0,.55); backdrop-filter: blur(4px);
        display: flex; align-items: center; justify-content: center;
      }
      .settings-modal {
        width: min(520px, 96vw); max-height: 90vh;
        background: #0d1528; border: 1px solid rgba(99,102,241,.35);
        border-radius: 14px; display: flex; flex-direction: column;
        overflow: hidden; box-shadow: 0 24px 80px rgba(0,0,0,.7);
      }
      .settings-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 18px 20px 14px; border-bottom: 1px solid rgba(99,102,241,.2);
      }
      .settings-title { font-size: 15px; font-weight: 600; color: #c8d8ff; }
      .settings-close {
        background: none; border: none; color: #7a90c0; font-size: 16px;
        cursor: pointer; padding: 2px 6px; border-radius: 4px;
      }
      .settings-close:hover { background: rgba(255,255,255,.07); color: #fff; }
      .settings-body {
        overflow-y: auto; padding: 16px 20px; display: flex;
        flex-direction: column; gap: 20px;
      }
      .settings-section { display: flex; flex-direction: column; gap: 10px; }
      .settings-section-title {
        font-size: 11px; font-weight: 600; letter-spacing: .06em;
        text-transform: uppercase; color: #6366f1; padding-bottom: 4px;
        border-bottom: 1px solid rgba(99,102,241,.2);
      }
      .settings-optional { font-weight: 400; color: #4a5568; text-transform: none; }
      .settings-label {
        display: flex; flex-direction: column; gap: 4px;
        font-size: 12px; color: #94a3b8;
      }
      .settings-input {
        background: rgba(255,255,255,.05); border: 1px solid rgba(99,102,241,.25);
        border-radius: 6px; color: #e2e8f0; padding: 7px 10px; font-size: 13px;
        outline: none; width: 100%;
      }
      .settings-input:focus { border-color: #6366f1; background: rgba(99,102,241,.08); }
      .settings-footer {
        display: flex; align-items: center; justify-content: flex-end;
        gap: 8px; padding: 14px 20px;
        border-top: 1px solid rgba(99,102,241,.2);
      }
      .settings-restart-note {
        font-size: 11px; color: #fbbf24; margin-right: auto;
      }
      .settings-btn-cancel, .settings-btn-save {
        padding: 7px 18px; border-radius: 7px; font-size: 13px;
        font-weight: 500; cursor: pointer; border: none;
      }
      .settings-btn-cancel {
        background: rgba(255,255,255,.07); color: #94a3b8;
      }
      .settings-btn-cancel:hover { background: rgba(255,255,255,.12); color: #fff; }
      .settings-btn-save {
        background: #6366f1; color: #fff;
      }
      .settings-btn-save:hover { background: #818cf8; }
      .settings-btn-save:disabled { opacity: .5; cursor: default; }
      .settings-toast {
        position: fixed; bottom: 24px; right: 24px; z-index: 10000;
        padding: 10px 18px; border-radius: 8px; font-size: 13px;
        font-weight: 500; pointer-events: none;
        animation: settings-toast-in .2s ease;
      }
      .settings-toast-success { background: #059669; color: #fff; }
      .settings-toast-error   { background: #dc2626; color: #fff; }
      @keyframes settings-toast-in {
        from { opacity: 0; transform: translateY(8px); }
        to   { opacity: 1; transform: translateY(0); }
      }
    `;
    document.head.appendChild(s);
  }
}
