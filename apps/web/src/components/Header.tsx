import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { useAuth } from '../state/AuthContext';
import { useCart } from '../state/CartContext';
import { Icon } from './ui';

export default function Header() {
  const { user, isAdmin, signOut } = useAuth();
  const { count } = useCart();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  const navLink = ({ isActive }: { isActive: boolean }) =>
    isActive
      ? 'text-label-lg text-primary font-bold transition-colors'
      : 'text-label-lg text-on-surface-variant hover:text-on-surface transition-colors';

  return (
    <header className="fixed inset-x-0 top-0 z-50 bg-surface-container-lowest shadow-overlay">
      <div className="mx-auto flex h-20 max-w-content items-center justify-between gap-gutter px-margin-mobile md:px-margin">
        <div className="flex shrink-0 items-center gap-gutter">
          <Link to="/" className="flex items-center gap-space-sm">
            <span className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-on-primary">
              <Icon name="lunch_dining" className="text-[22px]" />
            </span>
            <span className="flex flex-col leading-none">
              <span className="text-headline-sm tracking-tight text-on-surface">Hunger Birds</span>
              <span className="text-label-sm uppercase tracking-wide text-primary">
                BIT Mesra Campus
              </span>
            </span>
          </Link>

          {/* The mockup's "Deliver to" selector. This is campus pickup, so it
              states the collection point rather than offering addresses. */}
          <div className="hidden items-center gap-space-xs rounded-full bg-surface-container px-space-md py-space-sm lg:flex">
            <Icon name="storefront" className="text-[20px] text-primary" />
            <span className="flex flex-col">
              <span className="text-label-sm uppercase text-on-surface-variant">Pick up at</span>
              <span className="text-label-md text-on-surface">The stall counter</span>
            </span>
          </div>
        </div>

        <nav className="hidden items-center gap-space-lg xl:flex">
          <NavLink to="/" end className={navLink}>
            Explore
          </NavLink>
          <NavLink to="/orders" className={navLink}>
            Orders
          </NavLink>
          {isAdmin && (
            <NavLink to="/admin" className={navLink}>
              Admin
            </NavLink>
          )}
        </nav>

        <div className="flex shrink-0 items-center gap-space-md">
          <button
            type="button"
            aria-label="Cart"
            onClick={() => navigate('/checkout')}
            className="relative flex items-center justify-center rounded-full bg-surface-container p-space-sm transition-colors hover:bg-surface-container-high"
          >
            <Icon name="shopping_bag" className="text-[24px] text-on-surface" />
            {count > 0 && (
              <span className="absolute -right-1 -top-1 flex h-5 min-w-[20px] items-center justify-center rounded-full bg-primary px-space-xs text-label-sm text-on-primary shadow-card">
                {count}
              </span>
            )}
          </button>

          <div className="relative">
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              className="flex items-center gap-space-sm rounded-full py-space-xs pl-space-xs pr-space-sm transition-colors hover:bg-surface-container"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-tint text-label-md uppercase text-primary">
                {(user?.full_name ?? user?.email ?? '?').charAt(0)}
              </span>
              <Icon name="expand_more" className="hidden text-[18px] text-on-surface-variant sm:block" />
            </button>

            {menuOpen && (
              <>
                {/* Click-away layer, so the menu closes on any outside tap. */}
                <button
                  type="button"
                  aria-hidden
                  tabIndex={-1}
                  className="fixed inset-0 z-10 cursor-default"
                  onClick={() => setMenuOpen(false)}
                />
                <div className="absolute right-0 z-20 mt-space-sm w-60 overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest shadow-sheet">
                  <div className="border-b border-outline-variant px-space-md py-space-sm">
                    <p className="truncate text-label-lg text-on-surface">
                      {user?.full_name ?? 'Campus foodie'}
                    </p>
                    <p className="truncate text-body-sm text-on-surface-variant">{user?.email}</p>
                  </div>
                  <Link
                    to="/profile"
                    onClick={() => setMenuOpen(false)}
                    className="flex items-center gap-space-sm px-space-md py-space-sm text-body-sm text-on-surface-medium hover:bg-surface-container"
                  >
                    <Icon name="person" className="text-[18px]" /> Profile
                  </Link>
                  <Link
                    to="/orders"
                    onClick={() => setMenuOpen(false)}
                    className="flex items-center gap-space-sm px-space-md py-space-sm text-body-sm text-on-surface-medium hover:bg-surface-container"
                  >
                    <Icon name="receipt_long" className="text-[18px]" /> My orders
                  </Link>
                  {isAdmin && (
                    <Link
                      to="/admin"
                      onClick={() => setMenuOpen(false)}
                      className="flex items-center gap-space-sm px-space-md py-space-sm text-body-sm text-on-surface-medium hover:bg-surface-container"
                    >
                      <Icon name="shield_person" className="text-[18px]" /> Admin panel
                    </Link>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      signOut();
                    }}
                    className="flex w-full items-center gap-space-sm border-t border-outline-variant px-space-md py-space-sm text-left text-body-sm text-primary hover:bg-surface-container"
                  >
                    <Icon name="logout" className="text-[18px]" /> Log out
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
