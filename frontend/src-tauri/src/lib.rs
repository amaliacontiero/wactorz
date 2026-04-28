//! Wactorz desktop entry point.
//!
//! Boots the full Rust backend (actor system + REST/WS server) in the same
//! process as the Tauri WebView, then opens a window that talks to it over
//! localhost.  The backend port is injected into the page as
//! `window.__WACTORZ_API_PORT` before any JavaScript runs.
//!
//! ## Config loading order (highest priority first)
//! 1. `<app-config-dir>/config.json`  — persisted via the settings panel
//! 2. `.env` file in the working directory
//! 3. Environment variables
//! 4. Compiled-in defaults

use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use anyhow::Result;
use serde::{Deserialize, Serialize};
use tauri::{Manager};
use wactorz_agents::{LlmConfig, LlmProvider, MainActor};
use wactorz_core::{ActorConfig, ActorSystem, EventPublisher, Supervisor, SupervisorStrategy};
use wactorz_interfaces::ws::WsEnvelope;
use wactorz_interfaces::{RestServer, RuntimeConfig, WsBridge};
use wactorz_mqtt::{MqttClient, MqttConfig};
const DEFAULT_PORT: u16 = 8888;

// ── App config ────────────────────────────────────────────────────────────────

#[derive(Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AppConfig {
    pub api_port: u16,
    pub llm_provider: String,
    pub llm_model: String,
    pub llm_api_key: String,
    pub mqtt_host: String,
    pub mqtt_port: u16,
    pub mqtt_ws_port: u16,
    pub ha_url: String,
    pub ha_token: String,
    pub static_dir: String,
    /// Launch Wactorz automatically at OS login.
    pub autostart: bool,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            api_port: env_u16("API_PORT", DEFAULT_PORT),
            llm_provider: env_str("LLM_PROVIDER", "anthropic"),
            llm_model: env_str("LLM_MODEL", "claude-sonnet-4-6"),
            llm_api_key: env_str("LLM_API_KEY", ""),
            mqtt_host: env_str("MQTT_HOST", "localhost"),
            mqtt_port: env_u16("MQTT_PORT", 1883),
            mqtt_ws_port: env_u16("MQTT_WS_PORT", 9001),
            ha_url: env_str("HA_URL", ""),
            ha_token: env_str("HA_TOKEN", ""),
            static_dir: env_str("STATIC_DIR", "static/app"),
            autostart: false,
        }
    }
}

fn env_str(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_owned())
}

fn env_u16(key: &str, default: u16) -> u16 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn config_path(app: &tauri::AppHandle) -> std::path::PathBuf {
    app.path()
        .app_config_dir()
        .unwrap_or_else(|_| std::path::PathBuf::from("."))
        .join("config.json")
}

/// Load config: saved JSON wins over env/defaults for every stored key.
fn load_config(app: &tauri::AppHandle) -> AppConfig {
    let path = config_path(app);
    if let Ok(bytes) = std::fs::read(&path)
        && let Ok(saved) = serde_json::from_slice::<AppConfig>(&bytes) {
            tracing::info!("Loaded config from {}", path.display());
            return saved;
        }
    tracing::info!(
        "Using default/env config (no saved config at {})",
        path.display()
    );
    AppConfig::default()
}

// ── Tauri state ───────────────────────────────────────────────────────────────

struct ConfigState(Mutex<AppConfig>);
struct BadgeState(Mutex<u32>);

// ── Tauri commands ────────────────────────────────────────────────────────────

/// Send a native OS notification. Called from JS via invoke('notify', ...).
#[tauri::command]
fn notify(app: tauri::AppHandle, title: String, body: String) {
    use tauri_plugin_notification::NotificationExt;
    let _ = app.notification().builder().title(title).body(body).show();
}

/// Increment the unread badge on the tray icon. Called from JS after a notification fires.
#[tauri::command]
fn add_unread(app: tauri::AppHandle, badge: tauri::State<BadgeState>) {
    let count = {
        let mut n = badge.0.lock().unwrap();
        *n += 1;
        *n
    };
    update_tray_tooltip(&app, count);
}

