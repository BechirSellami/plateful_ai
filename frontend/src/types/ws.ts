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

/** Final result from the server after a pipeline run. */
export interface WsResultEvent {
  type: "result";
  intent: string | null;
  constraints: Record<string, unknown>;
  menu_items_count: number;
  recommendations: {
    name: string;
    price_usd: number;
    category: string;
    cuisine: string;
    calories: number;
    description: string;
  }[];
  recommendation_text: string | null;
  order: OrderPayload | null;
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
