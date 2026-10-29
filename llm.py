"""Optional local-LLM helpers using Ollama (open source, runs on your laptop).
Install: https://ollama.com  then  `ollama pull llama3.1:8b`  (or qwen2.5:7b)
Every function returns None on failure so the pipeline falls back to rules."""
import json
import os
import urllib.request

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")


def _generate(model: str, prompt: str, as_json=False, timeout=60):
    body = {"model": model, "prompt": prompt, "stream": False}
    if as_json:
        body["format"] = "json"
    try:
        req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r).get("response", "")
    except Exception:
        return None


def make_review_classifier(model: str):
    def classify(text: str):
        out = _generate(model, (
            "You screen hotel reviews for signs of a booking scam (fake website or phone number, "
            "advance payment taken with no booking, WhatsApp-only payment, refund refused). "
            'Reply as JSON: {"scam": true|false}.\nReview: ' + text), as_json=True)
        if not out:
            return None
        try:
            return bool(json.loads(out).get("scam"))
        except Exception:
            return None
    return classify


def polish_alert(model: str, draft: str):
    return _generate(model, (
        "Rewrite this notice to a hotel owner so it is clear, polite and factual. Keep every fact and "
        "URL. Do not accuse anyone; say 'possible mismatch'. Return plain text only.\n\n" + draft), timeout=120)
