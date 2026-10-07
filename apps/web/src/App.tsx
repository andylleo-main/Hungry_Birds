import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';
import Header from './components/Header';
import Footer from './components/Footer';
import { EmptyState, PageLoader } from './components/ui';
import { useAuth } from './state/AuthContext';
import Login from './pages/Login';
import Discover from './pages/Discover';
import Stall from './pages/Stall';
import Checkout from './pages/Checkout';
import Orders from './pages/Orders';
import OrderTracking from './pages/OrderTracking';
import Offers from './pages/Offers';
import Profile from './pages/Profile';
import AdminPanel from './pages/admin/AdminPanel';

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      {/* Offset the fixed 80px header. */}
      <main className="flex-1 pt-20">{children}</main>
      <Footer />
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
          title="Admins only"
          message="This account doesn't have admin access. Ask an existing admin to promote it."
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
        <Route path="/checkout" element={<Checkout />} />
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
