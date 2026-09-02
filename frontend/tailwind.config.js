/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        pitch: {
          DEFAULT: "#0f7a3a",
          dark: "#0b5e2c",
          line: "rgba(255,255,255,0.35)",
        },
      },
    },
  },
  plugins: [],
};
