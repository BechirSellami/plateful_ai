import type { MealPlan } from "../../types/ws";
import styles from "./MealPlanCard.module.css";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

const DAY_SHORT: Record<string, string> = {
  Monday: "Mon",
  Tuesday: "Tue",
  Wednesday: "Wed",
  Thursday: "Thu",
  Friday: "Fri",
};

interface Props {
  plan: MealPlan;
  /** When provided, renders a "Submit Plan" button. */
  onSubmit?: () => void;
  /** Disable the submit button (e.g. while processing). */
  submitted?: boolean;
}

export default function MealPlanCard({ plan, onSubmit, submitted }: Props) {
  const entries = WEEKDAYS.map((day) => ({ day, ...plan[day] })).filter(
    (e) => e.name
  );

  if (entries.length === 0) return null;

  const total = entries.reduce(
    (sum, e) => sum + (e.price_usd ?? 0),
    0
  );

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.title}>Weekly Meal Plan</span>
        <span className={styles.total}>${total.toFixed(2)}</span>
      </div>

      <div className={styles.grid}>
        {entries.map((e) => (
          <div key={e.day} className={styles.dayCard}>
            <div className={styles.dayLabel}>{DAY_SHORT[e.day] ?? e.day}</div>
            <div className={styles.itemName}>{e.name}</div>
            <div className={styles.meta}>
              {e.cuisine && (
                <span className={styles.cuisineBadge}>{e.cuisine}</span>
              )}
              {e.calories != null && (
                <span className={styles.cal}>{e.calories} cal</span>
              )}
            </div>
            {e.price_usd != null && (
              <div className={styles.price}>${e.price_usd.toFixed(2)}</div>
            )}
            {e.old_item && (
              <div className={styles.swapped}>
                Swapped from {e.old_item}
              </div>
            )}
          </div>
        ))}
      </div>

      {onSubmit && (
        <div className={styles.footer}>
          <button
            className={styles.submitBtn}
            onClick={onSubmit}
            disabled={submitted}
          >
            {submitted ? "Submitted" : "Submit Plan"}
          </button>
        </div>
      )}
    </div>
  );
}
