"use client";

export default function Error({ error, reset }) {
  return (
    <div className="mx-auto flex min-h-screen max-w-3xl items-center px-6 py-16">
      <div className="glass-card w-full p-8">
        <div className="text-sm uppercase tracking-[0.35em] text-rose-300">UI Runtime Error</div>
        <h1 className="mt-4 text-3xl font-semibold text-white">Bu panel çöktü, ama uygulama tamamen kaybolmamalı.</h1>
        <p className="mt-4 text-base leading-8 text-slate-300">
          İstemci tarafında beklenmeyen bir render hatası oluştu. Sayfayı resetleyebilir veya ana dashboard'a dönebilirsin.
        </p>
        <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-300">
          {String(error?.message || "unknown_client_error")}
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          <button className="btn-primary" onClick={() => reset()}>Tekrar Dene</button>
          <a className="btn-secondary" href="/">Ana Dashboard</a>
        </div>
      </div>
    </div>
  );
}
