/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        techBg: '#050b14',
        techSurface: '#07111f',
        techCard: '#0b132b',
        techCardSoft: '#111c33',
        techBorder: '#1e2a44',
        techText: '#e5edf7',
        techMuted: '#7f8ea3',
        techCyan: '#00eaff',
        techBlue: '#38bdf8',
        techGreen: '#10b981',
        techAmber: '#f59e0b',
        techRose: '#f43f5e',
      },
      boxShadow: {
        'cyan-glow': '0 0 18px rgba(0, 234, 255, 0.32)',
        'cyan-glow-strong': '0 0 32px rgba(0, 234, 255, 0.45)',
        'card-glow': '0 18px 50px rgba(0, 0, 0, 0.35)',
      },
      backgroundImage: {
        'tech-radial':
          'radial-gradient(circle at top left, rgba(0,234,255,0.12), transparent 32%), radial-gradient(circle at bottom right, rgba(56,189,248,0.08), transparent 36%)',
      },
    },
  },
  plugins: [],
};
