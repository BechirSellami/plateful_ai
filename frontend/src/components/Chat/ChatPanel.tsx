import { useCallback, useEffect, useRef, useState } from "react";
import { useUser } from "../../context/UserContext";
import { useWs } from "../../context/WsContext";
import type { WsIncoming, WsResultEvent } from "../../types/ws";
import styles from "./ChatPanel.module.css";

interface ChatMessage {
  id: number;
  role: "user" | "agent";
  content: string;
  intent?: string | null;
  order?: WsResultEvent["order"];
  steps?: string[];
}

const EXAMPLES = [
  "I want pasta or a sandwich",
  "Recommend something healthy under $16",
  "I'm allergic to shellfish",
  "Show me Thai food options",
];

let msgId = 0;

export default function ChatPanel() {
  const { userId, sessionId } = useUser();
  const { send, subscribe, connected } = useWs();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [processing, setProcessing] = useState(false);
  const [pendingSteps, setPendingSteps] = useState<string[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() =>
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
    );
  }, []);

  // Subscribe to WS messages
  useEffect(() => {
    const unsub = subscribe((data: WsIncoming) => {
      if (data.type === "step") {
        setPendingSteps((prev) => [...prev, data.step]);
        scrollToBottom();
      } else if (data.type === "result") {
        const steps = [...pendingSteps, "done"];
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
        scrollToBottom();
      } else if (data.type === "error") {
        setPendingSteps([]);
        setMessages((prev) => [
          ...prev,
          { id: ++msgId, role: "agent", content: `Error: ${data.detail}` },
        ]);
        setProcessing(false);
        scrollToBottom();
      }
    });
    return unsub;
  }, [subscribe, pendingSteps, scrollToBottom]);

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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleSend(input);
  };

  const showWelcome = messages.length === 0;

  return (
    <div className={styles.panel}>
      <div className={styles.chatArea}>
        {showWelcome && (
          <div className={styles.welcome}>
            <h2>Welcome to Plateful AI</h2>
            <p>
              Your personal catering assistant. Ask for recommendations, place
              orders, or tell me your preferences.
            </p>
            <div className={styles.examples}>
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  className={styles.exampleBtn}
                  onClick={() => handleSend(ex)}
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div
            key={m.id}
            className={`${styles.message} ${
              m.role === "user" ? styles.user : styles.agent
            }`}
          >
            {m.steps && m.steps.length > 0 && (
              <div className={styles.stepsBar}>
                {m.steps
                  .filter((s) => s !== "done")
                  .map((s, i) => (
                    <span key={i} className={`${styles.stepChip} ${styles.done}`}>
                      {s} &#10003;
                    </span>
                  ))}
              </div>
            )}
            <div className={styles.bubble}>
              {m.intent && m.role === "agent" && (
                <span className={styles.intentBadge}>{m.intent}</span>
              )}
              {m.role === "agent" ? (
                <span
                  dangerouslySetInnerHTML={{
                    __html: formatMarkdown(m.content),
                  }}
                />
              ) : (
                m.content
              )}
            </div>
          </div>
        ))}

        {/* Active steps indicator */}
        {pendingSteps.length > 0 && (
          <div className={styles.stepsBar}>
            {pendingSteps.map((s, i) => (
              <span
                key={i}
                className={`${styles.stepChip} ${
                  i < pendingSteps.length - 1 ? styles.done : ""
                }`}
              >
                {i === pendingSteps.length - 1 && (
                  <span className={styles.spinner} />
                )}
                {s}
                {i < pendingSteps.length - 1 && " \u2713"}
              </span>
            ))}
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      <form className={styles.inputBar} onSubmit={handleSubmit}>
        <input
          type="text"
          className={styles.textInput}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={processing}
          autoFocus
        />
        <button
          type="submit"
          className={styles.sendBtn}
          disabled={processing || !connected}
        >
          Send
        </button>
      </form>
    </div>
  );
}

function formatMarkdown(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}
