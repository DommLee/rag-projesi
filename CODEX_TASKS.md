# CODEX TASKS — BIST Agentic RAG Profesyonellestirme

Bu dosya, uygulamayi profesyonel seviyeye cikaracak gorev listesini icerir.
Her gorev bagimsiz olarak uygulanabilir. Oncelik sirasi: P0 > P1 > P2 > P3.

---

## P0 — Kritik Iyilestirmeler

### 1. GraphRAG Entity-Relationship Layer
**Dosyalar:** Yeni `app/knowledge_graph/` modulu
**Aciklama:** BIST sirketleri arasindaki iliskileri (holding yapisi, ortak yonetim kurulu uyeleri, sektor baglantilari) bir bilgi grafi olarak modelle. Neo4j veya NetworkX ile. "KOCHO'nun istirak yaptigi sirketler hangileri?" gibi iliskisel sorgulari cevapla.
**Adimlar:**
- `app/knowledge_graph/graph_builder.py` — KAP verilerinden entity extraction
- `app/knowledge_graph/query_engine.py` — Graf sorgu motoru
- `app/agent/nodes.py` intent_router'a `relationship_query` tipi ekle
- Agent pipeline'a graph retrieval node ekle

### 2. Multi-Agent Debate / Verification
**Dosyalar:** `app/agent/debate.py`, `app/agent/graph.py`
**Aciklama:** Tek agent yerine, farkli perspektiflerden bakan 2-3 agent calistir (bogazici/bearish/neutral). Sonuclari karsilastirip en saglikli sentezi sec. Contradiction detection'i dramatik olarak iyilestirir.
**Adimlar:**
- `app/agent/debate.py` — DebateOrchestrator sinifi: ayni soruyu farkli system prompt'larla 2-3 kez calistir
- Her agent'in cevabini karsilastir, ortak ve celisik noktalari bul
- Final cevabi consensus'a gore olustur
- `app/api/main.py` — `/v1/query/debate` endpoint

### 3. Cohere Rerank v3.5 Entegrasyonu (Production)
**Dosyalar:** `app/retrieval/rerank.py`, `app/config.py`, `.env.example`
**Aciklama:** `try_cross_encoder_rerank` fonksiyonu mevcut ama Cohere API key olmadan calismaz. `.env.example`'a `COHERE_API_KEY` ekle, config'e `cohere_api_key` field ekle, rerank pipeline'da otomatik aktif et.
**Adimlar:**
- `app/config.py` — `cohere_api_key: str = ""` ekle
- `app/retrieval/rerank.py` — settings'den key oku
- `.env.example` — `COHERE_API_KEY=` ekle
- `requirements.txt` — `cohere>=5.0` ekle
- Retrieval trace'e "cohere_rerank" step ekle

### 4. Weaviate Hybrid Search Alpha Tuning
**Dosyalar:** `app/vectorstore/weaviate_store.py`, `app/config.py`
**Aciklama:** Weaviate'in hybrid search'inde alpha parametresi (BM25 vs vector agirligi) su an default. Soru tipine gore dinamik alpha ayarla: ticker lookup icin BM25 agirlikli (alpha=0.3), tematik sorgularda vector agirlikli (alpha=0.8).
**Adimlar:**
- `app/config.py` — `weaviate_hybrid_alpha_default: float = 0.5` ekle
- `app/vectorstore/weaviate_store.py` search() — alpha parametresi kabul et
- `app/retrieval/retriever.py` — question_type'a gore alpha sec
- Test: ticker query vs. thematic query icin farkli sonuclar dogrula

### 5. Turkish Financial Sentiment Scorer
**Dosyalar:** Yeni `app/nlp/sentiment.py`
**Aciklama:** Her haber chunk'ina Turkce sentiment skoru ekle (pozitif/negatif/notr). Retrieval sirasinda sentiment metadata olarak filtrele veya agirliklandir. HuggingFace'den savasy/bert-base-turkish-sentiment veya dbmdz/bert-base-turkish-cased kullan.
**Adimlar:**
- `app/nlp/sentiment.py` — TurkishSentimentScorer sinifi (HuggingFace model lazy load)
- `app/ingestion/chunking.py` — chunk metadata'sina `sentiment_score` ekle
- `app/schemas.py` — DocumentChunk'a `sentiment_score: float = 0.0` field
- `app/retrieval/rerank.py` — rerank'ta sentiment'i agirlik olarak kullan

---

## P1 — Onemli Gelistirmeler

