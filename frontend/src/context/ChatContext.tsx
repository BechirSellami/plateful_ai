import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { WsIncoming, WsResultEvent } from "../types/ws";
import { useUser } from "./UserContext";
import { useWs } from "./WsContext";

export interface ChatMessage {
  id: number;
  role: "user" | "agent";
  content: string;
  intent?: string | null;
  order?: WsResultEvent["order"];
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

        let content = "";
        if (data.recommendation_text) {
          content = data.recommendation_text;
        } else if (data.intent === "declare_preference") {
          content = "Got it, I'll remember that for next time!";
        } else if (data.order?.status === "submitted") {
          const items = data.order.items.map((i) => i.name).join(", ");
          const total = data.order.total_usd
            ? `$${data.order.total_usd.toFixed(2)}`
            : "";
          content = `Order placed! #${data.order.order_id}: ${items} ${total}`;
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
