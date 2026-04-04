import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { ChatProvider } from "./context/ChatContext";
import { UserProvider } from "./context/UserContext";
import { WsProvider } from "./context/WsContext";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <UserProvider>
      <WsProvider>
        <ChatProvider>
          <App />
        </ChatProvider>
      </WsProvider>
    </UserProvider>
  </StrictMode>
);
