 = New-Object System.Text.UTF8Encoding(False)

function Write-Utf8NoBom([string], [string]) {
  [System.IO.File]::WriteAllText((Resolve-Path ), , )
}

 = 'app\\agent\\nodes.py'
 = [System.IO.File]::ReadAllText((Resolve-Path ))
 = .Replace('from app.utils.analytics import disclosure_news_tension_index', "from app.utils.analytics import disclosure_news_tension_index
from app.utils.text import normalize_visible_text")
 = [regex]::Replace(, '(?s)@staticmethod\s+def _normalize_question\(text: str\) -> str:.*?\n\s+@staticmethod', @'
    @staticmethod
    def _normalize_question(text: str) -> str:
        lowered = normalize_visible_text(text).lower()
        normalized = unicodedata.normalize("NFKD", lowered)
        ascii_safe = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return (
            ascii_safe.replace("ı", "i")
            .replace("ğ", "g")
            .replace("ş", "s")
            .replace("ç", "c")
            .replace("ö", "o")
            .replace("ü", "u")
        )

    @staticmethod
'@)
 = .Replace('title=chunk.title or f"{chunk.source_type.value} document",', 'title=normalize_visible_text(chunk.title or f"{chunk.source_type.value} document"),')
 = .Replace('institution=chunk.institution,', 'institution=normalize_visible_text(chunk.institution),')
 = .Replace('snippet=chunk.content[:220],', 'snippet=normalize_visible_text(chunk.content)[:220],')
 = [regex]::Replace(, '(?s)\s+mapping = \{.*?\n\s+\}', @'
        mapping = {
            "low": 0.35,
            "medium": 0.6,
            "high": 0.85,
            "very_low": 0.2,
            "very_high": 0.95,
            "dusuk": 0.35,
            "düşük": 0.35,
            "orta": 0.6,
            "yuksek": 0.85,
            "yüksek": 0.85,
        }
'@, 1)
 = [regex]::Replace(, '(?s)def reretriever\(self, state: AgentState\) -> AgentState:.*?return \{"pass2_docs": docs\}', @'
    def reretriever(self, state: AgentState) -> AgentState:
        docs = self.retriever.retrieve(
            query=f"{state['question']} resmi açıklama medya karşılaştırması",
            ticker=state["ticker"],
            source_types=[SourceType.KAP, SourceType.NEWS, SourceType.BROKERAGE],
            as_of_date=state.get("as_of_date"),
            top_k=self.settings.max_top_k + 4,
        )
        return {"pass2_docs": docs}
'@)
 = [regex]::Replace(, '(?s)def counterfactual_probe\(self, state: AgentState\) -> AgentState:.*?return \{"counterfactual_docs": docs\}', @'
    def counterfactual_probe(self, state: AgentState) -> AgentState:
        planned = set(state.get("source_plan") or [])
        opposing = [s for s in [SourceType.KAP, SourceType.NEWS, SourceType.BROKERAGE] if s not in planned]
        if not opposing:
            opposing = [SourceType.NEWS, SourceType.KAP]
        docs = self.retriever.retrieve(
            query=f"Bu soruya ters yönden bakan kanıtlar: {state['question']}",
            ticker=state["ticker"],
            source_types=opposing,
            as_of_date=state.get("as_of_date"),
            top_k=max(3, self.settings.max_top_k // 2),
        )
        return {"counterfactual_docs": docs}
'@)
 = [regex]::Replace(, 'answer_tr = append_disclaimer\(state\.get\("refusal_tr"\) or ".*?"\)', 'answer_tr = append_disclaimer(state.get("refusal_tr") or "Bu istek politika gereği engellendi.")')
 = .Replace('f"[{idx}] source={doc.source_type.value} date={doc.date.date()} institution={doc.institution}\n"', 'f"[{idx}] source={doc.source_type.value} date={doc.date.date()} institution={normalize_visible_text(doc.institution)}\n"')
 = .Replace('f"title={doc.title}\n{doc.content[:450]}"', 'f"title={normalize_visible_text(doc.title)}\n{normalize_visible_text(doc.content)[:450]}"')
 = [regex]::Replace(, '(?s)answer_tr = parsed\.get\("answer_tr"\) or \(.*?\n\s+\)', @'
        answer_tr = parsed.get("answer_tr") or (
            f"{state['ticker']} için kanıtlar {state.get('consistency_assessment', 'inconclusive')} görünmektedir. "
            "Detaylar aşağıdaki atıflarda listelenmiştir."
        )
'@, 1)
 = .Replace('        answer_en = parsed.get("answer_en") or (' + [Environment]::NewLine + '            f"For {state[''ticker'']}, evidence appears {state.get(''consistency_assessment'', ''inconclusive'')}. "' + [Environment]::NewLine + '            "Details are listed in citations."' + [Environment]::NewLine + '        )', '        answer_en = parsed.get("answer_en") or (' + [Environment]::NewLine + '            f"For {state[''ticker'']}, evidence appears {state.get(''consistency_assessment'', ''inconclusive'')}. "' + [Environment]::NewLine + '            "Details are listed in citations."' + [Environment]::NewLine + '        )' + [Environment]::NewLine + '        answer_tr = normalize_visible_text(answer_tr)' + [Environment]::NewLine + '        answer_en = normalize_visible_text(answer_en)')
 = [regex]::Replace(, 'if ".*?" not in answer_tr\.lower\(\):\s+answer_tr = f"\{as_of_text\} .*?, \{answer_tr\}"', 'if "itibarıyla" not in normalize_visible_text(answer_tr).lower():
            answer_tr = f"{as_of_text} itibarıyla, {answer_tr}"')
 = .Replace('gaps = list(dict.fromkeys(gaps_tr + gaps_en))', 'gaps = list(dict.fromkeys(normalize_visible_text(item) for item in gaps_tr + gaps_en if item))')
 = .Replace('[f"Ungrounded claim (TR): {claim}" for claim in tr_grounding.ungrounded_claims[:3]]', '[normalize_visible_text(f"Ungrounded claim (TR): {claim}") for claim in tr_grounding.ungrounded_claims[:3]]')
 = .Replace('[f"Ungrounded claim (EN): {claim}" for claim in en_grounding.ungrounded_claims[:3]]', '[normalize_visible_text(f"Ungrounded claim (EN): {claim}") for claim in en_grounding.ungrounded_claims[:3]]')
Write-Utf8NoBom  

 = 'app\\models\\providers.py'
 = [System.IO.File]::ReadAllText((Resolve-Path ))
 = .Replace('KAP kaynaÄŸÄ±nda sÄ±nÄ±rlÄ± kanÄ±t bulundu.', 'KAP kaynağında sınırlı kanıt bulundu.')
 = .Replace('Haber kaynaÄŸÄ±nda sÄ±nÄ±rlÄ± kanÄ±t bulundu.', 'Haber kaynağında sınırlı kanıt bulundu.')
 = .Replace('AracÄ± kurum raporlarÄ±nda sÄ±nÄ±rlÄ± kanÄ±t bulundu.', 'Aracı kurum raporlarında sınırlı kanıt bulundu.')
 = .Replace('iÃ§in kaynaklar', 'için kaynaklar')
 = .Replace('gÃ¶rÃ¼nÃ¼m veriyor.', 'görünüm veriyor.')
 = .Replace('KAP Ã¶zeti', 'KAP özeti')
 = .Replace('Haber Ã¶zeti', 'Haber özeti')
 = .Replace('AracÄ± kurum Ã¶zeti', 'Aracı kurum özeti')
 = .Replace('KanÄ±t yetersiz.', 'Kanıt yetersiz.')
Write-Utf8NoBom  

 = 'app\\service.py'
 = [System.IO.File]::ReadAllText((Resolve-Path ))
if ( -notmatch 'from app.utils.text import normalize_visible_text') {
   = .Replace('from app.utils.analytics import broker_bias_lens, disclosure_news_tension_index, narrative_drift_radar', "from app.utils.analytics import broker_bias_lens, disclosure_news_tension_index, narrative_drift_radar
from app.utils.text import normalize_visible_text")
}
 = .Replace('return "Yeterli kanit bulunamadi."', 'return "Yeterli kanıt bulunamadı."')
 = .Replace('snippet = citation.snippet.strip().replace("\n", " ")', 'snippet = normalize_visible_text(citation.snippet).strip().replace("\n", " ")')
 = .Replace('Kaynaklar genel olarak uyumlu gorunuyor.', 'Kaynaklar genel olarak uyumlu görünüyor.')
 = .Replace('Kaynaklar arasynda belirgin celiski sinyali var.', 'Kaynaklar arasında belirgin çelişki sinyali var.')
 = .Replace('Kanita dayali karar icin veri yetersiz.', 'Kanıta dayalı karar için veri yetersiz.')
 = .Replace('Durum su an belirsiz veya karisik.', 'Durum şu an belirsiz veya karışık.')
Write-Utf8NoBom  
