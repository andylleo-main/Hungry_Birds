import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api, tokens } from '../lib/api';
import type { AppUser } from '../lib/types';

type Status = 'loading' | 'signedOut' | 'signedIn';

interface AuthValue {
  status: Status;
  user: AppUser | null;
  isAdmin: boolean;
  requestOtp: (email: string) => Promise<string | null>;
  verifyOtp: (email: string, code: string) => Promise<void>;
  updateProfile: (changes: { full_name?: string; phone?: string }) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading');
  const [user, setUser] = useState<AppUser | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      if (!tokens.access) {
        if (!cancelled) setStatus('signedOut');
        return;
      }
      try {
        const me = await api.me();
        if (cancelled) return;
        setUser(me);
        setStatus('signedIn');
      } catch {
        // Expired or revoked - start clean rather than half-signed-in.
        tokens.clear();
        if (!cancelled) setStatus('signedOut');
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const requestOtp = useCallback(async (email: string) => {
    const res = await api.requestOtp(email);
    return res.debug_code;
  }, []);

  const verifyOtp = useCallback(async (email: string, code: string) => {
    const result = await api.verifyOtp(email, code);
    setUser(result.user);
    setStatus('signedIn');
  }, []);

  const updateProfile = useCallback(
    async (changes: { full_name?: string; phone?: string }) => {
      // Adopt what the backend returns - it normalizes the phone.
      setUser(await api.updateMe(changes));
    },
    [],
  );

  const signOut = useCallback(() => {
    api.logout();
    setUser(null);
    setStatus('signedOut');
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      status,
      user,
      isAdmin: user?.role === 'admin',
      requestOtp,
      verifyOtp,
      updateProfile,
      signOut,
    }),
    [status, user, requestOtp, verifyOtp, updateProfile, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
