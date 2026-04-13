import Script from "next/script";

import "./globals.css";

export const metadata = {
  title: "BIST Agentic RAG v2.3",
  description: "Canlı veri + analyst workspace dashboard"
};

export default function RootLayout({ children }) {
  return (
    <html lang="tr" className="dark">
      <body className="bg-[#07111f] text-slate-100">
        <Script src="/runtime-config.js" strategy="beforeInteractive" />
        {children}
      </body>
    </html>
  );
}
