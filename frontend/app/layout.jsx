import "./globals.css";

export const metadata = {
  title: "BIST Agentic RAG v2.0",
  description: "Canlı veri + Agentic RAG dashboard"
};

export default function RootLayout({ children }) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}

