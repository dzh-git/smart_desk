/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        techBg: '#0b1016',
        techSurface: '#0f1721',
        techCard: '#141e2a',
        techCardSoft: '#1a2937',
        techBorder: '#29394a',
        techText: '#edf5f8',
        techMuted: '#a1b3bf',
        techCyan: '#67e5d2',
        techBlue: '#91baf2',
        techGreen: '#69d7ac',
        techAmber: '#f4bf6b',
        techRose: '#ff879b',
      },
      boxShadow: {
        'cyan-glow': '0 0 20px rgba(103, 229, 210, 0.16)',
        'cyan-glow-strong': '0 0 32px rgba(103, 229, 210, 0.24)',
        'card-glow': '0 16px 36px rgba(0, 0, 0, 0.20)',
      },
      backgroundImage: {
        'tech-radial':
          'radial-gradient(ellipse at top left, rgba(103, 229, 210, 0.08), transparent 46%), radial-gradient(ellipse at bottom right, rgba(145, 186, 242, 0.06), transparent 45%)',
      },
    },
  },
  plugins: [],
};
