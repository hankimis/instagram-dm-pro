"use client";

import { useEffect, useState } from "react";
import DownloadButton from "./DownloadButton";

export default function Hero() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <section className="relative flex flex-col items-center justify-center text-center px-6 pt-32 pb-24 overflow-hidden">
      {/* Background decoration */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[800px] rounded-full opacity-30 pointer-events-none"
        style={{
          background: "radial-gradient(circle, var(--primary-light) 0%, transparent 70%)",
        }}
      />

      {/* Logo / Badge */}
      <div
        className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium mb-8 relative"
        style={{
          background: "var(--primary-light)",
          color: "var(--primary)",
          opacity: mounted ? 1 : 0,
          transform: mounted ? "translateY(0)" : "translateY(20px)",
          transition: "all 0.6s ease",
        }}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z" />
        </svg>
        Instagram DM Pro
      </div>

      {/* Main heading */}
      <h1
        className="text-5xl md:text-7xl font-bold tracking-tight leading-tight max-w-4xl mb-6 relative"
        style={{
          opacity: mounted ? 1 : 0,
          transform: mounted ? "translateY(0)" : "translateY(30px)",
          transition: "all 0.7s ease 0.1s",
        }}
      >
        인스타그램 마케팅
        <br />
        <span
          style={{
            background: "linear-gradient(135deg, var(--primary), var(--gradient-end))",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}
        >
          자동화의 시작
        </span>
      </h1>

      {/* Subtitle */}
      <p
        className="text-lg md:text-xl max-w-2xl mb-12 leading-relaxed relative"
        style={{
          color: "var(--gray-700)",
          opacity: mounted ? 1 : 0,
          transform: mounted ? "translateY(0)" : "translateY(30px)",
          transition: "all 0.7s ease 0.2s",
        }}
      >
        해시태그 크롤링부터 DM 발송까지,
        <br className="hidden md:block" />
        복잡한 마케팅 작업을 한 번에 자동화하세요.
      </p>

      {/* Download CTA */}
      <div
        className="relative"
        style={{
          opacity: mounted ? 1 : 0,
          transform: mounted ? "translateY(0)" : "translateY(30px)",
          transition: "all 0.7s ease 0.3s",
        }}
      >
        <DownloadButton />
      </div>

      {/* Trusted badge */}
      <div
        className="mt-12 flex items-center gap-6 relative"
        style={{
          opacity: mounted ? 1 : 0,
          transition: "opacity 0.7s ease 0.5s",
        }}
      >
        <div className="flex items-center gap-2 text-sm" style={{ color: "var(--gray-500)" }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            <path d="M9 12l2 2 4-4" />
          </svg>
          안전한 발송
        </div>
        <div className="flex items-center gap-2 text-sm" style={{ color: "var(--gray-500)" }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
          Win / Mac 지원
        </div>
        <div className="flex items-center gap-2 text-sm" style={{ color: "var(--gray-500)" }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
          </svg>
          멀티 계정
        </div>
      </div>
    </section>
  );
}
