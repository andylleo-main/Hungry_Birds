import { Icon } from './ui';

export default function Footer() {
  return (
    <footer className="mt-space-xl border-t border-outline-variant bg-surface-container-lowest">
      <div className="mx-auto grid max-w-content gap-space-xl px-margin-mobile py-space-xl md:grid-cols-2 md:px-margin lg:grid-cols-4">
        <div className="flex flex-col gap-space-sm">
          <div className="flex items-center gap-space-sm">
            <img src="/logo.png" alt="" width={32} height={32} className="h-8 w-8" />
            <span className="text-headline-sm text-on-surface">Hungry Birds</span>
          </div>
          <p className="max-w-xs text-body-sm text-on-surface-variant">
            Order ahead from the food stalls around campus, then walk up and collect. No queue, no
            waiting for your food to be made.
          </p>
        </div>

        <div className="flex flex-col gap-space-sm">
          <h3 className="text-label-lg uppercase tracking-wide text-on-surface">How it works</h3>
          <ul className="flex flex-col gap-space-xs text-body-sm text-on-surface-variant">
            <li>1. Sign in with your institute email</li>
            <li>2. Pick a stall and add what you want</li>
            <li>3. Track it live until it's ready</li>
            <li>4. Collect and pay cash at the counter</li>
          </ul>
        </div>

        <div className="flex flex-col gap-space-sm">
          <h3 className="text-label-lg uppercase tracking-wide text-on-surface">Campus only</h3>
          <p className="text-body-sm text-on-surface-variant">
            Sign-in is restricted to <span className="text-on-surface">@bitmesra.ac.in</span>{' '}
            addresses, so only students and staff can order.
          </p>
        </div>

        <div className="flex flex-col gap-space-sm">
          <h3 className="text-label-lg uppercase tracking-wide text-on-surface">Run a stall?</h3>
          <p className="text-body-sm text-on-surface-variant">
            Vendors manage their menu and orders from the Hungry Birds merchant app for Android.
            Apply from the app and an admin will approve you.
          </p>
        </div>
      </div>

      <div className="border-t border-outline-variant">
        <div className="mx-auto flex max-w-content flex-col gap-space-xs px-margin-mobile py-space-md text-body-sm text-on-surface-variant md:flex-row md:items-center md:justify-between md:px-margin">
          <span>© {new Date().getFullYear()} Hungry Birds · BIT Mesra</span>
          <span className="flex items-center gap-space-xs">
            <Icon name="payments" className="text-[18px] text-primary" />
            Cash on pickup only
          </span>
        </div>
      </div>
    </footer>
  );
}
