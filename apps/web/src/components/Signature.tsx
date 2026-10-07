/**
 * The one line that appears at the bottom of every page.
 *
 * Separate from `Footer`, which is the four-column block and belongs to the
 * landing page alone: on a checkout or a tracking screen it is a wall of
 * marketing under the thing somebody is actually doing. This is what "every page
 * has a footer" means here - a signature, not a sitemap.
 *
 * Rendered by `Shell`, so no page carries it itself and no page can forget it.
 */
export default function Signature() {
  return (
    <div className="border-t border-outline-variant bg-surface-container-lowest">
      <p className="mx-auto max-w-content px-margin-mobile py-space-md text-center text-label-md text-on-surface-variant md:px-margin">
        manifested into reality by{' '}
        <span className="tracking-wide text-on-surface">ARNAV</span>
      </p>
    </div>
  );
}
