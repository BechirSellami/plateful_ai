import type { RecommendationItem } from "../../types/ws";
import styles from "./RecommendationCards.module.css";

const RANK_ICONS = ["\u{1F947}", "\u{1F948}", "\u{1F949}"]; // gold, silver, bronze

interface Props {
  items: RecommendationItem[];
  /** Called with the item name when the user clicks "Order this". */
  onOrder?: (itemName: string) => void;
  /** Disable order buttons (e.g. while processing). */
  disabled?: boolean;
}

export default function RecommendationCards({
  items,
  onOrder,
  disabled,
}: Props) {
  if (!items || items.length === 0) return null;

  return (
    <div className={styles.stack}>
      {items.map((item, i) => (
        <div key={item.name} className={styles.card}>
          <div className={styles.top}>
            <div className={styles.rank}>{RANK_ICONS[i] ?? `${i + 1}.`}</div>
            <div className={styles.info}>
              <div className={styles.name}>{item.name}</div>
              <div className={styles.meta}>
                {item.cuisine && (
                  <span className={styles.cuisineBadge}>{item.cuisine}</span>
                )}
                {item.calories != null && (
                  <span className={styles.cal}>{item.calories} cal</span>
                )}
                {item.category && (
                  <span className={styles.category}>{item.category}</span>
                )}
              </div>
            </div>
            <div className={styles.price}>
              {item.price_usd != null ? `$${item.price_usd.toFixed(2)}` : ""}
            </div>
          </div>

          {item.description && (
            <p className={styles.description}>{item.description}</p>
          )}

          {onOrder && (
            <button
              className={styles.orderBtn}
              onClick={() => onOrder(item.name)}
              disabled={disabled}
            >
              Order this
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
