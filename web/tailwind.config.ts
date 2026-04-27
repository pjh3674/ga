import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          0: "#0a0a0b",
          1: "#111113",
          2: "#17171a",
          3: "#1e1e22",
        },
        ink: {
          0: "#f5f4f0",
          1: "#d8d6d0",
          2: "#a8a59f",
          3: "#7a776f",
        },
        agent: {
          pro: "#97C459",
          con: "#E24B4A",
          judge: "#EF9F27",
          fact: "#378ADD",
          crowd: "#7F77DD",
        },
        brand: {
          from: "#7F77DD",
          to: "#534AB7",
        },
      },
      borderColor: {
        subtle: "rgba(255,255,255,0.06)",
        default: "rgba(255,255,255,0.10)",
        strong: "rgba(255,255,255,0.18)",
      },
      borderRadius: { sm: "6px", md: "10px", lg: "14px", xl: "20px" },
      fontFamily: {
        sans: [
          "Pretendard Variable",
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "sans-serif",
        ],
      },
      boxShadow: {
        pop: "0 8px 32px -8px rgba(0,0,0,0.6), 0 2px 6px -2px rgba(0,0,0,0.4)",
        brand: "0 8px 28px -6px rgba(127,119,221,0.35)",
      },
    },
  },
  plugins: [],
} satisfies Config;