/// Clear the unread badge. Called from JS when the window gains focus.
#[tauri::command]
fn clear_unread(app: tauri::AppHandle, badge: tauri::State<BadgeState>) {
    *badge.0.lock().unwrap() = 0;
    update_tray_tooltip(&app, 0);
}

fn update_tray_tooltip(app: &tauri::AppHandle, count: u32) {
    if let Some(tray) = app.tray_by_id("main") {
        let tip = if count == 0 {
            "Wactorz".to_string()
        } else {
            format!("Wactorz · {count} unread")
        };
        let _ = tray.set_tooltip(Some(&tip));
    }
}

#[tauri::command]
fn get_api_port(state: tauri::State<ConfigState>) -> u16 {
    state.0.lock().unwrap().api_port
}

#[tauri::command]
fn get_config(state: tauri::State<ConfigState>) -> AppConfig {
    state.0.lock().unwrap().clone()
}

#[tauri::command]
fn save_config(
    config: AppConfig,
    state: tauri::State<ConfigState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    use tauri_plugin_autostart::ManagerExt;
    let path = config_path(&app);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    // Sync autostart registration with the saved preference.
    let autolaunch = app.autolaunch();
    if config.autostart {
        let _ = autolaunch.enable();
    } else {
        let _ = autolaunch.disable();
    }
    let json = serde_json::to_string_pretty(&config).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())?;
    *state.0.lock().unwrap() = config;
    tracing::info!("Config saved to {}", path.display());
    Ok(())
}

#[tauri::command]
fn get_autostart(app: tauri::AppHandle) -> bool {
    use tauri_plugin_autostart::ManagerExt;
    app.autolaunch().is_enabled().unwrap_or(false)
}

#[tauri::command]
fn set_autostart(enabled: bool, app: tauri::AppHandle) -> Result<(), String> {
    use tauri_plugin_autostart::ManagerExt;
    let autolaunch = app.autolaunch();
    if enabled {
        autolaunch.enable().map_err(|e| e.to_string())
    } else {
        autolaunch.disable().map_err(|e| e.to_string())
    }
}
// ── Tray ──────────────────────────────────────────────────────────────────────

fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    use tauri::{
        menu::{MenuBuilder, MenuItemBuilder},
        tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    };

    let show_hide = MenuItemBuilder::with_id("show_hide", "Show / Hide").build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "Quit Wactorz").build(app)?;
    let menu = MenuBuilder::new(app)
        .items(&[&show_hide, &quit])
        .build()?;

    TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("Wactorz")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show_hide" => toggle_window(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_window(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

fn toggle_window(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        if win.is_visible().unwrap_or(false) {
            let _ = win.hide();
        } else {
            let _ = win.unminimize();
            let _ = win.show();
            let _ = win.set_focus();
        }
    }
}

// ── Embedded backend ──────────────────────────────────────────────────────────

