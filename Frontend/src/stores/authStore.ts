import { create } from "zustand";

import type { AuthUser } from "@/lib/api";

export type AuthStatus = "unknown" | "authenticated" | "unauthenticated";

interface AuthState {
  user: AuthUser | null;
  status: AuthStatus;
  setUser: (user: AuthUser) => void;
  clearAuth: () => void;
  setUnauthenticated: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  status: "unknown",
  setUser: (user) => set({ user, status: "authenticated" }),
  clearAuth: () => set({ user: null, status: "unauthenticated" }),
  setUnauthenticated: () => set({ user: null, status: "unauthenticated" }),
}));
