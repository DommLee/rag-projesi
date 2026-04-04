from app.agent.nodes import AgentNodes


def test_turkish_intent_routing_works_with_utf8() -> None:
    assert AgentNodes._question_type("ASELS için son 6 ay KAP bildirimleri nelerdir?") == "kap_disclosure_types"
    assert AgentNodes._question_type("Aracı kurum raporlarında ortak temalar neler?") == "brokerage_narrative"
    assert AgentNodes._question_type("Haberler KAP ile çelişiyor mu?") == "consistency_check"
    assert AgentNodes._question_type("Anlatı zaman içinde nasıl değişti?") == "narrative_evolution"

