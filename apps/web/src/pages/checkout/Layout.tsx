import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { EmptyState, Icon } from '../../components/ui';
import { useCart } from '../../state/CartContext';
import { CheckoutProvider, useCheckout } from '../../state/CheckoutContext';

/** Which of the two pages we are on, and what to call it. */
function useStage() {
  const paying = useLocation().pathname.endsWith('/payment');
  return {
    paying,
    index: paying ? 2 : 1,
    title: paying ? 'Payment' : 'Your order',
  };
}

function Head() {
  const navigate = useNavigate();
  const { paying, index, title } = useStage();
  const { mockPayments } = useCheckout();

  return (
    <>
      <div className="mb-space-lg flex items-center gap-space-md">
        <button
          type="button"
          // Back to the review page rather than out of the checkout, because
          // that is the step behind this one. Browser history would often do
          // the same thing, but not after a redirect or a reload.
          onClick={() => (paying ? navigate('/checkout') : navigate(-1))}
          aria-label={paying ? 'Back to your order' : 'Go back'}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-container transition-colors hover:bg-surface-container-high"
        >
          <Icon name="arrow_back" className="text-[20px]" />
        </button>
        <div>
          <p className="text-label-sm uppercase tracking-wide text-primary">
            Step {index} of 2
          </p>
          <h1 className="text-headline-lg text-on-surface">{title}</h1>
        </div>
      </div>

      {mockPayments && (
        <div
          role="status"
          className="mb-space-lg flex items-start gap-space-sm rounded-lg border border-warning bg-warning-tint p-space-md"
        >
          <Icon name="science" className="mt-0.5 text-[20px] text-warning" aria-hidden="true" />
          <div className="text-body-sm text-on-surface">
            <p className="text-label-lg">Test payments are on</p>
            <p>
              This order will be marked as paid without charging anything. The stall
              will see it and can cook it, so don&apos;t place one you don&apos;t want made.
            </p>
          </div>
        </div>
      )}
    </>
  );
}

/**
 * Everything both checkout pages share: the state, the heading, the guard.
 *
 * A layout route rather than a component each page imports, so the provider
 * mounts once and survives the move between them. That is the whole reason the
 * split needed a context at all - local state would have dropped the customer's
 * answers on navigation.
 */
export default function CheckoutLayout() {
  const { isEmpty, vendor } = useCart();

  // Checked here rather than in each page, and before the provider: there is
  // nothing to set up for a cart that does not exist, and both pages would
  // otherwise need the same early return.
  if (isEmpty || !vendor) {
    return (
      <div className="mx-auto max-w-content px-margin-mobile py-space-xl md:px-margin">
        <EmptyState
          icon="shopping_bag"
          title="Your order is empty"
          message="Pick a stall and add a few dishes, then come back here to place the order."
          action={
            <Link to="/" className="btn-primary mt-space-sm">
              Browse stalls
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <CheckoutProvider>
      <div className="mx-auto max-w-content px-margin-mobile py-space-lg md:px-margin md:py-space-xl">
        <Head />
        <Outlet />
      </div>
    </CheckoutProvider>
  );
}