async fn start_backend(cfg: AppConfig, data_dir: std::path::PathBuf) -> Result<()> {
    let (publisher, mut pub_rx) = EventPublisher::channel();
    let system = ActorSystem::with_publisher(publisher.clone());

    let mqtt_config = MqttConfig {
        host: cfg.mqtt_host.clone(),
        port: cfg.mqtt_port,
        client_id: "wactorz-desktop".into(),
        ..Default::default()
    };
    let (mqtt_client, mut event_loop) = MqttClient::new(mqtt_config)?;
    let mqtt_client = Arc::new(mqtt_client);

    let (ws_tx, _) = tokio::sync::broadcast::channel::<WsEnvelope>(100);
    let ws_tx_mqtt = ws_tx.clone();

    let reg_route = system.registry.clone();
    let reg_qa = system.registry.clone();
    let reg_wik = system.registry.clone();
    let reg_switch = system.registry.clone();

    tokio::spawn(async move {
        MqttClient::run_event_loop(&mut event_loop, move |evt| {
            if let wactorz_mqtt::MqttEvent::Incoming { topic, payload } = evt
                && let Ok(json_val) = serde_json::from_slice::<serde_json::Value>(&payload) {
                    let _ = ws_tx_mqtt.send(WsEnvelope {
                        topic: topic.clone(),
                        payload: json_val.clone(),
                    });

                    if topic == wactorz_mqtt::topics::SYSTEM_LLM_ERROR {
                        let reg = reg_wik.clone();
                        let s = serde_json::to_string(&json_val).unwrap_or_default();
                        tokio::spawn(async move {
                            if let Some(e) = reg.get_by_name("wik-agent").await {
                                let _ = reg
                                    .send(
                                        &e.id,
                                        wactorz_core::Message::text(
                                            Some("system".into()),
                                            Some(e.id.clone()),
                                            s,
                                        ),
                                    )
                                    .await;
                            }
                        });
                    }

                    if topic == wactorz_mqtt::topics::SYSTEM_LLM_SWITCH {
                        let reg = reg_switch.clone();
                        let p = json_val.clone();
                        tokio::spawn(async move {
                            if let Some(e) = reg.get_by_name("main-actor").await {
                                let _ = reg
                                    .send(
                                        &e.id,
                                        wactorz_core::Message::new(
                                            Some("wik-agent".into()),
                                            Some(e.id.clone()),
                                            wactorz_core::MessageType::Task {
                                                task_id: "wik/switch".into(),
                                                description: "LLM provider switch".into(),
                                                payload: p,
                                            },
                                        ),
                                    )
                                    .await;
                            }
                        });
                    }

                    if topic.ends_with("/chat") {
                        let from = json_val.get("from").and_then(|v| v.as_str()).unwrap_or("");
                        let content = json_val
                            .get("content")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();

                        if !content.is_empty() && (from == "user" || from.is_empty()) {
                            if topic == wactorz_mqtt::topics::IO_CHAT {
                                let reg = reg_route.clone();
                                tokio::spawn(async move {
                                    if let Some(e) = reg.get_by_name("io-agent").await {
                                        let _ = reg
                                            .send(
                                                &e.id,
                                                wactorz_core::Message::text(
                                                    Some("user".into()),
                                                    Some(e.id.clone()),
                                                    content,
                                                ),
                                            )
                                            .await;
                                    }
                                });
                            } else if let Some(id) = topic
                                .strip_prefix("agents/")
                                .and_then(|s| s.strip_suffix("/chat"))
                            {
                                let reg = reg_route.clone();
                                let id = id.to_string();
                                tokio::spawn(async move {
                                    let _ = reg
                                        .send(
                                            &id,
                                            wactorz_core::Message::text(
                                                Some("user".into()),
                                                Some(id.clone()),
                                                content,
                                            ),
                                        )
                                        .await;
                                });
                            }
                        }

                        let reg = reg_qa.clone();
                        let s = serde_json::to_string(&json_val).unwrap_or_default();
                        tokio::spawn(async move {
                            if let Some(e) = reg.get_by_name("qa-agent").await {
                                let _ = reg
                                    .send(
                                        &e.id,
                                        wactorz_core::Message::text(
                                            Some("mqtt-router".into()),
                                            Some(e.id.clone()),
                                            s,
                                        ),
                                    )
                                    .await;
                            }
                        });
                    }
                }
        })
        .await;
    });

    for topic in ["agents/#", "system/#", "system/llm/#", "nodes/#"] {
        if let Err(e) = mqtt_client.subscribe(topic).await {
            tracing::warn!("MQTT subscribe {topic} failed (broker may not be running): {e}");
        }
    }
    if let Err(e) = mqtt_client.subscribe(wactorz_mqtt::topics::IO_CHAT).await {
        tracing::warn!("MQTT subscribe io/chat failed: {e}");
    }

    let mqtt_bridge = Arc::clone(&mqtt_client);
    tokio::spawn(async move {
        while let Some((topic, payload)) = pub_rx.recv().await {
            if let Err(e) = mqtt_bridge.publish_raw(&topic, payload).await {
                tracing::error!("MQTT publish error: {e}");
            }
        }
    });

    let llm_provider = match cfg.llm_provider.as_str() {
        "openai" => LlmProvider::OpenAI,
        "ollama" => LlmProvider::Ollama,
        "gemini" => LlmProvider::Gemini,
        "nim" => LlmProvider::Nim,
        _ => LlmProvider::Anthropic,
    };
    let llm_config = LlmConfig {
        provider: llm_provider,
        model: cfg.llm_model.clone(),
        api_key: Some(cfg.llm_api_key.clone()).filter(|s| !s.is_empty()),
        ..Default::default()
    };

    let mut sup = Supervisor::new(system.clone());

    {
        let lc = llm_config.clone();
        let sys = system.clone();
        let pub_ = publisher.clone();
        let dd = data_dir.clone();
        sup.supervise(
            "main-actor",
            Arc::new(move || {
                let mut actor = MainActor::new(
                    ActorConfig::new_with_node("main-actor", "alpha").protected(),
                    lc.clone(),
                    sys.clone(),
                )
                .with_publisher(pub_.clone());
                actor = actor.with_persistence(dd.clone());
                Box::new(actor)
            }),
            SupervisorStrategy::OneForOne,
            10,
            60.0,
            2.0,
        );
    }

    sup.start().await?;
    tracing::info!(
        "Wactorz desktop: all agents started, serving on port {}",
        cfg.api_port
    );

    let addr: SocketAddr = format!("127.0.0.1:{}", cfg.api_port).parse()?;
    let ws_bridge = WsBridge::new(
        ws_tx,
        mqtt_client,
        system.clone(),
        cfg.mqtt_host.clone(),
        cfg.mqtt_ws_port,
    );
    RestServer::new(
        system,
        addr,
        RuntimeConfig {
            ha_url: cfg.ha_url,
            ha_token: cfg.ha_token,
            mqtt_host: cfg.mqtt_host,
            mqtt_port: cfg.mqtt_port,
            mqtt_ws_port: cfg.mqtt_ws_port,
            llm_provider: cfg.llm_provider,
            llm_model: cfg.llm_model,
            ..Default::default()
        },
        cfg.static_dir,
    )
    .with_ws(ws_bridge.router())
    .serve()
    .await?;

    Ok(())
}

