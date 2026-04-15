import { useState } from "react";
import styles from "./ThinkingBubble.module.css";

interface Props {
  /** Steps collected so far. */
  steps: string[];
  /** true while the pipeline is still running. */
  active: boolean;
}

/**
 * Renders agent "thinking" state:
 *  - While active: pulsing dots + growing bulleted list of steps.
 *  - Once done: collapsed toggle that expands to reveal the step list.
 */
export default function ThinkingBubble({ steps, active }: Props) {
  const [expanded, setExpanded] = useState(false);

  // Nothing to render if there are no steps and we're not active
  if (!active && steps.length === 0) return null;

  // --- Active / in-progress view ---
  if (active) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.bubble}>
          <div className={styles.header}>
            <span className={styles.dots}>
              <span className={styles.dot} />
              <span className={styles.dot} />
              <span className={styles.dot} />
            </span>
            <span className={styles.label}>Thinking...</span>
          </div>

          {steps.length > 0 && (
            <ul className={styles.stepList}>
              {steps.map((s, i) => {
                const isLast = i === steps.length - 1;
                return (
                  <li key={i} className={styles.step}>
                    {isLast ? (
                      <span className={styles.spinner} />
                    ) : (
                      <span className={styles.check}>&#10003;</span>
                    )}
                    <span className={isLast ? styles.stepTextActive : styles.stepText}>
                      {s}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    );
  }

  // --- Collapsed / completed view ---
  return (
    <div className={styles.wrapper}>
      <button
        className={styles.toggle}
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className={styles.caret}>{expanded ? "\u25BE" : "\u25B8"}</span>
        <span className={styles.toggleLabel}>
          Thinking &middot; {steps.length} step{steps.length !== 1 ? "s" : ""}
        </span>
      </button>

      {expanded && (
        <ul className={styles.stepList}>
          {steps.map((s, i) => (
            <li key={i} className={styles.step}>
              <span className={styles.check}>&#10003;</span>
              <span className={styles.stepText}>{s}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
