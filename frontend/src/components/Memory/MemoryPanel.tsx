import { useCallback, useEffect, useState } from "react";
import { useUser } from "../../context/UserContext";
import type { MemoryEntry } from "../../types/ws";
import styles from "./MemoryPanel.module.css";

export default function MemoryPanel() {
  const { userId } = useUser();
  const [memories, setMemories] = useState<MemoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMemories = useCallback(async () => {
    if (!userId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/memories/${encodeURIComponent(userId)}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const data: MemoryEntry[] = await res.json();
      setMemories(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load memories");
      setMemories([]);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  // Reload when user changes
  useEffect(() => {
    fetchMemories();
  }, [fetchMemories]);

  const handleDelete = async (memoryId: string) => {
    try {
      await fetch(`/api/memories/${encodeURIComponent(userId)}/${memoryId}`, {
        method: "DELETE",
      });
      setMemories((prev) => prev.filter((m) => m.id !== memoryId));
    } catch {
      // Silently fail — will show on next refresh
    }
  };

  const handleDeleteAll = async () => {
    if (!confirm(`Delete all memories for ${userId}?`)) return;
    try {
      await fetch(`/api/memories/${encodeURIComponent(userId)}`, {
        method: "DELETE",
      });
      setMemories([]);
    } catch {
      // Silently fail
    }
  };

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <h2 className={styles.title}>
          Memories{" "}
          <span className={styles.badge}>{userId}</span>
        </h2>
        <div className={styles.actions}>
          <button className={styles.btn} onClick={fetchMemories} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
          {memories.length > 0 && (
            <button className={`${styles.btn} ${styles.danger}`} onClick={handleDeleteAll}>
              Delete All
            </button>
          )}
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {!loading && memories.length === 0 && !error && (
        <div className={styles.empty}>
          <p>No memories stored for <strong>{userId}</strong>.</p>
          <p className={styles.hint}>
            Chat with the agent to build up preferences and order history.
          </p>
        </div>
      )}

      <div className={styles.list}>
        {memories.map((m) => (
          <div key={m.id} className={styles.card}>
            <p className={styles.memoryText}>{m.memory}</p>
            <div className={styles.cardFooter}>
              <span className={styles.memoryId} title={m.id}>
                {m.id.slice(0, 8)}...
              </span>
              {m.updated_at && (
                <span className={styles.date}>
                  {new Date(m.updated_at).toLocaleDateString()}
                </span>
              )}
              <button
                className={styles.deleteBtn}
                onClick={() => handleDelete(m.id)}
                title="Delete this memory"
              >
                &#10005;
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
