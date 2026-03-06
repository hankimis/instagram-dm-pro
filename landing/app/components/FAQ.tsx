"use client";

import { useState } from "react";
import AnimateOnScroll from "./AnimateOnScroll";

const faqs = [
  {
    q: "무료로 사용할 수 있나요?",
    a: "네, 기본 기능은 무료로 제공됩니다. 다운로드 후 바로 사용할 수 있습니다.",
  },
  {
    q: "계정이 차단될 위험은 없나요?",
    a: "오타 시뮬레이션, 릴스 브라우징, 발송 간격 랜덤화 등 봇 탐지를 우회하는 다양한 기능이 내장되어 있습니다. 또한 일일/시간 발송 한도를 설정할 수 있어 안전하게 운영 가능합니다.",
  },
  {
    q: "Windows와 macOS 모두 지원하나요?",
    a: "네, 두 플랫폼 모두 지원합니다. 접속한 OS에 맞는 버전이 자동으로 다운로드됩니다.",
  },
  {
    q: "동시에 몇 개 계정까지 운영할 수 있나요?",
    a: "제한 없이 여러 계정을 동시에 운영할 수 있습니다. Chrome 창이 격자로 자동 정렬되어 한눈에 관리할 수 있습니다.",
  },
  {
    q: "프로그램 설치 시 보안 경고가 뜨는데요?",
    a: "코드 서명이 없는 프로그램이라 Windows SmartScreen이나 macOS Gatekeeper 경고가 뜰 수 있습니다. '추가 정보 > 실행' 또는 '확인'을 눌러 진행하세요. 프로그램은 안전합니다.",
  },
];

export default function FAQ() {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  return (
    <section className="px-6 py-24">
      <div className="max-w-3xl mx-auto">
        <AnimateOnScroll>
          <h2 className="text-3xl md:text-4xl font-bold text-center mb-4">
            자주 묻는 질문
          </h2>
          <p className="text-center text-lg mb-12" style={{ color: "var(--gray-700)" }}>
            궁금한 점이 있으신가요?
          </p>
        </AnimateOnScroll>

        <AnimateOnScroll delay={0.1}>
          <div className="bg-white rounded-2xl p-6 md:p-8" style={{ border: "1px solid var(--gray-200)" }}>
            {faqs.map((faq, i) => (
              <div key={i} className="faq-item">
                <div
                  className="faq-question"
                  onClick={() => setOpenIndex(openIndex === i ? null : i)}
                >
                  <span>{faq.q}</span>
                  <svg
                    className={`faq-chevron ${openIndex === i ? "open" : ""}`}
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </div>
                <div className={`faq-answer ${openIndex === i ? "open" : ""}`}>
                  <p className="leading-relaxed" style={{ color: "var(--gray-700)" }}>
                    {faq.a}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </AnimateOnScroll>
      </div>
    </section>
  );
}
