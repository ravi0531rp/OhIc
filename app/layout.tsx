import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("http://localhost:3000"),
  title: "OhIc — Local AI video restoration",
  description: "Restore and upscale video on your own computer. Private by design.",
  openGraph: {
    title: "OhIc — Local AI video restoration",
    description: "Bring old videos back into focus, privately on your own computer.",
    images: [{ url: "/og.png", width: 1729, height: 910, alt: "OhIc before and after video restoration" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "OhIc — Local AI video restoration",
    description: "Bring old videos back into focus, privately on your own computer.",
    images: ["/og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
