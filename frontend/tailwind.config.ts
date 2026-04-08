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
          light: '#1B2A4A',
        },
        teal: {
          DEFAULT: '#2A9D8F',
          light: '#3DB8A9',
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
    },
  },
  plugins: [],
};

export default config;
