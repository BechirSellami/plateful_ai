import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type {
  AllergenConflict,
  MealPlan,
  RecommendationItem,
  WsIncoming,
  WsResultEvent,
} from "../types/ws";
import { useUser } from "./UserContext";
import { useWs } from "./WsContext";

export interface ChatMessage {
  id: number;
  role: "user" | "agent";
  content: string;
  intent?: string | null;
  order?: WsResultEvent["order"];
  recommendations?: RecommendationItem[];
  allergen_conflicts?: AllergenConflict[];
  meal_plan?: MealPlan | null;
  steps?: string[];
}

interface ChatState {
  messages: ChatMessage[];
  input: string;
  setInput: (v: string) => void;
  processing: boolean;
  pendingSteps: string[];
  handleSend: (text: string) => void;
}

const ChatContext = createContext<ChatState | null>(null);

let msgId = 0;

export function ChatProvider({ children }: { children: ReactNode }) {
  const { userId, sessionId } = useUser();
  const { send, subscribe, connected } = useWs();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [processing, setProcessing] = useState(false);
  const [pendingSteps, setPendingSteps] = useState<string[]>([]);
  const pendingStepsRef = useRef<string[]>([]);

  // Keep ref in sync so the subscribe callback always sees latest steps
  useEffect(() => {
    pendingStepsRef.current = pendingSteps;
  }, [pendingSteps]);

  // Subscribe to WS messages — runs once, uses refs for mutable state
  useEffect(() => {
    const unsub = subscribe((data: WsIncoming) => {
      if (data.type === "step") {
        setPendingSteps((prev) => [...prev, data.step]);
      } else if (data.type === "result") {
        const steps = [...pendingStepsRef.current, "done"];
        setPendingSteps([]);

        // Build display text — cards are rendered separately for
        // meal plans and recommendations; text is only for non-card content.
        let content = "";
        const hasOrder = data.order?.status === "submitted" || data.order?.status === "pending_approval";
        const hasRecCards = !hasOrder && data.recommendations && data.recommendations.length > 0;
        const hasMealPlan = data.meal_plan && Object.keys(data.meal_plan).length > 0;
        if (hasOrder && data.recommendation_text) {
          // Order was placed — show the confirmation text (e.g. "Your order
          // has been placed! Order #X: Tofu Stir Fry ($14.00)").  Any carried-
          // forward recommendations are stale and should not drive content.
          content = data.recommendation_text;
        } else if (hasMealPlan) {
          content = "";
        } else if (hasRecCards) {
          // Show only allergen warning as companion text; cards handle the rest
          content = buildAllergenWarningText(data.allergen_conflicts || []);
        } else if (data.recommendation_text) {
          content = data.recommendation_text;
        } else if (data.intent === "declare_preference") {
          content = "Got it, I'll remember that for next time!";
        } else if (hasOrder) {
          const items = data.order!.items.map((i) => i.name).join(", ");
          const total = data.order!.total_usd
            ? `$${data.order!.total_usd.toFixed(2)}`
            : "";
          content = `Order placed! #${data.order!.order_id}: ${items} ${total}`;
        } else {
          content = "Done.";
        }

        setMessages((prev) => [
          ...prev,
          {
            id: ++msgId,
            role: "agent",
            content,
            intent: data.intent,
            order: data.order,
            recommendations: hasRecCards ? data.recommendations : undefined,
            allergen_conflicts: data.allergen_conflicts,
            meal_plan: data.meal_plan,
            steps,
          },
        ]);
        setProcessing(false);
      } else if (data.type === "error") {
        setPendingSteps([]);
        setMessages((prev) => [
          ...prev,
          { id: ++msgId, role: "agent", content: `Error: ${data.detail}` },
        ]);
        setProcessing(false);
      }
    });
    return unsub;
  }, [subscribe]);

  const handleSend = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || processing || !connected) return;

      setMessages((prev) => [
        ...prev,
        { id: ++msgId, role: "user", content: trimmed },
      ]);
      setProcessing(true);
      setPendingSteps([]);
      setInput("");

      send({ message: trimmed, user_id: userId, session_id: sessionId });
    },
    [processing, connected, send, userId, sessionId]
  );

  return (
    <ChatContext.Provider
      value={{ messages, input, setInput, processing, pendingSteps, handleSend }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChat(): ChatState {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be inside ChatProvider");
  return ctx;
}

/** Build a user-facing allergen warning string from conflict data. */
function buildAllergenWarningText(conflicts: AllergenConflict[]): string {
  if (!conflicts || conflicts.length === 0) return "";

  const parts: string[] = [];
  for (const c of conflicts) {
    if (c.ingredient) {
      const count = c.items_removed?.length ?? 0;
      parts.push(
        `**${c.ingredient}** is a ${c.allergen_group} allergen (${count} item${count !== 1 ? "s" : ""} removed)`
      );
    } else if (c.name) {
      parts.push(`**${c.name}** contains ${c.matched_allergens.join(", ")}`);
    }
  }
  if (parts.length === 0) return "";
  return `**Heads up!** ${parts.join("; ")} — removed from your options because of your allergy on file. Here are some safe alternatives:`;
}
