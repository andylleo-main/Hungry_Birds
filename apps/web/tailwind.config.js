/**
 * Design tokens from the Stitch "Crisp Culinary" spec.
 *
 * The exported tailwind.config that shipped with those mockups used
 * violet-tinted neutrals (surface #fbf8fc, surface-container #f0edf1,
 * surface-variant #e4e1e6 - every one has blue above red), which contradicts
 * that same spec's stated rule: "Zero Purple/Violet Spectrum ... neutral
 * undertones must remain strictly balanced zinc or neutral charcoal."
 *
 * We follow the written rule, not the exported values: zinc neutrals plus the
 * culinary red. Token NAMES are kept identical to the export so markup from
 * the mockups ports across unchanged.
 */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Culinary red
        primary: '#E53935',
        'primary-hover': '#D32F2F',
        'primary-accent': '#FF5252',
        'primary-tint': '#FFEBEE',
        'on-primary': '#FFFFFF',

        // Ink (zinc)
        'on-surface': '#18181B',
        'on-surface-medium': '#27272A',
        'on-surface-variant': '#71717A',

        // Surfaces (zinc)
        surface: '#FAFAFA',
        'surface-container-lowest': '#FFFFFF',
        'surface-container': '#F4F4F5',
        'surface-container-high': '#E4E4E7',
        outline: '#E4E4E7',
        'outline-variant': '#F4F4F5',

        success: '#16A34A',
        warning: '#D97706',
        // Amber 50. For a notice that has to be unmissable without reading as a
        // failure - the test-payments banner is a statement about the
        // deployment, not an error in the order.
        'warning-tint': '#FFFBEB',
        error: '#BA1A1A',
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        'display-hero': ['48px', { lineHeight: '56px', fontWeight: '800' }],
        'display-hero-mobile': ['32px', { lineHeight: '40px', fontWeight: '800' }],
        'headline-lg': ['32px', { lineHeight: '40px', fontWeight: '700' }],
        'headline-md': ['24px', { lineHeight: '32px', fontWeight: '700' }],
        'headline-sm': ['20px', { lineHeight: '28px', fontWeight: '600' }],
        'body-lg': ['18px', { lineHeight: '28px', fontWeight: '400' }],
        'body-md': ['16px', { lineHeight: '24px', fontWeight: '400' }],
        'body-sm': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'label-lg': ['15px', { lineHeight: '20px', fontWeight: '600' }],
        'label-md': ['13px', { lineHeight: '18px', fontWeight: '600' }],
        'label-sm': ['11px', { lineHeight: '16px', fontWeight: '700' }],
      },
      spacing: {
        gutter: '1.5rem',
        'gutter-mobile': '0.75rem',
        margin: '2rem',
        'margin-mobile': '1rem',
        'space-xs': '0.25rem',
        'space-sm': '0.5rem',
        'space-md': '1rem',
        'space-lg': '1.5rem',
        'space-xl': '2.5rem',
      },
      borderRadius: {
        DEFAULT: '0.5rem',
        md: '0.75rem',
        lg: '1rem',
        xl: '1.5rem',
      },
      boxShadow: {
        // Neutral charcoal alphas only - the spec forbids tinted shadows.
        card: '0px 2px 8px rgba(24, 24, 27, 0.04)',
        'card-hover': '0px 8px 24px rgba(24, 24, 27, 0.08)',
        overlay: '0px 4px 16px rgba(24, 24, 27, 0.06)',
        sheet: '0px 20px 40px rgba(24, 24, 27, 0.12)',
      },
      maxWidth: {
        content: '1200px',
      },
    },
  },
  plugins: [],
};
