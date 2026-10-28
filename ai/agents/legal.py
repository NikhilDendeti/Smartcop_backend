"""General legal and procedure information, for the public and for officers.

It explains how things usually work. It does not advise on a specific case, and it never shows a
citation: there is no document store behind it yet, so any citation would be invented."""

import re

from ai import gateway
from ai.agents.common import ask_model
from ai.guards import reply_is_safe, sanitize_incident
from ai.schemas import LEGAL_SCHEMA, LEGAL_SCHEMA_NAME, parse_legal
from users.access import CITIZEN, actor_role
from users.consent import require_consent

DISCLAIMERS = {
    "en": "This is general information written by AI. It is not legal advice. For your own case, speak to a lawyer or your police station.",
    "hi": "यह AI द्वारा लिखी गई सामान्य जानकारी है। यह कानूनी सलाह नहीं है। अपने मामले के लिए किसी वकील या अपने पुलिस स्टेशन से बात करें।",
    "te": "ఇది AI రాసిన సాధారణ సమాచారం. ఇది న్యాయ సలహా కాదు. మీ స్వంత కేసు కోసం న్యాయవాదిని లేదా మీ పోలీస్ స్టేషన్‌ను సంప్రదించండి.",
}
OUT_OF_SCOPE = {
    "en": "I can only answer questions about law, police procedure and the complaint process.",
    "hi": "मैं केवल कानून, पुलिस प्रक्रिया और शिकायत की प्रक्रिया से जुड़े सवालों का जवाब दे सकता हूँ।",
    "te": "నేను చట్టం, పోలీస్ విధానం మరియు ఫిర్యాదు ప్రక్రియ గురించిన ప్రశ్నలకు మాత్రమే సమాధానం ఇవ్వగలను.",
}
NOT_RELIABLE = {
    "en": "I could not give a reliable answer to that. Please ask your police station or a lawyer.",
    "hi": "मैं इसका भरोसेमंद उत्तर नहीं दे सका। कृपया अपने पुलिस स्टेशन या किसी वकील से पूछें।",
    "te": "దీనికి నేను నమ్మదగిన సమాధానం ఇవ్వలేకపోయాను. దయచేసి మీ పోలీస్ స్టేషన్ లేదా న్యాయవాదిని అడగండి.",
}
UNAVAILABLE = {
    "en": "The assistant is not available right now. Please ask your police station or a lawyer.",
    "hi": "सहायक अभी उपलब्ध नहीं है। कृपया अपने पुलिस स्टेशन या किसी वकील से पूछें।",
    "te": "సహాయకుడు ప్రస్తుతం అందుబాటులో లేడు. దయచేసి మీ పోలీస్ స్టేషన్ లేదా న్యాయవాదిని అడగండి.",
}
AUDIENCES = {
    True: "a member of the public who may be reporting a crime or may have been wronged",
    False: "a police officer who wants help with procedure and standard practice",
}
# "page 64", "p. 12": the model has no documents to cite, so a page reference can only be made up.
INVENTED_CITATION = re.compile(r"\b(?:pp?|pg|page)\.?\s*\d+\b", re.IGNORECASE)


def ask(user, question, language="en"):
    is_citizen = actor_role(user) == CITIZEN
    if is_citizen:
        require_consent(user)  # a citizen's words go to an AI vendor; an officer's procedure question does not
    language = language if language in DISCLAIMERS else "en"
    data = f"<question>\n{sanitize_incident(question)[:1000]}\n</question>"

    def result(answer, in_scope, ai_available=True):
        return {
            "answer": answer,
            "in_scope": in_scope,
            "disclaimer": DISCLAIMERS[language],
            "sources": [],
            "ai_available": ai_available,
        }

    try:
        outcome = ask_model(
            "legal", data, LEGAL_SCHEMA, LEGAL_SCHEMA_NAME, parse_legal, audience=AUDIENCES[is_citizen]
        )
    except gateway.AIUnavailable:
        return result(UNAVAILABLE[language], None, ai_available=False)

    parsed = outcome.parsed
    if not parsed.in_scope or not parsed.answer.strip():
        return result(OUT_OF_SCOPE[language], False)
    if not reply_is_safe(parsed.answer) or INVENTED_CITATION.search(parsed.answer):
        return result(NOT_RELIABLE[language], True)
    return result(parsed.answer.strip(), True)