// ── Tauri entry point ─────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let _ = dotenvy::dotenv();

    tauri::Builder::default()
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(|app| {
            let cfg = load_config(app.handle());
            let port = cfg.api_port;

            // Sync autostart registration with persisted preference on every launch.
            {
                use tauri_plugin_autostart::ManagerExt;
                let autolaunch = app.autolaunch();
                if cfg.autostart {
                    let _ = autolaunch.enable();
                } else {
                    let _ = autolaunch.disable();
                }
            }

            let data_dir = app
                .path()
                .app_data_dir()
                .unwrap_or_else(|_| std::path::PathBuf::from("."));

            app.manage(ConfigState(Mutex::new(cfg.clone())));
            app.manage(BadgeState(Mutex::new(0)));

            // window-state plugin restores position/size; .center() is the
            // fallback for the very first launch when no saved state exists.
            tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::default())
                .title("Wactorz")
                .inner_size(1400.0, 900.0)
                .min_inner_size(900.0, 600.0)
                .resizable(true)
                .center()
                .initialization_script(format!("window.__WACTORZ_API_PORT={port};"))
                .build()?;

            build_tray(app)?;

            tauri::async_runtime::spawn(async move {
                if let Err(e) = start_backend(cfg, data_dir).await {
                    tracing::error!("Embedded backend exited: {e}");
                }
            });

            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            get_api_port,
            get_config,
            save_config,
            notify,
            add_unread,
            clear_unread,
            get_autostart,
            set_autostart,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
