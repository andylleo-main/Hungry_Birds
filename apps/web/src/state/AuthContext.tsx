import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api, tokens } from '../lib/api';
import type { AppUser } from '../lib/types';

type Status = 'loading' | 'signedOut' | 'signedIn';

interface AuthValue {
  status: Status;
  user: AppUser | null;
  isAdmin: boolean;
  requestOtp: (email: string) => Promise<{ debugCode: string | null; resendAfter: number }>;
  verifyOtp: (email: string, code: string) => Promise<void>;
  updateProfile: (changes: { full_name?: string; phone?: string }) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading');
  const [user, setUser] = useState<AppUser | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      // A returning visitor usually has an access token that expired while
      // they were away. Asking /auth/me first lets the client's silent
      // refresh-and-retry handle that case transparently.
      if (tokens.access) {
        try {
          const me = await api.me();
          if (cancelled) return;
          setUser(me);
          setStatus('signedIn');
          return;
        } catch {
          // Fall through and try the refresh token on its own below.
        }
      }

      // No access token at all - cleared storage, or a device that has been
      // away longer than the access lifetime. The refresh token is still good
      // for thirty days, so use it instead of demanding another login.
      try {
        const me = await api.restoreSession();
        if (cancelled) return;
        if (me) {
          setUser(me);
          setStatus('signedIn');
          return;
        }
      } catch {
        // Nothing recoverable.
      }

      tokens.clear();
      if (!cancelled) setStatus('signedOut');
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const requestOtp = useCallback(async (email: string) => {
    const res = await api.requestOtp(email);
    return { debugCode: res.debug_code, resendAfter: res.resend_after_seconds };
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

  const signOut = useCallback(async () => {
    // Local state goes first so the UI never looks signed in while the network
    // call is in flight; the server revocation follows.
    setUser(null);
    setStatus('signedOut');
    await api.logout();
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
