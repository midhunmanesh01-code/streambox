/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        stage: {
          950: '#08080A',
          900: '#0D0D10',
          850: '#131316',
          800: '#18181C',
          700: '#232327',
          600: '#323238',
          500: '#4A4A52',
        },
        ink: {
          100: '#F3F1EC',
          300: '#C9C6BF',
          500: '#8B8A8C',
        },
        brass: {
          200: '#E8D5A8',
          300: '#D8BD82',
          400: '#C9A66B',
          500: '#B0894D',
          600: '#8A6F3E',
          700: '#5F4C2C',
        },
        signal: {
          red: '#E5484D',
          green: '#4ADE80',
        },
      },
      fontFamily: {
        display: ['"Newsreader"', 'Georgia', 'serif'],
        body: ['"Inter"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      letterSpacing: {
        marquee: '0.32em',
      },
      boxShadow: {
        stage: '0 40px 100px -30px rgba(0,0,0,0.7)',
        glow: '0 0 0 1px rgba(201,166,107,0.25), 0 20px 60px -20px rgba(201,166,107,0.15)',
      },
      keyframes: {
        grain: {
          '0%, 100%': { transform: 'translate(0,0)' },
          '10%': { transform: 'translate(-1%,-2%)' },
          '30%': { transform: 'translate(2%,1%)' },
          '50%': { transform: 'translate(-2%,2%)' },
          '70%': { transform: 'translate(1%,-1%)' },
          '90%': { transform: 'translate(-1%,1%)' },
        },
        rise: {
          '0%': { opacity: 0, transform: 'translateY(10px)' },
          '100%': { opacity: 1, transform: 'translateY(0)' },
        },
      },
      animation: {
        grain: 'grain 8s steps(10) infinite',
        rise: 'rise 0.5s ease-out both',
      },
    },
  },
  plugins: [],
}
