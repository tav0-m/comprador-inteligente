/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#e8eaf6',
          100: '#c5cae9',
          500: '#3949ab',
          600: '#1565c0',
          700: '#0d47a1',
          900: '#1a237e',
        },
        success: {
          50:  '#e8f5e9',
          600: '#2e7d32',
          700: '#1b5e20',
        },
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
