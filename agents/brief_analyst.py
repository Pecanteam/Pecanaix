"""
Conversational Brief Analyst: multi-turn chat to collect event brief fields.
Uses Kimi K2 via Groq (OpenAI-compatible API).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tools.llm_router import get_llm

load_dotenv()

_BRIEF_FIELDS = (
    "event_type",
    "topic",
    "date",
    "location_city",
    "location_country",
    "target_attendance",
    "audience_constraints",
    "event_platform",
    "exclusions",
    "goal_beyond_attendance",
)


def _safe_parse_json(text: str, fallback: Any = None) -> Any:
    cleaned = text.strip().strip("```json").strip("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = cleaned.find(start_char)
        end = cleaned.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    return fallback


def _non_none_fields(session: Dict[str, Any]) -> Dict[str, Any]:
    return {k: session[k] for k in _BRIEF_FIELDS if session.get(k) is not None}


def _missing_fields(session: Dict[str, Any]) -> List[str]:
    return [k for k in _BRIEF_FIELDS if session.get(k) is None]


def _history_to_messages(system_prompt: str, history: List[Dict[str, str]]) -> List:
    msgs: List = [SystemMessage(content=system_prompt)]
    for turn in history:
        role = turn.get("role")
        content = turn.get("content", "")
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            msgs.append(AIMessage(content=content))
    return msgs


def _format_conversation_for_extraction(history: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for turn in history:
        label = "User" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{label}: {turn.get('content', '')}")
    return "\n".join(lines)


def create_brief_session() -> Dict[str, Any]:
    session: Dict[str, Any] = {
        "event_type": None,
        "topic": None,
        "date": None,
        "location_city": None,
        "location_country": None,
        "target_attendance": None,
        "audience_constraints": None,
        "event_platform": None,
        "exclusions": None,
        "goal_beyond_attendance": None,
        "conversation_history": [],
        "is_complete": False,
    }
    return session


def process_user_message(
    session: Dict[str, Any], user_message: str
) -> Tuple[str, Dict[str, Any]]:
    llm = get_llm()
    history: List[Dict[str, str]] = session["conversation_history"]

    history.append({"role": "user", "content": user_message})

    collected = _non_none_fields(session)
    still_needed = _missing_fields(session)
    system_prompt = """You are the Brief Analyst for Pecan, an AI-powered alumni engagement platform. You help a university alumni team member describe an event in a short, natural chat.

Flow (keep the whole exchange to about 2–4 messages; ideally three: user describes → you summarise → they confirm):

1) When the user first describes their event (or gives enough to work with), infer everything you can from their message. For anything not stated, use these smart defaults—do not ask about each one separately:
   - event_type: "panel discussion"
   - location_country: "UK" (if they name a city or region, infer country when reasonable; otherwise default UK)
   - date: "in 3 weeks"
   - audience_constraints: "graduates from the last 5 years"
   - event_platform: "Eventbrite"
   - exclusions: "none"
   - goal_beyond_attendance: "networking and engagement"

2) Reply with a compact summary in a "Here's what I've got:" style, listing each field on its own line (event type, topic, location, target attendance, audience, platform, exclusions, goal—or equivalent). Clearly separate what they told you from what you assumed (e.g. "I've filled in some defaults"). End by asking them to confirm or correct (e.g. "Want to adjust anything, or shall I go ahead?"). Be warm and concise.

Example shape (adapt to their actual words): if they say "fintech event in London for 30 people", you might respond with something like:
"Here's what I've got:

Event type: panel discussion
Topic: fintech
Location: London, UK
Target attendance: 30
Audience: recent graduates (last 5 years)
Platform: Eventbrite
Exclusions: none

I've filled in some defaults — want to adjust anything, or shall I go ahead?"

3) Only ask a follow-up question if something critical is truly missing from what they said: topic OR target attendance (headcount). If one of those is missing, ask one short, targeted question—then give the same kind of summary with defaults for everything else.

4) If they confirm with phrases like yes, go ahead, looks good, perfect, confirmed, that's fine, sure, or similar: reply with a brief acknowledgment and end your message with exactly the word CONFIRMED alone on its own final line. Do not ask any further questions.

5) If they want to change something: update only what they said, keep the rest, and re-send the full summary; never revert to asking one unrelated question at a time.

6) Never drag the chat out with many rounds. Prefer defaults + one summary + confirmation over interrogation."""

    system_prompt += (
        "\n\nContext from prior extractions (often empty on the first user turn; their latest message is what matters): "
        f"{json.dumps(collected)}. "
        f"Fields not yet stored: {json.dumps(still_needed)}. "
        "Do not treat the 'not yet stored' list as a checklist to ask one-by-one—apply smart defaults above. "
        "Only ask a follow-up if topic or target attendance is still unknown after interpreting their latest message."
    )

    messages = _history_to_messages(system_prompt, history)
    response = llm.invoke(messages)
    assistant_text = response.content if hasattr(response, "content") else str(response)

    history.append({"role": "assistant", "content": assistant_text})

    conv_text = _format_conversation_for_extraction(history)
    extract_prompt = f"""From this conversation, extract the event brief as JSON with keys: event_type, topic, date, location_city, location_country, target_attendance, audience_constraints, event_platform, exclusions, goal_beyond_attendance.

Use the user's explicit statements first. Also take field values from the Assistant's consolidated summaries (e.g. lines under "Here's what I've got") when they state the proposed or agreed brief; later user corrections override earlier values. Omit a key only if it cannot be inferred from the conversation. Return valid JSON only.

Conversation:
{conv_text}"""

    extract_resp = llm.invoke(extract_prompt)
    extract_text = (
        extract_resp.content if hasattr(extract_resp, "content") else str(extract_resp)
    )
    extracted = _safe_parse_json(extract_text, {})
    if isinstance(extracted, dict):
        for key in _BRIEF_FIELDS:
            if key in extracted and extracted[key] is not None:
                val = extracted[key]
                if key == "target_attendance":
                    try:
                        session[key] = int(val)
                    except (TypeError, ValueError):
                        pass
                else:
                    session[key] = val

    if "CONFIRMED" in assistant_text:
        session["is_complete"] = True

    return assistant_text, session


def get_parsed_brief(session: Dict[str, Any]) -> Dict[str, Any]:
    """Return collected fields for the pipeline; target_attendance as int; default country UK."""
    def _int_or_none(v: Any) -> Optional[int]:
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    country = session.get("location_country")
    if country is None:
        country = "UK"

    return {
        "event_type": session.get("event_type"),
        "topic": session.get("topic"),
        "date": session.get("date"),
        "location_city": session.get("location_city"),
        "location_country": country,
        "target_attendance": _int_or_none(session.get("target_attendance")),
        "audience_constraints": session.get("audience_constraints"),
        "event_platform": session.get("event_platform"),
        "exclusions": session.get("exclusions"),
        "goal_beyond_attendance": session.get("goal_beyond_attendance"),
    }


if __name__ == "__main__":
    greeting = (
        "Let's get started! I am here to help you. "
        "Tell me a bit about what you have in mind — what kind of event are you thinking of?"
    )
    print(greeting)
    sess = create_brief_session()
    while not sess["is_complete"]:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        reply, sess = process_user_message(sess, user_input)
        print(f"\nBrief Analyst: {reply}")
    if sess["is_complete"]:
        brief = get_parsed_brief(sess)
        print("\n--- Parsed brief ---")
        print(json.dumps(brief, indent=2, ensure_ascii=False))
