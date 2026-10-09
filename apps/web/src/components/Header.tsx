import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { useAuth } from '../state/AuthContext';
import { useCart } from '../state/CartContext';
import { Icon } from './ui';

const NAV = [
  { to: '/', label: 'Stalls', icon: 'storefront', end: true },
  { to: '/orders', label: 'My orders', icon: 'receipt_long', end: false },
  { to: '/offers', label: 'Offers & cashback', icon: 'redeem', end: false },
];

function MenuLink({ to, icon, label, onClick }: { to: string; icon: string; label: string; onClick: () => void }) {
  return (
    <Link
      to={to}
      onClick={onClick}
      data-testid={`account-menu-${label.toLowerCase().replace(/[^a-z]+/g, '-')}`}
      className="flex items-center gap-space-sm px-space-md py-[10px] text-body-sm text-on-surface-medium transition-colors hover:bg-primary-tint hover:text-primary"
    >
      <Icon name={icon} className="text-[18px]" /> {label}
    </Link>
  );
}

export default function Header() {
  const { user, isAdmin, signOut } = useAuth();
  const { count } = useCart();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const close = () => setMenuOpen(false);

  const navLink = ({ isActive }: { isActive: boolean }) =>
    `relative rounded-full px-space-md py-space-sm text-label-lg transition-colors duration-200 ${
      isActive ? 'bg-primary-tint text-primary' : 'text-on-surface-medium hover:text-primary'
    }`;

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-outline bg-white/90 backdrop-blur-xl">
      <div className="mx-auto flex h-20 max-w-content items-center justify-between gap-gutter px-margin-mobile md:px-margin">
        <Link to="/" data-testid="header-logo-link" className="group flex shrink-0 items-center gap-space-sm">
          <span className="flex h-11 w-11 items-center justify-center rounded-md bg-primary transition-transform duration-300 group-hover:-rotate-6">
            <img src="/logo.png" alt="" width={34} height={34} className="h-[34px] w-[34px] rounded-sm bg-white/90 p-[2px]" />
          </span>
          <span className="flex flex-col leading-none">
            <span className="font-display text-[22px] font-extrabold tracking-tight text-on-surface">
              Hungry Birds
            </span>
            <span className="mt-[3px] text-label-sm uppercase tracking-[0.18em] text-primary">BIT Mesra</span>
          </span>
        </Link>

        <nav className="hidden items-center gap-space-xs md:flex" data-testid="header-nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={navLink} data-testid={`nav-${n.icon}`}>
              {n.label}
            </NavLink>
          ))}
          {isAdmin && (
            <NavLink to="/admin" className={navLink} data-testid="nav-admin">
              Admin
            </NavLink>
          )}
        </nav>

        <div className="flex shrink-0 items-center gap-space-sm">
          <button
            type="button"
            aria-label="Cart"
            data-testid="header-cart-button"
            onClick={() => navigate('/checkout')}
            className="relative flex h-11 items-center gap-space-xs rounded-full bg-on-surface px-space-md text-white transition-[background-color,transform] duration-200 hover:bg-primary active:scale-95"
          >
            <Icon name="shopping_bag" className="text-[20px]" />
            <span className="hidden text-label-md sm:inline">Cart</span>
            {count > 0 && (
              <span
                data-testid="header-cart-count"
                className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-primary px-[6px] text-label-sm text-white"
              >
                {count}
              </span>
            )}
          </button>

          <div className="relative">
            <button
              type="button"
              data-testid="header-account-button"
              onClick={() => setMenuOpen((open) => !open)}
              className="flex h-11 items-center gap-space-xs rounded-full border border-outline pl-[5px] pr-space-sm transition-colors hover:border-primary/40"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-label-md uppercase text-white">
                {(user?.full_name ?? user?.email ?? '?').charAt(0)}
              </span>
              <Icon name="expand_more" className="text-[18px] text-on-surface-variant" />
            </button>

            {menuOpen && (
              <>
                <button
                  type="button"
                  aria-hidden
                  tabIndex={-1}
                  className="fixed inset-0 z-10 cursor-default"
                  onClick={close}
                />
                <div
                  data-testid="account-menu"
                  className="absolute right-0 z-20 mt-space-sm w-64 animate-rise overflow-hidden rounded-lg border border-outline bg-white shadow-sheet"
                >
                  <div className="bg-primary px-space-md py-space-md text-white">
                    <p className="truncate text-label-lg">{user?.full_name ?? 'Hello there'}</p>
                    <p className="truncate text-body-sm text-white/80">{user?.email}</p>
                  </div>
                  <div className="py-space-xs">
                    <MenuLink to="/profile" icon="person" label="Profile" onClick={close} />
                    {/* The nav row is hidden on phones, so the menu carries it there. */}
                    <div className="md:hidden">
                      {NAV.map((n) => (
                        <MenuLink key={n.to} to={n.to} icon={n.icon} label={n.label} onClick={close} />
                      ))}
                    </div>
                    {isAdmin && <MenuLink to="/admin" icon="shield_person" label="Admin panel" onClick={close} />}
                  </div>
                  <button
                    type="button"
                    data-testid="account-menu-logout"
                    onClick={() => {
                      close();
                      void signOut();
                    }}
                    className="flex w-full items-center gap-space-sm border-t border-outline px-space-md py-[12px] text-left text-label-md text-primary transition-colors hover:bg-primary-tint"
                  >
                    <Icon name="logout" className="text-[18px]" /> Sign out
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
