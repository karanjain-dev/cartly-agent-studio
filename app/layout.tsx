import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cartly — Customer Support",
  description: "Review a policy-backed support resolution and approve exact terms before Cartly changes an order.",
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
