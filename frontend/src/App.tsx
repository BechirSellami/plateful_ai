import { useState } from "react";
import ChatPanel from "./components/Chat/ChatPanel";
import Header from "./components/Layout/Header";
import Sidebar, { type Panel } from "./components/Layout/Sidebar";
import MemoryPanel from "./components/Memory/MemoryPanel";

export default function App() {
  const [activePanel, setActivePanel] = useState<Panel>("chat");

  return (
    <>
      <Header />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar active={activePanel} onChange={setActivePanel} />
        {activePanel === "chat" && <ChatPanel />}
        {activePanel === "memory" && <MemoryPanel />}
      </div>
    </>
  );
}
