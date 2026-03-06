"use client";

import { useEffect, useState } from "react";

type OS = "windows" | "mac" | "mobile" | "unknown";

function detectOS(): OS {
  if (typeof navigator === "undefined") return "unknown";
  const ua = navigator.userAgent;

  if (/Android|iPhone|iPad|iPod|Opera Mini|IEMobile/i.test(ua)) return "mobile";
  if (/Mac/i.test(ua)) return "mac";
  if (/Win/i.test(ua)) return "windows";
  return "unknown";
}

const OS_LABELS: Record<OS, string> = {
  windows: "Windows",
  mac: "macOS",
  mobile: "",
  unknown: "",
};

const DOWNLOAD_URLS = {
  windows: process.env.NEXT_PUBLIC_DOWNLOAD_WIN || "#",
  mac: process.env.NEXT_PUBLIC_DOWNLOAD_MAC || "#",
};

export default function DownloadButton() {
  const [os, setOs] = useState<OS>("unknown");

  useEffect(() => {
    setOs(detectOS());
  }, []);

  if (os === "mobile") {
    return (
      <div className="text-center">
        <div
          className="inline-flex items-center gap-3 px-8 py-4 rounded-lg text-lg font-semibold"
          style={{ background: "var(--gray-100)", color: "var(--gray-700)" }}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="5" y="2" width="14" height="20" rx="2" ry="2" />
            <line x1="12" y1="18" x2="12.01" y2="18" />
          </svg>
          PC에서 다운로드해주세요
        </div>
        <p className="mt-3 text-sm" style={{ color: "var(--gray-500)" }}>
          Windows 또는 macOS에서 접속해주세요
        </p>
      </div>
    );
  }

  const primaryOS = os === "mac" ? "mac" : "windows";
  const secondaryOS = primaryOS === "windows" ? "mac" : "windows";

  return (
    <div className="text-center">
      <a href={DOWNLOAD_URLS[primaryOS]} className="btn-primary" download>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        Instagram DM Pro 다운로드
      </a>
      <p className="mt-3 text-sm" style={{ color: "var(--gray-500)" }}>
        {OS_LABELS[primaryOS]}용 &middot;{" "}
        <a
          href={DOWNLOAD_URLS[secondaryOS]}
          className="underline hover:no-underline"
          style={{ color: "var(--primary)" }}
        >
          {OS_LABELS[secondaryOS]}용 다운로드
        </a>
      </p>
    </div>
  );
}
