import { createContext, useContext, useState, type ReactNode } from "react";

interface UserState {
  userId: string;
  sessionId: string;
  setUserId: (id: string) => void;
  setSessionId: (id: string) => void;
}

const UserContext = createContext<UserState | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const [userId, setUserId] = useState("emp_demo");
  const [sessionId, setSessionId] = useState("sess_demo");

  return (
    <UserContext.Provider value={{ userId, sessionId, setUserId, setSessionId }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser(): UserState {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser must be inside UserProvider");
  return ctx;
}
