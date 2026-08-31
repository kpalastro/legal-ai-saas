import type { Metadata } from "next";
import "./globals.css";

export const metadata = { title: "LexSim AI", description: "Legal debate simulation" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}