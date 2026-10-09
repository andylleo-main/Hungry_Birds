import { Icon } from './ui';

const STEPS = [
  'Sign in with your BIT Mesra email',
  'Pick a stall and fill your cart',
  'Pay online, or on delivery to your hostel',
  'Watch it cook live, then eat in or get it delivered',
];

export default function Footer() {
  return (
    <footer className="mt-space-xl bg-on-surface text-white" data-testid="landing-footer">
      <div className="mx-auto grid max-w-content gap-space-xl px-margin-mobile py-space-xl md:grid-cols-2 md:px-margin lg:grid-cols-[1.3fr_1fr_1fr_1fr]">
        <div className="flex flex-col gap-space-md">
          <div className="flex items-center gap-space-sm">
            <span className="flex h-10 w-10 items-center justify-center rounded-md bg-primary">
              <img src="/logo.png" alt="" width={30} height={30} className="h-[30px] w-[30px] rounded-sm bg-white/90 p-[2px]" />
            </span>
            <span className="font-display text-headline-sm">Hungry Birds</span>
          </div>
          <p className="max-w-xs text-body-sm text-white/65">
            Every food stall at BIT Mesra, in one place. Order ahead, skip the queue and eat while
            it's still hot.
          </p>
        </div>

        <div className="flex flex-col gap-space-sm">
          <h3 className="text-label-sm uppercase tracking-[0.14em] text-primary-accent">How it works</h3>
          <ol className="flex flex-col gap-space-sm text-body-sm text-white/75">
            {STEPS.map((s, i) => (
              <li key={s} className="flex gap-space-sm">
                <span className="font-display font-bold text-white">0{i + 1}</span>
                {s}
              </li>
            ))}
          </ol>
        </div>

        <div className="flex flex-col gap-space-sm">
          <h3 className="text-label-sm uppercase tracking-[0.14em] text-primary-accent">Campus only</h3>
          <p className="text-body-sm text-white/75">
            Only <span className="text-white">@bitmesra.ac.in</span> accounts can sign in, so every
            order comes from someone on campus.
          </p>
        </div>

        <div className="flex flex-col gap-space-sm">
          <h3 className="text-label-sm uppercase tracking-[0.14em] text-primary-accent">Own a stall?</h3>
          <p className="text-body-sm text-white/75">
            Stall owners run their menu and orders from the Hungry Birds merchant app on Android. Sign
            up there and we'll approve your stall.
          </p>
        </div>
      </div>

      <div className="border-t border-white/10">
        <div className="mx-auto flex max-w-content flex-col gap-space-xs px-margin-mobile py-space-md text-body-sm text-white/55 md:flex-row md:items-center md:justify-between md:px-margin">
          <span>© {new Date().getFullYear()} Hungry Birds · BIT Mesra</span>
          <span className="flex items-center gap-space-xs">
            <Icon name="lock" className="text-[18px] text-primary-accent" />
            Payments secured by Razorpay
          </span>
        </div>
      </div>
    </footer>
  );
}
