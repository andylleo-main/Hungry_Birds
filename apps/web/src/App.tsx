import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useLayoutEffect } from 'react';
import type { ReactNode } from 'react';
import Header from './components/Header';
import Footer from './components/Footer';
import Signature from './components/Signature';
import { EmptyState, PageLoader } from './components/ui';
import { useAuth } from './state/AuthContext';
import Login from './pages/Login';
import Discover from './pages/Discover';
import Stall from './pages/Stall';
import CheckoutLayout from './pages/checkout/Layout';
import Review from './pages/checkout/Review';
import Payment from './pages/checkout/Payment';
import Orders from './pages/Orders';
import OrderTracking from './pages/OrderTracking';
import Offers from './pages/Offers';
import Profile from './pages/Profile';
import AdminPanel from './pages/admin/AdminPanel';

/** Every navigation lands at the top of the new page, not where the old one was. */
function ScrollToTop() {
  const { pathname, search } = useLocation();
  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [pathname, search]);
  return null;
}

function Shell({ children }: { children: ReactNode }) {
  // The four-column footer is the landing page's, and only its. Under a
  // checkout, an order being tracked or the admin panel it is a wall of
  // marketing beneath the thing somebody came to do - so every other page gets
  // the signature alone.
  const onLanding = useLocation().pathname === '/';

  return (
    <div className="flex min-h-screen flex-col">
      <ScrollToTop />
      <Header />
      {/* Offset the fixed 80px header. */}
      <main className="flex-1 pt-20">{children}</main>
      {onLanding && <Footer />}
      <Signature />
    </div>
  );
}

/** Admin routes live inside the customer app, gated on role. */
function AdminOnly({ children }: { children: ReactNode }) {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-content px-margin-mobile py-space-xl md:px-margin">
        <EmptyState
          icon="lock"
          title="This page is for admins"
          message="Your account can't open the admin panel. If you should have access, ask an existing admin to add you."
        />
      </div>
    );
  }
  return <>{children}</>;
}

export default function App() {
  const { status } = useAuth();

  if (status === 'loading') return <PageLoader />;
  if (status === 'signedOut') return <Login />;

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Discover />} />
        <Route path="/stall/:vendorId" element={<Stall />} />
        {/* A layout route, so the checkout's state mounts once and survives
            the move between its two pages. */}
        <Route path="/checkout" element={<CheckoutLayout />}>
          <Route index element={<Review />} />
          <Route path="payment" element={<Payment />} />
        </Route>
        <Route path="/orders" element={<Orders />} />
        <Route path="/orders/:orderId" element={<OrderTracking />} />
        <Route path="/offers" element={<Offers />} />
        <Route path="/profile" element={<Profile />} />
        <Route
          path="/admin"
          element={
            <AdminOnly>
              <AdminPanel />
            </AdminOnly>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
