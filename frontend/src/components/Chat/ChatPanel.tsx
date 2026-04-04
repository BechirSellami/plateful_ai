import { useEffect, useRef } from "react";
import { useChat } from "../../context/ChatContext";
import { useWs } from "../../context/WsContext";
import styles from "./ChatPanel.module.css";

const EXAMPLES = [
  "I want pasta or a sandwich",
  "Recommend something healthy under $16",
  "I'm allergic to shellfish",
  "Show me Thai food options",
];

export default function ChatPanel() {
  const { messages, input, setInput, processing, pendingSteps, handleSend } =
    useChat();
  const { connected } = useWs();
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages or steps
  useEffect(() => {
    requestAnimationFrame(() =>
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
    );
  }, [messages, pendingSteps]);

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
                    <span
                      key={i}
                      className={`${styles.stepChip} ${styles.done}`}
                    >
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
