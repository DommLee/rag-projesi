"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

const FALLBACK_API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:18000";
const FALLBACK_API_CANDIDATES = (process.env.NEXT_PUBLIC_API_CANDIDATES || "http://127.0.0.1:18000,http://127.0.0.1:18002,http://127.0.0.1:18001,http://127.0.0.1:8088")
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);
const TABS = [
  ["overview", "Overview"],
  ["live", "Live Monitor"],
  ["workspace", "Ticker Workspace"],
  ["chat", "Research Chat"],
  ["uploads", "Uploads"],
  ["crossasset", "Cross-Asset Context"],
  ["evaluation", "Evaluation"],
  ["ops", "Ops"]
];
const TAB_ROUTES = {
  overview: "/overview",
  live: "/live-monitor",
  workspace: "/ticker-workspace",
  chat: "/research-chat",
  uploads: "/uploads",
  crossasset: "/cross-asset-context",
  evaluation: "/evaluation",
  ops: "/ops"
};
const ROUTE_TABS = Object.fromEntries(Object.entries(TAB_ROUTES).map(([key, value]) => [value, key]));

function cx(...values) { return values.filter(Boolean).join(" "); }
function maybeFixMojibake(value) {
  const text = String(value ?? "");
  if (!text || !/[ÃÄÅ]/.test(text)) return text;
  try {
    const bytes = new Uint8Array(Array.from(text).map((ch) => ch.charCodeAt(0)));
    return new TextDecoder("utf-8").decode(bytes);
  } catch { return text; }
}
function asArray(value) {
  if (Array.isArray(value)) return value;
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value.items)) return value.items;
  if (Array.isArray(value.rows)) return value.rows;
  if (Array.isArray(value.prices)) return value.prices;
  if (Array.isArray(value.data)) return value.data;
  return Object.entries(value).map(([key, item]) => (
    item && typeof item === "object" && !Array.isArray(item) ? { key, ...item } : { key, label: key, value: item }
  ));
}
function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}
function formatDate(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" });
}
function formatPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}
function formatBytes(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = n; let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) { size /= 1024; unitIndex += 1; }
  return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}
function slugify(value) {
  return String(value || "report")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "") || "report";
}
function downloadTextFile(filename, content, contentType = "text/plain;charset=utf-8") {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
function buildWorkspaceMarkdownReport({ ticker, response, sections, timeline, tables, summary }) {
  const citationLines = asArray(response?.citations).map((citation, index) => (
    `${index + 1}. [${citation.source_type}] ${maybeFixMojibake(citation.title)} | ${maybeFixMojibake(citation.institution)} | ${formatDate(citation.date)} | ${citation.url}`
  ));
  const tableLines = asArray(tables).filter((block) => asArray(block?.rows).length).map((block) => {
    const rows = asArray(block.rows).slice(0, 5).map((row) => asArray(block.columns).map((col) => `${col}: ${maybeFixMojibake(String(row[col] ?? "-"))}`).join(" | "));
    return [`## ${block.title}`, ...rows].join("\n");
  });
  const timelineLines = asArray(timeline).slice(0, 8).map((item) => `- ${formatDate(item.date)} | ${maybeFixMojibake(item.title)} (${item.source_type})`);
  return [
    `# ${ticker} Analyst Workspace Raporu`,
    `As Of: ${formatDate(response?.as_of_date)}`,
    "",
    "## Executive Summary",
    stripDisclaimer(summary || response?.answer_tr || "Henüz özet oluşmadı."),
    "",
    "## Resmi Durum (KAP)",
    maybeFixMojibake(sections?.official_disclosure || "Yeterli veri yok."),
    "",
    "## Haber Anlatısı",
    maybeFixMojibake(sections?.news_framing || "Yeterli veri yok."),
    "",
    "## Aracı Kurum Çerçevesi",
    maybeFixMojibake(sections?.brokerage_view || "Yeterli veri yok."),
    "",
    "## Sosyal Sinyal",
    maybeFixMojibake(sections?.social_signal || "Sosyal sinyal devre dışı veya sınırlı."),
    "",
    "## Tutarlılık Özeti",
    maybeFixMojibake(sections?.consistency_summary || response?.consistency_assessment || "Belirsiz."),
    "",
    "## Timeline",
    ...(timelineLines.length ? timelineLines : ["- Timeline verisi oluşmadı."]),
    "",
    "## Source Tables",
    ...(tableLines.length ? tableLines : ["Kaynak tablo verisi oluşmadı."]),
    "",
    "## Citations",
    ...(citationLines.length ? citationLines : ["Citation bulunamadı."]),
    "",
    response?.disclaimer || "This system does not provide investment advice.",
  ].join("\n");
}
function buildChatMarkdownReport({ ticker, messages }) {
  const rows = asArray(messages).map((item) => {
    const role = item.role === "user" ? "Analist" : "Research Agent";
    return `## ${role}\n${item.text || ""}`;
  });
  return [`# ${ticker} Research Chat Dökümü`, "", ...rows, "", "This system does not provide investment advice."].join("\n");
}
function stripDisclaimer(text) {
  return maybeFixMojibake(String(text || "")).replace(/\n*\s*This system does not provide investment advice\.\s*$/i, "").trim();
}
function toBulletPoints(text, limit = 4) {
  const clean = stripDisclaimer(text);
  if (!clean) return [];
  return clean
    .split(/(?<=[.!?])\s+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 24)
    .slice(0, limit);
}
function toUserError(err) {
  const raw = String(err?.message || err || "");
  if (!raw) return "Beklenmeyen bir hata oluştu.";
  if (raw.includes("Failed to fetch")) return "API bağlantısı kurulamadı. API Base alanını ve çalışan backend'i kontrol edin.";
  return maybeFixMojibake(raw);
}
async function readFileAsBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.slice(i, i + 0x8000));
  return btoa(binary);
}

class TabErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  render() {
    if (this.state.hasError) {
      return (
        <div className="mt-6 rounded-2xl border border-rose-800 bg-rose-950/30 p-6 text-sm text-rose-200">
          <div className="mb-2 text-base font-semibold">Bu sekme yuklenirken hata olustu</div>
          <pre className="mt-3 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{String(this.state.error?.message || this.state.error || "Bilinmeyen hata")}{"\n"}{String(this.state.error?.stack || "").slice(0, 600)}</pre>
          <button className="mt-4 rounded-lg bg-rose-700 px-4 py-2 text-sm text-white hover:bg-rose-600" onClick={() => this.setState({ hasError: false, error: null })}>Tekrar Dene</button>
        </div>
      );
    }
    return this.props.children;
  }
}
function Panel({ children, className = "" }) { return <div className={cx("glass-card p-5", className)}>{children}</div>; }
function SectionTitle({ title, subtext }) {
  return <div className="mb-4"><div className="section-title">{title}</div>{subtext ? <div className="mt-1 text-sm text-slate-400">{subtext}</div> : null}</div>;
}
function Pill({ children, tone = "default" }) {
  const tones = {
    default: "border-slate-700 bg-slate-900/70 text-slate-200",
    success: "border-emerald-700 bg-emerald-900/30 text-emerald-200",
    warn: "border-amber-700 bg-amber-900/30 text-amber-200",
    danger: "border-rose-700 bg-rose-900/30 text-rose-200",
    info: "border-cyan-700 bg-cyan-900/30 text-cyan-200"
  };
  return <span className={cx("pill", tones[tone] || tones.default)}>{children}</span>;
}
function MetricCard({ label, value, hint }) {
  return <Panel><div className="text-xs uppercase tracking-[0.22em] text-slate-500">{label}</div><div className="mt-2 text-3xl font-semibold text-white truncate" title={String(value)}>{value}</div>{hint ? <div className="mt-2 text-sm text-slate-400">{hint}</div> : null}</Panel>;
}
const CHART_COLORS = ["#22d3ee", "#10b981", "#818cf8", "#f59e0b", "#fb7185", "#f97316", "#38bdf8", "#14b8a6"];
function ChartTooltip({ active, payload, label, formatter = (value) => value }) {
  const rows = asArray(payload);
  if (!active || !rows.length) return null;
  return (
    <div className="rounded-2xl border border-slate-800 bg-[#08111d]/95 px-4 py-3 shadow-2xl shadow-black/40">
      {label ? <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div> : null}
      {rows.map((item, index) => (
        <div key={`${item.name}-${index}`} className="flex items-center justify-between gap-4 text-sm">
          <span className="text-slate-400">{item.name}</span>
          <span className="font-medium text-white">{formatter(item.value, item)}</span>
        </div>
      ))}
    </div>
  );
}
function MiniBarChart({ items, valueFormatter = (v) => String(v) }) {
  const rows = asArray(items);
  if (!rows.length) return <div className="text-sm text-slate-500">Grafik verisi yok.</div>;
  const data = rows.map((row) => ({ label: row.label, value: Number(row.value || 0) }));
  const height = Math.max(220, data.length * 44);
  return (
    <div className="h-[240px] w-full md:h-[280px]">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 6, right: 8, left: 0, bottom: 6 }}>
          <CartesianGrid stroke="#172234" strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="label" width={110} tick={{ fill: "#cbd5e1", fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip content={<ChartTooltip formatter={(value) => valueFormatter(Number(value))} />} cursor={{ fill: "rgba(34,211,238,0.08)" }} />
          <Bar dataKey="value" name="Değer" radius={[8, 8, 8, 8]}>
            {data.map((_, index) => <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
function Sparkline({ points }) {
  const rows = asArray(points);
  if (rows.length < 2) return <div className="text-xs text-slate-500">Sparkline verisi yok.</div>;
  const data = rows.map((row) => ({ ts: row.ts ? formatDate(row.ts) : "", price: Number(row.price || 0) }));
  return (
    <div className="h-24 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="sparklineFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.4} />
              <stop offset="100%" stopColor="#22d3ee" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <Tooltip content={<ChartTooltip formatter={(value) => Number(value).toFixed(2)} />} />
          <Area type="monotone" dataKey="price" stroke="#22d3ee" strokeWidth={3} fill="url(#sparklineFill)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
function readRuntimeConfig() {
  if (typeof window === "undefined") {
    return { apiBase: FALLBACK_API, apiCandidates: FALLBACK_API_CANDIDATES };
  }
  const runtime = window.__BIST_RUNTIME_CONFIG__ || {};
  const apiBase = String(runtime.apiBase || FALLBACK_API).trim() || FALLBACK_API;
  const apiCandidates = Array.isArray(runtime.apiCandidates)
    ? runtime.apiCandidates.map((item) => String(item || "").trim()).filter(Boolean)
    : FALLBACK_API_CANDIDATES;
  return {
    apiBase,
    apiCandidates: [...new Set([apiBase, ...apiCandidates, ...FALLBACK_API_CANDIDATES])],
  };
}
function LineTrendChart({ items, xKey = "label", yKey = "value", formatter = (value) => Number(value).toFixed(2) }) {
  const rows = asArray(items);
  if (!rows.length) return <div className="text-sm text-slate-500">Trend verisi yok.</div>;
  return (
    <div className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
          <CartesianGrid stroke="#172234" strokeDasharray="3 3" />
          <XAxis dataKey={xKey} tick={{ fill: "#94a3b8", fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip content={<ChartTooltip formatter={(value) => formatter(Number(value))} />} />
          <Line type="monotone" dataKey={yKey} name={yKey} stroke="#22d3ee" strokeWidth={3} dot={{ r: 3, fill: "#22d3ee" }} activeDot={{ r: 6 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
function DonutLegend({ items }) {
  const rows = asArray(items).filter((row) => Number(row.value || 0) > 0);
  if (!rows.length) return <div className="text-sm text-slate-500">Dağılım verisi yok.</div>;
  return (
    <div className="flex flex-col gap-5 lg:flex-row lg:items-center">
      <div className="h-48 w-full max-w-[220px] shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={rows} dataKey="value" nameKey="label" innerRadius={44} outerRadius={74} paddingAngle={2}>
              {rows.map((_, index) => <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}
            </Pie>
            <Tooltip content={<ChartTooltip formatter={(value) => Number(value).toFixed(2)} />} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="grid flex-1 gap-3">
        {rows.map((row, index) => (
          <div key={`${row.label}-${index}`} className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="h-3 w-3 rounded-full" style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }} />
              <span className="text-sm text-slate-300">{row.label}</span>
            </div>
            <span className="text-sm font-medium text-white">{Number(row.value || 0).toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
function GaugeBar({ label, value, hint, color = "from-cyan-500 to-emerald-500" }) {
  const safe = Math.max(0, Math.min(1, Number(value || 0)));
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="text-slate-300">{label}</span>
        <span className="font-medium text-white">{safe.toFixed(2)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full rounded-full bg-gradient-to-r ${color}`} style={{ width: `${Math.max(6, safe * 100)}%` }} />
      </div>
      {hint ? <div className="text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}
function CitationList({ citations }) {
  const rows = asArray(citations);
  if (!rows.length) return <Panel className="border-amber-800/70 bg-amber-950/20 text-sm text-amber-200">Bu analiz için doğrulanmış citation bulunamadı. Sistem quick-ingest denemiş olabilir ancak yeterli kanıt oluşmamış olabilir.</Panel>;
  return <div className="grid gap-3">{rows.map((row, idx) => <Panel key={`${row.url}-${idx}`} className="p-4"><div className="flex flex-wrap items-center gap-2"><Pill tone={row.source_type === "kap" ? "success" : row.source_type === "news" ? "info" : "warn"}>{row.source_type}</Pill><span className="text-sm text-slate-400">{formatDate(row.date)}</span></div><div className="mt-3 text-lg font-medium text-white">{maybeFixMojibake(row.title)}</div><div className="mt-1 text-sm text-slate-400">{maybeFixMojibake(row.institution)}</div><div className="mt-3 text-sm leading-7 text-slate-200">{maybeFixMojibake(row.snippet)}</div>{row.url ? <a className="mt-3 inline-flex text-sm text-cyan-300" href={row.url} target="_blank" rel="noreferrer">Kaynağı aç</a> : null}</Panel>)}</div>;
}
function Timeline({ items }) {
  const rows = asArray(items);
  if (!rows.length) return <div className="text-sm text-slate-500">Timeline verisi henüz oluşmadı.</div>;
  return <div className="space-y-4">{rows.map((row, idx) => <div key={`${row.title}-${idx}`} className="flex gap-4"><div className="mt-1 h-3 w-3 rounded-full bg-emerald-400 shadow-[0_0_0_6px_rgba(16,185,129,0.12)]" /><div className="flex-1 rounded-xl border border-slate-800 bg-slate-950/60 p-4"><div className="flex flex-wrap items-center gap-2"><Pill tone={row.source_type === "kap" ? "success" : row.source_type === "news" ? "info" : "warn"}>{row.source_type}</Pill><span className="text-sm text-slate-400">{formatDate(row.date)}</span></div><div className="mt-2 text-base font-medium text-white">{maybeFixMojibake(row.title)}</div><div className="mt-1 text-sm text-slate-400">{maybeFixMojibake(row.institution)}</div>{row.note ? <div className="mt-2 text-sm text-slate-300">{maybeFixMojibake(row.note)}</div> : null}</div></div>)}</div>;
}
function AnalysisSections({ sections }) {
  const items = [["official_disclosure", "Resmi Durum (KAP)"], ["news_framing", "Haber Anlatısı"], ["brokerage_view", "Aracı Kurum Çerçevesi"], ["social_signal", "Sosyal Sinyal"], ["web_research_context", "Açık Web Araştırma"], ["consistency_summary", "Tutarlılık + Kanıt Boşlukları"]];
  return <div className="grid gap-4 lg:grid-cols-2">{items.map(([key, title]) => <Panel key={key}><SectionTitle title={title} /><div className="whitespace-pre-wrap text-sm leading-8 text-slate-200">{maybeFixMojibake(sections?.[key] || "Bu bölüm için yeterli özet oluşmadı.")}</div></Panel>)}</div>;
}
function DataTable({ block }) {
  const rows = asArray(block?.rows);
  const columns = asArray(block?.columns);
  if (!rows.length || !columns.length) return <div className="text-sm text-slate-500">Tablo verisi yok.</div>;
  return <div className="overflow-x-auto rounded-2xl border border-slate-800"><table className="min-w-full divide-y divide-slate-800 text-left text-sm"><thead className="bg-slate-950/80 text-slate-400"><tr>{columns.map((col) => <th key={col} className="px-4 py-3">{col}</th>)}</tr></thead><tbody className="divide-y divide-slate-800 bg-slate-950/50">{rows.map((row, idx) => <tr key={`${block?.title}-${idx}`}>{columns.map((col) => <td key={col} className="px-4 py-3 text-slate-300">{col === "date" ? formatDate(row[col]) : maybeFixMojibake(String(row[col] ?? "-"))}</td>)}</tr>)}</tbody></table></div>;
}
function SummaryCardGrid({ items }) {
  const rows = asArray(items);
  if (!rows.length) return null;
  return <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{rows.map((item) => <MetricCard key={item.label} label={item.label} value={item.value} hint={item.hint} />)}</div>;
}
function EvidenceGapList({ gaps }) {
  const rows = asArray(gaps).filter(Boolean);
  if (!rows.length) return <Panel className="border-emerald-800/60 bg-emerald-950/15 text-sm text-emerald-200">Belirgin evidence gap görünmüyor.</Panel>;
  return (
    <details className="rounded-2xl border border-amber-800/70 bg-amber-950/15 p-4">
      <summary className="cursor-pointer text-sm font-medium text-amber-200">Evidence Gaps ({rows.length})</summary>
      <div className="mt-4 space-y-3">
        {rows.map((gap, index) => <div key={`${gap}-${index}`} className="rounded-xl border border-amber-900/50 bg-slate-950/40 px-4 py-3 text-sm leading-7 text-amber-100">{maybeFixMojibake(gap)}</div>)}
      </div>
    </details>
  );
}
function Markdownish({ text }) {
  const lines = maybeFixMojibake(String(text || "")).split(/\n+/).filter(Boolean);
  if (!lines.length) return <div className="text-sm text-slate-500">Henüz içerik yok.</div>;
  return (
    <div className="space-y-3">
      {lines.map((line, index) => {
        if (line.startsWith("## ")) return <div key={index} className="text-lg font-semibold text-white">{line.slice(3)}</div>;
        if (line.startsWith("**") && line.endsWith("**")) return <div key={index} className="font-medium text-cyan-200">{line.slice(2, -2)}</div>;
        if (line.startsWith("- ")) return <div key={index} className="pl-4 text-sm leading-7 text-slate-200">• {line.slice(2)}</div>;
        return <div key={index} className="text-sm leading-7 text-slate-200">{line}</div>;
      })}
    </div>
  );
}
export function DashboardApp({ initialTab = "overview" }) {
  const [activeTab, setActiveTab] = useState(initialTab);
  const [apiBase, setApiBase] = useState(FALLBACK_API);
  const [apiCandidates, setApiCandidates] = useState(FALLBACK_API_CANDIDATES);
  const [apiToken, setApiToken] = useState("");
  const [apiStatus, setApiStatus] = useState("connecting");
  const [globalError, setGlobalError] = useState("");
  const [providerPref, setProviderPref] = useState("auto");
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState("http://host.docker.internal:11434");
  const [ollamaModel, setOllamaModel] = useState("llama3.1:8b");
  const [providerTest, setProviderTest] = useState(null);
  const [providerRegistry, setProviderRegistry] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [sourceCatalog, setSourceCatalog] = useState([]);
  const [sourceHealth, setSourceHealth] = useState([]);
  const [sourceCoverage, setSourceCoverage] = useState(null);
  const [kapWarmupStatus, setKapWarmupStatus] = useState("");
  const [warmUpBusy, setWarmUpBusy] = useState(false);
  const [warmUpResult, setWarmUpResult] = useState(null);
  const [universe, setUniverse] = useState([]);
  const [prices, setPrices] = useState([]);
  const [workspaceTicker, setWorkspaceTicker] = useState("ASELS");
  const [workspaceQuestion, setWorkspaceQuestion] = useState("Son 30 günde resmi durum, haber anlatısı ve aracı kurum çerçevesini analiz et.");
  const [analysis, setAnalysis] = useState(null);
  const [analysisStatus, setAnalysisStatus] = useState("idle");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [autoAnalyze, setAutoAnalyze] = useState(true);
  const [refreshSeconds, setRefreshSeconds] = useState(60);
  const [tickerSearch, setTickerSearch] = useState("");
  const [chatSessionId, setChatSessionId] = useState("workspace-default");
  const [chatInput, setChatInput] = useState("Seçili hisse için resmi durum, haber anlatısı ve karşıt kanıtları tabloyla açıkla.");
  const [chatMessages, setChatMessages] = useState([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatStreamEvents, setChatStreamEvents] = useState([]);
  const [tickerSuggestions, setTickerSuggestions] = useState([]);
  const [compareTickers, setCompareTickers] = useState("");
  const [compareResult, setCompareResult] = useState(null);
  const [compareBusy, setCompareBusy] = useState(false);
  const [uploads, setUploads] = useState([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [selectedUploadFile, setSelectedUploadFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [evalMode, setEvalMode] = useState("heuristic");
  const [evalProvider, setEvalProvider] = useState("auto");
  const [evalSampleSize, setEvalSampleSize] = useState(15);
  const [evalResult, setEvalResult] = useState(null);
  const [evalBusy, setEvalBusy] = useState(false);

  const providerOverrides = useMemo(() => providerPref === "ollama" ? { ollama_base_url: ollamaBaseUrl, ollama_model: ollamaModel } : null, [providerPref, ollamaBaseUrl, ollamaModel]);
  const latestAnalysis = analysis?.latest_analysis || null;
  const analysisResponse = latestAnalysis?.response || null;
  const analysisSections = latestAnalysis?.analysis_sections || {};
  const insight = asObject(latestAnalysis?.insight);
  const analysisOverviewCards = asArray(analysis?.overview_cards || latestAnalysis?.overview_cards);
  const analysisTimeline = asArray(analysis?.timeline || latestAnalysis?.timeline);
  const analysisTables = asArray(analysis?.source_tables || latestAnalysis?.source_tables);
  const diagnostics = asObject(analysis?.diagnostics || latestAnalysis?.diagnostics);
  const crossAssetContext = asObject(analysis?.cross_asset_context || insight?.cross_asset_context);
  const webResearchContext = asObject(analysis?.web_research || insight?.web_research_context);
  const dossierSnapshot = asObject(analysis?.dossier_snapshot || latestAnalysis?.dossier_snapshot);
  const auditSummary = asObject(analysis?.audit_summary || metrics?.audit_summary);
  const auditLedgerPreview = asObject(analysis?.audit_ledger_preview);
  const auditVerification = asObject(analysis?.audit_verification || metrics?.audit_verification || auditLedgerPreview?.verification);
  const sourceMixItems = Object.entries(asObject(insight?.source_mix)).map(([label, value]) => ({ label, value }));
  const sourceReliabilityItems = Object.entries(asObject(insight?.source_reliability_mix)).map(([label, value]) => ({ label, value }));
  const attentionItems = asArray(metrics?.attention_leaders).map((item) => ({ label: item.ticker, value: item.score }));
  const queueItems = Object.entries(asObject(metrics?.queue_depths)).map(([label, value]) => ({ label, value }));
  const tensionIndex = Number(latestAnalysis?.insight?.tension_index || diagnostics?.disclosure_news_tension_index?.tension_index || 0);
  const freshnessScore = Number(latestAnalysis?.insight?.freshness_score || 0);
  const attentionScore = Number(latestAnalysis?.insight?.attention_score || 0);
  const evidenceSufficiencyScore = Number(latestAnalysis?.insight?.evidence_sufficiency_score || dossierSnapshot?.evidence_sufficiency_score || 0);
  const rumorRiskScore = Number(latestAnalysis?.insight?.rumor_risk_score || dossierSnapshot?.rumor_risk_score || 0);
  const sourceHealthRows = asArray(sourceHealth).length ? asArray(sourceHealth) : asArray(sourceCatalog);
  const sourceVolumeItems = sourceHealthRows.map((row) => ({ label: row.label || row.key, value: Number(row.accepted_count || row.inserted || 0) }));
  const latestDocTimesList = Object.entries(asObject(insight?.latest_doc_times)).map(([label, value]) => ({ label, value }));
  const rejectedAuditRows = sourceHealthRows.flatMap((row) => asArray(row.rejected_samples).map((sample, index) => ({ id: `${row.key}-${index}`, source: row.label || row.key, title: sample.title, score: sample.score, reason: sample.reason }))).slice(0, 12);
  const providerHealthRows = Object.entries(asObject(providerRegistry?.available)).map(([key, value]) => ({ label: key, value: String(value) }));
  const connectorCards = asArray(analysis?.connector_cards || insight?.connector_cards);
  const warmStatus = asObject(analysis?.warm_status);
  const driftItems = asArray(diagnostics?.weekly_drift || diagnostics?.narrative_drift_radar?.weekly_drift);
  const tensionTimelineItems = asArray(diagnostics?.tension_timeline);
  const brokerBiasItems = asArray(diagnostics?.broker_bias_series);
  const cryptoItems = asArray(crossAssetContext?.crypto_context?.items);
  const macroContextItems = asArray(crossAssetContext?.macro_snapshot || analysis?.macro_snapshot);
  const macroPairItems = asArray(crossAssetContext?.macro_pairs);
  const contextCards = asArray(crossAssetContext?.context_cards);
  const contextSignalItems = asArray(crossAssetContext?.context_signals);
  const riskDashboardItems = asArray(crossAssetContext?.risk_dashboard);
  const webResearchItems = asArray(webResearchContext?.items);
  const webResearchThemes = asArray(webResearchContext?.theme_buckets);
  const webScraperStats = asObject(webResearchContext?.scraper_stats);
  const marketRegime = asObject(crossAssetContext?.market_regime);
  const topCryptoMover = asObject(crossAssetContext?.top_crypto_mover);
  const auditEventRows = asArray(auditLedgerPreview.items);
  const auditRepairRows = asArray(auditLedgerPreview.repairs);
  const recentChatSessions = asArray(analysis?.recent_chat_sessions);
  const recentUploadEvents = asArray(analysis?.recent_upload_events);
  const recentConnectorRuns = asArray(analysis?.recent_connector_runs);
  const executiveSummary = stripDisclaimer(analysisResponse?.answer_tr || latestAnalysis?.executive_summary || "");
  const executiveBullets = toBulletPoints(executiveSummary, 5);
  const recentCitationPreview = asArray(analysisResponse?.citations).slice(0, 4);
  const routingCounterItems = Object.entries(asObject(metrics?.routing_counters)).map(([label, value]) => ({ label, value }));
  const latestTimelinePreview = analysisTimeline.slice(0, 5);
  const reliabilityDonutItems = sourceReliabilityItems.length ? sourceReliabilityItems : Object.entries(asObject(dossierSnapshot?.source_reliability_mix)).map(([label, value]) => ({ label, value }));
  const enabledSourceCount = sourceHealthRows.filter((row) => row.enabled !== false).length;
  const disabledSourceCount = sourceHealthRows.filter((row) => row.enabled === false).length;
  const errorSourceCount = sourceHealthRows.filter((row) => row.status === "error").length;
  const sourceSuccessItems = sourceHealthRows.map((row) => ({ label: row.label || row.key, value: Number(row.success_rate || 0) }));
  const freshnessHeatmapItems = asArray(metrics?.freshness_heatmap).map((item) => ({
    label: item.source,
    value: Number(item.fresh_doc_ratio || 0),
    latency: item.freshness_latency_seconds,
  }));
  const auditEventTypeItems = Object.entries(asObject(auditVerification?.event_type_counts)).map(([label, value]) => ({ label, value }));
  const auditSourceKeyItems = Object.entries(asObject(auditVerification?.source_key_counts)).map(([label, value]) => ({ label, value }));
  const auditScopeItems = Object.entries(asObject(auditVerification?.asset_scope_counts)).map(([label, value]) => ({ label, value }));
  const auditTickerItems = Object.entries(asObject(auditVerification?.ticker_breakdown)).map(([label, value]) => ({ label, value }));
  const auditHeadPreview = asArray(auditVerification?.head_preview);
  const auditTailPreview = asArray(auditVerification?.tail_preview);
  const sourceCoverageSummary = asObject(sourceCoverage || metrics?.source_coverage);
  const sourceCoverageRecommendations = asArray(sourceCoverageSummary.recommendations);
  const premiumMissingItems = asArray(sourceCoverageSummary.premium_missing);
  const premiumConnectedItems = asArray(sourceCoverageSummary.premium_connected);
  const kapCoverageSummary = asObject(sourceCoverageSummary.kap_coverage);
  const kapEndpointItems = Object.entries(asObject(kapCoverageSummary.endpoint_counts)).map(([label, value]) => ({ label, value }));
  const rawLakeSummary = asObject(metrics?.raw_lake);
  const visibleTickers = useMemo(() => {
    const q = tickerSearch.trim().toUpperCase();
    const rows = asArray(universe);
    if (!q) return rows;
    return rows.filter((item) => String(item.ticker || "").includes(q));
  }, [tickerSearch, universe]);
  const selectedPrice = useMemo(() => asArray(analysis?.prices?.prices || prices).find((item) => item.ticker === workspaceTicker) || null, [analysis, prices, workspaceTicker]);
  const latestChatPayload = useMemo(() => [...chatMessages].reverse().find((item) => item.payload)?.payload || null, [chatMessages]);
  const promptSuggestions = useMemo(() => ([
    `${workspaceTicker} için son 30 gündeki resmi KAP açıklamalarını ve haber çerçevesini karşılaştır.`,
    `${workspaceTicker} için çelişen haber veya zayıf kanıt alanlarını tabloyla çıkar.`,
    `${workspaceTicker} için aracı kurum raporlarında tekrar eden ana temaları özetle.`,
    `${workspaceTicker} için son gelişmelerin zaman çizelgesini ve kaynak güvenilirliğini yaz.`,
  ]), [workspaceTicker]);
  const uploadPreview = useMemo(() => selectedUploadFile ? ({ name: selectedUploadFile.name, size: selectedUploadFile.size, type: selectedUploadFile.type || "unknown" }) : null, [selectedUploadFile]);

  async function call(path, options = {}, baseOverride = apiBase) {
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    const headers = { ...(isFormData ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) };
    if (apiToken) headers["X-API-Token"] = apiToken;
    const response = await fetch(`${baseOverride}${path}`, { ...options, headers });
    const text = await response.text();
    let data = text;
    try { data = JSON.parse(text); } catch {}
    if (!response.ok) {
      const detail = typeof data === "object" && data?.detail ? data.detail : text;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  async function detectApiBase() {
    for (const candidate of [...new Set([apiBase, ...apiCandidates])]) {
      try {
        const response = await fetch(`${candidate}/v1/health`);
        if (response.ok) {
          setApiBase(candidate); setApiStatus("connected"); setGlobalError(""); return candidate;
        }
      } catch {}
    }
    setApiStatus("error");
    setGlobalError("API bulunamadı. 110_run_modern_app.bat veya 30_run_api.bat ile backend'i başlatın.");
    return null;
  }

  async function loadBootstrap(base = apiBase) {
    try {
      const [metricsPayload, catalogPayload, healthPayload, universePayload, pricesPayload, providersPayload, uploadsPayload] = await Promise.all([
        call("/v1/metrics", {}, base),
        call("/v1/source-catalog", {}, base),
        call("/v1/source-health", {}, base),
        call("/v1/market/universe?limit=18&mode=priority", {}, base),
        call("/v1/market/prices?limit=8", {}, base),
        call("/v1/providers", {}, base),
        call(`/v1/uploads/${encodeURIComponent(chatSessionId)}`, {}, base)
      ]);
      setMetrics(metricsPayload);
      setSourceCatalog(asArray(catalogPayload?.items || catalogPayload));
      setSourceHealth(asArray(healthPayload?.items || healthPayload));
      setSourceCoverage(asObject(healthPayload?.coverage_summary || metricsPayload?.source_coverage));
      setUniverse(asArray(universePayload?.items || universePayload));
      setPrices(asArray(pricesPayload?.prices || pricesPayload));
      setProviderRegistry(providersPayload);
      setUploads(asArray(uploadsPayload?.items || uploadsPayload));
      setApiStatus("connected");
      setGlobalError("");
    } catch (error) { setApiStatus("error"); setGlobalError(toUserError(error)); }
  }

  async function refreshAll() { const base = await detectApiBase(); if (!base) return; await loadBootstrap(base); if (autoAnalyze) await runWorkspaceAnalysis(true, base); }
  async function runProviderTest(pref = providerPref) {
    try { const result = await call("/v1/provider/validate", { method: "POST", body: JSON.stringify({ provider_pref: pref === "auto" ? null : pref, provider_overrides: providerOverrides }) }); setProviderTest(result); if (pref === "ollama" && result.ok) setProviderPref("ollama"); }
    catch (error) { setProviderTest({ ok: false, error: toUserError(error) }); }
  }
  async function runWarmUpAllSources() {
    const base = await detectApiBase();
    if (!base) return;
    setWarmUpBusy(true);
    setWarmUpResult(null);
    try {
      const result = await call("/v1/sources/warm-up", { method: "POST" }, base);
      setWarmUpResult(result);
      await loadBootstrap(base);
    } catch (error) {
      setWarmUpResult({ error: toUserError(error) });
    } finally {
      setWarmUpBusy(false);
    }
  }
  async function runKapWarmupFull() {
    const base = await detectApiBase();
    if (!base) return;
    setKapWarmupStatus("running");
    try {
      const since = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString();
      const response = await call("/v1/ingest/kap", {
        method: "POST",
        body: JSON.stringify({
          ticker: workspaceTicker,
          institution: "KAP",
          source_urls: [],
          date_from: since,
          delta_mode: true,
          max_docs: 75,
          force_reingest: false,
        }),
      }, base);
      setKapWarmupStatus(`ok: ${response.inserted_chunks || 0} chunk, skipped=${response.skipped_docs || 0}`);
      await loadBootstrap(base);
      await runWorkspaceAnalysis(true, base);
    } catch (error) {
      setKapWarmupStatus(`error: ${toUserError(error)}`);
      setGlobalError(toUserError(error));
    }
  }
  function navigateToTab(key) {
    setActiveTab(key);
    if (typeof window === "undefined") return;
    const target = TAB_ROUTES[key] || "/";
    const params = new URLSearchParams(window.location.search);
    if (workspaceTicker) params.set("ticker", workspaceTicker);
    const query = params.toString();
    window.history.pushState({ tab: key }, "", `${target}${query ? `?${query}` : ""}`);
  }
  async function runWorkspaceAnalysis(questionless = false, base = apiBase) {
    setAnalysisStatus("running");
    try {
      if (questionless) {
        setAnalysis(asObject(await call(`/v1/research/ticker/${encodeURIComponent(workspaceTicker)}?session_id=${encodeURIComponent(chatSessionId)}`, {}, base)));
      } else {
        const insight = asObject(await call("/v1/query/insight", { method: "POST", body: JSON.stringify({ ticker: workspaceTicker, question: workspaceQuestion, language: "bilingual", provider_pref: providerPref === "auto" ? null : providerPref, provider_overrides: providerOverrides, session_id: chatSessionId, include_user_files: true, include_social_signal: true }) }, base));
        const bundle = asObject(await call(`/v1/research/ticker/${encodeURIComponent(workspaceTicker)}?session_id=${encodeURIComponent(chatSessionId)}`, {}, base));
        const insightInner = asObject(insight.insight);
        setAnalysis({
          ...bundle,
          ticker: workspaceTicker,
          latest_analysis: insight,
          overview_cards: asArray(insight.overview_cards || bundle.overview_cards),
          timeline: asArray(insight.timeline || bundle.timeline),
          source_tables: asArray(insight.source_tables || bundle.source_tables),
          diagnostics: asObject(insight.diagnostics || bundle.diagnostics),
          macro_snapshot: asArray(insightInner.macro_context || bundle.macro_snapshot),
          social_signal: asObject(insightInner.social_snapshot || bundle.social_signal),
          cross_asset_context: asObject(bundle.cross_asset_context || insightInner.cross_asset_context),
          connector_cards: asArray(bundle.connector_cards || insightInner.connector_cards),
          warm_status: asObject(bundle.warm_status),
          audit_summary: asObject(bundle.audit_summary),
          dossier_snapshot: asObject(bundle.dossier_snapshot || insight.dossier_snapshot),
        });
      }
      setAnalysisStatus("ok");
    } catch (error) { setAnalysisStatus("error"); setGlobalError(toUserError(error)); }
  }
  async function sendChat() {
    if (!chatInput.trim()) return;
    const nextMessages = [...chatMessages, { role: "user", text: chatInput.trim() }]; setChatMessages(nextMessages); setChatBusy(true);
    try {
      const reply = await call("/v1/chat/query", { method: "POST", body: JSON.stringify({ ticker: workspaceTicker, message: chatInput.trim(), session_id: chatSessionId, provider_pref: providerPref === "auto" ? null : providerPref, provider_overrides: providerOverrides, include_user_files: true, include_social_signal: true, include_crypto_context: true, market_scope: "bist_plus_context", research_mode: "deep", time_range: "30d", language: "bilingual" }) });
      setChatMessages([...nextMessages, { role: "assistant", text: maybeFixMojibake(reply.reply_markdown), payload: reply }]); setChatInput("");
    } catch (error) { setChatMessages([...nextMessages, { role: "assistant", text: toUserError(error) }]); } finally { setChatBusy(false); }
  }
  async function sendStreamingQuery() {
    if (!chatInput.trim()) return;
    const nextMessages = [...chatMessages, { role: "user", text: chatInput.trim() }];
    setChatMessages(nextMessages); setChatBusy(true); setChatStreamEvents([]);
    try {
      const resp = await fetch(`${apiBase}/v1/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}) },
        body: JSON.stringify({ ticker: workspaceTicker, question: chatInput.trim(), provider_pref: providerPref === "auto" ? null : providerPref }),
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalResponse = null;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const evt = JSON.parse(line.slice(6));
              setChatStreamEvents((prev) => [...prev, evt]);
              if (evt.node === "final" && evt.response) finalResponse = evt.response;
            } catch {}
          }
        }
      }
      if (finalResponse) {
        const answerText = `**[EN]** ${maybeFixMojibake(finalResponse.answer_en)}\n\n**[TR]** ${maybeFixMojibake(finalResponse.answer_tr)}`;
        setChatMessages([...nextMessages, { role: "assistant", text: answerText, payload: finalResponse }]);
      }
      setChatInput("");
    } catch (error) {
      setChatMessages([...nextMessages, { role: "assistant", text: toUserError(error) }]);
    } finally { setChatBusy(false); }
  }
  async function fetchTickerSuggestions(prefix) {
    if (!prefix || prefix.length < 1) { setTickerSuggestions([]); return; }
    try {
      const data = await call(`/v1/ticker/suggest?q=${encodeURIComponent(prefix)}&limit=8`);
      setTickerSuggestions(asArray(data.suggestions));
    } catch { setTickerSuggestions([]); }
  }
  async function runCompare() {
    const tickers = compareTickers.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean);
    if (tickers.length < 2) return;
    setCompareBusy(true); setCompareResult(null);
    try {
      const result = await call("/v1/query/compare", { method: "POST", body: JSON.stringify({ tickers, question: workspaceQuestion, provider_pref: providerPref === "auto" ? null : providerPref }) });
      setCompareResult(result);
    } catch (error) { setGlobalError(toUserError(error)); } finally { setCompareBusy(false); }
  }
  async function downloadPdfReport() {
    try {
      const resp = await fetch(`${apiBase}/v1/query/export/pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}) },
        body: JSON.stringify({ ticker: workspaceTicker, question: workspaceQuestion, provider_pref: providerPref === "auto" ? null : providerPref }),
      });
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `${workspaceTicker}_report.pdf`; a.click(); URL.revokeObjectURL(url);
    } catch (error) { setGlobalError(toUserError(error)); }
  }
  function selectUploadFile(file) {
    if (!file) return;
    setSelectedUploadFile(file);
    setUploadStatus(`Hazır: ${file.name} (${formatBytes(file.size)})`);
  }
  async function handleUpload(file) {
    if (!file) return; setUploadBusy(true); setUploadStatus("");
    try {
      const formData = new FormData();
      formData.set("session_id", chatSessionId);
      formData.set("ticker", workspaceTicker);
      formData.set("file", file);
      const response = await call("/v1/uploads", { method: "POST", body: formData });
      setUploadStatus(`Yüklendi: ${response.inserted_chunks} chunk, ticker=${response.detected_ticker || workspaceTicker}`); const uploadsPayload = await call(`/v1/uploads/${encodeURIComponent(chatSessionId)}`); setUploads(asArray(uploadsPayload.items || uploadsPayload)); if (autoAnalyze) await runWorkspaceAnalysis(true);
    } catch (error) { setUploadStatus(toUserError(error)); } finally { setUploadBusy(false); }
  }
  async function runEval() {
    setEvalBusy(true);
    try { setEvalResult(await call("/v1/eval/run", { method: "POST", body: JSON.stringify({ mode: evalMode, provider: evalProvider, sample_size: Number(evalSampleSize || 15), dataset_path: "datasets/eval_questions.json", store_artifacts: true, run_ragas: true, run_deepeval: true }) })); }
    catch (error) { setGlobalError(toUserError(error)); } finally { setEvalBusy(false); }
  }
  function downloadWorkspaceMarkdown() {
    if (!analysisResponse) return;
    const content = buildWorkspaceMarkdownReport({
      ticker: workspaceTicker,
      response: analysisResponse,
      sections: analysisSections,
      timeline: analysisTimeline,
      tables: analysisTables,
      summary: executiveSummary,
    });
    downloadTextFile(`${slugify(workspaceTicker)}-analyst-report.md`, content, "text/markdown;charset=utf-8");
  }
  function downloadWorkspaceJson() {
    if (!analysis) return;
    downloadTextFile(`${slugify(workspaceTicker)}-analysis-snapshot.json`, JSON.stringify(analysis, null, 2), "application/json;charset=utf-8");
  }
  function downloadChatTranscript() {
    if (!chatMessages.length) return;
    const content = buildChatMarkdownReport({ ticker: workspaceTicker, messages: chatMessages });
    downloadTextFile(`${slugify(workspaceTicker)}-research-chat.md`, content, "text/markdown;charset=utf-8");
  }

  useEffect(() => {
    const runtime = readRuntimeConfig();
    const storedApi = localStorage.getItem("bist-api-base"); const storedToken = localStorage.getItem("bist-api-token"); const storedProvider = localStorage.getItem("bist-provider-pref"); const storedOllamaBase = localStorage.getItem("bist-ollama-base"); const storedOllamaModel = localStorage.getItem("bist-ollama-model");
    setApiCandidates(runtime.apiCandidates);
    setApiBase(storedApi || runtime.apiBase); if (storedToken) setApiToken(storedToken); if (storedProvider) setProviderPref(storedProvider); if (storedOllamaBase) setOllamaBaseUrl(storedOllamaBase); if (storedOllamaModel) setOllamaModel(storedOllamaModel);
    const params = new URLSearchParams(window.location.search);
    const tickerParam = params.get("ticker");
    if (tickerParam) setWorkspaceTicker(tickerParam.toUpperCase());
    setActiveTab(ROUTE_TABS[window.location.pathname] || initialTab);
  }, []);
  useEffect(() => { localStorage.setItem("bist-api-base", apiBase); localStorage.setItem("bist-api-token", apiToken); localStorage.setItem("bist-provider-pref", providerPref); localStorage.setItem("bist-ollama-base", ollamaBaseUrl); localStorage.setItem("bist-ollama-model", ollamaModel); }, [apiBase, apiToken, providerPref, ollamaBaseUrl, ollamaModel]);
  useEffect(() => { refreshAll(); }, []);
  useEffect(() => { if (!autoRefresh) return undefined; const timer = setInterval(() => { refreshAll(); }, Math.max(15, Number(refreshSeconds || 60)) * 1000); return () => clearInterval(timer); }, [autoRefresh, refreshSeconds, workspaceTicker, chatSessionId]);
  useEffect(() => { if (!autoAnalyze || !apiBase) return undefined; const timer = setTimeout(() => { runWorkspaceAnalysis(true); }, 350); return () => clearTimeout(timer); }, [workspaceTicker]);
  return (
    <div className="mx-auto min-h-screen max-w-[1600px] px-5 pb-10 pt-8 md:px-8">
      <div className="mb-8 flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between"><div><div className="text-sm uppercase tracking-[0.35em] text-emerald-300">BIST Agentic RAG v2.3</div><h1 className="mt-3 max-w-4xl text-4xl font-semibold tracking-tight text-white md:text-5xl">Canlı veriyle çalışan analyst intelligence workspace</h1><p className="mt-4 max-w-3xl text-base leading-8 text-slate-300">KAP, haber, fiyat, kullanıcı dosyaları, audit zinciri ve cross-asset context aynı analyst yüzeyinde birleşir. Çıktılar citation-first, zaman damgalı ve non-advisory kalır.</p></div><div className="flex flex-wrap gap-2"><Pill tone={metrics?.weaviate_connected ? "success" : "warn"}>Weaviate {metrics?.weaviate_connected ? "connected" : "fallback"}</Pill><Pill tone={apiStatus === "connected" ? "success" : apiStatus === "error" ? "danger" : "info"}>API {apiStatus}</Pill><Pill tone="info">{metrics?.active_provider || providerPref}</Pill><Pill tone="info">Audit {metrics?.audit_summary?.chain_ok ? "verified" : "tracking"}</Pill><Pill tone="warn">No Advice</Pill></div></div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"><MetricCard label="API" value={apiStatus} hint={apiBase} /><MetricCard label="Coverage (24h)" value={metrics ? `${(metrics.ticker_coverage_ratio || 0).toFixed(2)}` : "-"} hint="processed_tickers_24h / universe" /><MetricCard label="Fresh Doc Ratio" value={metrics ? `${(metrics.fresh_doc_ratio || 0).toFixed(2)}` : "-"} hint="canlı ingest tazelik oranı" /><MetricCard label="Last Live Ingest" value={metrics?.last_live_ingest_success_at ? formatDate(metrics.last_live_ingest_success_at) : "-"} hint={`Uptime: ${metrics ? `${metrics.uptime_seconds}s` : "-"}`} /></div>
      <Panel className="mt-6">
        <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
          <div>
            <SectionTitle title="Source Coverage Board" subtext="Kaynaklar %100 mü sorusunu ikiye ayırır: bağlantı hazır mı ve canlı veri geldi mi." />
            <div className="grid gap-4 md:grid-cols-2">
              <GaugeBar label="Demo Readiness" value={Number(sourceCoverageSummary.demo_readiness_score || 0)} hint="BIST/KAP demo için ağırlıklı hazırlık skoru" color="from-emerald-500 to-cyan-500" />
              <GaugeBar label="Configured Sources" value={Number(sourceCoverageSummary.configured_ratio || 0)} hint={`${sourceCoverageSummary.enabled_sources ?? 0}/${sourceCoverageSummary.total_sources ?? 0} kaynak aktif`} color="from-cyan-500 to-indigo-500" />
              <GaugeBar label="Live Data Observed" value={Number(sourceCoverageSummary.live_data_ratio || 0)} hint={`${sourceCoverageSummary.sources_with_live_data ?? 0} kaynakta veri görüldü`} color="from-amber-500 to-emerald-500" />
              <GaugeBar label="Core BIST Ready" value={Number(sourceCoverageSummary.core_bist_ready_ratio || 0)} hint="KAP, BIST evreni, fiyat, brokerage ve web research" color="from-emerald-500 to-lime-500" />
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel className="bg-slate-950/80">
              <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Premium / Social</div>
              <div className="mt-3 flex flex-wrap gap-2">
                {premiumConnectedItems.length ? premiumConnectedItems.map((item) => <Pill key={item} tone="success">{item} connected</Pill>) : <Pill tone="warn">premium connector yok</Pill>}
                {premiumMissingItems.map((item) => <Pill key={item} tone="warn">{item} key bekliyor</Pill>)}
              </div>
              <div className="mt-4 text-sm leading-7 text-slate-400">X/Twitter yalnız resmi API token ile açılır; discovery/social veriler resmi KAP kanıtının yerine geçmez.</div>
            </Panel>
            <Panel className="bg-slate-950/80">
              <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Sonraki Aksiyon</div>
              {!sourceCoverageRecommendations.length ? (
                <div className="mt-3 text-sm leading-7 text-emerald-200">Kritik kaynak board'unda belirgin aksiyon görünmüyor.</div>
              ) : (
                <div className="mt-3 space-y-2">
                  {sourceCoverageRecommendations.slice(0, 4).map((item, index) => (
                    <div key={`${item}-${index}`} className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm leading-7 text-slate-200">{maybeFixMojibake(item)}</div>
                  ))}
                </div>
              )}
            </Panel>
            <Panel className="bg-slate-950/80 lg:col-span-2">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-xs uppercase tracking-[0.22em] text-slate-500">KAP Coverage Diagnostics</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Pill tone={kapCoverageSummary.has_live_data ? "success" : "warn"}>{kapCoverageSummary.has_live_data ? "KAP verisi var" : "KAP verisi zayıf"}</Pill>
                    <Pill tone="info">mode: {kapCoverageSummary.policy_mode || "bekleniyor"}</Pill>
                    <Pill>fetched: {kapCoverageSummary.fetched ?? 0}</Pill>
                    <Pill>accepted: {kapCoverageSummary.accepted_count ?? 0}</Pill>
                    <Pill>blocked: {kapCoverageSummary.blocked ?? 0}</Pill>
                  </div>
                  <div className="mt-3 text-sm leading-7 text-slate-400">
                    KAP düşük görünüyorsa tam warmup çalıştır: public KAP REST API denenir, gerekirse legal HTML fallback devreye girer.
                  </div>
                  {kapEndpointItems.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {kapEndpointItems.slice(0, 4).map((item) => <Pill key={item.label} tone="info">{item.label}: {item.value}</Pill>)}
                    </div>
                  ) : null}
                </div>
                <div className="min-w-64">
                  <button className="btn-primary w-full" onClick={runKapWarmupFull} disabled={kapWarmupStatus === "running"}>
                    {kapWarmupStatus === "running" ? "KAP çekiliyor..." : `${workspaceTicker} için Tam KAP Warmup`}
                  </button>
                  {kapWarmupStatus ? <div className="mt-3 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-xs leading-6 text-slate-300">{maybeFixMojibake(kapWarmupStatus)}</div> : null}
                </div>
              </div>
            </Panel>
            <Panel className="bg-slate-950/80 lg:col-span-2">
              <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Compressed Raw Lake</div>
              <div className="mt-4 grid gap-3 md:grid-cols-4">
                <MetricCard label="Storage Mode" value={rawLakeSummary.storage_mode || "-"} hint="hash + gzip + dedup" />
                <MetricCard label="Retained Files" value={String(rawLakeSummary.file_count ?? 0)} hint="kalıcı kanıt payload dosyası" />
                <MetricCard label="Compressed MB" value={String(rawLakeSummary.compressed_mb ?? 0)} hint={rawLakeSummary.root || "data/raw_docs"} />
                <MetricCard label="Categories" value={String(Object.keys(asObject(rawLakeSummary.categories)).length)} hint="connector_run / ingest_chunks vb." />
              </div>
              <div className="mt-3 text-sm leading-7 text-slate-400">
                Veriyi “bit” düzeyinde küçültmenin pratik karşılığı budur: ham payload JSON olarak değil, hash adıyla gzip sıkıştırılmış dosyada saklanır; aynı payload tekrar gelirse yeniden yazılmaz.
              </div>
            </Panel>
          </div>
        </div>
      </Panel>
      <Panel className="mt-6"><div className="grid gap-4 xl:grid-cols-[1.3fr_1fr_0.7fr]"><div className="space-y-3"><SectionTitle title="Bağlantı ve provider ayarları" subtext="UI bu kontrat üzerinden backend ile konuşur." /><div className="grid gap-3 md:grid-cols-3"><input className="field" value={apiBase} onChange={(e) => setApiBase(e.target.value)} placeholder="API base" /><input className="field" value={apiToken} onChange={(e) => setApiToken(e.target.value)} placeholder="API token (optional)" /><select className="field" value={providerPref} onChange={(e) => setProviderPref(e.target.value)}><option value="auto">auto</option><option value="ollama">ollama</option><option value="groq">groq</option><option value="gemini">gemini</option><option value="openai">openai</option><option value="together">together</option></select></div><div className="grid gap-3 md:grid-cols-2"><input className="field" value={ollamaBaseUrl} onChange={(e) => setOllamaBaseUrl(e.target.value)} placeholder="Ollama base URL" /><input className="field" value={ollamaModel} onChange={(e) => setOllamaModel(e.target.value)} placeholder="Ollama model" /></div><div className="flex flex-wrap gap-3"><button className="btn-primary" onClick={() => refreshAll()}>Yenile</button><button className="btn-secondary" onClick={() => runProviderTest(providerPref)}>Provider Test Et</button><button className="btn-secondary" onClick={() => { setProviderPref("ollama"); runProviderTest("ollama"); }}>Ollama'yı Seç</button></div></div><div><SectionTitle title="Runtime" subtext="Provider ve embedding omurgası" /><div className="grid gap-3"><Panel className="bg-slate-950/80"><div className="text-sm text-slate-400">LLM Default</div><div className="mt-1 text-xl font-semibold text-white">{metrics?.provider_runtime?.llm_default || "-"}</div></Panel><Panel className="bg-slate-950/80"><div className="text-sm text-slate-400">Embedding</div><div className="mt-1 text-xl font-semibold text-white">{metrics?.provider_runtime?.embedding_provider || "-"}</div><div className="mt-1 text-sm text-slate-500">{metrics?.provider_runtime?.embedding_model || "-"}</div></Panel></div></div><div><SectionTitle title="Provider Test Sonucu" subtext="Ollama bağlantısı burada görünür" /><Panel className="bg-slate-950/80"><div className="text-sm leading-7 text-slate-200">{providerTest ? maybeFixMojibake(providerTest.error || providerTest.preview || JSON.stringify(providerTest)) : "Henüz provider testi çalıştırılmadı."}</div></Panel></div></div>{globalError ? <div className="mt-4 rounded-2xl border border-rose-800 bg-rose-950/20 px-4 py-3 text-sm text-rose-200">{globalError}</div> : null}</Panel>
      <div className="mt-6 flex flex-wrap gap-2">{TABS.map(([key, label]) => <button key={key} className={cx("tab-chip", activeTab === key && "tab-chip-active")} onClick={() => navigateToTab(key)}>{label}</button>)}</div>

      {activeTab === "overview" ? (
        <div className="mt-6 grid gap-6">
          <div className="grid gap-6 xl:grid-cols-[1.12fr_0.88fr]">
            <Panel>
              <SectionTitle title="Executive Board" subtext="Seçili ticker için üst seviye görünüm, hızlı aksiyonlar ve özet." />
              {latestAnalysis ? (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill tone={analysisResponse?.consistency_assessment === "aligned" ? "success" : analysisResponse?.consistency_assessment === "contradiction" ? "danger" : "warn"}>{analysisResponse?.consistency_assessment || "-"}</Pill>
                    <Pill tone="info">Provider: {analysisResponse?.provider_used || metrics?.active_provider || "-"}</Pill>
                    <Pill>Coverage: {(analysisResponse?.citation_coverage_score || 0).toFixed(2)}</Pill>
                    <Pill>Attention: {attentionScore.toFixed(2)}</Pill>
                  </div>
                  <div>
                    <div className="text-sm uppercase tracking-[0.25em] text-slate-500">Selected ticker</div>
                    <div className="mt-2 text-3xl font-semibold text-white">{workspaceTicker}</div>
                    <div className="mt-3 max-w-3xl text-base leading-8 text-slate-200">{executiveSummary || "Henüz executive summary oluşmadı."}</div>
                  </div>
                  {executiveBullets.length ? (
                    <div className="grid gap-3 md:grid-cols-2">
                      {executiveBullets.map((point, index) => (
                        <div key={`${point}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm leading-7 text-slate-200">• {point}</div>
                      ))}
                    </div>
                  ) : null}
                  <div className="flex flex-wrap gap-3">
                    <button className="btn-primary" onClick={() => navigateToTab("workspace")}>Ticker Workspace Aç</button>
                    <button className="btn-secondary" onClick={() => navigateToTab("chat")}>Research Chat Aç</button>
                    <button className="btn-secondary" onClick={downloadWorkspaceMarkdown} disabled={!latestAnalysis}>Markdown Raporu İndir</button>
                    <button className="btn-secondary" onClick={downloadWorkspaceJson} disabled={!analysis}>JSON Snapshot İndir</button>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-slate-500">Henüz seçili ticker için özet analiz oluşmadı. Workspace sekmesinden analiz çalıştırabilir veya otomatik analiz akışını kullanabilirsin.</div>
              )}
            </Panel>
            <Panel>
              <SectionTitle title="Signal Deck" subtext="Tension, freshness, attention ve kaynak karışımı aynı bakışta." />
              <div className="space-y-5">
                <GaugeBar label="Tension Index" value={tensionIndex} hint="0'a yakın ise hizalanma, 1'e yakın ise çelişki" color={tensionIndex >= 0.55 ? "from-rose-500 to-orange-500" : "from-cyan-500 to-emerald-500"} />
                <GaugeBar label="Freshness Score" value={freshnessScore} hint="Yakın tarihli kanıtlar daha yukarı taşınır" />
                <GaugeBar label="Attention Score" value={attentionScore} hint="Haber hacmi + sorgu aktivitesi" color="from-indigo-500 to-cyan-500" />
                <GaugeBar label="Evidence Sufficiency" value={evidenceSufficiencyScore} hint="Coverage + reliability + freshness birleşik skoru" color="from-emerald-500 to-cyan-500" />
                <GaugeBar label="Rumor Risk" value={rumorRiskScore} hint="Discovery/social baskısı yüksekse yükselir" color="from-amber-500 to-rose-500" />
                <div className="grid gap-4 xl:grid-cols-2">
                  <Panel className="bg-slate-950/70">
                    <div className="mb-3 text-sm font-medium text-slate-300">Source Mix</div>
                    <DonutLegend items={sourceMixItems} />
                  </Panel>
                  <Panel className="bg-slate-950/70">
                    <div className="mb-3 text-sm font-medium text-slate-300">Reliability Mix</div>
                    <DonutLegend items={reliabilityDonutItems} />
                  </Panel>
                </div>
              </div>
            </Panel>
          </div>
          <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
            <Panel>
              <SectionTitle title="Attention Leaders" subtext="Haber ve kullanıcı aktivitesine göre öncelikli ticker'lar" />
              <MiniBarChart items={attentionItems} valueFormatter={(v) => v.toFixed(2)} />
            </Panel>
            <Panel>
              <SectionTitle title="Universe Queue Mix" subtext="Hot / active / background dağılımı" />
              <MiniBarChart items={queueItems} />
            </Panel>
          </div>
          <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
            <Panel>
              <SectionTitle title="Market Pulse" subtext="Canlı fiyat kartları ve sparkline görünümü" />
              <div className="grid gap-4 lg:grid-cols-2">
                {asArray(prices).map((row) => (
                  <Panel key={row.ticker} className="bg-slate-950/80">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-emerald-300">{row.ticker}</div>
                        <div className="mt-1 text-2xl font-semibold text-white">{row.price ?? "-"} <span className="text-sm text-slate-400">{row.currency}</span></div>
                      </div>
                      <Pill tone={Number(row.change_pct || 0) >= 0 ? "success" : "danger"}>{formatPct(row.change_pct)}</Pill>
                    </div>
                    <div className="mt-3"><Sparkline points={row.sparkline_points} /></div>
                    <div className="mt-2 flex items-center justify-between text-xs text-slate-500"><span>{row.provider}</span><span>{formatDate(row.market_time)}</span></div>
                  </Panel>
                ))}
              </div>
            </Panel>
            <div className="grid gap-6">
              <Panel>
                <SectionTitle title="Freshness Heatmap" subtext="Canlı ingest tazelik görünümü" />
                <MiniBarChart items={asArray(metrics?.freshness_heatmap).map((item) => ({ label: item.source, value: item.fresh_doc_ratio || 0 }))} valueFormatter={(v) => v.toFixed(2)} />
              </Panel>
              <Panel>
                <SectionTitle title="Routing Snapshot" subtext="Agentic graph'in son davranış dağılımı" />
                <MiniBarChart items={routingCounterItems} />
              </Panel>
            </div>
          </div>
          <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <Panel>
              <SectionTitle title="Recent Citations" subtext="Seçili ticker için son doğrulanmış atıflar" />
              <CitationList citations={recentCitationPreview} />
            </Panel>
            <Panel>
              <SectionTitle title="Timeline Preview" subtext="Son olay akışını hızlı tarama görünümü" />
              <Timeline items={latestTimelinePreview} />
            </Panel>
          </div>
        </div>
      ) : null}

      {activeTab === "live" ? (
        <div className="mt-6 grid gap-6">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Enabled Sources" value={String(enabledSourceCount)} hint="aktif connector sayısı" />
            <MetricCard label="Disabled Sources" value={String(disabledSourceCount)} hint="anahtar/policy nedeniyle pasif" />
            <MetricCard label="Erroring Sources" value={String(errorSourceCount)} hint="son çalıştırmada hata verenler" />
            <MetricCard
              label="Audit Verify"
              value={auditVerification?.ok ? "verified" : "needs attention"}
              hint={`events=${auditVerification?.count ?? auditSummary?.event_count ?? 0}`}
            />
          </div>
          <Panel>
            <div className="flex items-center justify-between mb-2">
              <SectionTitle title="Source Health Matrix" subtext="Authority, legal mode, rejected entity ve hata oranı tek tabloda." />
              <button onClick={runWarmUpAllSources} disabled={warmUpBusy} className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50 whitespace-nowrap">
                {warmUpBusy ? "Aktive ediliyor..." : "Tum Kaynaklari Aktive Et"}
              </button>
            </div>
            {warmUpResult && !warmUpResult.error && (
              <div className="mb-3 rounded-lg border border-emerald-800 bg-emerald-950/30 px-3 py-2 text-xs text-emerald-300">
                {warmUpResult.activated}/{warmUpResult.total} kaynak basariyla aktive edildi.
              </div>
            )}
            <div className="overflow-x-auto rounded-2xl border border-slate-800">
              <table className="min-w-full divide-y divide-slate-800 text-left text-sm">
                <thead className="bg-slate-950/80 text-slate-400">
                  <tr>
                    <th className="px-4 py-3">Kaynak</th>
                    <th className="px-4 py-3">Katman</th>
                    <th className="px-4 py-3">Scope</th>
                    <th className="px-4 py-3">Authority</th>
                    <th className="px-4 py-3">Fetched</th>
                    <th className="px-4 py-3">Accepted</th>
                    <th className="px-4 py-3">Rejected</th>
                    <th className="px-4 py-3">Error Rate</th>
                    <th className="px-4 py-3">Last Success</th>
                    <th className="px-4 py-3">Durum</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 bg-slate-950/50">
                  {sourceHealthRows.map((row) => (
                    <tr key={row.key}>
                      <td className="px-4 py-3">
                        <div className="font-medium text-white">{row.label}</div>
                        <div className="text-xs text-slate-500">{row.notes}</div>
                      </td>
                      <td className="px-4 py-3 text-slate-300">{row.channel}</td>
                      <td className="px-4 py-3 text-slate-300">{row.asset_scope || "-"}</td>
                      <td className="px-4 py-3 text-slate-300">{row.authority_level}</td>
                      <td className="px-4 py-3 text-slate-300">{row.fetched ?? 0}</td>
                      <td className="px-4 py-3 text-slate-300">{row.accepted_count ?? row.inserted ?? 0}</td>
                      <td className="px-4 py-3 text-slate-300">{row.rejected_entity ?? 0}</td>
                      <td className="px-4 py-3 text-slate-300">{Number(row.error_rate || 0).toFixed(2)}</td>
                      <td className="px-4 py-3 text-slate-300">{formatDate(row.last_success_at)}</td>
                      <td className="px-4 py-3">
                        <Pill tone={!row.enabled ? "warn" : row.status === "error" ? "danger" : "success"}>{!row.enabled ? "disabled" : row.status || "enabled"}</Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <Panel>
              <SectionTitle title="Freshness Heatmap" subtext="Kaynakların tazelik ve gecikme görünümü." />
              {!freshnessHeatmapItems.length ? (
                <div className="text-sm text-slate-500">Tazelik verisi henüz oluşmadı.</div>
              ) : (
                <div className="space-y-3">
                  {freshnessHeatmapItems.map((item) => (
                    <div key={item.label} className="rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                      <div className="mb-2 flex items-center justify-between gap-3">
                        <span className="text-sm text-slate-300">{item.label}</span>
                        <span className="text-sm font-medium text-white">{Number(item.value || 0).toFixed(2)}</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                        <div className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-emerald-500" style={{ width: `${Math.max(5, Number(item.value || 0) * 100)}%` }} />
                      </div>
                      <div className="mt-2 text-xs text-slate-500">latency: {item.latency ?? "-"}s</div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
            <Panel>
              <SectionTitle title="Connector Status Wall" subtext="Başarı oranı ve güncel durum tek bakışta." />
              <div className="grid gap-4 md:grid-cols-2">
                {sourceHealthRows.map((row) => (
                  <div key={row.key} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-white">{row.label || row.key}</div>
                      <Pill tone={!row.enabled ? "warn" : row.status === "error" ? "danger" : "success"}>{!row.enabled ? "disabled" : row.status || "ok"}</Pill>
                    </div>
                    <div className="mt-3">
                      <GaugeBar label="Success Rate" value={Number(row.success_rate || 0)} hint={row.disabled_reason || row.notes || "source health"} color="from-emerald-500 to-cyan-500" />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-400">
                      <span>accepted={row.accepted_count ?? row.inserted ?? 0}</span>
                      <span>rejected={row.rejected_entity ?? 0}</span>
                      <span>blocked={row.blocked ?? 0}</span>
                      <span>retry={row.retries ?? 0}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
          <div className="grid gap-6 xl:grid-cols-[0.8fr_1.2fr]">
            <Panel>
              <SectionTitle title="Universe Preview" subtext="Öncelik kuyruğundaki ticker’lar" />
              <div className="space-y-3">
                {asArray(universe).map((item) => (
                  <button
                    key={item.ticker}
                    className="flex w-full items-center justify-between rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-left hover:border-emerald-700"
                    onClick={() => { setWorkspaceTicker(item.ticker); navigateToTab("workspace"); }}
                  >
                    <div>
                      <div className="font-medium text-white">{item.ticker}</div>
                      <div className="text-xs text-slate-500">{item.reason}</div>
                    </div>
                    <Pill tone={item.queue === "hot" ? "success" : item.queue === "active" ? "info" : "default"}>{item.queue}</Pill>
                  </button>
                ))}
              </div>
            </Panel>
            <Panel>
              <SectionTitle title="Near Real-Time Price Grid" subtext="Son fiyat, provider ve sparkline" />
              <div className="grid gap-4 md:grid-cols-2">
                {asArray(prices).map((row) => (
                  <Panel key={row.ticker} className="bg-slate-950/80">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-lg font-semibold text-white">{row.ticker}</div>
                      <Pill tone={row.stale ? "warn" : "success"}>{row.stale ? "stale" : "fresh"}</Pill>
                    </div>
                    <div className="mt-3 text-2xl font-semibold text-white">{row.price ?? "-"}</div>
                    <div className="mt-1 text-sm text-slate-400">{formatPct(row.change_pct)} • {row.provider}</div>
                    <div className="mt-4"><Sparkline points={row.sparkline_points} /></div>
                  </Panel>
                ))}
              </div>
            </Panel>
          </div>
          <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <Panel>
              <SectionTitle title="Accepted Source Volume" subtext="Kaynak bazlı kabul edilen canlı kayıt hacmi" />
              <MiniBarChart items={sourceVolumeItems} />
            </Panel>
            <Panel>
              <SectionTitle title="Rejected News Audit" subtext="Entity-resolution tarafından elenen aday haber örnekleri" />
              {!rejectedAuditRows.length ? (
                <div className="text-sm text-slate-500">Şu an rejected audit kaydı yok.</div>
              ) : (
                <div className="space-y-3">
                  {rejectedAuditRows.map((row) => (
                    <div key={row.id} className="rounded-xl border border-amber-900/50 bg-slate-950/60 px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Pill tone="warn">{row.source}</Pill>
                        <span className="text-xs text-slate-500">score={Number(row.score || 0).toFixed(2)}</span>
                      </div>
                      <div className="mt-2 text-sm font-medium text-white">{maybeFixMojibake(row.title)}</div>
                      <div className="mt-1 text-xs text-slate-400">{maybeFixMojibake(row.reason)}</div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>
        </div>
      ) : null}

      {activeTab === "workspace" ? (
        <TabErrorBoundary key="workspace"><div className="mt-6 grid gap-6 xl:grid-cols-[0.92fr_1.08fr]">
          <div className="space-y-6">
            <Panel>
              <SectionTitle title="Ticker seçim + otomatik analiz" subtext="Ticker değiştiğinde backend warm-ingest yapar ve gerekirse analizi yeniler." />
              <div className="flex flex-wrap items-center gap-3">
                <label className="inline-flex items-center gap-2 text-sm text-slate-300">
                  <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} /> Otomatik yenile
                </label>
                <label className="inline-flex items-center gap-2 text-sm text-slate-300">
                  <input type="checkbox" checked={autoAnalyze} onChange={(e) => setAutoAnalyze(e.target.checked)} /> Soru yazmadan otomatik analiz
                </label>
                <input className="field !w-24" value={refreshSeconds} onChange={(e) => setRefreshSeconds(e.target.value)} />
              </div>
              <div className="mt-4 grid gap-3">
                <input className="field" value={tickerSearch} onChange={(e) => setTickerSearch(e.target.value)} placeholder="Hisse ara (ASELS, THYAO...)" />
                <div className="flex flex-wrap gap-2">
                  {visibleTickers.map((item) => (
                    <button key={item.ticker} className={cx("ticker-chip", workspaceTicker === item.ticker && "ticker-chip-active")} onClick={() => setWorkspaceTicker(item.ticker)}>
                      {item.ticker}
                    </button>
                  ))}
                </div>
                <div className="relative">
                  <input className="field" value={workspaceTicker} onChange={(e) => { setWorkspaceTicker(e.target.value.toUpperCase()); fetchTickerSuggestions(e.target.value); }} placeholder="Ticker (yazarak ara)" />
                  {tickerSuggestions.length > 0 && (
                    <div className="absolute z-20 mt-1 w-full rounded-xl border border-slate-700 bg-slate-900 shadow-xl">
                      {tickerSuggestions.map((s) => (
                        <button key={s.ticker} className="block w-full px-4 py-2 text-left text-sm text-slate-200 hover:bg-slate-800" onClick={() => { setWorkspaceTicker(s.ticker); setTickerSuggestions([]); }}>{s.ticker}</button>
                      ))}
                    </div>
                  )}
                </div>
                <textarea className="field min-h-36" value={workspaceQuestion} onChange={(e) => setWorkspaceQuestion(e.target.value)} />
                <div className="flex flex-wrap gap-3">
                  <button className="btn-primary" onClick={() => runWorkspaceAnalysis(false)}>Analizi Calistir</button>
                  <button className="btn-secondary" onClick={() => runWorkspaceAnalysis(true)}>Soru Yazmadan Analiz</button>
                  <button className="btn-secondary" onClick={runKapWarmupFull} disabled={kapWarmupStatus === "running"}>Tam KAP Warmup</button>
                  <button className="btn-secondary" onClick={downloadPdfReport}>PDF Rapor Indir</button>
                </div>
                <div className="mt-2 rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
                  <div className="mb-2 text-xs uppercase tracking-widest text-slate-500">Cross-Ticker Karsilastirma</div>
                  <div className="flex gap-2">
                    <input className="field flex-1" value={compareTickers} onChange={(e) => setCompareTickers(e.target.value.toUpperCase())} placeholder="THYAO,ASELS,TUPRS" />
                    <button className="btn-secondary whitespace-nowrap" onClick={runCompare} disabled={compareBusy}>{compareBusy ? "..." : "Karsilastir"}</button>
                  </div>
                  {compareResult && (
                    <div className="mt-3 space-y-2">
                      {asArray(compareResult.comparison).map((row) => (
                        <div key={row.ticker} className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-2 text-sm">
                          <span className="font-medium text-white">{row.ticker}</span>
                          <span className="text-slate-400">{row.consistency || row.error || "-"}</span>
                          <span className="text-slate-400">conf: {typeof row.confidence === "number" ? row.confidence.toFixed(2) : "-"}</span>
                          <Pill tone={row.status === "ok" ? "success" : "danger"}>{row.status}</Pill>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-300">
                  Analiz durumu: {analysisStatus}
                  {warmStatus?.inserted_chunks_total !== undefined ? ` • warm-ingest chunk: ${warmStatus.inserted_chunks_total}` : ""}
                  {analysis?.cache_age_seconds !== undefined && analysis?.cache_age_seconds !== null ? ` • cache age: ${Math.round(analysis.cache_age_seconds)}s` : ""}
                  {kapWarmupStatus ? ` • KAP: ${kapWarmupStatus}` : ""}
                </div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(asObject(analysis?.auto_refresh_due)).map(([key, value]) => (
                    <Pill key={key} tone={value ? "warn" : "success"}>{key}: {value ? "due" : "fresh"}</Pill>
                  ))}
                </div>
              </div>
            </Panel>

            <Panel>
              <SectionTitle title="Price + Signal" subtext="Seçili ticker için fiyat, değişim ve canlı kısa nabız." />
              {selectedPrice ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-sm text-slate-400">{workspaceTicker}</div>
                      <div className="text-4xl font-semibold text-white">{selectedPrice.price ?? "-"}</div>
                    </div>
                    <Pill tone={Number(selectedPrice.change_pct || 0) >= 0 ? "success" : "danger"}>{formatPct(selectedPrice.change_pct)}</Pill>
                  </div>
                  <Sparkline points={selectedPrice.sparkline_points} />
                  <div className="text-sm text-slate-500">{formatDate(selectedPrice.market_time)} • {selectedPrice.provider}</div>
                </div>
              ) : <div className="text-sm text-slate-500">Seçili ticker için fiyat kartı henüz dolmadı.</div>}
            </Panel>

            <SummaryCardGrid items={analysisOverviewCards} />

            <Panel>
              <SectionTitle title="Ticker Dossier" subtext="Append-only audit ile tutulan son resmi durum ve değişim özeti." />
              {dossierSnapshot ? (
                <div className="space-y-4">
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                    <MetricCard label="Consistency" value={dossierSnapshot.consistency || "-"} hint="son doğrulanmış görünüm" />
                    <MetricCard label="Citation Coverage" value={Number(dossierSnapshot.citation_coverage || 0).toFixed(2)} hint="claim-level grounding" />
                    <MetricCard label="Evidence Sufficiency" value={Number(dossierSnapshot.evidence_sufficiency_score || evidenceSufficiencyScore || 0).toFixed(2)} hint="kanıt gücü birleşik skoru" />
                    <MetricCard label="Rumor Risk" value={Number(dossierSnapshot.rumor_risk_score || rumorRiskScore || 0).toFixed(2)} hint="discovery/social baskı skoru" />
                  </div>
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    <MetricCard label="Freshness" value={Number(dossierSnapshot.freshness_score || freshnessScore || 0).toFixed(2)} hint="yakın tarihli kanıt ağırlığı" />
                    <MetricCard label="Attention" value={Number(dossierSnapshot.attention_score || attentionScore || 0).toFixed(2)} hint="haber + sorgu aktivitesi" />
                    <MetricCard label="Tension Index" value={Number(dossierSnapshot.tension_index || tensionIndex || 0).toFixed(2)} hint="KAP vs haber gerilim seviyesi" />
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm leading-7 text-slate-200">{maybeFixMojibake(dossierSnapshot.why_changed || "Henüz değişim açıklaması yok.")}</div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Resmi durum</div>
                    <div className="mt-3 text-sm leading-7 text-slate-200">{maybeFixMojibake(dossierSnapshot.official_status || "Yeterli resmi özet yok.")}</div>
                  </div>
                  <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
                    <Panel className="bg-slate-950/80">
                      <div className="mb-3 text-sm font-medium text-slate-300">Source Reliability Mix</div>
                      <DonutLegend items={reliabilityDonutItems} />
                    </Panel>
                    <Panel className="bg-slate-950/80">
                      <div className="mb-3 text-sm font-medium text-slate-300">Latest Document Times</div>
                      {!latestDocTimesList.length ? (
                        <div className="text-sm text-slate-500">Henüz tarihli citation görünmüyor.</div>
                      ) : (
                        <div className="space-y-3">
                          {latestDocTimesList.map((row) => (
                            <div key={row.label} className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
                              <span className="text-sm text-slate-300">{row.label}</span>
                              <span className="text-sm text-white">{formatDate(row.value)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </Panel>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Pill tone={auditSummary?.chain_ok ? "success" : "warn"}>Audit chain: {auditSummary?.chain_ok ? "ok" : "pending"}</Pill>
                    <Pill>Events: {auditSummary?.event_count ?? 0}</Pill>
                    <Pill>Updated: {formatDate(dossierSnapshot.updated_at)}</Pill>
                    <Pill>Repairs: {auditSummary?.repair_count ?? 0}</Pill>
                    <Pill tone={marketRegime?.regime === "risk_on" ? "success" : marketRegime?.regime === "risk_off" ? "danger" : "info"}>Regime: {marketRegime?.regime || "mixed"}</Pill>
                  </div>
                </div>
              ) : <div className="text-sm text-slate-500">Dossier henüz oluşmadı.</div>}
            </Panel>

            <Panel>
              <SectionTitle title="Audit Trail" subtext="Append-only zincirde seçili ticker için son olaylar ve repair geçmişi." />
              <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
                <div className="space-y-3">
                  {!auditEventRows.length ? <div className="text-sm text-slate-500">Henüz audit event görünmüyor.</div> : auditEventRows.slice(0, 8).map((row, index) => (
                    <div key={`${row.event_id || row.created_at}-${index}`} className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Pill tone={row.event_type === "analysis" ? "success" : row.event_type === "chat" ? "info" : "warn"}>{row.event_type}</Pill>
                        <span className="text-xs text-slate-500">{formatDate(row.created_at)}</span>
                      </div>
                      <div className="mt-2 text-sm text-slate-200">{maybeFixMojibake(row.source_key || row.asset_scope || "-")}</div>
                      <div className="mt-1 text-xs text-slate-500">{row.actor || "system"} • {row.retention_tier || "permanent"}</div>
                    </div>
                  ))}
                </div>
                <div className="space-y-4">
                  <Panel className="bg-slate-950/80">
                    <div className="text-sm text-slate-400">Repair history</div>
                    {!auditRepairRows.length ? <div className="mt-3 text-sm text-slate-500">Repair kaydı yok.</div> : (
                      <div className="mt-3 space-y-3">
                        {auditRepairRows.slice(0, 4).map((row, index) => (
                          <div key={`${row.created_at}-${index}`} className="rounded-xl border border-slate-800 bg-slate-900/70 px-4 py-3">
                            <div className="flex items-center justify-between gap-3">
                              <span className="text-sm font-medium text-white">{maybeFixMojibake(row.reason)}</span>
                              <Pill tone="info">{row.repaired_rows} row</Pill>
                            </div>
                            <div className="mt-2 text-xs text-slate-500">{formatDate(row.created_at)}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </Panel>
                  <Panel className="bg-slate-950/80">
                    <div className="text-sm text-slate-400">Workspace activity</div>
                    <div className="mt-3 grid gap-3 md:grid-cols-3">
                      <MetricCard label="Chats" value={String(recentChatSessions.length)} hint="recent sessions" />
                      <MetricCard label="Uploads" value={String(recentUploadEvents.length)} hint="retained corpus" />
                      <MetricCard label="Connector Runs" value={String(recentConnectorRuns.length)} hint="latest source runs" />
                    </div>
                  </Panel>
                </div>
              </div>
            </Panel>

            <Panel>
              <SectionTitle title="Connector Status" subtext="TCMB, premium news ve sosyal katman canlı durumu." />
              <div className="grid gap-4 md:grid-cols-3">
                {connectorCards.length ? connectorCards.map((card) => (
                  <Panel key={card.label} className="bg-slate-950/80">
                    <div className="text-sm text-slate-400">{card.label}</div>
                    <div className="mt-2 text-2xl font-semibold text-white">{card.value}</div>
                    <div className="mt-2 text-sm text-slate-500">{card.hint || "Durum bilgisi mevcut."}</div>
                  </Panel>
                )) : <div className="text-sm text-slate-500 md:col-span-3">Connector snapshot henüz oluşmadı.</div>}
              </div>
            </Panel>

            <Panel>
              <SectionTitle title="Macro + Social Snapshot" subtext="Resmi makro bağlam, sosyal sinyal ve citation freshness görünümü." />
              <div className="grid gap-6 lg:grid-cols-2">
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">TCMB Macro</div>
                  <MiniBarChart items={asArray(analysis?.macro_snapshot).map((item) => ({ label: item.label, value: Number(item.value || 0) }))} valueFormatter={(v) => Number(v).toFixed(2)} />
                </div>
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Social Signal</div>
                  <MiniBarChart items={asArray(analysis?.social_signal?.theme_buckets).map((item) => ({ label: item.label, value: item.value }))} />
                </div>
              </div>
              <div className="mt-5 grid gap-3 md:grid-cols-3">
                {latestDocTimesList.length ? latestDocTimesList.map((item) => (
                  <div key={item.label} className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</div>
                    <div className="mt-2 text-sm text-white">{formatDate(item.value)}</div>
                  </div>
                )) : <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-500 md:col-span-3">Kaynak freshness kartları için yeterli citation oluşmadı.</div>}
              </div>
            </Panel>

            <Panel>
              <SectionTitle title="Open Web Research" subtext="Açık web araştırma adayları yalnız discovery/context katmanıdır; resmi kanıtın yerine geçmez." />
              <div className="mb-5 grid gap-3 sm:grid-cols-4">
                <MetricCard label="Scrape Attempt" value={String(webScraperStats.attempted ?? 0)} hint="Policy'den geçen aday URL denemesi" />
                <MetricCard label="Article Body" value={String(webScraperStats.scraped ?? 0)} hint="Makale gövdesi başarıyla okundu" />
                <MetricCard label="Robots/Policy Block" value={String(webScraperStats.blocked ?? 0)} hint="Legal policy nedeniyle geçilmedi" />
                <MetricCard label="Fetch Error" value={String(webScraperStats.errors ?? 0)} hint="Bağlantı veya entity doğrulama hatası" />
              </div>
              <div className="grid gap-6 xl:grid-cols-[0.72fr_1.28fr]">
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Theme Buckets</div>
                  <MiniBarChart items={webResearchThemes.map((item) => ({ label: item.label, value: item.value }))} />
                </div>
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Candidate Results</div>
                  {!webResearchItems.length ? <div className="text-sm text-slate-500">Açık web araştırma sonucu henüz oluşmadı.</div> : (
                    <div className="space-y-3">
                      {webResearchItems.slice(0, 6).map((row, index) => (
                        <div key={`${row.url}-${index}`} className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <Pill tone="info">score {Number(row.entity_score || 0).toFixed(2)}</Pill>
                            <Pill>rel {Number(row.source_reliability || 0).toFixed(2)}</Pill>
                          </div>
                          <div className="mt-3 text-sm font-medium leading-7 text-white">{maybeFixMojibake(row.title)}</div>
                          <div className="mt-2 text-xs text-slate-500">{maybeFixMojibake(row.query)}</div>
                          <div className="mt-2 text-sm leading-7 text-slate-300">{maybeFixMojibake(row.snippet || "Snippet yok.")}</div>
                          {row.article_preview ? (
                            <div className="mt-3 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-sm leading-7 text-emerald-50">
                              {maybeFixMojibake(row.article_preview)}
                            </div>
                          ) : row.scraper_status ? (
                            <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs leading-6 text-amber-100">
                              Scraper: {maybeFixMojibake(row.scraper_status)} {row.scraper_error ? `- ${maybeFixMojibake(row.scraper_error)}` : ""}
                            </div>
                          ) : null}
                          {row.url ? <a className="mt-3 inline-flex text-sm text-cyan-300" href={row.url} target="_blank" rel="noreferrer">Kaynağı aç</a> : null}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </Panel>
          </div>

          <div className="space-y-6">
            <Panel>
              <SectionTitle title="Analyst Output" subtext="Özet, yön, risk ve kanıt boşlukları aynı yüzeyde." />
              {latestAnalysis ? (
                <div className="space-y-5">
                  <div className="flex flex-wrap gap-2">
                    <Pill tone={analysisResponse?.consistency_assessment === "aligned" ? "success" : analysisResponse?.consistency_assessment === "contradiction" ? "danger" : "warn"}>{analysisResponse?.consistency_assessment || "-"}</Pill>
                    <Pill tone="info">Provider: {analysisResponse?.provider_used || "-"}</Pill>
                    <Pill>Coverage: {(analysisResponse?.citation_coverage_score || 0).toFixed(2)}</Pill>
                    <Pill>Güven: {(analysisResponse?.confidence || 0).toFixed(2)}</Pill>
                  </div>
                  <div className="text-sm text-slate-400">As of {formatDate(analysisResponse?.as_of_date)}</div>
                  <Panel className="bg-slate-950/80">
                    <SectionTitle title="Executive Summary" subtext="Tek bakışta okunabilir analist notu" />
                    <div className="text-base leading-8 text-slate-100">{executiveSummary || "Henüz özet oluşmadı."}</div>
                    {executiveBullets.length ? (
                      <div className="mt-4 space-y-2">
                        {executiveBullets.map((point, index) => (
                          <div key={`${point}-${index}`} className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm leading-7 text-slate-200">• {point}</div>
                        ))}
                      </div>
                    ) : null}
                  </Panel>
                  <AnalysisSections sections={analysisSections} />
                  <EvidenceGapList gaps={asArray(analysisResponse?.evidence_gaps)} />
                </div>
              ) : <div className="text-sm text-slate-500">Henüz analiz üretilmedi.</div>}
            </Panel>

            <div className="grid gap-6 2xl:grid-cols-[0.95fr_1.05fr]">
              <Panel>
                <SectionTitle title="Citations" subtext="Kaynak türlerine göre son atıflar." />
                <CitationList citations={asArray(analysisResponse?.citations)} />
              </Panel>
              <Panel>
                <SectionTitle title="Timeline" subtext="Son belgeler ve özet olay akışı." />
                <Timeline items={analysisTimeline} />
              </Panel>
            </div>

            <Panel>
              <SectionTitle title="Diagnostics" subtext="Tension timeline, weekly drift ve broker bias aynı yüzeyde." />
              <div className="grid gap-6 xl:grid-cols-2">
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Source Reliability Mix</div>
                  <MiniBarChart items={sourceReliabilityItems} valueFormatter={(v) => v.toFixed(2)} />
                </div>
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Broker Bias Lens</div>
                  <MiniBarChart items={brokerBiasItems.map((item) => ({ label: item.institution || "broker", value: item.theme_score || 0 }))} valueFormatter={(v) => v.toFixed(2)} />
                </div>
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Weekly Drift</div>
                  <MiniBarChart items={driftItems.map((item) => ({ label: item.to || item.window || "-", value: item.drift_score || 0 }))} valueFormatter={(v) => v.toFixed(2)} />
                </div>
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Tension Timeline</div>
                  <LineTrendChart items={tensionTimelineItems.map((item) => ({ label: item.week, value: item.tension_index || 0 }))} formatter={(v) => v.toFixed(2)} />
                </div>
              </div>
            </Panel>

            <Panel>
              <SectionTitle title="Source Tables" subtext="KAP, haber ve aracı kurum kayıtları tablo görünümünde." />
              <div className="space-y-5">
                {analysisTables.filter((block) => asArray(block?.rows).length).map((block) => (
                  <div key={block.title}>
                    <div className="mb-3 text-sm font-medium text-slate-300">{block.title}</div>
                    <DataTable block={block} />
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </div></TabErrorBoundary>
      ) : null}
      {activeTab === "chat" ? (
        <div className="mt-6 grid gap-6 xl:grid-cols-[0.78fr_1.22fr]">
          <div className="space-y-6">
            <Panel>
              <SectionTitle title="Research Chat" subtext="Seçili ticker, canlı kaynaklar ve yüklenen dosyalarla uzun form araştırma üretir." />
              <div className="grid gap-3">
                <input className="field" value={chatSessionId} onChange={(e) => setChatSessionId(e.target.value)} placeholder="session id" />
                <div className="flex flex-wrap gap-2">
                  {promptSuggestions.map((prompt) => (
                    <button key={prompt} className="rounded-full border border-slate-800 bg-slate-950/70 px-4 py-2 text-left text-sm text-slate-300 transition hover:border-cyan-700 hover:text-cyan-200" onClick={() => setChatInput(prompt)}>{prompt}</button>
                  ))}
                </div>
                <textarea className="field min-h-44" value={chatInput} onChange={(e) => setChatInput(e.target.value)} placeholder="Araştırma sorunu yaz" />
                <div className="flex flex-wrap gap-3">
                  <button className="btn-primary" onClick={sendChat} disabled={chatBusy}>{chatBusy ? "Gonderiliyor..." : "Chat Sorgusu Gonder"}</button>
                  <button className="btn-secondary" onClick={sendStreamingQuery} disabled={chatBusy}>Streaming Sorgu</button>
                  <button className="btn-secondary" onClick={() => { setChatMessages([]); setChatStreamEvents([]); }}>Temizle</button>
                  <button className="btn-secondary" onClick={() => { setChatInput(`${workspaceTicker} için en önemli 5 bulguyu tabloyla özetle.`); navigateToTab("chat"); }}>Hazır Özet Sorusu</button>
                  <button className="btn-secondary" onClick={downloadChatTranscript} disabled={!chatMessages.length}>Chat Dökümünü İndir</button>
                </div>
              </div>
            </Panel>
            <Panel>
              <SectionTitle title="Chat Session Snapshot" subtext="Konusma baglami, dosya kapsami ve son AI ciktisi." />
              {chatStreamEvents.length > 0 && (
                <div className="mb-4 space-y-1">
                  <div className="text-xs uppercase tracking-widest text-cyan-400">Agent Progress</div>
                  {chatStreamEvents.map((evt, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs text-slate-400">
                      <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
                      <span className="font-medium text-slate-200">{evt.node}</span>
                      {evt.docs_found !== undefined && <span>({evt.docs_found} docs)</span>}
                      {evt.consistency && <span>consistency: {evt.consistency}</span>}
                      {evt.tension !== undefined && <span>tension: {evt.tension}</span>}
                      {evt.question_type && <span>type: {evt.question_type}</span>}
                      {evt.web_results_count !== undefined && <span>web: {evt.web_results_count} results</span>}
                    </div>
                  ))}
                </div>
              )}
              <div className="grid gap-4 md:grid-cols-2">
                <MetricCard label="Ticker" value={workspaceTicker} hint="çalışılan şirket" />
                <MetricCard label="Uploads" value={String(uploads.length)} hint="session corpus" />
                <MetricCard label="Mesaj" value={String(chatMessages.length)} hint="toplam konuşma girdisi" />
                <MetricCard label="Provider" value={analysisResponse?.provider_used || providerPref} hint="aktif reasoning yolu" />
              </div>
              {latestChatPayload ? (
                <div className="mt-5 space-y-4">
                  <SummaryCardGrid items={latestChatPayload.summary_cards} />
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm leading-7 text-slate-300">Son chat yanıtı {asArray(latestChatPayload.citations).length} citation ve {asArray(latestChatPayload.evidence_gaps).length} evidence gap içeriyor.</div>
                </div>
              ) : (
                <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-500">Henüz chat yanıtı üretilmedi.</div>
              )}
            </Panel>
          </div>
          <Panel>
            <SectionTitle title="Conversation" subtext="Uzun form yanıt, karşıt kanıt, tablolar ve timeline burada birikir." />
            <div className="max-h-[920px] space-y-4 overflow-y-auto pr-1">
              {!chatMessages.length ? <div className="text-sm text-slate-500">Henüz konuşma başlatılmadı.</div> : null}
              {chatMessages.map((item, idx) => (
                <div key={`${item.role}-${idx}`} className={cx("rounded-2xl border p-4", item.role === "user" ? "border-cyan-800 bg-cyan-950/20" : "border-slate-800 bg-slate-950/70")}>
                  <div className="mb-2 text-xs uppercase tracking-[0.2em] text-slate-500">{item.role === "user" ? "Analist" : "Research Agent"}</div>
                  {item.role === "user" ? <div className="whitespace-pre-wrap text-sm leading-7 text-slate-100">{item.text}</div> : <Markdownish text={item.text} />}
                  {item.payload ? (
                    <div className="mt-4 space-y-4">
                      <SummaryCardGrid items={item.payload.summary_cards} />
                      {asArray(item.payload.tables).map((block) => <Panel key={block.title} className="bg-slate-950/80"><SectionTitle title={block.title} /><DataTable block={block} /></Panel>)}
                      <Panel className="bg-slate-950/80"><SectionTitle title="Timeline" /><Timeline items={asArray(item.payload.timeline)} /></Panel>
                      {asArray(item.payload.cross_asset_context?.crypto_context?.items).length ? (
                        <Panel className="bg-slate-950/80">
                          <SectionTitle title="Cross-Asset Context" />
                          <MiniBarChart items={asArray(item.payload.cross_asset_context.crypto_context.items).map((row) => ({ label: row.symbol, value: Number(row.change_pct_24h || 0) }))} valueFormatter={(v) => `${Number(v).toFixed(2)}%`} />
                        </Panel>
                      ) : null}
                      <Panel className="bg-slate-950/80"><SectionTitle title="Citations" /><CitationList citations={asArray(item.payload.citations)} /></Panel>
                      <EvidenceGapList gaps={asArray(item.payload.evidence_gaps)} />
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </Panel>
        </div>
      ) : null}
      {activeTab === "uploads" ? (
        <div className="mt-6 grid gap-6 xl:grid-cols-[0.84fr_1.16fr]">
          <div className="space-y-6">
            <Panel>
              <SectionTitle title="Dosya yükleme" subtext="pdf, txt, md, html, csv, json session corpus'a eklenir." />
              <div className="grid gap-4">
                <input className="field" value={chatSessionId} onChange={(e) => setChatSessionId(e.target.value)} placeholder="session id" />
                <div className={cx("rounded-2xl border border-dashed p-6 transition", dragActive ? "border-cyan-500 bg-cyan-950/10" : "border-slate-700 bg-slate-950/60")} onDragOver={(e) => { e.preventDefault(); setDragActive(true); }} onDragLeave={() => setDragActive(false)} onDrop={(e) => { e.preventDefault(); setDragActive(false); selectUploadFile(e.dataTransfer?.files?.[0]); }}>
                  <input type="file" onChange={(e) => selectUploadFile(e.target.files?.[0])} />
                  <div className="mt-3 text-sm text-slate-400">Desteklenen tipler: pdf, txt, md, html, csv, json</div>
                  <div className="mt-2 text-xs text-slate-500">Dosyayı sürükleyip bırakabilir veya seçebilirsiniz.</div>
                  {uploadPreview ? (
                    <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
                      <div className="text-sm font-medium text-white">{uploadPreview.name}</div>
                      <div className="mt-1 text-sm text-slate-400">{uploadPreview.type} • {formatBytes(uploadPreview.size)}</div>
                      <div className="mt-4 flex flex-wrap gap-3">
                        <button className="btn-primary" onClick={() => handleUpload(selectedUploadFile)} disabled={uploadBusy}>{uploadBusy ? "Yükleniyor..." : "Seçili Dosyayı Yükle"}</button>
                        <button className="btn-secondary" onClick={() => { setSelectedUploadFile(null); setUploadStatus(""); }}>Temizle</button>
                      </div>
                    </div>
                  ) : null}
                  {uploadStatus ? <div className="mt-3 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm text-slate-200">{uploadStatus}</div> : null}
                </div>
              </div>
            </Panel>
            <Panel>
              <SectionTitle title="Upload kullanım rehberi" subtext="Analyst workspace içinde dosya yüklemenin en etkili akışı." />
              <div className="space-y-3 text-sm leading-7 text-slate-300">
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">1. Ticker seç. 2. İlgili PDF/CSV/HTML dosyasını yükle. 3. Chat ekranında doğrudan dosyayı da kapsayan soru sor.</div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">Kullanıcı yüklemeleri ayrı citation tipi olarak tutulur ve yalnız istenirse query/chat akışına dahil edilir.</div>
              </div>
            </Panel>
          </div>
          <Panel>
            <SectionTitle title="Session uploads" subtext="Yüklenen dosyalar cite edilebilir corpus olarak tutulur." />
            <div className="space-y-3">
              {!uploads.length ? <div className="text-sm text-slate-500">Bu session için henüz upload yok.</div> : null}
              {asArray(uploads).map((item) => (
                <div key={item.upload_id} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-medium text-white">{item.filename}</div>
                      <div className="text-sm text-slate-400">detected_ticker: {item.detected_ticker || "-"}</div>
                    </div>
                    <Pill tone="info">{item.inserted_chunks} chunk</Pill>
                  </div>
                  <div className="mt-3 grid gap-2 text-sm text-slate-400">
                    <div>Created: {formatDate(item.created_at)}</div>
                    <div>Stored: {item.stored_path}</div>
                    {asArray(item.warnings).length ? <div>Warnings: {asArray(item.warnings).join(" | ")}</div> : null}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      ) : null}
      {activeTab === "crossasset" ? (
        <TabErrorBoundary key="crossasset"><div className="mt-6 grid gap-6">
          <div className="grid gap-6 xl:grid-cols-[0.86fr_1.14fr]">
            <Panel>
              <SectionTitle title="Cross-Asset Context" subtext="Kripto ve makro bağlam yalnız context katmanı olarak gösterilir; BIST kanıtının yerine geçmez." />
              <div className="space-y-4">
                <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm leading-7 text-slate-200">{maybeFixMojibake(crossAssetContext?.context_note || "Cross-asset context henüz oluşmadı.")}</div>
                <div className="grid gap-4 md:grid-cols-3">
                  <MetricCard label="Ticker" value={workspaceTicker} hint="aktif çalışma dosyası" />
                  <MetricCard label="Crypto Assets" value={String(cryptoItems.length)} hint="context only" />
                  <MetricCard label="Audit Chain" value={auditSummary?.chain_ok ? "verified" : "pending"} hint={`events=${auditSummary?.event_count ?? 0}`} />
                </div>
                {riskDashboardItems.length ? (
                  <div className="grid gap-4 md:grid-cols-3">
                    {riskDashboardItems.map((item) => (
                      <Panel key={item.label} className="bg-slate-950/80">
                        <GaugeBar label={item.label} value={Number(item.value || 0)} hint={maybeFixMojibake(item.hint || "")} color="from-fuchsia-500 to-cyan-500" />
                      </Panel>
                    ))}
                  </div>
                ) : null}
                {contextCards.length ? <SummaryCardGrid items={contextCards} /> : null}
                {contextSignalItems.length ? (
                  <div className="grid gap-3">
                    {contextSignalItems.map((item, index) => (
                      <div key={`${item}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm leading-7 text-slate-200">
                        {maybeFixMojibake(item)}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </Panel>
            <Panel>
              <SectionTitle title="Macro Snapshot" subtext="TCMB bağlamı ve seçili ticker fiyatı." />
              <div className="grid gap-4 lg:grid-cols-2">
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">TCMB Series</div>
                  <MiniBarChart items={asArray(macroContextItems).map((item) => ({ label: item.label, value: Number(item.value || 0) }))} valueFormatter={(v) => Number(v).toFixed(2)} />
                </div>
                <div className="grid gap-4">
                  <Panel className="bg-slate-950/80">
                    <div className="text-sm text-slate-400">Selected ticker price</div>
                    <div className="mt-2 text-3xl font-semibold text-white">{crossAssetContext?.market_price?.price ?? selectedPrice?.price ?? "-"}</div>
                    <div className="mt-2 text-sm text-slate-400">{formatPct(crossAssetContext?.market_price?.change_pct ?? selectedPrice?.change_pct)} • {crossAssetContext?.market_price?.provider || selectedPrice?.provider || "-"}</div>
                  </Panel>
                  <Panel className="bg-slate-950/80">
                    <div className="text-sm text-slate-400">Macro Pairs</div>
                    {!macroPairItems.length ? (
                      <div className="mt-3 text-sm text-slate-500">Makro pariteler henüz gelmedi.</div>
                    ) : (
                      <div className="mt-3 space-y-3">
                        {macroPairItems.map((item) => (
                          <div key={item.label} className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
                            <span className="text-sm text-slate-300">{item.label}</span>
                            <span className="text-sm font-medium text-white">{maybeFixMojibake(String(item.value ?? "-"))}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </Panel>
                </div>
              </div>
            </Panel>
          </div>
          <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
            <Panel>
              <SectionTitle title="Crypto Context Monitor" subtext="CoinGecko primary, Binance secondary." />
              {cryptoItems.length ? (
                <div className="space-y-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <MetricCard label="Market Regime" value={marketRegime?.regime || "-"} hint={maybeFixMojibake(marketRegime?.note || "cross-asset regime yok")} />
                    <MetricCard label="Top Crypto Mover" value={topCryptoMover?.symbol || "-"} hint={topCryptoMover?.change_pct_24h !== undefined ? `${Number(topCryptoMover.change_pct_24h || 0).toFixed(2)}% 24s` : "veri yok"} />
                  </div>
                  <MiniBarChart items={cryptoItems.map((item) => ({ label: item.symbol, value: Number(item.change_pct_24h || 0) }))} valueFormatter={(v) => `${Number(v).toFixed(2)}%`} />
                  <div className="grid gap-4 md:grid-cols-2">
                  {cryptoItems.map((item) => (
                    <Panel key={item.symbol} className="bg-slate-950/80">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm text-slate-400">{item.name || item.symbol}</div>
                          <div className="mt-2 text-3xl font-semibold text-white">{item.price_usd ?? "-"}</div>
                        </div>
                        <Pill tone={Number(item.change_pct_24h || 0) >= 0 ? "success" : "danger"}>{formatPct(item.change_pct_24h)}</Pill>
                      </div>
                      <div className="mt-3 text-sm text-slate-400">provider: {item.provider} {item.secondary_provider ? `| fallback: ${item.secondary_provider}` : ""}</div>
                      <div className="mt-2 text-xs text-slate-500">market_cap_rank: {item.market_cap_rank ?? "-"}</div>
                    </Panel>
                  ))}
                  </div>
                </div>
              ) : <div className="text-sm text-slate-500">Kripto context verisi henüz oluşmadı veya connector kapalı.</div>}
            </Panel>
            <Panel>
              <SectionTitle title="Narrative Drift + Tension" subtext="BIST cevabından ayrı bir bağlam paneli olarak tutulur." />
              <div className="grid gap-6">
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Narrative Drift Bars</div>
                  <MiniBarChart items={driftItems.map((item) => ({ label: item.to || item.window || "-", value: item.drift_score || 0 }))} valueFormatter={(v) => v.toFixed(2)} />
                </div>
                <div>
                  <div className="mb-3 text-sm font-medium text-slate-300">Tension Timeline</div>
                  <LineTrendChart items={tensionTimelineItems.map((item) => ({ label: item.week, value: item.tension_index || 0 }))} formatter={(v) => v.toFixed(2)} />
                </div>
              </div>
            </Panel>
          </div>
        </div></TabErrorBoundary>
      ) : null}
      {activeTab === "evaluation" ? <div className="mt-6 grid gap-6 xl:grid-cols-[0.7fr_1.3fr]"><Panel><SectionTitle title="Evaluation Controls" subtext="Heuristic-first eval ve gate snapshot" /><div className="grid gap-3"><select className="field" value={evalMode} onChange={(e) => setEvalMode(e.target.value)}><option value="heuristic">heuristic</option><option value="hybrid">hybrid</option><option value="mock">mock</option><option value="real">real</option></select><select className="field" value={evalProvider} onChange={(e) => setEvalProvider(e.target.value)}><option value="auto">auto</option><option value="ollama">ollama</option><option value="groq">groq</option><option value="gemini">gemini</option><option value="openai">openai</option><option value="together">together</option></select><input className="field" value={evalSampleSize} onChange={(e) => setEvalSampleSize(e.target.value)} /><button className="btn-primary" onClick={runEval} disabled={evalBusy}>{evalBusy ? "Çalışıyor..." : "Eval Çalıştır"}</button></div></Panel><Panel><SectionTitle title="Eval Scorecard" subtext="Ham JSON yerine metrik kartları" />{evalResult ? <div className="space-y-6"><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"><MetricCard label="Citation Coverage" value={Number(evalResult.citation_coverage || 0).toFixed(2)} /><MetricCard label="Disclaimer Presence" value={Number(evalResult.disclaimer_presence || 0).toFixed(2)} /><MetricCard label="Contradiction Accuracy" value={Number(evalResult.contradiction_detection_accuracy || 0).toFixed(2)} /><MetricCard label="Avg Confidence" value={Number(evalResult.avg_confidence || 0).toFixed(2)} /></div><Panel className="bg-slate-950/80"><div className="mb-3 text-sm font-medium text-slate-300">Gate Results</div><div className="flex flex-wrap gap-2">{Object.entries(asObject(evalResult.gate_results)).map(([key, value]) => <Pill key={key} tone={value ? "success" : "danger"}>{key}: {String(value)}</Pill>)}</div></Panel><Panel className="bg-slate-950/80"><div className="mb-3 text-sm font-medium text-slate-300">Rubric Scores</div><MiniBarChart items={Object.entries(asObject(evalResult.rubric_scores)).map(([label, value]) => ({ label, value }))} valueFormatter={(v) => v.toFixed(2)} /></Panel></div> : <div className="text-sm text-slate-500">Henüz eval sonucu oluşmadı.</div>}</Panel></div> : null}
      {activeTab === "ops" ? (
        <TabErrorBoundary key="ops"><div className="mt-6 grid gap-6">
          <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
            <Panel>
              <SectionTitle title="Audit Verification Wall" subtext="Append-only zincirin doğrulama durumu, kırılımı ve hash preview." />
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Chain Status" value={auditVerification?.ok ? "verified" : "broken"} hint={`repairs=${auditVerification?.repair_count ?? 0}`} />
                <MetricCard label="Event Count" value={String(auditVerification?.count ?? auditSummary?.event_count ?? 0)} hint={`global=${auditVerification?.global_count ?? "-"}`} />
                <MetricCard label="First Event" value={auditVerification?.first_event_at ? formatDate(auditVerification.first_event_at) : "-"} hint={auditVerification?.first_event_id || "genesis"} />
                <MetricCard label="Last Event" value={auditVerification?.last_event_at ? formatDate(auditVerification.last_event_at) : "-"} hint={auditVerification?.last_event_id || auditSummary?.last_event_type || "-"} />
              </div>
              <div className="mt-6 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
                <Panel className="bg-slate-950/80">
                  <div className="mb-3 text-sm font-medium text-slate-300">Event Type Distribution</div>
                  <MiniBarChart items={auditEventTypeItems} valueFormatter={(v) => Number(v).toFixed(0)} />
                </Panel>
                <Panel className="bg-slate-950/80">
                  <div className="mb-3 text-sm font-medium text-slate-300">Source Key Distribution</div>
                  <MiniBarChart items={auditSourceKeyItems} valueFormatter={(v) => Number(v).toFixed(0)} />
                </Panel>
              </div>
              <div className="mt-6 grid gap-6 xl:grid-cols-[0.7fr_0.7fr_0.6fr]">
                <Panel className="bg-slate-950/80">
                  <div className="mb-3 text-sm font-medium text-slate-300">Asset Scope Mix</div>
                  <DonutLegend items={auditScopeItems} />
                </Panel>
                <Panel className="bg-slate-950/80">
                  <div className="mb-3 text-sm font-medium text-slate-300">Ticker Breakdown</div>
                  <MiniBarChart items={auditTickerItems} valueFormatter={(v) => Number(v).toFixed(0)} />
                </Panel>
                <Panel className="bg-slate-950/80">
                  <div className="mb-3 text-sm font-medium text-slate-300">Hash Preview</div>
                  <div className="space-y-3 text-xs text-slate-400">
                    <div>
                      <div className="uppercase tracking-[0.18em] text-slate-500">Last Hash</div>
                      <div className="mt-1 break-all text-slate-300">{auditVerification?.last_hash || "-"}</div>
                    </div>
                    {auditVerification?.broken_at ? (
                      <div>
                        <div className="uppercase tracking-[0.18em] text-rose-400">Broken At</div>
                        <div className="mt-1 break-all text-rose-200">{auditVerification.broken_at}</div>
                      </div>
                    ) : null}
                    <div>
                      <div className="uppercase tracking-[0.18em] text-slate-500">Last Repair</div>
                      <div className="mt-1 text-slate-300">{auditVerification?.last_repair_at ? formatDate(auditVerification.last_repair_at) : "-"}</div>
                    </div>
                  </div>
                </Panel>
              </div>
              <div className="mt-6 grid gap-6 md:grid-cols-2">
                <Panel className="bg-slate-950/80">
                  <div className="mb-3 text-sm font-medium text-slate-300">Chain Head Preview</div>
                  {!auditHeadPreview.length ? <div className="text-sm text-slate-500">Head preview yok.</div> : (
                    <div className="space-y-3">
                      {auditHeadPreview.map((row) => (
                        <div key={row.event_id} className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-sm font-medium text-white">{row.event_type}</span>
                            <Pill tone="info">{row.ticker || row.asset_scope}</Pill>
                          </div>
                          <div className="mt-2 text-xs text-slate-500">{formatDate(row.created_at)} • {row.source_key}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </Panel>
                <Panel className="bg-slate-950/80">
                  <div className="mb-3 text-sm font-medium text-slate-300">Chain Tail Preview</div>
                  {!auditTailPreview.length ? <div className="text-sm text-slate-500">Tail preview yok.</div> : (
                    <div className="space-y-3">
                      {auditTailPreview.map((row) => (
                        <div key={row.event_id} className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-sm font-medium text-white">{row.event_type}</span>
                            <Pill tone="success">{row.ticker || row.asset_scope}</Pill>
                          </div>
                          <div className="mt-2 text-xs text-slate-500">{formatDate(row.created_at)} • {row.source_key}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </Panel>
              </div>
            </Panel>
            <Panel>
              <SectionTitle title="Connector Status Wall" subtext="Ops tarafında enabled/disabled/error dağılımı ve canlı oranlar." />
              <div className="grid gap-4 md:grid-cols-2">
                <MetricCard label="Enabled" value={String(enabledSourceCount)} hint="çalışabilir kaynak sayısı" />
                <MetricCard label="Disabled" value={String(disabledSourceCount)} hint="anahtar/policy bekleyenler" />
                <MetricCard label="Errors" value={String(errorSourceCount)} hint="son çevrimde hata" />
                <MetricCard label="Fresh Doc Ratio" value={metrics ? Number(metrics.fresh_doc_ratio || 0).toFixed(2) : "-"} hint="global canlı ingest tazeliği" />
              </div>
              <div className="mt-6">
                <div className="mb-3 text-sm font-medium text-slate-300">Connector Success Rate</div>
                <MiniBarChart items={sourceSuccessItems} valueFormatter={(v) => Number(v).toFixed(2)} />
              </div>
              <div className="mt-6 space-y-3">
                {sourceHealthRows.map((row) => (
                  <div key={row.key} className="rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium text-white">{row.label || row.key}</div>
                        <div className="text-xs text-slate-500">{row.asset_scope || "-"} • {row.authority_level || "-"}</div>
                      </div>
                      <Pill tone={!row.enabled ? "warn" : row.status === "error" ? "danger" : "success"}>{!row.enabled ? "disabled" : row.status || "ok"}</Pill>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-slate-400 md:grid-cols-2">
                      <div>success={Number(row.success_rate || 0).toFixed(2)}</div>
                      <div>error={Number(row.error_rate || 0).toFixed(2)}</div>
                      <div>fetched={row.fetched ?? 0}</div>
                      <div>accepted={row.accepted_count ?? row.inserted ?? 0}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
          <Panel>
            <SectionTitle title="Ops Console" subtext="Provider health, kaynak kataloğu ve son hata listesi" />
            <div className="grid gap-6 xl:grid-cols-3">
              <div>
                <div className="mb-3 text-sm font-medium text-slate-300">Provider Registry</div>
                <div className="space-y-3">
                  {providerHealthRows.map((row) => (
                    <div key={row.label} className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                      <span className="text-slate-300">{row.label}</span>
                      <Pill tone={row.value === "true" ? "success" : "warn"}>{row.value}</Pill>
                    </div>
                  ))}
                  <div className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm text-slate-300">
                    Default LLM: <span className="text-white">{providerRegistry?.defaults?.llm_default || "-"}</span>
                    <br />
                    Embedding: <span className="text-white">{providerRegistry?.defaults?.embedding_provider || "-"} / {typeof providerRegistry?.defaults?.embedding_model === "object" ? JSON.stringify(providerRegistry.defaults.embedding_model) : String(providerRegistry?.defaults?.embedding_model || "-")}</span>
                  </div>
                </div>
              </div>
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-300">Source Catalog</span>
                  <button onClick={runWarmUpAllSources} disabled={warmUpBusy} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50">
                    {warmUpBusy ? "Aktive ediliyor..." : "Tum Kaynaklari Aktive Et"}
                  </button>
                </div>
                {warmUpResult && (
                  <div className={`mb-3 rounded-lg border px-3 py-2 text-xs ${warmUpResult.error ? "border-rose-800 bg-rose-950/30 text-rose-300" : "border-emerald-800 bg-emerald-950/30 text-emerald-300"}`}>
                    {warmUpResult.error ? warmUpResult.error : `${warmUpResult.activated}/${warmUpResult.total} kaynak aktive edildi.`}
                  </div>
                )}
                <div className="space-y-3">
                  {asArray(sourceCatalog).map((item) => (
                    <div key={item.key} className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium text-white">{item.label}</span>
                        <Pill tone={item.enabled ? "success" : "warn"}>{item.legal_mode}</Pill>
                      </div>
                      <div className="mt-1 text-xs text-slate-500">{item.authority_level} • {item.asset_scope} • {item.ticker_resolution_method}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-3 text-sm font-medium text-slate-300">Last Errors + Audit</div>
                <div className="space-y-3">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm text-slate-300">
                    Audit Chain: <span className="text-white">{auditSummary?.chain_ok ? "verified" : "pending"}</span>
                    <br />
                    Event Count: <span className="text-white">{auditSummary?.event_count ?? 0}</span>
                    <br />
                    Last Event: <span className="text-white">{formatDate(auditSummary?.last_event_at)}</span>
                  </div>
                  {asArray(metrics?.last_errors).length ? asArray(metrics?.last_errors).map((item) => (
                    <div key={item} className="rounded-xl border border-rose-900/60 bg-rose-950/10 px-4 py-3 text-sm text-rose-200">{maybeFixMojibake(item)}</div>
                  )) : <div className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm text-slate-500">Son hata kaydı yok.</div>}
                </div>
              </div>
            </div>
          </Panel>
          <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
            <Panel>
              <SectionTitle title="Source Error Rate" subtext="Rejected + blocked oranı yüksek kaynakları hızlı gör." />
              <MiniBarChart items={sourceHealthRows.map((row) => ({ label: row.label || row.key, value: Number(row.error_rate || 0) }))} valueFormatter={(v) => v.toFixed(2)} />
            </Panel>
            <Panel>
              <SectionTitle title="Source Counts" subtext="Kaynak bazlı accepted count özet görünümü" />
              <div className="space-y-3">
                {sourceHealthRows.map((row) => (
                  <div key={row.key} className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-medium text-white">{row.label}</span>
                      <span className="text-sm text-slate-400">{row.accepted_count ?? row.inserted ?? 0}</span>
                    </div>
                    <div className="mt-2 text-xs text-slate-500">{Object.entries(asObject(row.source_counts)).map(([label, value]) => `${label}: ${value}`).join(" • ") || "Henüz kaynak kırılımı yok."}</div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
          <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
            <Panel>
              <SectionTitle title="Recent Connector Runs" subtext="Son canlı connector çağrıları ve durumları." />
              <div className="space-y-3">
                {!recentConnectorRuns.length ? <div className="text-sm text-slate-500">Henüz connector run kaydı görünmüyor.</div> : recentConnectorRuns.slice(0, 8).map((row, index) => (
                  <div key={`${row.source_key}-${row.created_at}-${index}`} className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium text-white">{row.source_key}</div>
                        <div className="text-xs text-slate-500">{formatDate(row.created_at)}</div>
                      </div>
                      <Pill tone={row.status === "ok" ? "success" : row.status === "disabled" ? "warn" : "danger"}>{row.status}</Pill>
                    </div>
                    <div className="mt-2 text-xs text-slate-500">fetched={row.fetched} • inserted={row.inserted} • rejected={row.rejected} • blocked={row.blocked}</div>
                  </div>
                ))}
              </div>
            </Panel>
            <Panel>
              <SectionTitle title="Audit Repairs" subtext="Legacy zincir migration ve sonraki repair kayıtları." />
              <div className="space-y-3">
                {!auditRepairRows.length ? <div className="text-sm text-slate-500">Audit repair kaydı yok.</div> : auditRepairRows.map((row, index) => (
                  <div key={`${row.created_at}-${index}`} className="rounded-xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-white">{maybeFixMojibake(row.reason)}</div>
                      <Pill tone="info">{row.repaired_rows} repair</Pill>
                    </div>
                    <div className="mt-2 text-xs text-slate-500">{formatDate(row.created_at)}</div>
                    {row.broken_at ? <div className="mt-1 text-xs text-slate-500">broken_at: {row.broken_at}</div> : null}
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </div></TabErrorBoundary>
      ) : null}
      <div className="mt-8 rounded-2xl border border-slate-800 bg-slate-950/70 px-5 py-4 text-center text-sm text-slate-400">This system does not provide investment advice.</div>
    </div>
  );
}

export default function Page() {
  return <DashboardApp initialTab="overview" />;
}

