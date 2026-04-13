export default function Loading() {
  return (
    <div className="mx-auto flex min-h-screen max-w-3xl items-center px-6 py-16">
      <div className="glass-card w-full p-8">
        <div className="text-sm uppercase tracking-[0.35em] text-cyan-300">BIST Analyst Workspace</div>
        <h1 className="mt-4 text-3xl font-semibold text-white">Panel yükleniyor</h1>
        <p className="mt-4 text-base leading-8 text-slate-300">
          Canlı veri, connector durumu ve workspace görünümü hazırlanıyor.
        </p>
      </div>
    </div>
  );
}
