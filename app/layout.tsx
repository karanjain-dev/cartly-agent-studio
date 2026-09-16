import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cartly — Customer Support",
  description: "Chat with Cartly, see live guardrail checks and tool calls, and approve exact proposals before any order changes.",
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
