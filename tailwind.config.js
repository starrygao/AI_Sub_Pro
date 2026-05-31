module.exports = {
  content: [
    './app/static/index.html',
    './app/static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
        },
        accent: {
          DEFAULT: '#0f766e',
          light: '#14b8a6',
          dark: '#115e59',
          glow: 'rgba(15,118,110,0.16)',
        },
        success: {
          DEFAULT: '#16a34a',
          light: '#22c55e',
        },
        warn: {
          DEFAULT: '#d97706',
          light: '#f59e0b',
        },
        danger: {
          DEFAULT: '#dc2626',
          light: '#ef4444',
        },
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'SF Pro Display',
          'SF Pro Text',
          'Helvetica Neue',
          'Helvetica',
          'Arial',
          'PingFang SC',
          'sans-serif',
        ],
      },
      borderRadius: {
        '2xl': '16px',
        '3xl': '20px',
        '4xl': '24px',
      },
      backdropBlur: {
        xs: '8px',
      },
    },
  },
  plugins: [],
};