### 6. Parallel Scatter-Gather Retrieval (LangGraph Send)
**Dosyalar:** `app/agent/graph.py`, `app/agent/nodes.py`
**Aciklama:** Su an KAP + News + Brokerage sirali retrieve ediliyor. LangGraph'in `Send()` API'si ile paralel calistir. Latency %40-60 duser.
**Adimlar:**
- `app/agent/graph.py` — retriever_pass1'i 3 paralel node'a bol (retriever_kap, retriever_news, retriever_brokerage)
- Sonuclari bir gather node'da birlestir
- State'e `parallel_retrieval_latency_ms` ekle

### 7. Streaming Chat Frontend Iyilestirmesi
**Dosyalar:** `frontend/app/page.jsx`
**Aciklama:** Streaming Sorgu butonu calisiyor ama UX iyilestirilebilir:
- Agent adimlarini progress bar olarak goster (intent -> source plan -> retrieval -> verification -> composition)
- Her adimin suresi (ms) gosterilsin
- Typing indicator animasyonu
- Error state'leri icin retry butonu
**Adimlar:**
- `frontend/app/page.jsx` — `AgentProgressBar` componenti yaz
- Her SSE event'i icin animasyonlu step gostergesi
- Completion yuzdesi hesapla (current_step / total_steps)

### 8. TULIP Turkish Financial LLM Entegrasyonu
**Dosyalar:** `app/models/providers.py`, `app/config.py`
**Aciklama:** TULIP (Llama 3.1 8B / Qwen 2.5 7B Turkce finans fine-tune) modelini Ollama uzerinden kullanilabilir yap. Turkce finansal terminolojiyi cok daha iyi anlar ("memzuc", "karsilik", "tedbirli kazanc").
**Adimlar:**
- `app/config.py` — `tulip_model_name: str = "tulip-finance-tr"` ekle
- `app/models/providers.py` — Ollama provider'a TULIP modeli secenegi ekle
- README'ye TULIP kurulum talimati ekle

### 9. Evaluation Dashboard Zenginlestirme
**Dosyalar:** `frontend/app/page.jsx`
**Aciklama:** Evaluation tab'ini daha detayli yap:
- Soru bazinda pass/fail tablosu
- Metrik trend grafikleri (son 10 eval run karsilastirmasi)
- Gate failure root cause analizi (retrieval mi? generation mi?)
- Export: eval sonuclarini CSV/JSON olarak indir
**Adimlar:**
- Backend: `/v1/eval/history` endpoint — son N eval sonucunu dondur
- Frontend: Recharts ile metrik trend ciz
- Per-question detail table

### 10. Webhook Alert Dispatch
**Dosyalar:** `app/alerts.py`, `app/config.py`
**Aciklama:** Alert'ler su an sadece in-memory. Onemli alert'leri Slack/Discord/email webhook'una gonder.
**Adimlar:**
- `app/config.py` — `alert_webhook_url: str = ""`, `alert_webhook_type: str = "slack"`
- `app/alerts.py` — `_dispatch_webhook()` metodu: Slack/Discord JSON format
- Sadece CRITICAL seviye alert'leri gonder
- Test: mock webhook ile dispatch dogrula

### 11. Query Result Caching with Redis
**Dosyalar:** `app/service.py`, `app/config.py`
**Aciklama:** Su an query cache in-memory dict. Redis'e tasi ki birden fazla worker instance'i ayni cache'i kullansin. TTL: 1 saat.
**Adimlar:**
- `app/cache/redis_cache.py` — RedisQueryCache sinifi
- `app/service.py` — `_query_cache` yerine RedisQueryCache kullan
- `app/config.py` — `redis_url: str = "redis://localhost:6379/0"`
- Docker-compose'da redis servisi zaten var, baglanti kur

### 12. Rate Limiting & API Throttling
**Dosyalar:** `app/api/main.py`, Yeni `app/api/rate_limiter.py`
**Aciklama:** API'ye rate limiting ekle (slowapi veya custom). IP bazli ve token bazli limitleme.
**Adimlar:**
- `requirements.txt` — `slowapi>=0.1.9` ekle
- `app/api/rate_limiter.py` — Limiter configuration
- `app/api/main.py` — Her endpoint'e uygun limit (query: 30/min, ingest: 10/min, eval: 2/min)

---

## P2 — Ileri Seviye Ozellikler

### 13. Financial Table Extraction (Document AI)
**Dosyalar:** Yeni `app/ingestion/table_extractor.py`
**Aciklama:** KAP bildirimlerinde ve broker raporlarindaki finansal tablolari (gelir tablosu, bilanco) yapisal olarak cikart. `unstructured` veya `camelot` kutuphanesi ile.
**Adimlar:**
- `app/ingestion/table_extractor.py` — PDF'den tablo cikarma
- Tablolari JSON'a donustur ve chunk metadata'sina ekle
- Agent'in composer'inda tablo verisini kullanarak sayisal cevaplar uret

