import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg:        '#fbfaf7',
        surface:   '#ffffff',
        ink:       '#0b1a2c',
        ink2:      '#3b4a5b',
        ink3:      '#6b7280',
        ink4:      '#9aa1ab',
        rule:      '#dfe3ea',
        rule2:     '#eef0f4',
        rule3:     '#f5f7fa',
        navy:      '#0b1a2c',
        navyDeep:  '#06121f',
        navyMid:   '#16273c',
        accent:    '#c7a14a',
        accent2:   '#e2bb66',
        accentSoft:'#f3e6c0',
        teal:      '#2A9D8F',
        tealLight: '#3DB8A9',
        tealDark:  '#1E7A6E',
        green:     '#1f7a4a',
        red:       '#a8362b',
        amber:     '#b07827',
      },
      boxShadow: {
        card:  '0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03)',
        panel: '0 4px 12px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)',
      },
      fontSize: {
        'display-sm': ['1.875rem', { lineHeight: '1.2', fontWeight: '600' }],
        'display-md': ['2.5rem',   { lineHeight: '1.15', fontWeight: '600' }],
        'display-lg': ['3rem',     { lineHeight: '1.1', fontWeight: '600' }],
      },
      fontFamily: {
        display: ['var(--font-display)', 'Georgia', 'serif'],
        body:    ['var(--font-body)', 'system-ui', 'sans-serif'],
        mono:    ['var(--font-mono)', 'ui-monospace', 'monospace'],
      },
      borderColor: {
        DEFAULT: '#dfe3ea',
      },
    },
  },
  plugins: [],
};

export default config;
