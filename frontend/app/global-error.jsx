"use client";

export default function GlobalError({ error, reset }) {
  return (
    <html lang="tr" className="dark">
      <body className="bg-[#07111f] text-slate-100">
        <div className="mx-auto flex min-h-screen max-w-3xl items-center px-6 py-16">
          <div className="glass-card w-full p-8">
            <div className="text-sm uppercase tracking-[0.35em] text-rose-300">Global UI Error</div>
            <h1 className="mt-4 text-3xl font-semibold text-white">Uygulama yüzeyi beklenmeyen şekilde koptu.</h1>
            <p className="mt-4 text-base leading-8 text-slate-300">
              Bu ekran beyaz sayfa yerine kontrollü hata görünümü sağlar. Runtime hatası çözüldükten sonra reset ile tekrar deneyebilirsin.
            </p>
            <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-300">
              {String(error?.message || "unknown_global_error")}
            </div>
            <div className="mt-6 flex flex-wrap gap-3">
              <button className="btn-primary" onClick={() => reset()}>Uygulamayı Yeniden Dene</button>
              <a className="btn-secondary" href="/">Ana Dashboard</a>
            </div>
          </div>
        </div>
      </body>
    </html>
  );
}
