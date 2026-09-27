import { useState } from 'react';
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
  const [error, setError] = useState<string | null>(null);

  async function sendCode(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setDebugCode(await requestOtp(email.trim()));
      setStep('code');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send the code. Try again.');
    } finally {
      setBusy(false);
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

              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? <Spinner /> : 'Verify & continue'}
              </button>

              <button
                type="button"
                className="btn-ghost w-full"
                onClick={() => {
                  setStep('email');
                  setCode('');
                  setError(null);
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
