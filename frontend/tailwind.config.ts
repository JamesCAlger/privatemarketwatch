import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: '#0F1B2D',
          50: '#1A2C47',
          100: '#162338',
          200: '#1B2A4A',
          light: '#1B2A4A',
          800: '#0C1520',
          900: '#080E16',
        },
        teal: {
          DEFAULT: '#2A9D8F',
          light: '#3DB8A9',
          dark: '#228176',
        },
        gold: {
          DEFAULT: '#C9A84C',
          light: '#D4BC72',
          dark: '#A88B3A',
        },
        red: {
          DEFAULT: '#E63946',
        },
        surface: {
          DEFAULT: '#F8F9FA',
          muted: '#E9ECEF',
        },
        page: {
          DEFAULT: '#F0F2F5',
        },
        muted: {
          DEFAULT: '#6C757D',
        },
      },
      fontFamily: {
        sans: ['Libre Franklin', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        'display-lg': ['3.5rem', { lineHeight: '1.1', fontWeight: '700', letterSpacing: '-0.02em' }],
        'display-sm': ['2.25rem', { lineHeight: '1.15', fontWeight: '700', letterSpacing: '-0.01em' }],
        'stat-lg': ['2.5rem', { lineHeight: '1', fontWeight: '700', letterSpacing: '-0.02em' }],
        'stat-sm': ['1.5rem', { lineHeight: '1.2', fontWeight: '700' }],
      },
      boxShadow: {
        card: '0 1px 3px rgba(15, 27, 45, 0.08), 0 1px 2px rgba(15, 27, 45, 0.04)',
        'card-hover': '0 4px 12px rgba(15, 27, 45, 0.12), 0 2px 4px rgba(15, 27, 45, 0.06)',
        panel: '0 8px 24px rgba(15, 27, 45, 0.10), 0 2px 8px rgba(15, 27, 45, 0.05)',
      },
    },
  },
  plugins: [],
};

export default config;
