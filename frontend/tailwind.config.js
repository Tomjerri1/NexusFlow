/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        nexus: {
          bg: "#0f172a",
          panel: "#1e293b",
          border: "#334155",
          text: "#e2e8f0",
          muted: "#94a3b8",
          accent: "#38bdf8",
        },
      },
    },
  },
  plugins: [],
};
