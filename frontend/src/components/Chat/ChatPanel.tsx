import { useEffect, useRef } from "react";
import { useChat } from "../../context/ChatContext";
import { useWs } from "../../context/WsContext";
import MealPlanCard from "./MealPlanCard";
import RecommendationCards from "./RecommendationCards";
import ThinkingBubble from "./ThinkingBubble";
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

  // Find the last message with recommendations (for "Order this" buttons)
  const lastRecMsgId = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].recommendations && messages[i].recommendations!.length > 0)
        return messages[i].id;
    }
    return null;
  })();

  // Check if an order was already placed after the last recommendations
  const recOrdered = (() => {
    if (lastRecMsgId === null) return false;
    const idx = messages.findIndex((m) => m.id === lastRecMsgId);
    return messages.slice(idx + 1).some((m) => m.order);
  })();

  // Find the last message that has a meal plan (for the submit button)
  const lastMealPlanMsgId = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.meal_plan && Object.keys(m.meal_plan).length > 0) return m.id;
    }
    return null;
  })();

  // Check if the plan has already been submitted (any later message has intent submit_mealplan)
  const planSubmitted = (() => {
    if (lastMealPlanMsgId === null) return false;
    const idx = messages.findIndex((m) => m.id === lastMealPlanMsgId);
    return messages
      .slice(idx + 1)
      .some((m) => m.intent === "submit_mealplan");
  })();

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
          <div key={m.id}>
            {/* Collapsed thinking toggle for completed agent messages */}
            {m.role === "agent" && m.steps && m.steps.length > 0 && (
              <ThinkingBubble
                steps={m.steps.filter((s) => s !== "done")}
                active={false}
              />
            )}

            <div
              className={`${styles.message} ${
                m.role === "user" ? styles.user : styles.agent
              }`}
            >
              {/* Meal plan card */}
              {m.meal_plan && Object.keys(m.meal_plan).length > 0 && (
                <MealPlanCard
                  plan={m.meal_plan}
                  onSubmit={
                    m.id === lastMealPlanMsgId && !planSubmitted && !processing
                      ? () => handleSend("Submit my meal plan")
                      : undefined
                  }
                  submitted={m.id === lastMealPlanMsgId && planSubmitted}
                />
              )}

              {/* Recommendation cards */}
              {m.recommendations && m.recommendations.length > 0 && (
                <RecommendationCards
                  items={m.recommendations}
                  onOrder={
                    m.id === lastRecMsgId && !recOrdered && !processing
                      ? (name) => handleSend(`I'll take the ${name}`)
                      : undefined
                  }
                  disabled={processing}
                />
              )}

              {/* Text bubble — skip if cards cover everything */}
              {m.content && (
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
              )}
            </div>
          </div>
        ))}

        {/* Active thinking indicator while processing */}
        {processing && (
          <ThinkingBubble steps={pendingSteps} active={true} />
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