### 14. A/B Testing Framework
**Dosyalar:** Yeni `app/evaluation/ab_testing.py`
**Aciklama:** Farkli prompt varyasyonlari, LLM provider'lar veya retrieval stratejileri karsilastir. Her query'de rastgele variant sec, metrikleri logla, istatistiksel anlamlilik hesapla.
**Adimlar:**
- `app/evaluation/ab_testing.py` — ABTestManager sinifi
- Variant config: prompt_a vs prompt_b, provider_a vs provider_b
- Metrikleri audit ledger'a kaydet
- `/v1/eval/ab-report` endpoint

### 15. Scheduled Report Generation
**Dosyalar:** `app/jobs.py`, `app/api/main.py`
**Aciklama:** Haftalik/aylik otomatik rapor ureti. Belirli ticker'lar icin zamanlanmis analiz calistir ve PDF'e kaydet.
**Adimlar:**
- `app/jobs.py` — ScheduledReportJob sinifi
- Cron-style zamanlama (APScheduler)
- Her run'da secili ticker'lar icin query + PDF export
- Email dispatch (opsiyonel)

### 16. User Authentication & Multi-Tenant
**Dosyalar:** Yeni `app/auth/` modulu
**Aciklama:** JWT tabanli auth ekle. Kullanici bazli session, upload, chat izolasyonu. Rol bazli erisim (admin, analyst, viewer).
**Adimlar:**
- `app/auth/jwt.py` — Token create/verify
- `app/auth/models.py` — User model (SQLite)
- `app/api/main.py` — Auth middleware
- Frontend: login ekrani

### 17. Observability: LangSmith / Langfuse Entegrasyonu
**Dosyalar:** `app/agent/graph.py`, `app/config.py`
**Aciklama:** Her agent run'ini LangSmith veya Langfuse'a trace olarak gonder. Latency breakdown, token usage, retrieval quality gorunur olsun.
**Adimlar:**
- `app/config.py` — `langfuse_public_key`, `langfuse_secret_key`, `langfuse_host`
- `app/agent/graph.py` — LangGraph callback handler ekle
- Docker-compose'da langfuse profili zaten var, baglanti kur

### 18. Incremental Embedding Updates
**Dosyalar:** `app/vectorstore/weaviate_store.py`
**Aciklama:** Yeni dokumanlar eklendiginde sadece yeni chunk'lari embed et, eskilerini yeniden hesaplama. Delta-sync ile %80 embedding maliyeti dususu.
**Adimlar:**
- `app/vectorstore/weaviate_store.py` — chunk_id bazli varlik kontrol
- Sadece yeni chunk'lari embed ve insert et
- Var olanlari skip et (hash bazli)

---

## P3 — Nice-to-Have / Gelecek Vizyon

### 19. Mobile Responsive Frontend
**Aciklama:** Next.js dashboard'u mobilde kullanilabilir yap. Responsive breakpoint'ler, touch-friendly butonlar.

### 20. Multilingual Support (EN/TR/AR)
**Aciklama:** Arapca ve diger dillerde soru-cevap destegi. Otomatik dil algilama.

### 21. Voice Query (Speech-to-Text)
**Aciklama:** Mikrofon ile soru sorma. Whisper API entegrasyonu.

### 22. Portfolio Tracker
**Aciklama:** Kullanicinin BIST portfoyunu tanimla, portfoy bazli alert ve analiz.

### 23. Automated KAP Monitoring Daemon
**Aciklama:** 7/24 KAP'i izleyen daemon. Yeni ozel durum aciklamasi geldiginde otomatik ingest + alert.

### 24. Backtesting Engine
**Aciklama:** Gecmis veriler uzerinde RAG pipeline'in dogrulugunu test et. "3 ay once bu soruya ne cevap verirdi?" analizi.

### 25. Export to PowerPoint
**Aciklama:** Analiz sonuclarini PPTX sunumuna cevir. Yonetim toplantisi formati.

---

## Nasil Kullanilir

Her gorev icin Codex'e su formatta komut verin:

```
Gorev #3'u uygula: Cohere Rerank v3.5 Entegrasyonu.
Dosyalar: app/retrieval/rerank.py, app/config.py, .env.example, requirements.txt
Adimlar: [yukaridaki adimlari aynen yapistir]
Tamamlaninca pytest calistir ve 100/100 eval'i dogrula.
```
