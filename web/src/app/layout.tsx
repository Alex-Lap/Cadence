import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
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
  title: "Cadence",
  description: "Syllabi in, study schedule out.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <ClerkProvider
          appearance={{
            // Clerk's sign-in modal and account menu in Cadence's palette.
            variables: {
              colorPrimary: "#8ab8ff",
              colorPrimaryForeground: "#0d1015",
              colorBackground: "#151920",
              colorForeground: "#e8eaef",
              colorMutedForeground: "#8c95a5",
              colorInput: "#1c212a",
              colorInputForeground: "#e8eaef",
              colorBorder: "#262c36",
              colorNeutral: "#e8eaef",
              borderRadius: "0.5rem",
            },
          }}
        >
          {children}
        </ClerkProvider>
      </body>
    </html>
  );
}
