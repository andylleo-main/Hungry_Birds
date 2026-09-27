import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../lib/api';
import { useAuth } from '../state/AuthContext';
import { Icon, Spinner } from '../components/ui';

const ALLOWED_DOMAIN = 'bitmesra.ac.in';

export default function Login() {
  const { requestOtp, verifyOtp } = useAuth();
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
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
      setError(err instanceof ApiError ? err.message : 'Could not send the code. Try again.');
    } finally {
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
      setNotice('A new code is on its way.');
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
      setError(err instanceof ApiError ? err.message : 'Could not verify the code. Try again.');
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen bg-surface">
      {/* Brand panel - hidden on mobile so the form gets the whole screen. */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden bg-primary p-space-xl text-on-primary lg:flex">
        <div className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-white/10 blur-3xl" />
        <div className="relative flex items-center gap-space-sm">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-white/15">
            <Icon name="lunch_dining" className="text-[22px]" />
          </span>
          <span className="text-headline-sm">Hunger Birds</span>
        </div>

        <div className="relative flex flex-col gap-space-md">
          <h1 className="text-display-hero leading-[1.1] tracking-tight">
            Campus food,
            <br />
            <span className="italic">ordered ahead.</span>
          </h1>
          <p className="max-w-md text-body-lg text-white/85">
            Skip the queue at the stall. Order from your phone, watch it being made, and collect
            when it's ready.
          </p>
        </div>

        <ul className="relative flex flex-col gap-space-sm text-body-md text-white/85">
          {[
            ['school', 'Only @bitmesra.ac.in accounts'],
            ['bolt', 'Live order updates from the stall'],
            ['payments', 'Cash when you pick up'],
          ].map(([icon, label]) => (
            <li key={label} className="flex items-center gap-space-sm">
              <Icon name={icon} className="text-[20px]" />
              {label}
            </li>
          ))}
        </ul>
      </div>

      <div className="flex w-full items-center justify-center px-margin-mobile lg:w-1/2 lg:px-margin">
        <div className="w-full max-w-md">
          <div className="mb-space-lg flex items-center gap-space-sm lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-on-primary">
              <Icon name="lunch_dining" className="text-[22px]" />
            </span>
            <span className="text-headline-sm text-on-surface">Hunger Birds</span>
          </div>

          {step === 'email' ? (
            <form onSubmit={sendCode} className="flex flex-col gap-space-md">
              <div className="flex flex-col gap-space-xs">
                <h2 className="text-headline-lg text-on-surface">Sign in</h2>
                <p className="text-body-md text-on-surface-variant">
                  We'll email you a 6-digit code. Use your institute address.
                </p>
              </div>

              <label className="flex flex-col gap-space-xs">
                <span className="text-label-md text-on-surface-medium">Institute email</span>
                <input
                  className="field"
                  type="email"
                  required
                  autoFocus
                  autoComplete="email"
                  placeholder={`yourname@${ALLOWED_DOMAIN}`}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>

              {error && <p className="text-body-sm text-primary">{error}</p>}

              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? <Spinner /> : 'Send code'}
              </button>
            </form>
          ) : (
            <form onSubmit={confirmCode} className="flex flex-col gap-space-md">
              <div className="flex flex-col gap-space-xs">
                <h2 className="text-headline-lg text-on-surface">Enter the code</h2>
                <p className="text-body-md text-on-surface-variant">
                  Sent to <span className="text-on-surface">{email}</span>. It expires in 5 minutes.
                </p>
              </div>

              {/* Only present when the backend runs with OTP_DEBUG_ECHO on,
                  which must never be the case on a public deployment. */}
              {debugCode && (
                <p className="rounded bg-primary-tint px-space-md py-space-sm text-body-sm text-primary">
                  Dev mode - your code is <strong>{debugCode}</strong>
                </p>
              )}

              <label className="flex flex-col gap-space-xs">
                <span className="text-label-md text-on-surface-medium">6-digit code</span>
                <input
                  ref={codeInputRef}
                  className="field text-center text-headline-md tracking-[0.5em]"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  autoFocus
                  autoComplete="one-time-code"
                  placeholder="000000"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                />
              </label>

              {error && <p className="text-body-sm text-primary">{error}</p>}
              {notice && !error && (
                <p className="text-body-sm text-success" role="status">
                  {notice}
                </p>
              )}

              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? <Spinner /> : 'Verify & continue'}
              </button>

              <div className="flex items-center justify-center gap-space-xs text-body-sm">
                <span className="text-on-surface-variant">Didn't get it?</span>
                {cooldown > 0 ? (
                  // Disabled rather than hidden, so the wait is visible and
                  // nobody sits wondering whether resending is possible.
                  <span className="text-on-surface-medium" aria-live="polite">
                    Resend in {cooldown}s
                  </span>
                ) : (
                  <button
                    type="button"
                    className="font-medium text-primary underline underline-offset-2 disabled:opacity-60"
                    onClick={() => void resend()}
                    disabled={resending}
                  >
                    {resending ? 'Sending...' : 'Resend code'}
                  </button>
                )}
              </div>

              <button
                type="button"
                className="btn-ghost w-full"
                onClick={() => {
                  setStep('email');
                  setCode('');
                  setError(null);
                  setNotice(null);
                  setCooldown(0);
                }}
              >
                Use a different email
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
