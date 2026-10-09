/**
 * Hungry Birds design tokens: red and white, warm neutrals, no purple.
 *
 * Neutrals lean warm (red channel above blue) on purpose - the project rule is
 * "no purple anywhere", and cool greys drift violet next to a saturated red.
 * Token NAMES are unchanged from the first design so every page keeps working.
 */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#D7263D',
        'primary-hover': '#B81D32',
        'primary-accent': '#FF4D5E',
        'primary-tint': '#FFF0F1',
        'primary-deep': '#8E1324',
        'on-primary': '#FFFFFF',

        'on-surface': '#1C1414',
        'on-surface-medium': '#3A2E2E',
        'on-surface-variant': '#7A6A68',

        surface: '#FFFFFF',
        'surface-container-lowest': '#FFFFFF',
        'surface-container': '#FBF4F3',
        'surface-container-high': '#F3E6E4',
        outline: '#EBDCD9',
        'outline-variant': '#F4EAE8',

        success: '#15803D',
        warning: '#C2410C',
        'warning-tint': '#FFF7ED',
        error: '#B3261E',
      },
      fontFamily: {
        sans: ['"DM Sans"', 'system-ui', 'sans-serif'],
        display: ['"Bricolage Grotesque"', '"DM Sans"', 'sans-serif'],
      },
      fontSize: {
        'display-hero': ['64px', { lineHeight: '64px', fontWeight: '800', letterSpacing: '-0.03em' }],
        'display-hero-mobile': ['40px', { lineHeight: '42px', fontWeight: '800', letterSpacing: '-0.03em' }],
        'headline-lg': ['34px', { lineHeight: '40px', fontWeight: '800', letterSpacing: '-0.02em' }],
        'headline-md': ['24px', { lineHeight: '30px', fontWeight: '700', letterSpacing: '-0.01em' }],
        'headline-sm': ['19px', { lineHeight: '26px', fontWeight: '700' }],
        'title-md': ['17px', { lineHeight: '24px', fontWeight: '700' }],
        'body-lg': ['18px', { lineHeight: '28px', fontWeight: '400' }],
        'body-md': ['16px', { lineHeight: '24px', fontWeight: '400' }],
        'body-sm': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'label-lg': ['15px', { lineHeight: '20px', fontWeight: '600' }],
        'label-md': ['13px', { lineHeight: '18px', fontWeight: '600' }],
        'label-sm': ['11px', { lineHeight: '16px', fontWeight: '700', letterSpacing: '0.04em' }],
      },
      spacing: {
        gutter: '1.5rem',
        'gutter-mobile': '0.75rem',
        margin: '2.5rem',
        'margin-mobile': '1.25rem',
        'space-xs': '0.25rem',
        'space-sm': '0.5rem',
        'space-md': '1rem',
        'space-lg': '1.5rem',
        'space-xl': '3rem',
      },
      borderRadius: {
        DEFAULT: '0.625rem',
        md: '0.875rem',
        lg: '1.125rem',
        xl: '1.75rem',
      },
      boxShadow: {
        card: '0 1px 2px rgba(28, 20, 20, 0.04)',
        'card-hover': '0 14px 32px -12px rgba(215, 38, 61, 0.28)',
        overlay: '0 1px 0 rgba(28, 20, 20, 0.06)',
        sheet: '0 24px 48px -12px rgba(28, 20, 20, 0.22)',
        stamp: '4px 4px 0 0 #1C1414',
      },
      maxWidth: {
        content: '1240px',
      },
      keyframes: {
        rise: {
          from: { opacity: '0', transform: 'translateY(14px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        marquee: {
          from: { transform: 'translateX(0)' },
          to: { transform: 'translateX(-50%)' },
        },
      },
      animation: {
        rise: 'rise 0.55s cubic-bezier(0.2, 0.7, 0.2, 1) both',
        marquee: 'marquee 28s linear infinite',
      },
    },
  },
  plugins: [],
};
