//! Wactorz desktop entry point.
//!
//! Boots the full Rust backend (actor system + REST/WS server) in the same
//! process as the Tauri WebView, then opens a window that talks to it over
//! localhost.  The backend port is injected into the page as
//! `window.__WACTORZ_API_PORT` before any JavaScript runs.

use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::Result;
use wactorz_agents::{
    CatalogAgent, DynamicAgent, FusekiAgent, HomeAssistantActuatorAgent, HomeAssistantAgent,
    HomeAssistantStateBridgeAgent, IOAgent, InstallerAgent, LlmConfig, LlmProvider, MainActor,
    ManualAgent, MonitorAgent, WeatherAgent,
};
use wactorz_core::{ActorConfig, ActorSystem, EventPublisher, Supervisor, SupervisorStrategy};
use wactorz_interfaces::ws::WsEnvelope;
use wactorz_interfaces::{RestServer, RuntimeConfig, WsBridge};
use wactorz_mqtt::{MqttClient, MqttConfig};

// Default port the embedded HTTP+WS server listens on.
const DEFAULT_PORT: u16 = 8888;

// ── Desktop config ────────────────────────────────────────────────────────────

#[derive(Clone)]
struct DesktopConfig {
    port: u16,
    llm_provider: String,
    llm_model: String,
    llm_api_key: Option<String>,
    mqtt_host: String,
    mqtt_port: u16,
    mqtt_ws_port: u16,
    ha_url: String,
    ha_token: String,
    static_dir: String,
}

