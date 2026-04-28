//! Per-actor SQLite-backed key-value persistence.
//!
//! Each actor that needs durable state gets its own `ActorPersistence` instance
//! pointing at a single SQLite file.  Values are stored as JSON strings so any
//! `serde_json::Value` can round-trip without a schema migration.
//!
//! ## File layout
//! ```text
//! <data_dir>/actors/<actor_name>.db
//! ```
//!
//! ## Schema
//! ```sql
//! CREATE TABLE IF NOT EXISTS kv_store (
//!     key   TEXT PRIMARY KEY,
//!     value TEXT NOT NULL
//! );
//! ```

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use anyhow::Result;
use rusqlite::{Connection, params};

/// SQLite-backed KV store scoped to one actor.
///
/// `Connection` is `Send` but not `Sync`; the `Mutex` wrapper makes this struct
/// both `Send` and `Sync` so it can be held by actors that must satisfy
/// `Send + Sync + 'static`.
pub struct ActorPersistence {
    conn: Mutex<Connection>,
    path: PathBuf,
}

impl std::fmt::Debug for ActorPersistence {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ActorPersistence")
            .field("path", &self.path)
            .finish()
    }
}

impl ActorPersistence {
    /// Open (or create) the persistence DB for `actor_name` under `data_dir`.
    pub fn open(data_dir: &Path, actor_name: &str) -> Result<Self> {
        let dir = data_dir.join("actors");
        std::fs::create_dir_all(&dir)?;
        let safe_name: String = actor_name
            .chars()
            .map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
            .collect();
        let path = dir.join(format!("{safe_name}.db"));
        let conn = Connection::open(&path)?;
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             CREATE TABLE IF NOT EXISTS kv_store (
                 key   TEXT PRIMARY KEY,
                 value TEXT NOT NULL
             );",
        )?;
        tracing::debug!("Opened persistence DB: {}", path.display());
        Ok(Self { conn: Mutex::new(conn), path })
    }

    /// Persist `value` under `key`, overwriting any previous value.
    pub fn set(&self, key: &str, value: &serde_json::Value) -> Result<()> {
        let serialized = serde_json::to_string(value)?;
        self.conn.lock().unwrap().execute(
            "INSERT INTO kv_store (key, value) VALUES (?1, ?2)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            params![key, serialized],
        )?;
        Ok(())
    }

    /// Recall a previously persisted value, or `None` if not found.
    pub fn get(&self, key: &str) -> Option<serde_json::Value> {
        self.conn
            .lock()
            .unwrap()
            .query_row(
                "SELECT value FROM kv_store WHERE key = ?1",
                params![key],
                |row| row.get::<_, String>(0),
            )
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
    }

    /// Delete a key; silently succeeds if the key does not exist.
    pub fn delete(&self, key: &str) -> Result<()> {
        self.conn
            .lock()
            .unwrap()
            .execute("DELETE FROM kv_store WHERE key = ?1", params![key])?;
        Ok(())
    }

    /// Path to the underlying DB file.
    pub fn path(&self) -> &Path {
        &self.path
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn tmp_db(name: &str) -> (TempDir, ActorPersistence) {
        let dir = TempDir::new().unwrap();
        let db = ActorPersistence::open(dir.path(), name).unwrap();
        (dir, db)
    }

    // ── open ────────────────────────────────────────────────────────────────

    #[test]
    fn open_creates_db_file() {
        let (_dir, db) = tmp_db("alpha");
        assert!(db.path().exists(), "DB file should be created on open");
    }

    #[test]
    fn open_sanitises_actor_name() {
        let dir = TempDir::new().unwrap();
        let db = ActorPersistence::open(dir.path(), "my agent/v2").unwrap();
        let file_name = db.path().file_name().unwrap().to_string_lossy();
        assert!(
            !file_name.contains('/'),
            "slash should be replaced: {file_name}"
        );
        assert!(file_name.ends_with(".db"));
    }

    #[test]
    fn open_idempotent_reopens_existing_db() {
        let dir = TempDir::new().unwrap();
        {
            let db = ActorPersistence::open(dir.path(), "bravo").unwrap();
            db.set("k", &serde_json::json!("hello")).unwrap();
        }
        // Reopen — existing data must survive.
        let db2 = ActorPersistence::open(dir.path(), "bravo").unwrap();
        assert_eq!(db2.get("k"), Some(serde_json::json!("hello")));
    }

    // ── set / get ───────────────────────────────────────────────────────────

    #[test]
    fn set_and_get_string() {
        let (_dir, db) = tmp_db("charlie");
        db.set("greeting", &serde_json::json!("hello")).unwrap();
        assert_eq!(db.get("greeting"), Some(serde_json::json!("hello")));
    }

    #[test]
    fn set_and_get_number() {
        let (_dir, db) = tmp_db("delta");
        db.set("count", &serde_json::json!(42u64)).unwrap();
        assert_eq!(db.get("count"), Some(serde_json::json!(42u64)));
    }

    #[test]
    fn set_and_get_float() {
        let (_dir, db) = tmp_db("echo");
        db.set("cost", &serde_json::json!(1.23456)).unwrap();
        let v = db.get("cost").unwrap();
        let f = v.as_f64().unwrap();
        assert!((f - 1.23456).abs() < 1e-9);
    }

    #[test]
    fn set_and_get_object() {
        let (_dir, db) = tmp_db("foxtrot");
        let payload = serde_json::json!({
            "input_tokens": 100u64,
            "output_tokens": 200u64,
            "cost_usd": 0.001234,
            "name": "foxtrot-llm"
        });
        db.set("_final_cost", &payload).unwrap();
        let got = db.get("_final_cost").unwrap();
        assert_eq!(got["input_tokens"], 100u64);
        assert_eq!(got["output_tokens"], 200u64);
        assert_eq!(got["name"], "foxtrot-llm");
    }

    #[test]
    fn set_and_get_array() {
        let (_dir, db) = tmp_db("golf");
        let history = serde_json::json!([
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"}
        ]);
        db.set("conversation_history", &history).unwrap();
        let got = db.get("conversation_history").unwrap();
        assert_eq!(got.as_array().unwrap().len(), 2);
        assert_eq!(got[0]["role"], "user");
        assert_eq!(got[1]["content"], "Hello!");
    }

    #[test]
    fn get_missing_key_returns_none() {
        let (_dir, db) = tmp_db("hotel");
        assert_eq!(db.get("nonexistent"), None);
    }

    #[test]
    fn set_overwrites_existing_key() {
        let (_dir, db) = tmp_db("india");
        db.set("x", &serde_json::json!(1)).unwrap();
        db.set("x", &serde_json::json!(2)).unwrap();
        assert_eq!(db.get("x"), Some(serde_json::json!(2)));
    }

    #[test]
    fn multiple_keys_are_independent() {
        let (_dir, db) = tmp_db("juliet");
        db.set("a", &serde_json::json!("alpha")).unwrap();
        db.set("b", &serde_json::json!("bravo")).unwrap();
        assert_eq!(db.get("a"), Some(serde_json::json!("alpha")));
        assert_eq!(db.get("b"), Some(serde_json::json!("bravo")));
    }

    // ── delete ──────────────────────────────────────────────────────────────

    #[test]
    fn delete_removes_key() {
        let (_dir, db) = tmp_db("kilo");
        db.set("gone", &serde_json::json!("bye")).unwrap();
        db.delete("gone").unwrap();
        assert_eq!(db.get("gone"), None);
    }

    #[test]
    fn delete_nonexistent_key_is_ok() {
        let (_dir, db) = tmp_db("lima");
        assert!(db.delete("no-such-key").is_ok());
    }

    // ── durability (simulated restart) ──────────────────────────────────────

    #[test]
    fn cost_survives_reopen() {
        let dir = TempDir::new().unwrap();
        {
            let db = ActorPersistence::open(dir.path(), "mike-llm").unwrap();
            db.set(
                "_final_cost",
                &serde_json::json!({
                    "input_tokens": 500u64,
                    "output_tokens": 250u64,
                    "cost_usd": 0.003,
                    "name": "mike-llm"
                }),
            )
            .unwrap();
        }
        let db2 = ActorPersistence::open(dir.path(), "mike-llm").unwrap();
        let saved = db2.get("_final_cost").unwrap();
        assert_eq!(saved["input_tokens"], 500u64);
        assert_eq!(saved["output_tokens"], 250u64);
        assert_eq!(saved["name"], "mike-llm");
    }

    #[test]
    fn history_survives_reopen() {
        let dir = TempDir::new().unwrap();
        {
            let db = ActorPersistence::open(dir.path(), "november-llm").unwrap();
            let history = serde_json::json!([
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "4"}
            ]);
            db.set("conversation_history", &history).unwrap();
        }
        let db2 = ActorPersistence::open(dir.path(), "november-llm").unwrap();
        let restored = db2.get("conversation_history").unwrap();
        let arr = restored.as_array().unwrap();
        assert_eq!(arr.len(), 2);
        assert_eq!(arr[1]["content"], "4");
    }

    // ── thread-safety ───────────────────────────────────────────────────────

    #[test]
    fn send_sync_bounds() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<ActorPersistence>();
    }

    #[test]
    fn concurrent_writes_from_threads() {
        use std::sync::Arc;
        use std::thread;

        let dir = TempDir::new().unwrap();
        let db = Arc::new(ActorPersistence::open(dir.path(), "oscar").unwrap());

        let handles: Vec<_> = (0..8)
            .map(|i| {
                let db = Arc::clone(&db);
                thread::spawn(move || {
                    db.set(&format!("key-{i}"), &serde_json::json!(i)).unwrap();
                })
            })
            .collect();

        for h in handles {
            h.join().unwrap();
        }

        for i in 0..8u64 {
            assert_eq!(db.get(&format!("key-{i}")), Some(serde_json::json!(i)));
        }
    }

    // ── debug repr ──────────────────────────────────────────────────────────

    #[test]
    fn debug_repr_includes_path() {
        let (_dir, db) = tmp_db("papa");
        let repr = format!("{db:?}");
        assert!(repr.contains("ActorPersistence"), "{repr}");
        assert!(repr.contains("papa"), "{repr}");
    }
}
