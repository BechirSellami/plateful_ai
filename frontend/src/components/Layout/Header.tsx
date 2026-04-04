import { useUser } from "../../context/UserContext";
import { useWs } from "../../context/WsContext";
import styles from "./Header.module.css";

export default function Header() {
  const { userId, sessionId, setUserId, setSessionId } = useUser();
  const { connected } = useWs();

  return (
    <header className={styles.header}>
      <div className={styles.left}>
        <span className={styles.logo}>&#127869;</span>
        <h1 className={styles.title}>Plateful AI</h1>
      </div>
      <div className={styles.right}>
        <label className={styles.field}>
          <span className={styles.label}>User</span>
          <input
            className={styles.input}
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Session</span>
          <input
            className={styles.input}
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
          />
        </label>
        <span
          className={`${styles.dot} ${connected ? styles.connected : ""}`}
          title={connected ? "Connected" : "Disconnected"}
        />
      </div>
    </header>
  );
}