impl DesktopConfig {
    fn from_env() -> Self {
        Self {
            port: env_u16("API_PORT", DEFAULT_PORT),
            llm_provider: env_str("LLM_PROVIDER", "anthropic"),
            llm_model: env_str("LLM_MODEL", "claude-sonnet-4-6"),
            llm_api_key: std::env::var("LLM_API_KEY")
                .ok()
                .filter(|s| !s.is_empty()),
            mqtt_host: env_str("MQTT_HOST", "localhost"),
            mqtt_port: env_u16("MQTT_PORT", 1883),
            mqtt_ws_port: env_u16("MQTT_WS_PORT", 9001),
            ha_url: env_str("HA_URL", ""),
            ha_token: env_str("HA_TOKEN", ""),
            // Serve the same bundled assets that Tauri uses, so a plain browser
            // pointing at http://localhost:PORT also gets the UI.
            static_dir: env_str("STATIC_DIR", "static/app"),
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

// ── Embedded backend ──────────────────────────────────────────────────────────

async fn start_backend(cfg: DesktopConfig) -> Result<()> {
    // ── Publisher channel ─────────────────────────────────────────────────────
    let (publisher, mut pub_rx) = EventPublisher::channel();

    // ── Actor system ──────────────────────────────────────────────────────────
    let system = ActorSystem::with_publisher(publisher.clone());

    // ── MQTT (optional — warns gracefully if broker is not running) ───────────
    let mqtt_config = MqttConfig {
        host: cfg.mqtt_host.clone(),
        port: cfg.mqtt_port,
        client_id: "wactorz-desktop".into(),
        ..Default::default()
    };

    let (mqtt_client, mut event_loop) = MqttClient::new(mqtt_config)?;
    let mqtt_client = Arc::new(mqtt_client);

    // WebSocket broadcast channel
    let (ws_tx, _) = tokio::sync::broadcast::channel::<WsEnvelope>(100);
    let ws_tx_for_mqtt = ws_tx.clone();

    let registry_for_route = system.registry.clone();
    let registry_for_qa = system.registry.clone();
    let registry_for_wik = system.registry.clone();
    let registry_for_switch = system.registry.clone();

    // MQTT event loop task
    tokio::spawn(async move {
        MqttClient::run_event_loop(&mut event_loop, move |evt| {
            if let wactorz_mqtt::MqttEvent::Incoming { topic, payload } = evt {
                if let Ok(json_val) = serde_json::from_slice::<serde_json::Value>(&payload) {
                    let envelope = WsEnvelope {
                        topic: topic.clone(),
                        payload: json_val.clone(),
                    };
                    let _ = ws_tx_for_mqtt.send(envelope);

                    if topic == wactorz_mqtt::topics::SYSTEM_LLM_ERROR {
                        let reg = registry_for_wik.clone();
                        let payload_str = serde_json::to_string(&json_val).unwrap_or_default();
                        tokio::spawn(async move {
                            if let Some(entry) = reg.get_by_name("wik-agent").await {
                                let msg = wactorz_core::Message::text(
                                    Some("system".to_string()),
                                    Some(entry.id.clone()),
                                    payload_str,
                                );
                                let _ = reg.send(&entry.id, msg).await;
                            }
                        });
                    }

                    if topic == wactorz_mqtt::topics::SYSTEM_LLM_SWITCH {
                        let reg = registry_for_switch.clone();
                        let switch_payload = json_val.clone();
                        tokio::spawn(async move {
                            if let Some(entry) = reg.get_by_name("main-actor").await {
                                let msg = wactorz_core::Message::new(
                                    Some("wik-agent".to_string()),
                                    Some(entry.id.clone()),
                                    wactorz_core::MessageType::Task {
                                        task_id: "wik/switch".to_string(),
                                        description: "LLM provider switch".to_string(),
                                        payload: switch_payload,
                                    },
                                );
                                let _ = reg.send(&entry.id, msg).await;
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
                                let reg = registry_for_route.clone();
                                tokio::spawn(async move {
                                    if let Some(entry) = reg.get_by_name("io-agent").await {
                                        let msg = wactorz_core::Message::text(
                                            Some("user".to_string()),
                                            Some(entry.id.clone()),
                                            content,
                                        );
                                        let _ = reg.send(&entry.id, msg).await;
                                    }
                                });
                            } else if let Some(actor_id) = topic
                                .strip_prefix("agents/")
                                .and_then(|s| s.strip_suffix("/chat"))
                            {
                                let reg = registry_for_route.clone();
                                let id = actor_id.to_string();
                                tokio::spawn(async move {
                                    let msg = wactorz_core::Message::text(
                                        Some("user".to_string()),
                                        Some(id.clone()),
                                        content,
                                    );
                                    let _ = reg.send(&id, msg).await;
                                });
                            }
                        }

                        // Forward chat to QA agent
                        if topic.ends_with("/chat") {
                            let reg_qa = registry_for_qa.clone();
                            let qa_content = serde_json::to_string(&json_val).unwrap_or_default();
                            tokio::spawn(async move {
                                if let Some(entry) = reg_qa.get_by_name("qa-agent").await {
                                    let msg = wactorz_core::Message::text(
                                        Some("mqtt-router".to_string()),
                                        Some(entry.id.clone()),
                                        qa_content,
                                    );
                                    let _ = reg_qa.send(&entry.id, msg).await;
                                }
                            });
                        }
                    }
                }
            }
        })
        .await;
    });

    if let Err(e) = mqtt_client.subscribe("agents/#").await {
        tracing::warn!("MQTT subscribe failed (broker may not be running): {e}");
    }
    if let Err(e) = mqtt_client.subscribe("system/#").await {
        tracing::warn!("MQTT subscribe failed: {e}");
    }
    if let Err(e) = mqtt_client.subscribe(wactorz_mqtt::topics::IO_CHAT).await {
        tracing::warn!("MQTT subscribe io/chat failed: {e}");
    }
    if let Err(e) = mqtt_client.subscribe("system/llm/#").await {
        tracing::warn!("MQTT subscribe system/llm/# failed: {e}");
    }
    if let Err(e) = mqtt_client.subscribe("nodes/#").await {
        tracing::warn!("MQTT subscribe nodes/# failed: {e}");
    }

    // Publisher bridge: drain pub_rx → MQTT
    let mqtt_for_bridge = Arc::clone(&mqtt_client);
    tokio::spawn(async move {
        while let Some((topic, payload)) = pub_rx.recv().await {
            if let Err(e) = mqtt_for_bridge.publish_raw(&topic, payload).await {
                tracing::error!("MQTT publish error: {e}");
            }
        }
    });

    // ── LLM config ────────────────────────────────────────────────────────────
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
        api_key: cfg.llm_api_key.clone(),
        ..Default::default()
    };

    // ── Supervisor + agents ───────────────────────────────────────────────────
    let mut sup = Supervisor::new(system.clone());

    {
        let lc = llm_config.clone();
        let sys = system.clone();
        let pub_ = publisher.clone();
        sup.supervise(
            "main-actor",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("main-actor", "alpha").protected();
                Box::new(MainActor::new(c, lc.clone(), sys.clone()).with_publisher(pub_.clone()))
            }),
            SupervisorStrategy::OneForOne,
            10,
            60.0,
            2.0,
        );
    }
    {
        let sys = system.clone();
        let pub_ = publisher.clone();
        sup.supervise(
            "monitor-agent",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("monitor-agent", "bravo").protected();
                Box::new(MonitorAgent::new(c, sys.clone()).with_publisher(pub_.clone()))
            }),
            SupervisorStrategy::OneForOne,
            10,
            60.0,
            1.0,
        );
    }
    {
        let sys = system.clone();
        let pub_ = publisher.clone();
        sup.supervise(
            "io-agent",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("io-agent", "charlie");
                Box::new(IOAgent::new(c, sys.clone()).with_publisher(pub_.clone()))
            }),
            SupervisorStrategy::OneForOne,
            10,
            60.0,
            1.0,
        );
    }
    {
        let pub_ = publisher.clone();
        sup.supervise(
            "installer-agent",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("installer-agent", "delta");
                Box::new(InstallerAgent::new(c).with_publisher(pub_.clone()))
            }),
            SupervisorStrategy::OneForOne,
            5,
            60.0,
            2.0,
        );
    }
    {
        let pub_ = publisher.clone();
        sup.supervise(
            "code-agent",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("code-agent", "echo");
                Box::new(DynamicAgent::new(c, "").with_publisher(pub_.clone()))
            }),
            SupervisorStrategy::OneForOne,
            5,
            60.0,
            1.0,
        );
    }
    {
        let lc = llm_config.clone();
        let pub_ = publisher.clone();
        sup.supervise(
            "manual-agent",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("manual-agent", "foxtrot");
                Box::new(ManualAgent::new(c, lc.clone()).with_publisher(pub_.clone()))
            }),
            SupervisorStrategy::OneForOne,
            5,
            60.0,
            1.0,
        );
    }
    {
        let pub_ = publisher.clone();
        let ha_url = cfg.ha_url.clone();
        let ha_token = cfg.ha_token.clone();
        sup.supervise(
            "home-assistant-agent",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("home-assistant-agent", "golf");
                Box::new(
                    HomeAssistantAgent::new(c)
                        .with_ha_config(ha_url.clone(), ha_token.clone())
                        .with_publisher(pub_.clone()),
                )
            }),
            SupervisorStrategy::OneForOne,
            5,
            60.0,
            2.0,
        );
    }
    {
        let pub_ = publisher.clone();
        sup.supervise(
            "weather-agent",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("weather-agent", "hotel");
                Box::new(WeatherAgent::new(c).with_publisher(pub_.clone()))
            }),
            SupervisorStrategy::OneForOne,
            5,
            60.0,
            1.0,
        );
    }
    {
        let pub_ = publisher.clone();
        sup.supervise(
            "fuseki-agent",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("fuseki-agent", "india");
                Box::new(FusekiAgent::new(c).with_publisher(pub_.clone()))
            }),
            SupervisorStrategy::OneForOne,
            5,
            60.0,
            2.0,
        );
    }
    {
        let pub_ = publisher.clone();
        sup.supervise(
            "catalog",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("catalog", "juliet").protected();
                Box::new(CatalogAgent::new(c).with_publisher(pub_.clone()))
            }),
            SupervisorStrategy::OneForOne,
            5,
            60.0,
            1.0,
        );
    }
    {
        let pub_ = publisher.clone();
        let ha_url = cfg.ha_url.clone();
        let ha_token = cfg.ha_token.clone();
        sup.supervise(
            "ha-actuator",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("ha-actuator", "kilo");
                Box::new(
                    HomeAssistantActuatorAgent::new(c)
                        .with_ha_config(ha_url.clone(), ha_token.clone())
                        .with_publisher(pub_.clone()),
                )
            }),
            SupervisorStrategy::OneForOne,
            5,
            60.0,
            2.0,
        );
    }
    {
        let pub_ = publisher.clone();
        let sys = system.clone();
        let ha_url = cfg.ha_url.clone();
        let ha_token = cfg.ha_token.clone();
        sup.supervise(
            "ha-state-bridge",
            Arc::new(move || {
                let c = ActorConfig::new_with_node("ha-state-bridge", "lima");
                Box::new(
                    HomeAssistantStateBridgeAgent::new(c)
                        .with_system(sys.clone())
                        .with_ha_config(ha_url.clone(), ha_token.clone(), "ha/state".into(), vec![])
                        .with_publisher(pub_.clone()),
                )
            }),
            SupervisorStrategy::OneForOne,
            5,
            60.0,
            2.0,
        );
    }

    sup.start().await?;
    tracing::info!("Wactorz desktop backend started on port {}", cfg.port);

    // ── REST + WS server ──────────────────────────────────────────────────────
    let addr: SocketAddr = format!("127.0.0.1:{}", cfg.port).parse()?;
    let runtime_cfg = RuntimeConfig {
        ha_url: cfg.ha_url.clone(),
        ha_token: cfg.ha_token.clone(),
        mqtt_host: cfg.mqtt_host.clone(),
        mqtt_port: cfg.mqtt_port,
        mqtt_ws_port: cfg.mqtt_ws_port,
        llm_provider: cfg.llm_provider.clone(),
        llm_model: cfg.llm_model.clone(),
        ..Default::default()
    };
    let ws_bridge = WsBridge::new(
        ws_tx,
        mqtt_client,
        system.clone(),
        cfg.mqtt_host.clone(),
        cfg.mqtt_ws_port,
    );
    let server = RestServer::new(system.clone(), addr, runtime_cfg, cfg.static_dir)
        .with_ws(ws_bridge.router());
    server.serve().await?;

    Ok(())
}

// ── Tauri entry point ─────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Load .env from cwd if present (for local dev overrides)
    let _ = dotenvy::dotenv();

    let cfg = DesktopConfig::from_env();
    let port = cfg.port;

    tauri::Builder::default()
        .setup(move |app| {
            // Inject the backend port so the frontend can build absolute URLs.
            // This runs before any page JavaScript, covering both dev and release.
            tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::default())
                .title("Wactorz")
                .inner_size(1400.0, 900.0)
                .min_inner_size(900.0, 600.0)
                .center()
                .resizable(true)
                .initialization_script(&format!("window.__WACTORZ_API_PORT={port};"))
                .build()?;

            // Start the embedded backend on a background tokio task.
            // The frontend retries fetches, so a brief startup lag is fine.
            tauri::async_runtime::spawn(async move {
                if let Err(e) = start_backend(cfg).await {
                    tracing::error!("Embedded backend exited with error: {e}");
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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
