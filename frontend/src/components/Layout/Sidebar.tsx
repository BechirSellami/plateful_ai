import styles from "./Sidebar.module.css";

export type Panel = "chat" | "memory";

interface Props {
  active: Panel;
  onChange: (panel: Panel) => void;
}

const tabs: { id: Panel; label: string; icon: string }[] = [
  { id: "chat", label: "Chat", icon: "💬" },
  { id: "memory", label: "Memory", icon: "🧠" },
];

export default function Sidebar({ active, onChange }: Props) {
  return (
    <nav className={styles.sidebar}>
      {tabs.map((t) => (
        <button
          key={t.id}
          className={`${styles.tab} ${active === t.id ? styles.active : ""}`}
          onClick={() => onChange(t.id)}
          title={t.label}
        >
          <span className={styles.icon}>{t.icon}</span>
          <span className={styles.label}>{t.label}</span>
        </button>
      ))}
    </nav>
  );
}
