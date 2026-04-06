"use client";

import { useEffect, useMemo, useState } from "react";

const TABS = [
  { key: "query", label: "Query Studio" },
  { key: "ingestion", label: "Live Ingestion" },
  { key: "eval", label: "Evaluation Scorecard" },
  { key: "narrative", label: "Narrative Explorer" }
];

const DEFAULT_API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:18002";

function formatJson(data) {
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

function Stat({ label, value, hint }) {
  return (
    <div className="glass-card p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-white">{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-400">{hint}</div> : null}
    </div>
  );
}

export default function HomePage() {
  const [apiBase, setApiBase] = useState(DEFAULT_API);
  const [apiToken, setApiToken] = useState("");
  const [activeTab, setActiveTab] = useState("query");
  const [health, setHealth] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [streamState, setStreamState] = useState("idle");
  const [ingestStreamState, setIngestStreamState] = useState("idle");
  const [prices, setPrices] = useState([]);
  const [queryPayload, setQueryPayload] = useState({
    ticker: "ASELS",
    question: "Do recent news articles align with official KAP disclosures?",
    language: "bilingual",
    provider_pref: null
  });
  const [queryResult, setQueryResult] = useState(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [ingestPayload, setIngestPayload] = useState({
    ticker: "ASELS",
    institution: "BIST-Collector",
    source_urls: "https://news.google.com/rss/search?q=ASELS%20BIST&hl=tr&gl=TR&ceid=TR:tr",
    delta_mode: true,
    max_docs: 100,
    force_reingest: false
  });
  const [ingestResult, setIngestResult] = useState(null);
  const [evalPayload, setEvalPayload] = useState({
    mode: "heuristic",
    provider: "auto",
    sample_size: 15,
    dataset_path: "datasets/eval_questions.json",
    store_artifacts: true
  });
  const [evalResult, setEvalResult] = useState(null);
  const [narrativeTicker, setNarrativeTicker] = useState("ASELS");
  const [narrativeResult, setNarrativeResult] = useState(null);
  const [providerRegistry, setProviderRegistry] = useState(null);
  const [universe, setUniverse] = useState([]);
  const [errorText, setErrorText] = useState("");

  const headers = useMemo(() => {
    const h = { "Content-Type": "application/json" };
    if (apiToken.trim()) h["X-API-Token"] = apiToken.trim();
    return h;
  }, [apiToken]);

  async function call(path, options = {}) {
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      headers: options.headers || headers
    });
    const text = await response.text();
    const data = text ? JSON.parse(text) : {};
    if (!response.ok) {
      throw new Error(data?.detail || text || `HTTP ${response.status}`);
    }
    return data;
  }

  async function loadBootstrap() {
    try {
      setErrorText("");
      const [h, m, p, u, providers] = await Promise.all([
        call("/v1/health"),
        call("/v1/metrics"),
        call("/v1/market/prices?limit=8"),
        call("/v1/market/universe?limit=20"),
        call("/v1/providers")
      ]);
      setHealth(h);
      setMetrics(m);
      setPrices(p.prices || []);
      setUniverse(u.items || []);
      setProviderRegistry(providers);
    } catch (err) {
      setErrorText(String(err.message || err));
    }
  }

  useEffect(() => {
    loadBootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  useEffect(() => {
    let es = null;
    try {
      const tokenPart = apiToken.trim() ? `&token=${encodeURIComponent(apiToken.trim())}` : "";
      es = new EventSource(`${apiBase}/v1/stream/metrics?interval=2.0${tokenPart}`);
      setStreamState("connected");
      es.addEventListener("metrics", (evt) => {
        const payload = JSON.parse(evt.data);
        setMetrics(payload);
        if (payload?.live_universe_preview) setUniverse(payload.live_universe_preview);
      });
      es.onerror = () => {
        setStreamState("error");
        es?.close();
      };
    } catch {
      setStreamState("error");
    }
    return () => es?.close();
  }, [apiBase, apiToken]);

  useEffect(() => {
    let es = null;
    try {
      const tokenPart = apiToken.trim() ? `&token=${encodeURIComponent(apiToken.trim())}` : "";
      es = new EventSource(`${apiBase}/v1/stream/ingest?interval=3.0${tokenPart}`);
      setIngestStreamState("connected");
      es.addEventListener("ingest", (evt) => {
        const payload = JSON.parse(evt.data);
        const live = payload?.market_prices?.prices || [];
        if (live.length) setPrices(live);
      });
      es.onerror = () => {
        setIngestStreamState("error");
        es?.close();
      };
    } catch {
      setIngestStreamState("error");
    }
    return () => es?.close();
  }, [apiBase, apiToken]);

  async function runQuery() {
    try {
      setQueryLoading(true);
      setErrorText("");
      const payload = { ...queryPayload };
      if (!payload.provider_pref) delete payload.provider_pref;
      const data = await call("/v1/query", { method: "POST", body: JSON.stringify(payload) });
      setQueryResult(data);
    } catch (err) {
      setErrorText(String(err.message || err));
    } finally {
      setQueryLoading(false);
    }
  }

  async function runIngest(type) {
    try {
      setErrorText("");
      const payload = {
        ticker: ingestPayload.ticker.trim().toUpperCase(),
        institution: ingestPayload.institution,
        source_urls: ingestPayload.source_urls
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean),
        delta_mode: ingestPayload.delta_mode,
        max_docs: Number(ingestPayload.max_docs),
        force_reingest: ingestPayload.force_reingest
      };
      const data = await call(`/v1/ingest/${type}`, { method: "POST", body: JSON.stringify(payload) });
      setIngestResult(data);
      await loadBootstrap();
    } catch (err) {
      setErrorText(String(err.message || err));
    }
  }

  async function runEval() {
    try {
      setErrorText("");
      const data = await call("/v1/eval/run", { method: "POST", body: JSON.stringify(evalPayload) });
      setEvalResult(data);
      await loadBootstrap();
    } catch (err) {
      setErrorText(String(err.message || err));
    }
  }

  async function runNarrative() {
    try {
      setErrorText("");
      const data = await call(`/v1/diagnostics/${narrativeTicker.trim().toUpperCase()}`);
      setNarrativeResult(data);
    } catch (err) {
      setErrorText(String(err.message || err));
    }
  }

  const routeCounters = metrics?.routing_counters || { direct: 0, reretrieve: 0, blocked: 0 };
  const uptime = metrics?.uptime_seconds ?? 0;
  const disclaimerText = "This system does not provide investment advice.";

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,_#1e293b_0%,_#020617_55%)] p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <section className="glass-card p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-white">BIST Agentic RAG v2.0</h1>
              <p className="mt-2 text-sm text-slate-300">
                Canlı veri, agentic doğrulama döngüsü ve kanıt-temelli piyasa anlatısı.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className="pill">Weaviate-only</span>
              <span className="pill">Live News/KAP</span>
              <span className="pill">Claim-level Citation</span>
              <span className="pill">No Advice</span>
            </div>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-4">
            <Stat label="Stream (metrics)" value={streamState} hint="SSE + polling fallback hazır" />
            <Stat label="Stream (ingest)" value={ingestStreamState} hint="Canlı ingest ve fiyat güncellemesi" />
            <Stat label="Uptime" value={`${uptime}s`} hint={health?.time || "-"} />
            <Stat label="Fallback Mode" value={metrics?.fallback_mode || "-"} hint={`Weaviate: ${String(metrics?.weaviate_connected ?? false)}`} />
          </div>
        </section>

        <section className="glass-card p-4">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-slate-300">API Base</label>
            <input
              className="w-80 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
            />
            <label className="text-sm text-slate-300">API Token</label>
            <input
              className="w-72 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              value={apiToken}
              onChange={(e) => setApiToken(e.target.value)}
              placeholder="optional"
            />
            <button className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold" onClick={loadBootstrap}>
              Yenile
            </button>
          </div>
          {errorText ? <div className="mt-3 rounded-lg border border-rose-700 bg-rose-950/40 p-3 text-sm text-rose-200">{errorText}</div> : null}
        </section>

        <section className="glass-card p-4">
          <div className="flex flex-wrap gap-2">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`rounded-lg px-4 py-2 text-sm font-semibold ${
                  activeTab === tab.key ? "bg-emerald-600 text-white" : "bg-slate-800 text-slate-200"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </section>

        {activeTab === "query" ? (
          <section className="grid gap-6 lg:grid-cols-2">
            <div className="glass-card p-5">
              <div className="section-title">Query Studio</div>
              <div className="mt-4 space-y-3">
                <input
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={queryPayload.ticker}
                  onChange={(e) => setQueryPayload((s) => ({ ...s, ticker: e.target.value.toUpperCase() }))}
                  placeholder="Ticker"
                />
                <textarea
                  className="min-h-28 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={queryPayload.question}
                  onChange={(e) => setQueryPayload((s) => ({ ...s, question: e.target.value }))}
                />
                <select
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={queryPayload.provider_pref || ""}
                  onChange={(e) =>
                    setQueryPayload((s) => ({ ...s, provider_pref: e.target.value || null }))
                  }
                >
                  <option value="">auto</option>
                  <option value="ollama">ollama</option>
                  <option value="groq">groq</option>
                  <option value="gemini">gemini</option>
                  <option value="openai">openai</option>
                  <option value="together">together</option>
                  <option value="mock">mock</option>
                </select>
                <button
                  onClick={runQuery}
                  disabled={queryLoading}
                  className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold disabled:opacity-50"
                >
                  {queryLoading ? "Sorgulanıyor..." : "Sorguyu Çalıştır"}
                </button>
              </div>
              <div className="mt-6 text-xs text-slate-400">{disclaimerText}</div>
            </div>

            <div className="glass-card p-5">
              <div className="section-title">Answer + Citations</div>
              <pre className="mt-4 max-h-[540px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-200">
                {queryResult ? formatJson(queryResult) : "Henüz sorgu sonucu yok."}
              </pre>
            </div>
          </section>
        ) : null}

        {activeTab === "ingestion" ? (
          <section className="grid gap-6 lg:grid-cols-2">
            <div className="glass-card p-5">
              <div className="section-title">Live Ingestion Controls</div>
              <div className="mt-4 space-y-3">
                <input
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={ingestPayload.ticker}
                  onChange={(e) => setIngestPayload((s) => ({ ...s, ticker: e.target.value.toUpperCase() }))}
                  placeholder="Ticker"
                />
                <input
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={ingestPayload.institution}
                  onChange={(e) => setIngestPayload((s) => ({ ...s, institution: e.target.value }))}
                  placeholder="Institution"
                />
                <textarea
                  className="min-h-24 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={ingestPayload.source_urls}
                  onChange={(e) => setIngestPayload((s) => ({ ...s, source_urls: e.target.value }))}
                  placeholder="Comma separated URLs"
                />
                <div className="flex gap-2">
                  <button className="rounded-lg bg-slate-700 px-3 py-2 text-sm" onClick={() => runIngest("kap")}>
                    Ingest KAP
                  </button>
                  <button className="rounded-lg bg-slate-700 px-3 py-2 text-sm" onClick={() => runIngest("news")}>
                    Ingest News
                  </button>
                  <button className="rounded-lg bg-slate-700 px-3 py-2 text-sm" onClick={() => runIngest("report")}>
                    Ingest Report
                  </button>
                </div>
              </div>
              <pre className="mt-4 max-h-72 overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-200">
                {ingestResult ? formatJson(ingestResult) : "Henüz ingest sonucu yok."}
              </pre>
            </div>

            <div className="space-y-4">
              <div className="glass-card p-5">
                <div className="section-title">Near Real-time Prices</div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  {prices.map((row) => (
                    <div key={row.ticker} className="rounded-xl border border-slate-800 bg-slate-950 p-3">
                      <div className="text-sm font-semibold">{row.ticker}</div>
                      <div className="mt-1 text-xl font-bold">{row.price ?? "-"}</div>
                      <div className="text-xs text-slate-400">
                        {row.change_pct === null || row.change_pct === undefined ? "-" : `${row.change_pct}%`} | {row.provider}
                        {row.stale ? " (stale)" : ""}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="glass-card p-5">
                <div className="section-title">Dynamic Universe Queue</div>
                <div className="mt-4 grid gap-2">
                  {universe.map((item) => (
                    <div key={item.ticker} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm">
                      <span>{item.ticker}</span>
                      <span className="text-slate-400">{item.priority_score}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {activeTab === "eval" ? (
          <section className="grid gap-6 lg:grid-cols-2">
            <div className="glass-card p-5">
              <div className="section-title">Evaluation Scorecard</div>
              <div className="mt-4 space-y-3">
                <select
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={evalPayload.mode}
                  onChange={(e) => setEvalPayload((s) => ({ ...s, mode: e.target.value }))}
                >
                  <option value="heuristic">heuristic</option>
                  <option value="hybrid">hybrid</option>
                  <option value="real">real</option>
                  <option value="mock">mock</option>
                </select>
                <select
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={evalPayload.provider}
                  onChange={(e) => setEvalPayload((s) => ({ ...s, provider: e.target.value }))}
                >
                  <option value="auto">auto</option>
                  <option value="ollama">ollama</option>
                  <option value="groq">groq</option>
                  <option value="gemini">gemini</option>
                  <option value="openai">openai</option>
                  <option value="together">together</option>
                </select>
                <input
                  type="number"
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={evalPayload.sample_size}
                  onChange={(e) => setEvalPayload((s) => ({ ...s, sample_size: Number(e.target.value || 15) }))}
                />
                <button className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold" onClick={runEval}>
                  Eval Çalıştır
                </button>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2">
                <Stat label="Direct" value={routeCounters.direct} />
                <Stat label="ReRetrieve" value={routeCounters.reretrieve} />
                <Stat label="Blocked" value={routeCounters.blocked} />
              </div>
            </div>

            <div className="glass-card p-5">
              <div className="section-title">Eval Output</div>
              <pre className="mt-4 max-h-[520px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-200">
                {evalResult ? formatJson(evalResult) : "Henüz eval sonucu yok."}
              </pre>
            </div>
          </section>
        ) : null}

        {activeTab === "narrative" ? (
          <section className="grid gap-6 lg:grid-cols-2">
            <div className="glass-card p-5">
              <div className="section-title">Narrative Explorer</div>
              <div className="mt-4 flex gap-2">
                <input
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2"
                  value={narrativeTicker}
                  onChange={(e) => setNarrativeTicker(e.target.value.toUpperCase())}
                />
                <button className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold" onClick={runNarrative}>
                  Analiz
                </button>
              </div>
              <div className="mt-4 grid gap-2 text-sm text-slate-300">
                <div className="rounded-lg border border-slate-800 bg-slate-950 px-3 py-2">
                  Provider Availability: {providerRegistry ? formatJson(providerRegistry.available) : "-"}
                </div>
              </div>
            </div>

            <div className="glass-card p-5">
              <div className="section-title">Diagnostics</div>
              <pre className="mt-4 max-h-[520px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-200">
                {narrativeResult ? formatJson(narrativeResult) : "Henüz diagnostics sonucu yok."}
              </pre>
            </div>
          </section>
        ) : null}

        <section className="glass-card p-4 text-center text-xs text-slate-400">{disclaimerText}</section>
      </div>
    </main>
  );
}
