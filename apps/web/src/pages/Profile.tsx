import { useEffect, useState } from 'react';
import { ApiError, api } from '../lib/api';
import type { UserSession } from '../lib/api';
import { displayPhone, validateIndianMobile } from '../lib/format';
import { Icon, Spinner } from '../components/ui';
import { useAuth } from '../state/AuthContext';

/** Short, human description of a browser from its user-agent string.
 *  Full UA strings are unreadable, and the only question being answered here is
 *  "do I recognise this device?" */
function describeDevice(ua: string | null): string {
  if (!ua) return 'Unknown device';
  const browser =
    /Edg\//.test(ua) ? 'Edge'
    : /OPR\//.test(ua) ? 'Opera'
    : /Chrome\//.test(ua) ? 'Chrome'
    : /Firefox\//.test(ua) ? 'Firefox'
    : /Safari\//.test(ua) ? 'Safari'
    : 'Browser';
  const os =
    /Android/.test(ua) ? 'Android'
    : /iPhone|iPad|iOS/.test(ua) ? 'iOS'
    : /Windows/.test(ua) ? 'Windows'
    : /Mac OS X/.test(ua) ? 'macOS'
    : /Linux/.test(ua) ? 'Linux'
    : '';
  return os ? `${browser} on ${os}` : browser;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 2) return 'just now';
  if (mins < 60) return `${mins} minutes ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
  const days = Math.round(hours / 24);
  return `${days} ${days === 1 ? 'day' : 'days'} ago`;
}

function SignedInDevices() {
  const [sessions, setSessions] = useState<UserSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    try {
      setSessions(await api.listSessions());
    } catch {
      setError("Couldn't load your devices.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function end(id: string) {
    setBusyId(id);
    try {
      await api.endSession(id);
      setSessions((current) => (current ?? []).filter((s) => s.id !== id));
    } catch {
      setError("Couldn't sign that device out.");
    } finally {
      setBusyId(null);
    }
  }

  if (error) return <p className="text-body-sm text-primary">{error}</p>;
  if (!sessions) return <Spinner className="text-primary" />;

  return (
    <div className="flex flex-col gap-space-sm">
      <ul className="flex flex-col gap-space-xs">
        {sessions.map((session) => (
          <li
            key={session.id}
            className="flex flex-wrap items-center gap-space-sm rounded-md bg-surface-container px-space-md py-space-sm"
          >
            <Icon name="devices" className="text-[20px] text-on-surface-variant" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-label-md text-on-surface">
                {describeDevice(session.user_agent)}
              </p>
              <p className="text-body-sm text-on-surface-variant">
                Last used {relativeTime(session.last_used_at)}
              </p>
            </div>
            <button
              type="button"
              className="text-label-md text-primary disabled:opacity-60"
              onClick={() => void end(session.id)}
              disabled={busyId === session.id}
            >
              {busyId === session.id ? 'Ending...' : 'Sign out'}
            </button>
          </li>
        ))}
      </ul>

      {sessions.length > 1 && (
        <button
          type="button"
          className="self-start text-label-md text-primary"
          onClick={async () => {
            await api.endAllSessions();
            // Revoking everything includes this device, so the only honest
            // next step is back to the login page.
            window.location.href = '/';
          }}
        >
          Sign out of all devices
        </button>
      )}
    </div>
  );
}

export default function Profile() {
  const { user, updateProfile, signOut } = useAuth();
  const [name, setName] = useState(user?.full_name ?? '');
  const [phone, setPhone] = useState(user?.phone ?? '');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const phoneError = phone.trim() ? validateIndianMobile(phone) : null;
    if (phoneError) {
      setError(phoneError);
      return;
    }

    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await updateProfile({ full_name: name.trim(), phone: phone.trim() });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-margin-mobile py-space-lg md:px-margin md:py-space-xl">
      <h1 className="mb-space-lg text-headline-lg text-on-surface">Profile</h1>

      <div className="card mb-space-md flex items-center gap-space-md p-space-md">
        <span className="flex h-14 w-14 items-center justify-center rounded-full bg-primary-tint text-headline-md uppercase text-primary">
          {(user?.full_name ?? user?.email ?? '?').charAt(0)}
        </span>
        <div className="min-w-0">
          <p className="truncate text-headline-sm text-on-surface">
            {user?.full_name ?? 'Campus foodie'}
          </p>
          <p className="truncate text-body-sm text-on-surface-variant">{user?.email}</p>
          {user?.role !== 'customer' && (
            <span className="badge mt-space-xs capitalize">{user?.role}</span>
          )}
        </div>
      </div>

      <form onSubmit={save} className="card flex flex-col gap-space-md p-space-md md:p-space-lg">
        <h2 className="text-headline-sm text-on-surface">Contact details</h2>
        <p className="-mt-space-sm text-body-sm text-on-surface-variant">
          Stalls use these to reach you about a ready order. A phone number is required before you
          can place one.
        </p>

        <label className="flex flex-col gap-space-xs">
          <span className="text-label-md text-on-surface-medium">Your name</span>
          <input
            className="field"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="So they know who to call for"
            autoComplete="name"
          />
        </label>

        <label className="flex flex-col gap-space-xs">
          <span className="text-label-md text-on-surface-medium">Phone number</span>
          <input
            className="field"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="98765 43210"
            inputMode="tel"
            autoComplete="tel"
          />
          {user?.phone && (
            <span className="text-label-md text-on-surface-variant">
              Saved as +91 {displayPhone(user.phone)}
            </span>
          )}
        </label>

        {error && <p className="text-body-sm text-primary">{error}</p>}
        {saved && !error && (
          <p className="flex items-center gap-space-xs text-body-sm text-success">
            <Icon name="check_circle" className="text-[18px]" />
            Saved.
          </p>
        )}

        <button type="submit" className="btn-primary w-full sm:w-fit" disabled={busy}>
          {busy ? <Spinner /> : 'Save changes'}
        </button>
      </form>

      <div className="card mt-space-md flex items-center gap-space-md p-space-md">
        <Icon name="lock" className="text-[24px] text-primary" />
        <p className="text-body-sm text-on-surface-variant">
          Orders are paid online through Razorpay. We never see or store your card
          details, and a stall that declines your order refunds it automatically.
        </p>
      </div>

      <section className="card mt-space-md flex flex-col gap-space-md p-space-md">
        <div className="flex flex-col gap-1">
          <h2 className="text-title-md text-on-surface">Where you're signed in</h2>
          <p className="text-body-sm text-on-surface-variant">
            Signing a device out here ends its session immediately, even if someone
            else has it.
          </p>
        </div>
        <SignedInDevices />
      </section>

      <button type="button" onClick={() => void signOut()} className="btn-secondary mt-space-lg w-full sm:w-fit">
        <Icon name="logout" className="text-[18px]" />
        Log out
      </button>
    </div>
  );
}
