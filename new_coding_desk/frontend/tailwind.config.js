/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        techBg: '#0a0911',
        techSurface: '#100e1a',
        techCard: '#171522',
        techCardSoft: '#211d30',
        techBorder: '#382f49',
        techText: '#f3effd',
        techMuted: '#b4adca',
        techCyan: 'rgb(var(--desk-accent, 195 170 255) / <alpha-value>)',
        techBlue: '#91baf2',
        techGreen: '#69d7ac',
        techAmber: '#f4bf6b',
        techRose: '#ff879b',
      },
      boxShadow: {
        'cyan-glow': '0 0 20px rgb(var(--desk-accent, 195 170 255) / 0.16)',
        'cyan-glow-strong': '0 0 32px rgb(var(--desk-accent, 195 170 255) / 0.24)',
        'card-glow': '0 16px 36px rgba(0, 0, 0, 0.20)',
      },
      backgroundImage: {
        'tech-radial':
          'radial-gradient(ellipse at top left, rgb(var(--desk-accent, 195 170 255) / 0.08), transparent 46%), radial-gradient(ellipse at bottom right, rgba(145, 186, 242, 0.06), transparent 45%)',
      },
    },
  },
  plugins: [],
};
