/** The one line at the bottom of every page, rendered by `Shell`. */
export default function Signature() {
  return (
    <div className="border-t border-outline bg-white" data-testid="page-signature">
      <p className="mx-auto max-w-content px-margin-mobile py-space-md text-center text-label-md text-on-surface-variant md:px-margin">
        manifested into reality by{' '}
        <span className="font-display font-extrabold tracking-[0.12em] text-primary">ARNAV</span>
      </p>
    </div>
  );
}
