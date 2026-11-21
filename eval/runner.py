"""Run FastEvaluation turn.

Usage (from the repo root, with the project venv):

    .venv/Scripts/python.exe -m eval.runner
    .venv/Scripts/python.exe -m eval.runner --case tokyo_history_avoid_shibuya
    .venv/Scripts/python.exe -m eval.runner --tools-only
    .venv/Scripts/python.exe -m eval.runner --mode api --model-url http://10-0-4-10:8000/v1/chat/stream

Writes JSON + CSV under eval/results/ and prints a summary table.
The runner uses an isolated SQLite file so it does not touch your .env database.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from agents.chat_tools import execute_agent_tool
from agents.coordinator.agent import run as coordinate_run
from agents.estimate_transport.agent import run as estimate_transport_run
from agents.search_stays.agent import run as search_stays_run
from agents.coordinator.agent import revise as revise_run
from agents.travel_history.agent import TravelHistoryStore
from config import settings as settings_mod
from config.settings import get_settings
from eval.cases import CASES, REVISE_CASES, EvalCase, ReviseCase
from eval.metrics import score_itinerary, score_stays, score_transport
from eval.tool_cases import TOOL_CASES
from eval.tool_metrics import score_tool_calls
from shared.schemas import TripRequest

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "eval" / "results"
VARIANTS = ("baseline_a", "proposed")


def _set_runtime(
    *,
    enable_travel_history: bool,
    database_url: str,
    mode: str = "stub",
    model_url: str = "",
) -> None:
    os.environ["ENABLE_TRAVEL_HISTORY"] = "1" if enable_travel_history else "0"
    os.environ["DATABASE_URL"] = database_url
    os.environ["TOOL_STAYS_MODE"] = "stub"
    os.environ["TOOL_MAPS_MODE"] = "stub"
    os.environ["WEB_SEARCH_MODE"] = "stub"
    # Keep eval silent: no Langfuse export attempts from local .env credentials.
    os.environ["LANGFUSE_ENABLED"] = "0"
    if mode == "api":
        if model_url:
            os.environ["QWEN_BASE_URL"] = model_url.rstrip("/")
    else:
        os.environ["QWEN_BASE_URL"] = ""
        os.environ["QWEN_API_KEY"] = ""
    settings_mod.get_settings.cache_clear()


def _seed_history(database_url: str, user_id: str, history: list[dict[str, str]]) -> list[str]:
    if not history:
        return []
    store = TravelHistoryStore(database_url)
    for item in history:
        store.record_visit(user_id, item["location"], country=item.get("country"), city=item.get("city"))
    return store.list_places(user_id)


def _first_transport_from_expect(case: EvalCase, request: TripRequest) -> tuple[str, str]:
    expect = case.get("expect") or {}
    from_place = expect.get("transport_from") or request.origin or request.destination
    to_place = expect.get("transport_to") or request.destination
    return from_place, to_place


def _call_model_stream(
    message: str,
    model_url: str,
    user_id: str,
    timeout: float = 60.0,
) -> tuple[str, dict[str, Any] | None]:
    """Call the Qwen model via streaming chat completions endpoint and return
    full text response + metrics.

    Returns (text, metrics) where metrics contains ttft_ms, tps, tpot_ms.
    """
    url = model_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"

    ttft_ms: float | None = None
    token_count = 0
    full_text = ""
    first_delta_time = None
    start_time = time.perf_counter()
    model_config = get_settings()
    headers = (
        {"Authorization": f"Bearer {model_config.qwen_api_key}"}
        if model_config.qwen_api_key
        else {}
    )

    try:
        with httpx.stream(
            "POST",
            url,
            json={
                "model": model_config.qwen_model,
                "messages": [{"role": "user", "content": message}],
                "max_tokens": 512,
                "stream": True,
                "temperature": 1.0,
                "top_p": 0.95,
            },
            headers=headers,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "") or ""
                    reasoning = (
                        delta.get("reasoning", "")
                        or delta.get("reasoning_content", "")
                        or ""
                    )
                    current_time = time.perf_counter()

                    if (content or reasoning) and first_delta_time is None:
                        first_delta_time = current_time
                        ttft_ms = round((first_delta_time - start_time) * 1000, 1)

                    if content:
                        full_text += content
                        token_count += len(content.split())
                    if reasoning:
                        full_text += reasoning
                        token_count += len(reasoning.split())

    except Exception as error:  # noqa: BLE001
        return f"[ERROR: {type(error).__name__}: {error}]", None

    total_time = time.perf_counter() - start_time
    total_time_ms = round(total_time * 1000, 1)

    metrics: dict[str, Any] = {}
    if token_count > 0:
        metrics["ttft_ms"] = ttft_ms
        metrics["total_time_ms"] = total_time_ms
        metrics["token_count"] = token_count
        metrics["tps"] = round(token_count / total_time, 2) if total_time > 0 else 0.0
        metrics["tpot_ms"] = round((total_time * 1000) / token_count, 1) if token_count > 0 else None
    else:
        metrics["ttft_ms"] = None
        metrics["total_time_ms"] = total_time_ms
        metrics["token_count"] = token_count
        metrics["tps"] = 0.0
        metrics["tpot_ms"] = None

    return full_text, metrics


def _judge_model_response(
    message: str,
    response: str,
    model_url: str,
    metrics: dict[str, Any],
    user_id: str,
    timeout: float = 60.0,
) -> dict[str, Any] | None:
    """Use the model itself to judge response quality (LLM-as-a-judge).

    Asks the model to rate its own response on relevance, completeness,
    helpfulness, and accuracy. Returns a dict with scores (1-5 scale) and
    reasoning, or None if judging fails.
    """
    judge_prompt = (
        "You are an impartial judge evaluating a model's response to a user "
        "request. Rate the response on a 1-5 scale for each criterion below.\n"
        "\n"
        "USER REQUEST:\n{message}\n\n"
        "MODEL RESPONSE:\n{response}\n\n"
        "METRICS:\n- TTFT: {ttft_ms} ms\n"
        "- Token count: {token_count}\n"
        "- TPS: {tps} tokens/sec\n"
        "- TPOT: {tpot_ms} ms/token\n\n"
        "Rate each criterion 1-5 (5 = best):\n"
        "1. relevance: Does the response directly address the user's request?\n"
        "2. completeness: Does it fully answer all parts of the request?\n"
        "3. helpfulness: Is the response useful and actionable?\n"
        "4. accuracy: Is the information factually correct and consistent?\n\n"
        "Respond with ONLY a JSON object containing these four scores and "
        "a brief reasoning string. Do NOT include any other text.\n"
        "Example: {{\"relevance\": 4, \"completeness\": 3, \"helpfulness\": 4, "
        "\"accuracy\": 3, \"reasoning\": \"Good coverage but missed some details\"}}"
    ).format(
        message=message,
        response=response[:2000],
        ttft_ms=metrics.get("ttft_ms", "N/A"),
        token_count=metrics.get("token_count", "N/A"),
        tps=metrics.get("tps", "N/A"),
        tpot_ms=metrics.get("tpot_ms", "N/A"),
    )

    try:
        judge_text, _ = _call_model_stream(
            message=judge_prompt,
            model_url=model_url,
            user_id=user_id,
            timeout=timeout,
        )
        import re as _re

        # Try to extract JSON from the response
        json_match = _re.search(r"\{.*\}", judge_text, _re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
                if all(k in parsed for k in ("relevance", "completeness", "helpfulness", "accuracy")):
                    return parsed
            except json.JSONDecodeError:
                pass
        # Fallback: try to extract individual scores from text
        scores: dict[str, Any] = {}
        for key in ("relevance", "completeness", "helpfulness", "accuracy"):
            m = _re.search(
                rf'{key}[\s"=:]*(\d)',
                judge_text,
                _re.IGNORECASE,
            )
            if m:
                scores[key] = int(m.group(1))
        # Also try pattern like "rating of 4" or "score of 5" or "give it a 3"
        if len(scores) < 4:
            for key in ("relevance", "completeness", "helpfulness", "accuracy"):
                if key in scores:
                    continue
                m = _re.search(
                    rf'(?:rating|score|give (?:it|them))\s*(?:of|is|:)?\s*{key[0]}',
                    judge_text,
                    _re.IGNORECASE,
                )
                if m:
                    scores[key] = int(m.group(1))
        # If still missing scores, extract all digits from text in order
        if len(scores) < 4:
            all_digits = _re.findall(r'\b([1-5])\b', judge_text)
            remaining = [k for k in ("relevance", "completeness", "helpfulness", "accuracy") if k not in scores]
            for i, key in enumerate(remaining):
                if i < len(all_digits):
                    scores[key] = int(all_digits[i])
        if len(scores) == 4:
            scores["reasoning"] = "Extracted from judge response text"
            return scores
        # Last resort: store raw text as reasoning
        scores = {
            "relevance": None,
            "completeness": None,
            "helpfulness": None,
            "accuracy": None,
            "reasoning": judge_text[:500] if judge_text else "",
        }
        return scores
    except Exception:  # noqa: BLE001
        pass
    return None


def _judge_model_response_nemotron(
    message: str,
    response: str,
    model_url: str,
    metrics: dict[str, Any],
    user_id: str,
    timeout: float = 60.0,
) -> dict[str, Any] | None:
    """Use NVIDIA Nemotron model as judge for response quality.

    Uses Nemotron-3.5-Bolt-E4B via NVIDIA NIM API to rate response quality
    on relevance, completeness, helpfulness, and accuracy (1-5 scale each).

    Returns dict with scores and reasoning, or None if judging fails.
    """
    from config.settings import get_settings

    s = get_settings()
    api_key = s.nemotron_api_key
    if not api_key:
        return None

    judge_prompt = (
        "Rate this response 1-5:\n\n"
        f"USER: {message}\n\n"
        f"MODEL: {response}\n\n"
        "Reply with ONLY four numbers separated by commas: "
        "relevance,completeness,helpfulness,accuracy"
    )

    try:
        client = httpx.Client(timeout=timeout)
        resp = client.post(
            s.nemotron_api_url,
            json={
                "model": "nvidia/nemotron-3.5-bolt-e4b",
                "messages": [{"role": "user", "content": judge_prompt}],
                "max_tokens": 100,
                "stream": False,
                "temperature": 0.0,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()

        # Extract four digits
        import re as _re

        digits = _re.findall(r"\b([1-5])\b", text)
        if len(all_digits := digits) >= 4:
            return {
                "relevance": int(all_digits[0]),
                "completeness": int(all_digits[1]),
                "helpfulness": int(all_digits[2]),
                "accuracy": int(all_digits[3]),
                "reasoning": "Extracted from Nemotron response",
            }

        # Fallback: try any digits
        digits = _re.findall(r"\b([1-5])\b", text)
        if len(digits) >= 4:
            return {
                "relevance": int(digits[0]),
                "completeness": int(digits[1]),
                "helpfulness": int(digits[2]),
                "accuracy": int(digits[3]),
                "reasoning": "Extracted from Nemotron response",
            }

        return None
    except Exception:  # noqa: BLE001
        pass
    return None


def _extract_hotels_from_text(text: str) -> list[dict[str, Any]]:
    """Extract hotel/stay mentions from model response text.

    Robust extraction that tolerates varied model output formats:
    - Prices with or without a currency symbol ($, ¥, €, £, etc.)
    - Prices written as bare numbers (e.g. "95/night")
    - Hotel keywords on the same line or within a small window of lines
    - Bullet points, numbered lists, and free paragraphs
    - Lowercase or mixed-case hotel names

    Returns list of dicts with name, nightly_cost, currency, notes.
    """
    import re

    hotels: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # Match a price:
    #   * With a currency symbol: 1+ digits (e.g. $95, ¥9500)
    #   * Without a symbol: 2-4 digits (avoids matching list enumerators "1.", "2.")
    # Optionally followed by /night, /pn, per night, nightly.
    price_re = re.compile(
        r"(?:"
        r"(?P<sym>[\$¥€£]|USD|EUR|GBP|JPY|HKD|TWD|THB|KRW|INR|SGD|AUD|CAD|CNY)"
        r"\s?(?P<amt_with_sym>\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)"
        r"|(?P<amt_bare>\d{2,4}(?:,\d{3})*(?:\.\d{1,2})?)"
        r")"
        r"\s*(?:/night|/pn|per night|nightly)?",
        re.IGNORECASE,
    )

    # Currency symbol → ISO code
    CURRENCY_MAP = {
        "$": "USD", "USD": "USD",
        "€": "EUR", "EUR": "EUR",
        "£": "GBP", "GBP": "GBP",
        "¥": "JPY", "JPY": "JPY",
        "HKD": "HKD", "HK$": "HKD",
        "TWD": "TWD", "NT$": "TWD",
        "THB": "THB",
        "KRW": "KRW",
        "INR": "INR",
        "SGD": "SGD", "S$": "SGD",
        "AUD": "AUD", "A$": "AUD",
        "CAD": "CAD", "C$": "CAD",
        "CNY": "CNY",
    }

    hotel_keywords = [
        "hotel", "hostel", "ryokan", "guesthouse", "guest house",
        "capsule", "inn", "motel", "resort", "lodge", "apartment",
        "b&b", "bed and breakfast", "accommodation", "stay",
        # Japanese (CJK) hotel terms
        "ホテル", "旅館", "ホステル", "ペンション", "ロッジ", "民宿",
    ]

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    for i, line in enumerate(lines):
        price_match = price_re.search(line)
        if not price_match:
            continue

        # Determine currency and amount
        sym = (price_match.group("sym") or "").upper()
        amt_str = price_match.group("amt_with_sym") or price_match.group("amt_bare")
        currency = CURRENCY_MAP.get(sym, "USD")
        price_text = price_match.group(0)

        try:
            nightly_cost = int(float(amt_str.replace(",", "")))
        except (ValueError, TypeError):
            continue

        # Determine the search window for hotel keywords:
        # same line, next 2 lines, previous 1 line.
        window_lines = [line]
        if i + 1 < len(lines):
            window_lines.append(lines[i + 1])
        if i + 2 < len(lines):
            window_lines.append(lines[i + 2])
        if i - 1 >= 0:
            window_lines.append(lines[i - 1])
        window_text = " ".join(window_lines).lower()

        if not any(kw in window_text for kw in hotel_keywords):
            continue

        # Extract hotel name from text BEFORE the price on the same line,
        # taking the segment closest to the price (after splitting by delimiters).
        # Only fall back to adjacent lines if the price line yields nothing.
        price_pos = line.find(price_text)
        before_text = line[:price_pos].strip() if price_pos >= 0 else line.strip()

        cleaned = ""
        if before_text:
            segments = re.split(r"[-:|•]", before_text)
            for seg in reversed(segments):  # closest to price first
                seg = seg.strip(" -:,\t").strip()
                if len(seg) >= 3 and any(c.isalpha() for c in seg):
                    seg_words = seg.lower().split()
                    if seg_words and seg_words[-1].lower() in {
                        "under", "around", "about", "for", "in", "to", "the",
                        "a", "an", "of", "from", "with", "by", "on", "at", "per",
                    }:
                        continue
                    cleaned = seg
                    break
            if not cleaned:
                cleaned = before_text.strip(" -:,\t").strip()

        # Strip list markers
        cleaned = re.sub(r"^[-•\d\.\s]*", "", cleaned)
        cleaned = re.sub(r"^\d+\.\s*", "", cleaned)
        cleaned = re.sub(r"^\d+\)\s*", "", cleaned)
        cleaned = cleaned.strip(" -:,:|-").strip()

        # If cleaned still looks like a sentence (contains hotel keyword plus
        # extra words), extract just the hotel name portion: find the hotel
        # keyword and take the 2-3 capitalized words immediately before it.
        if cleaned and any(kw in cleaned.lower() for kw in hotel_keywords):
            words = cleaned.split()
            kw_idx = None
            for j, w in enumerate(words):
                if any(kw == w.lower().strip(".,:;") for kw in hotel_keywords):
                    kw_idx = j
                    break
            if kw_idx is not None and kw_idx > 0:
                start = max(0, kw_idx - 3)
                name_words = words[start:kw_idx + 1]
                # Drop leading prepositions/articles
                while name_words and name_words[0].lower() in {"at", "in", "the", "a", "an", "staying", "at", "is", "are", "was", "were", "has", "have", "for", "with", "by"}:
                    name_words.pop(0)
                if name_words:
                    cleaned = " ".join(name_words)[:40]

        # If nothing usable from the price line, try adjacent lines that
        # contain a hotel keyword (for cases where price and name are on
        # different lines). Prefer the line immediately before the price.
        if not cleaned:
            for offset in (-1, 1):
                cand_idx = i + offset
                if 0 <= cand_idx < len(lines):
                    candidate_line = lines[cand_idx]
                    if any(kw in candidate_line.lower() for kw in hotel_keywords):
                        cand = candidate_line.strip()
                        cand = re.sub(r"^[-•\d\.\s]*", "", cand)
                        cand = re.sub(r"^\d+\.\s*", "", cand)
                        cand = re.sub(r"^\d+\)\s*", "", cand)
                        cand = cand.strip(" -:,:|-").strip()
                        if len(cand) >= 3 and any(c.isalpha() for c in cand):
                            cleaned = cand[:40]
                            break

        # If still nothing, try text AFTER the price on the same line
        if not cleaned:
            after_text = line[price_match.end():].strip() if price_match.end() < len(line) else ""
            if after_text:
                segments = re.split(r"[-:|•]", after_text)
                for seg in segments:
                    seg = seg.strip(" -:,\t").strip()
                    if len(seg) >= 3 and any(c.isalpha() for c in seg):
                        cleaned = seg
                        break
                if not cleaned:
                    cleaned = after_text.strip(" -:,\t").strip()

        if not cleaned:
            continue

        name = cleaned[:40]

        # Drop leading sentence starters (but keep multi-word names)
        name_lower = name.lower().strip()
        first_word = name_lower.split()[0] if name_lower.split() else ""
        sentence_starters = {"the", "this", "that", "a", "an", "here", "there",
                             "it", "its", "i", "we", "you", "he", "she", "they"}
        if first_word in sentence_starters and len(name_lower.split()) > 1:
            name = " ".join(name_lower.split()[1:])[:40]

        if not name or len(name) < 3:
            continue

        name = name.strip(" -:,:|-").strip()
        # Strip trailing punctuation that isn't part of a name
        name = name.rstrip(".,;:!?~*")
        key = name.lower().replace(" ", "")
        if key in seen_names:
            continue
        seen_names.add(key)

        # Skip obvious non-hotel extractions from chain-of-thought text:
        # standalone common words, sentence fragments, or lowercase-only names.
        name_lower = name.lower().strip()
        non_hotel_words = {
            "food", "budget", "cost", "price", "night", "day", "trip", "plan",
            "stay", "accommodation", "total", "per", "approximately", "around",
            "about", "hotel", "hotels", "hostel", "hostels", "estimate",
            "estimation", "breakdown", "allocation", "remaining",
            "assess", "constraint", "acknowledge", "structure", "provide",
            "options", "first", "wait", "maybe", "perhaps",
        }
        if name_lower in non_hotel_words:
            continue
        # Skip names that look like sentence fragments (start with lowercase
        # and contain sentence verbs) unless they contain a hotel keyword.
        if name and name[0].islower() and not any(
            kw in name_lower for kw in hotel_keywords
        ):
            continue
        # Skip very short names that are just common words
        if len(name) <= 4 and name_lower in {
            "hotel", "food", "stay", "room", "bed", "inn",
        }:
            continue
        name_words = name_lower.split()
        # Skip names that end with common prepositions (not a hotel name)
        if name_words and name_words[-1].lower() in {
            "under", "around", "about", "for", "in", "to", "the", "a", "an",
            "of", "from", "with", "by", "on", "at", "per",
        }:
            continue
        # Skip names that are sentence fragments (contain discourse verbs
        # or question words that indicate this isn't a hotel name).
        discourse_words = {
            "assess", "acknowledge", "structure", "provide", "let's",
            "should", "would", "could", "might", "maybe", "perhaps",
            "wait", "think", "consider", "note", "remember",
        }
        if any(w in discourse_words for w in name_words):
            continue

        hotels.append({
            "name": name,
            "nightly_cost": nightly_cost,
            "currency": currency,
            "notes": f"Model suggested: {name}",
        })

    return hotels[:5]


def run_variant(
    case: EvalCase,
    *,
    variant: str,
    database_url: str,
    mode: str = "stub",
    model_url: str = "",
) -> dict[str, Any]:
    enable_history = variant == "proposed"
    _set_runtime(enable_travel_history=enable_history, database_url=database_url, mode=mode, model_url=model_url)
    expect = case.get("expect") or {}
    expect_error = bool(expect.get("expect_error"))

    started = time.perf_counter()
    error = None
    itinerary = None
    try:
        request = TripRequest.model_validate(case["request"])
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        passed = expect_error
        return {
            "variant": variant,
            "enable_travel_history": enable_history,
            "elapsed_ms": elapsed_ms,
            "error": f"{type(exc).__name__}: {exc}",
            "history_places": [],
            "agent1": {"pass": passed, "checks": {"expect_error": passed}, "stay_count": 0, "stay_locations": []},
            "agent2": {"pass": passed, "checks": {"expect_error": passed}},
            "plan": {"pass": passed, "checks": {"expect_error": passed, "fail_closed": True}, "warnings": []},
            "pass": passed,
        }

    history_places = _seed_history(database_url, request.user_id or "eval-user", case.get("history") or [])
    try:
        if mode == "api":
            model_url = model_url or get_settings().qwen_base_url
            if not model_url:
                raise ValueError("Set QWEN_BASE_URL or pass --model-url for API mode.")
            model_url = model_url.rstrip("/")
            if not model_url.endswith("/chat/completions"):
                model_url = model_url.rstrip("/") + "/chat/completions"

            prompt = (
                f"Plan a {request.days or 3}-day trip to {request.destination} "
                f"with a budget of ${request.budget}. "
                f"Focus on: {', '.join(request.interests) if request.interests else 'general sightseeing'}. "
                f"Recommend specific hotels with names, nightly prices in USD, and brief reasons. "
                f"Format: Hotel Name - $price/night - reason"
            )
            model_response, model_metrics = _call_model_stream(message=prompt, model_url=model_url, user_id=request.user_id or "eval-user")
            model_metrics = model_metrics or {}

            # LLM-as-a-judge: evaluate response quality using Nemotron model
            judge_metrics = _judge_model_response_nemotron(
                message=prompt,
                response=model_response,
                model_url=get_settings().nemotron_api_url,
                metrics=model_metrics,
                user_id=request.user_id or "eval-user",
            )
            if judge_metrics:
                model_metrics["model_judge"] = judge_metrics

            stays = _extract_hotels_from_text(model_response)

            itinerary = {
                "destination": request.destination,
                "days": request.days or 3,
                "budget": request.budget,
                "currency": "USD",
                "stays": stays,
                "notes": [model_response[:200] if model_response else ""],
                "model_metrics": model_metrics,
            }
        else:
            itinerary = coordinate_run(request, session_id=f"eval-{case['id']}-{variant}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    if mode == "api":
        stays = itinerary.get("stays", []) if isinstance(itinerary, dict) else []
        model_metrics = (itinerary.get("model_metrics") or {}) if isinstance(itinerary, dict) else {}

        agent1 = {
            "pass": len(stays) > 0,
            "checks": {
                "has_stays": len(stays) > 0,
                "has_reasonable_prices": all((s.get("nightly_cost") or 0) > 0 for s in stays),
            },
            "stay_count": len(stays),
            "stay_locations": [s.get("name", "") for s in stays],
        }
        agent2 = {"pass": True, "checks": {"transport_not_required": True}}
        plan = {
            "pass": len(stays) > 0,
            "checks": {
                "has_stays": len(stays) > 0,
                "budget_respectful": all((s.get("nightly_cost") or 0) <= (request.budget or 9999) for s in stays),
            },
            "model_metrics": {
                "ttft_ms": model_metrics.get("ttft_ms"),
                "tps": model_metrics.get("tps"),
                "tpot_ms": model_metrics.get("tpot_ms"),
                "token_count": model_metrics.get("token_count"),
                "model_judge": model_metrics.get("model_judge"),
            },
            "warnings": [],
        }
    else:
        excluded = history_places if (request.avoid_visited and enable_history) else []
        stays = search_stays_run(request, excluded_locations=excluded)
        from_place, to_place = _first_transport_from_expect(case, request)
        transport = estimate_transport_run(request, from_place, to_place)

        apply_filter = bool(
            expect.get("history_avoidance") or expect.get("poi_history_avoidance")
        ) and enable_history and request.avoid_visited
        agent1 = score_stays(
            stays,
            request,
            expect,
            history_places,
            apply_history_filter=apply_filter,
        )
        agent2 = score_transport(transport, expect)
        plan = None
        if itinerary is not None:
            plan = score_itinerary(
                itinerary,
                request,
                expect,
                history_places,
                apply_history_filter=apply_filter,
            )
        elif expect_error and error is not None:
            plan = {
                "pass": True,
                "checks": {"expect_error": True, "fail_closed": True},
                "warnings": [],
                "error": error,
            }

    if expect_error:
        passed = error is not None
    else:
        passed = error is None and agent1["pass"] and agent2["pass"] and (plan["pass"] if plan else False)
    return {
        "variant": variant,
        "enable_travel_history": enable_history,
        "elapsed_ms": elapsed_ms,
        "error": error,
        "history_places": history_places,
        "agent1": agent1,
        "agent2": agent2,
        "plan": plan,
        "pass": passed,
    }


def _collect_pois(variant: dict[str, Any]) -> list[str]:
    plan = variant.get("plan") or {}
    pois = plan.get("pois")
    if pois:
        return list(pois)
    stays = plan.get("stays") or variant.get("agent1", {}) or {}
    if isinstance(stays, dict):
        return [s.get("name", "") for s in stays.get("stays", []) if s.get("name")]
    return []


def _history_contrast(case: EvalCase, results: dict[str, Any]) -> dict[str, Any] | None:
    if not (case.get("expect") or {}).get("history_avoidance"):
        return None
    request = TripRequest.model_validate(case["request"])
    if not request.avoid_visited:
        return None
    baseline_stays = (results["baseline_a"].get("plan") or {}).get("stays") or results["baseline_a"]["agent1"]
    proposed_stays = (results["proposed"].get("plan") or {}).get("stays") or results["proposed"]["agent1"]
    history = results["proposed"].get("history_places") or []
    baseline_overlap = baseline_stays.get("overlapping_history") or []
    proposed_overlap = proposed_stays.get("overlapping_history") or []
    if not baseline_overlap:
        baseline_overlap = results["baseline_a"]["agent1"].get("overlapping_history") or []
    if not proposed_overlap:
        proposed_overlap = results["proposed"]["agent1"].get("overlapping_history") or []
    passed = bool(history) and bool(baseline_overlap) and not proposed_overlap
    return {
        "history_places": history,
        "baseline_overlap": baseline_overlap,
        "proposed_overlap": proposed_overlap,
        "pass": passed,
        "detail": (
            "Proposed avoided visited stays while Baseline A still recommended them"
            if passed
            else "Expected Baseline A to still recommend a visited stay, and Proposed to avoid all of them"
        ),
    }


def _poi_contrast(case: EvalCase, results: dict[str, Any]) -> dict[str, Any] | None:
    expect = case.get("expect") or {}
    if not expect.get("poi_history_avoidance"):
        return None
    forbidden = [place.casefold().strip() for place in (expect.get("forbidden_pois") or []) if place]
    if not forbidden:
        return None
    baseline_pois = _collect_pois(results["baseline_a"])
    proposed_pois = _collect_pois(results["proposed"])

    def _hit(name: str) -> bool:
        folded = name.lower()
        return any(place == folded or place in folded for place in forbidden)

    baseline_overlap = [name for name in baseline_pois if _hit(name)]
    proposed_overlap = [name for name in proposed_pois if _hit(name)]
    passed = bool(baseline_overlap) and not proposed_overlap
    return {
        "forbidden_pois": expect.get("forbidden_pois") or [],
        "baseline_overlap": baseline_overlap,
        "proposed_overlap": proposed_overlap,
        "pass": passed,
        "detail": (
            "Proposed avoided visited POIs while Baseline A still included them"
            if passed
            else "Expected Baseline A to still include a visited POI, and Proposed to drop all of them"
        ),
    }


def run_case(
    case: EvalCase,
    database_url: str,
    mode: str = "stub",
    model_url: str = "",
) -> dict[str, Any]:
    variants = {
        name: run_variant(case, variant=name, database_url=database_url, mode=mode, model_url=model_url)
        for name in VARIANTS
    }
    contrast = _history_contrast(case, variants)
    poi_contrast = _poi_contrast(case, variants)
    passed = all(variants[name]["pass"] for name in VARIANTS)
    if contrast is not None:
        passed = passed and contrast["pass"]
    if poi_contrast is not None:
        passed = passed and poi_contrast["pass"]
    return {
        "kind": "plan",
        "id": case["id"],
        "description": case.get("description"),
        "request": case["request"],
        "variants": variants,
        "history_contrast": contrast,
        "poi_contrast": poi_contrast,
        "pass": passed,
    }


def run_tool_case(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    scored = score_tool_calls(list(case.get("gold_calls") or []))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "kind": "tools",
        "id": case["id"],
        "description": case.get("description"),
        "message": case.get("message"),
        "elapsed_ms": elapsed_ms,
        "tools": scored,
        "pass": scored["pass"],
    }


def run_revise_case(
    case: ReviseCase,
    database_url: str,
    mode: str = "stub",
    model_url: str = "",
) -> dict[str, Any]:
    """Run a plan, then re-enter the pipeline with changed constraints."""
    expect = case.get("expect") or {}
    note_contains = [n.casefold() for n in (case.get("note_contains") or [])]
    variants: dict[str, Any] = {}
    for variant_name in VARIANTS:
        enable_history = variant_name == "proposed"
        _set_runtime(
            enable_travel_history=enable_history,
            database_url=database_url,
            mode=mode,
            model_url=model_url,
        )
        request = TripRequest.model_validate(case["request"])
        revised_request = TripRequest.model_validate(case["revised_request"])
        history_places = _seed_history(
            database_url, request.user_id or "eval-user", case.get("history") or []
        )
        started = time.perf_counter()
        error = None
        revised = None
        try:
            initial = coordinate_run(
                request, session_id=f"eval-{case['id']}-{variant_name}-initial"
            )
            revised = revise_run(
                revised_request,
                initial,
                session_id=f"eval-{case['id']}-{variant_name}-revised",
            )
        except Exception as exc:  # pragma: no cover - surfaced in the report
            error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        apply_filter = (
            bool(expect.get("history_avoidance"))
            and enable_history
            and revised_request.avoid_visited
        )
        plan = None
        revision_note_ok = True
        if revised is not None:
            plan = score_itinerary(
                revised,
                revised_request,
                expect,
                history_places,
                apply_history_filter=apply_filter,
            )
            missing = [
                needle
                for needle in note_contains
                if not any(needle in note.casefold() for note in revised.notes or [])
            ]
            revision_note_ok = not missing
            plan["checks"]["revision_note"] = revision_note_ok
        passed = (
            error is None
            and plan is not None
            and bool(plan.get("pass"))
            and revision_note_ok
        )
        variants[variant_name] = {
            "variant": variant_name,
            "enable_travel_history": enable_history,
            "elapsed_ms": elapsed_ms,
            "error": error,
            "history_places": history_places,
            "plan": plan,
            "revision_note_ok": revision_note_ok,
            "notes": list(revised.notes or []) if revised is not None else [],
            "pass": passed,
        }
    return {
        "kind": "revise",
        "id": case["id"],
        "description": case.get("description"),
        "request": case["request"],
        "revised_request": case["revised_request"],
        "variants": variants,
        "pass": all(variants[name]["pass"] for name in VARIANTS),
    }


def run_suite(
    case_ids: list[str] | None = None,
    *,
    include_plan: bool = True,
    include_tools: bool = True,
    mode: str = "stub",
    model_url: str = "",
) -> dict[str, Any]:
    known_ids = (
        {c["id"] for c in CASES}
        | {c["id"] for c in TOOL_CASES}
        | {c["id"] for c in REVISE_CASES}
    )
    missing = [cid for cid in (case_ids or []) if cid not in known_ids]
    if missing:
        raise SystemExit(f"Unknown case id(s): {', '.join(missing)}")

    plan_selected = [case for case in CASES if include_plan and (not case_ids or case["id"] in case_ids)]
    tool_selected = [case for case in TOOL_CASES if include_tools and (not case_ids or case["id"] in case_ids)]
    revise_selected = [
        case
        for case in REVISE_CASES
        if include_plan and (not case_ids or case["id"] in case_ids)
    ]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="trip-eval-") as tmp:
        database_url = "sqlite:///" + str(Path(tmp) / "travel_history.sqlite")
        _set_runtime(
            enable_travel_history=True,
            database_url=database_url,
            mode=mode,
            model_url=model_url,
        )
        cases.extend(run_case(case, database_url, mode=mode, model_url=model_url) for case in plan_selected)
        cases.extend(
            run_revise_case(case, database_url, mode=mode, model_url=model_url)
            for case in revise_selected
        )
        cases.extend(run_tool_case(case) for case in tool_selected)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    plan_cases = [case for case in cases if case.get("kind") == "plan"]
    tool_cases = [case for case in cases if case.get("kind") == "tools"]
    contrast_cases = [case for case in plan_cases if case.get("history_contrast") is not None]
    latencies = [
        variant["elapsed_ms"]
        for case in plan_cases
        for variant in (case.get("variants") or {}).values()
        if variant.get("elapsed_ms") is not None
    ]
    report = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "model_url": model_url if mode == "api" else None,
        "case_count": len(cases),
        "passed": sum(1 for case in cases if case["pass"]),
        "failed": sum(1 for case in cases if not case["pass"]),
        "elapsed_ms": elapsed_ms,
        "history_contrast_pass": sum(1 for case in contrast_cases if case["history_contrast"]["pass"]),
        "history_contrast_total": len(contrast_cases),
        "tool_pass": sum(1 for case in tool_cases if case["pass"]),
        "tool_total": len(tool_cases),
        "latency_ms": {
            "plan_runs": len(latencies),
            "mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "cases": cases,
    }
    return report


def _write_outputs(report: dict[str, Any], cases: list[dict[str, Any]], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"eval-{stamp}.json"
    csv_path = out_dir / f"eval-{stamp}.csv"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for case in cases:
        if case.get("kind") == "tools":
            rows.append(
                {
                    "case_id": case["id"],
                    "kind": "tools",
                    "variant": "",
                    "pass": case["pass"],
                    "elapsed_ms": case.get("elapsed_ms"),
                    "error": "",
                    "agent1_pass": "",
                    "agent2_pass": "",
                    "plan_pass": "",
                    "day_count": "",
                    "expected_days": "",
                    "total_estimated_cost": "",
                    "budget": "",
                    "stay_names": "",
                    "transport_mode": "",
                    "history_contrast_pass": "",
                    "tool_names": "; ".join(call["name"] for call in (case.get("tools") or {}).get("calls") or []),
                }
            )
            continue
        contrast = case.get("history_contrast") or {}
        for name in VARIANTS:
            variant = case["variants"][name]
            plan = variant.get("plan") or {}
            stays = (plan.get("stays") or variant.get("agent1") or {})
            transport = (plan.get("transport") or variant.get("agent2") or {})
            model_metrics = plan.get("model_metrics", {}) if isinstance(plan, dict) else {}
            rows.append(
                {
                    "case_id": case["id"],
                    "kind": case.get("kind", "plan"),
                    "variant": name,
                    "pass": variant["pass"],
                    "elapsed_ms": variant["elapsed_ms"],
                    "error": variant.get("error") or "",
                    "agent1_pass": variant.get("agent1", {}).get("pass"),
                    "agent2_pass": variant.get("agent2", {}).get("pass"),
                    "plan_pass": plan.get("pass"),
                    "day_count": plan.get("day_count"),
                    "expected_days": plan.get("expected_days"),
                    "total_estimated_cost": plan.get("total_estimated_cost"),
                    "budget": plan.get("budget"),
                    "stay_names": "; ".join(
                        stays.get("stay_names", [])
                        if isinstance(stays, dict)
                        else [s.get("name", "") for s in stays]
                    ),
                    "transport_mode": transport.get("mode"),
                    "history_contrast_pass": contrast.get("pass", ""),
                    "tool_names": "",
                    "ttft_ms": model_metrics.get("ttft_ms", ""),
                    "tps": model_metrics.get("tps", ""),
                    "tpot_ms": model_metrics.get("tpot_ms", ""),
                    "token_count": model_metrics.get("token_count", ""),
                    "judge_relevance": (
                        model_metrics.get("model_judge", {}).get("relevance", "")
                        if isinstance(model_metrics.get("model_judge"), dict)
                        else ""
                    ),
                    "judge_completeness": (
                        model_metrics.get("model_judge", {}).get("completeness", "")
                        if isinstance(model_metrics.get("model_judge"), dict)
                        else ""
                    ),
                    "judge_helpfulness": (
                        model_metrics.get("model_judge", {}).get("helpfulness", "")
                        if isinstance(model_metrics.get("model_judge"), dict)
                        else ""
                    ),
                    "judge_accuracy": (
                        model_metrics.get("model_judge", {}).get("accuracy", "")
                        if isinstance(model_metrics.get("model_judge"), dict)
                        else ""
                    ),
                }
            )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["case_id"])
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def _fmt_bool(value: Any) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "-"


def print_summary(report: dict[str, Any], json_path: Path, csv_path: Path) -> None:
    latency = report.get("latency_ms") or {}
    mode_label = report.get("mode", "stub").upper()
    print(
        f"Eval [{mode_label}] {report['passed']}/{report['case_count']} cases passed "
        f"({report['elapsed_ms']} ms). "
        f"History contrast {report['history_contrast_pass']}/{report['history_contrast_total']}. "
        f"Tool layer {report.get('tool_pass', 0)}/{report.get('tool_total', 0)}."
    )
    if latency.get("mean") is not None:
        print(f"Plan latency mean {latency['mean']} ms, max {latency['max']} ms.")
    model_metrics = report.get("model_metrics")
    if model_metrics:
        print(
            f"Model metrics: TTFT={model_metrics.get('ttft_ms')}ms, "
            f"TPS={model_metrics.get('tps')}, TPT={model_metrics.get('tpot_ms')}ms, "
            f"Tokens={model_metrics.get('token_count')}"
        )
    print(
        f"{'case':<36} {'kind':<8} {'baseline':<10} {'proposed':<10} {'days (exp)':<12} {'extra':<10}"
    )
    print("-" * 90)
    for case in report["cases"]:
        if case.get("kind") == "tools":
            print(
                f"{case['id']:<36} {'tools':<8} "
                f"{'-':<10} {_fmt_bool(case['pass']):<10} {'-':<12} {'-':<10}"
            )
            if not case["pass"]:
                failed = []
                for call in (case.get("tools") or {}).get("calls") or []:
                    bad = [key for key, ok in (call.get("checks") or {}).items() if ok is False]
                    if bad:
                        failed.append(f"{call['name']}: {', '.join(bad)}")
                    elif call.get("error"):
                        failed.append(f"{call['name']}: {call['error']}")
                if failed:
                    print("    " + " | ".join(failed))
            continue
        baseline = case["variants"]["baseline_a"]
        proposed = case["variants"]["proposed"]
        plan = proposed.get("plan") or {}
        days = plan.get("day_count")
        expected = plan.get("expected_days")
        contrast = case.get("history_contrast")
        poi_contrast = case.get("poi_contrast")
        kind = case.get("kind", "plan")
        if kind == "revise":
            extra = (plan.get("checks") or {}).get("revision_note")
        elif contrast is not None:
            extra = contrast["pass"]
        elif poi_contrast is not None:
            extra = poi_contrast["pass"]
        else:
            extra = (plan.get("checks") or {}).get("budget_revise")
        print(
            f"{case['id']:<36} {kind:<8} "
            f"{_fmt_bool(baseline['pass']):<10} "
            f"{_fmt_bool(proposed['pass']):<10} "
            f"{str(days) + '/' + str(expected):<12} "
            f"{_fmt_bool(extra):<10}"
        )
        plan_checks = (case.get("variants") or {}).get("proposed", {}).get("plan") or {}
        info_flags = plan_checks.get("checks") or {}
        warnings = plan_checks.get("warnings") or []
        if not case["pass"] or (plan_checks.get("checks") or {}).get("budget_revise") is False or (
            info_flags.get("city_level_keeps_stays") is False
        ) or (
            info_flags.get("transport_city_consistent") is False
        ) or (
            info_flags.get("fail_closed") is False
        ):
            reasons = []
            if baseline.get("error"):
                reasons.append(f"baseline error: {baseline['error']}")
            if proposed.get("error"):
                reasons.append(f"proposed error: {proposed['error']}")
            for name in VARIANTS:
                plan_variant = case["variants"][name].get("plan") or {}
                checks = plan_variant.get("checks") or {}
                failed_checks = [key for key, ok in checks.items() if isinstance(ok, bool) and not ok]
                if failed_checks:
                    reasons.append(f"{name}: {', '.join(failed_checks)}")
            if contrast and not contrast["pass"]:
                reasons.append(contrast["detail"])
            if info_flags.get("city_level_keeps_stays") is False:
                reasons.append("city-level history dropped destination stays")
            if info_flags.get("transport_city_consistent") is False:
                reasons.append("transport matched another city's catalog")
            if info_flags.get("fail_closed") is False:
                reasons.append("invalid or infeasible request did not fail closed")
            if info_flags.get("day_coverage") is False:
                reasons.append("itinerary day count did not match the request")
            if (plan_checks.get("checks") or {}).get("budget_revise") is False:
                reasons.append("coordinator did not revise an over-budget plan")
            if info_flags.get("revise_noted") is False:
                reasons.append("revise succeeded but was not noted")
            if info_flags.get("revision_note") is False:
                reasons.append("revised plan did not note the constraint change")
            if info_flags.get("cost_scale_ok") is False and warnings:
                reasons.append("cost-scale warning: " + ", ".join(warnings))
            poi_contrast = case.get("poi_contrast")
            if poi_contrast and not poi_contrast["pass"]:
                reasons.append(poi_contrast["detail"])
            if reasons:
                print("    " + " | ".join(reasons))
    print()
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Baseline A vs Proposed eval cases.")
    parser.add_argument("--case", action="append", dest="cases", help="Case id to run (repeatable).")
    parser.add_argument("--plan-only", action="store_true", help="Skip gold tool-call cases.")
    parser.add_argument("--tools-only", action="store_true", help="Run only gold tool-call cases.")
    parser.add_argument(
        "--mode",
        choices=["stub", "api"],
        default="stub",
        help="Evaluation mode: stub (local tools) or api (real model calls).",
    )
    parser.add_argument(
        "--model-url",
        default="",
        help="OpenAI-compatible model base URL for API mode (defaults to QWEN_BASE_URL).",
    )
    parser.add_argument(
        "--out",
        default=str(RESULTS_DIR),
        help="Directory for JSON/CSV reports (default: eval/results).",
    )
    args = parser.parse_args(argv)
    if args.mode == "api" and not (args.model_url or get_settings().qwen_base_url):
        parser.error("API mode requires QWEN_BASE_URL or --model-url.")
    report = run_suite(
        args.cases,
        include_plan=not args.tools_only,
        include_tools=not args.plan_only,
        mode=args.mode,
        model_url=args.model_url,
    )
    json_path, csv_path = _write_outputs(report, report["cases"], Path(args.out))
    print_summary(report, json_path, csv_path)
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())