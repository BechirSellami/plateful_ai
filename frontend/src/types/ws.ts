/** Messages sent from the client to the server. */
export interface WsOutgoing {
  message: string;
  user_id: string;
  session_id: string;
}

/** Step progress event from the server. */
export interface WsStepEvent {
  type: "step";
  step: string;
  agent: string;
}

/** Order details embedded in the result. */
export interface OrderPayload {
  order_id: string;
  status: string;
  items: { name: string; price_usd?: number }[];
  total_usd?: number;
}

/** A single day entry in a meal plan. */
export interface MealPlanEntry {
  name: string;
  price_usd: number | null;
  category: string;
  cuisine: string;
  calories: number | null;
  description: string;
  old_item?: string;
}

/** Monday–Friday meal plan keyed by day name. */
export type MealPlan = Record<string, MealPlanEntry>;

/** A single recommendation item. */
export interface RecommendationItem {
  name: string;
  price_usd: number;
  category: string;
  cuisine: string;
  calories: number;
  description: string;
}

/** An allergen conflict detected by the menu agent. */
export interface AllergenConflict {
  /** Present when the user mentioned an allergen ingredient directly. */
  ingredient?: string;
  allergen_group?: string;
  items_removed?: string[];
  /** Present when a specific menu item matched by name. */
  name?: string;
  matched_allergens: string[];
}

/** Final result from the server after a pipeline run. */
export interface WsResultEvent {
  type: "result";
  intent: string | null;
  constraints: Record<string, unknown>;
  menu_items_count: number;
  recommendations: RecommendationItem[];
  recommendation_text: string | null;
  allergen_conflicts: AllergenConflict[];
  order: OrderPayload | null;
  meal_plan: MealPlan | null;
  user_profile: Record<string, unknown>;
}

/** Error event from the server. */
export interface WsErrorEvent {
  type: "error";
  detail: string;
}

/** All possible incoming server messages. */
export type WsIncoming = WsStepEvent | WsResultEvent | WsErrorEvent;

/** Memory entry from the /api/memories endpoint. */
export interface MemoryEntry {
  id: string;
  memory: string;
  created_at?: string;
  updated_at?: string;
}
