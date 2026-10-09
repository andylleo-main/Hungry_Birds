import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../lib/api';
import { useAuth } from '../state/AuthContext';
import { Icon, Spinner } from '../components/ui';

const ALLOWED_DOMAIN = 'bitmesra.ac.in';

export default function Login() {
  const { requestOtp, verifyOtp, adminLogin } = useAuth();
  const [step, setStep] = useState<'email' | 'code' | 'admin'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [debugCode, setDebugCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [resending, setResending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Seconds until another code may be requested. The server decides the
  // number and sends it back, so this countdown can't drift from the real
  // policy the way a hard-coded 60 would.
  const [cooldown, setCooldown] = useState(0);
  const codeInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  async function sendCode(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { debugCode: dev, resendAfter } = await requestOtp(email.trim());
      setDebugCode(dev);
      setCooldown(resendAfter);
      setStep('code');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't send the code. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function signInAsAdmin(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await adminLogin(email.trim(), password);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 404
          ? 'Password sign-in is switched off on this server.'
          : err instanceof ApiError
            ? err.message
            : 'Could not sign in. Try again.',
      );
      setBusy(false);
    }
  }

  async function resend() {
    setResending(true);
    setError(null);
    setNotice(null);
    try {
      const { debugCode: dev, resendAfter } = await requestOtp(email.trim());
      setDebugCode(dev);
      setCooldown(resendAfter);
      setCode('');
      setNotice('New code sent. Check your inbox.');
      codeInputRef.current?.focus();
    } catch (err) {
      // A 429 here means the cooldown is still running - most likely this tab
      // drifted from the server, so adopt the server's number rather than
      // arguing with it.
      if (err instanceof ApiError && err.status === 429) {
        const seconds = Number(err.message.match(/(\d+)s/)?.[1]);
        if (Number.isFinite(seconds) && seconds > 0) setCooldown(seconds);
      }
      setError(err instanceof ApiError ? err.message : 'Could not resend the code.');
    } finally {
      setResending(false);
    }
  }

  async function confirmCode(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await verifyOtp(email.trim(), code.trim());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That code didn't work. Check it and try again.");
      setBusy(false);
    }
  }

  const heading = (title: string, sub: React.ReactNode) => (
    <div className="flex flex-col gap-space-xs">
      <h2 className="text-headline-lg text-on-surface">{title}</h2>
      <p className="text-body-md text-on-surface-variant">{sub}</p>
    </div>
  );

  return (
    <div className="flex min-h-screen bg-white" data-testid="login-page">
      <div className="relative hidden w-[52%] flex-col justify-between overflow-hidden bg-primary p-space-xl text-on-primary lg:flex">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.08]"
          style={{ backgroundImage: 'radial-gradient(#fff 1.2px, transparent 1.2px)', backgroundSize: '22px 22px' }}
        />
        <div className="relative flex items-center gap-space-sm">
          <span className="flex h-12 w-12 items-center justify-center rounded-md bg-white">
            <img src="/logo.png" alt="" width={40} height={40} className="h-10 w-10" />
          </span>
          <span className="font-display text-headline-sm">Hungry Birds</span>
        </div>

        <div className="relative flex animate-rise flex-col gap-space-md">
          <span className="eyebrow text-white/80">BIT Mesra · campus food</span>
          <h1 className="text-[76px] font-extrabold leading-[0.95] tracking-[-0.04em]">
            Hungry?
            <br />
            <span className="text-on-surface">Skip the line.</span>
          </h1>
          <p className="max-w-md text-body-lg text-white/85">
            Order from any stall on campus on your phone, watch it get made, and pick it up or get
            it delivered the moment it's ready.
          </p>
        </div>

        <ul className="relative grid grid-cols-3 gap-space-sm text-body-sm">
          {[
            ['school', 'Only for @bitmesra.ac.in'],
            ['bolt', 'Live updates from the kitchen'],
            ['verified_user', 'Refunded if a stall declines'],
          ].map(([icon, label]) => (
            <li key={label} className="flex flex-col gap-space-sm rounded-md bg-white/10 p-space-md backdrop-blur">
              <Icon name={icon} className="text-[22px]" />
              {label}
            </li>
          ))}
        </ul>
      </div>

      <div className="flex w-full items-center justify-center px-margin-mobile py-space-xl lg:w-[48%] lg:px-margin">
        <div className="w-full max-w-md animate-rise">
          <div className="mb-space-xl flex items-center gap-space-sm lg:hidden">
            <span className="flex h-11 w-11 items-center justify-center rounded-md bg-primary">
              <img src="/logo.png" alt="" width={34} height={34} className="h-[34px] w-[34px] rounded-sm bg-white/90 p-[2px]" />
            </span>
            <span className="font-display text-headline-sm text-on-surface">Hungry Birds</span>
          </div>

          {step === 'admin' ? (
            <form onSubmit={signInAsAdmin} className="flex flex-col gap-space-md" data-testid="admin-login-form">
              {heading('Admin sign-in', 'Only for admin accounts. Students and staff sign in with an email code.')}

              <label className="flex flex-col gap-space-xs">
                <span className="text-label-md text-on-surface-medium">Admin email</span>
                <input
                  className="field"
                  type="email"
                  required
                  autoFocus
                  autoComplete="username"
                  data-testid="admin-login-email-input"
                  placeholder={`admin@${ALLOWED_DOMAIN}`}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>

              <label className="flex flex-col gap-space-xs">
                <span className="text-label-md text-on-surface-medium">Password</span>
                <input
                  className="field"
                  type="password"
                  required
                  autoComplete="current-password"
                  data-testid="admin-login-password-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>

              {error && <p className="text-body-sm text-primary" data-testid="login-error">{error}</p>}

              <button type="submit" className="btn-primary w-full" disabled={busy} data-testid="admin-login-submit">
                {busy ? <Spinner /> : 'Sign in'}
              </button>

              <button
                type="button"
                className="btn-ghost w-full"
                data-testid="admin-login-back"
                onClick={() => {
                  setStep('email');
                  setPassword('');
                  setError(null);
                }}
              >
                Sign in with an email code instead
              </button>
            </form>
          ) : step === 'email' ? (
            <form onSubmit={sendCode} className="flex flex-col gap-space-md" data-testid="email-login-form">
              {heading('Welcome back', "Enter your college email and we'll send you a 6-digit code. No password needed.")}

              <label className="flex flex-col gap-space-xs">
                <span className="text-label-md text-on-surface-medium">College email</span>
                <input
                  className="field"
                  type="email"
                  required
                  autoFocus
                  autoComplete="email"
                  data-testid="login-email-input"
                  placeholder={`yourname@${ALLOWED_DOMAIN}`}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>

              {error && <p className="text-body-sm text-primary" data-testid="login-error">{error}</p>}

              <button type="submit" className="btn-primary w-full" disabled={busy} data-testid="login-send-code">
                {busy ? <Spinner /> : (<>Send me a code <Icon name="arrow_forward" className="text-[18px]" /></>)}
              </button>

              <div className="dotted-rule my-space-xs" />

              <button
                type="button"
                data-testid="login-admin-link"
                className="self-center text-label-md text-on-surface-variant transition-colors hover:text-primary"
                onClick={() => {
                  setStep('admin');
                  setError(null);
                }}
              >
                Are you an admin? Sign in with a password
              </button>
            </form>
          ) : (
            <form onSubmit={confirmCode} className="flex flex-col gap-space-md" data-testid="code-login-form">
              {heading(
                'Check your inbox',
                <>
                  We sent a code to <span className="font-semibold text-on-surface">{email}</span>. It works for 5
                  minutes.
                </>,
              )}

              {debugCode && (
                <p className="rounded-md bg-primary-tint px-space-md py-space-sm text-body-sm text-primary" data-testid="login-debug-code">
                  Dev mode: your code is <strong>{debugCode}</strong>
                </p>
              )}

              <label className="flex flex-col gap-space-xs">
                <span className="text-label-md text-on-surface-medium">6-digit code</span>
                <input
                  ref={codeInputRef}
                  className="field h-14 text-center font-display text-headline-md tracking-[0.5em]"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  autoFocus
                  autoComplete="one-time-code"
                  data-testid="login-code-input"
                  placeholder="000000"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                />
              </label>

              {error && <p className="text-body-sm text-primary" data-testid="login-error">{error}</p>}
              {notice && !error && (
                <p className="text-body-sm text-success" role="status">
                  {notice}
                </p>
              )}

              <button type="submit" className="btn-primary w-full" disabled={busy} data-testid="login-verify-code">
                {busy ? <Spinner /> : 'Sign in'}
              </button>

              <div className="flex items-center justify-center gap-space-xs text-body-sm">
                <span className="text-on-surface-variant">No code yet?</span>
                {cooldown > 0 ? (
                  <span className="text-on-surface-medium" aria-live="polite">
                    You can ask again in {cooldown}s
                  </span>
                ) : (
                  <button
                    type="button"
                    data-testid="login-resend-code"
                    className="font-semibold text-primary underline underline-offset-2 disabled:opacity-60"
                    onClick={() => void resend()}
                    disabled={resending}
                  >
                    {resending ? 'Sending...' : 'Send another'}
                  </button>
                )}
              </div>

              <button
                type="button"
                className="btn-ghost w-full"
                data-testid="login-change-email"
                onClick={() => {
                  setStep('email');
                  setCode('');
                  setError(null);
                  setNotice(null);
                  setCooldown(0);
                }}
              >
                Use another email
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
