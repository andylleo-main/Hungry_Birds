import { useState } from 'react';
import { ApiError } from '../lib/api';
import { displayPhone, validateIndianMobile } from '../lib/format';
import { Icon, Spinner } from '../components/ui';
import { useAuth } from '../state/AuthContext';

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
        <Icon name="payments" className="text-[24px] text-primary" />
        <p className="text-body-sm text-on-surface-variant">
          Every order is cash on pickup. Nothing is charged online, ever.
        </p>
      </div>

      <button type="button" onClick={signOut} className="btn-secondary mt-space-lg w-full sm:w-fit">
        <Icon name="logout" className="text-[18px]" />
        Log out
      </button>
    </div>
  );
}
