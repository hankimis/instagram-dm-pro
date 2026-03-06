import type { Metadata } from "next";
import { Noto_Sans_KR } from "next/font/google";
import "./globals.css";

const notoSansKR = Noto_Sans_KR({
  variable: "--font-noto-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Instagram DM Pro - 인스타그램 마케팅 자동화",
  description:
    "해시태그 크롤링부터 DM 발송까지, 인스타그램 마케팅을 자동화하세요. 멀티 계정 운영, 스마트 발송, 안전한 운영.",
  openGraph: {
    title: "Instagram DM Pro",
    description: "해시태그 크롤링부터 DM 발송까지, 인스타그램 마케팅 자동화",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className={`${notoSansKR.variable} antialiased`}>{children}</body>
    </html>
  );
}
