import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cartly — Agent Studio",
  description: "Try Cartly customer support and follow every policy lookup, tool call, and session change.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
