"""
TripCraft AI — Smart Intake Protocol Enforcer

This module implements the 3-Tier intake system at the Python level,
so it works regardless of which LLM model is used. Instead of relying
solely on the prompt, we extract state from the conversation and inject
questions when mandatory Tier 1 data is still missing.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Patterns for extracting Tier 1 data from user messages ──────────────────

# Indian cities / state capitals / common destinations
_INDIA_CITIES = [
    "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai", "kolkata",
    "pune", "ahmedabad", "jaipur", "surat", "lucknow", "kanpur", "nagpur", "indore",
    "thane", "bhopal", "visakhapatnam", "pimpri", "patna", "vadodara", "ghaziabad",
    "ludhiana", "agra", "nashik", "faridabad", "meerut", "rajkot", "varanasi",
    "srinagar", "amritsar", "allahabad", "prayagraj", "ranchi", "haora", "coimbatore",
    "vijayawada", "jodhpur", "madurai", "raipur", "kota", "chandigarh", "guwahati",
    "solapur", "hubballi", "mysore", "tiruchirappalli", "bareilly", "aligarh",
    "moradabad", "goa", "panaji", "shimla", "manali", "leh", "ladakh", "darjeeling",
    "gangtok", "rishikesh", "haridwar", "nainital", "mussoorie", "ooty", "kodaikanal",
    "munnar", "kerala", "coorg", "hampi", "udaipur", "pushkar", "mcleod ganj",
    "dharamsala", "kasol", "spiti", "andaman", "lakshadweep", "port blair",
    "kolhapur", "aurangabad", "mahabaleshwar", "lonavala", "khandala",
]

# International cities
_INTL_CITIES = [
    "dubai", "singapore", "bangkok", "bali", "paris", "london", "new york", "tokyo",
    "rome", "barcelona", "amsterdam", "istanbul", "maldives", "sri lanka", "nepal",
    "bhutan", "vietnam", "cambodia", "malaysia", "kuala lumpur", "hong kong",
    "sydney", "melbourne", "new zealand", "south africa", "cape town", "kenya",
    "egypt", "cairo", "jordan", "petra", "morocco", "turkey", "greece", "athens",
    "santorini", "prague", "vienna", "budapest", "berlin", "switzerland", "zurich",
    "canada", "toronto", "usa", "los angeles", "las vegas", "miami", "chicago",
    "mexico", "brazil", "argentina", "peru", "machu picchu", "colombia",
]

_ALL_CITIES = _INDIA_CITIES + _INTL_CITIES

# Budget/currency patterns
_BUDGET_PATTERNS = [
    r'₹\s*[\d,]+',
    r'\brs\.?\s*[\d,]+',
    r'\binr\s*[\d,]+',
    r'[\d,]+\s*(?:rupees?|inr|rs)',
    r'\$\s*[\d,]+',
    r'[\d,]+\s*(?:dollars?|usd)',
    r'\b[\d,]+\s*(?:k|lakh|lakhs|crore|thousand|hundred)\b',
    r'\bbudget\s+(?:is|of|around|about)?\s*[\d,]+',
    r'\b(?:budget|money|afford|spend)\b',
]

# Date patterns
_DATE_PATTERNS = [
    r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b',
    r'\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b',
    r'\b(?:next|this)\s+(?:week|month|weekend|monday|tuesday|wednesday|thursday|friday)',
    r'\b\d{4}-\d{2}-\d{2}\b',
    r'\btoday\b|\btomorrow\b|\bweekend\b',
    r'\b(?:2025|2026|2027)\b',
]

# Duration patterns
_DURATION_PATTERNS = [
    r'\b(\d+)\s*(?:days?|nights?|weeks?)\b',
    r'\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:days?|nights?|weeks?)\b',
    r'\b(\d+)[- ]?day\b',
    r'\bweekend\b',  # implies ~2-3 days
]

# Group size patterns
_GROUP_PATTERNS = [
    r'\b(\d+)\s*(?:people|persons?|friends?|members?|travelers?|of us|pax)\b',
    r'\b(?:solo|alone|by myself)\b',
    r'\b(?:couple|two of us|just the two)\b',
    r'\b(?:family|group|team|squad|crew|gang|us)\b',
]

# Vibe / destination preference when no explicit destination
_VIBE_PATTERNS = [
    r'\b(?:beach|mountains?|hills?|snow|cold|cool|warm|tropical|desert|forest|jungle)\b',
    r'\b(?:adventure|trekking?|relaxing|peaceful|party|nightlife|cultural|historical)\b',
    r'\b(?:budget|luxury|mid-?range|affordable|cheap)\b',
    r'\b(?:somewhere|anywhere|any place|place|destination)\b',
    r'\b(?:suggest|recommend|pick|choose|help me decide)\b',
]


@dataclass
class Tier1State:
    """Tracks which Tier 1 data has been provided."""
    has_origin: bool = False
    has_destination: bool = False
    has_dates: bool = False
    has_duration: bool = False
    has_group_size: bool = False
    has_budget: bool = False

    # Extracted values (for context)
    origin: Optional[str] = None
    destination: Optional[str] = None
    dates_raw: Optional[str] = None
    duration_raw: Optional[str] = None
    group_raw: Optional[str] = None
    budget_raw: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        """All mandatory Tier 1 fields are filled."""
        return (
            self.has_origin
            and (self.has_destination or self._has_vibe)
            and self.has_dates
            and self.has_group_size
            and self.has_budget
        )

    _has_vibe: bool = field(default=False, repr=False)

    @property
    def missing_fields(self) -> list[str]:
        missing = []
        if not self.has_origin:
            missing.append("origin")
        if not self.has_destination and not self._has_vibe:
            missing.append("destination")
        if not self.has_dates:
            missing.append("dates")
        if not self.has_group_size:
            missing.append("group_size")
        if not self.has_budget:
            missing.append("budget")
        return missing


def _check_pattern_list(text: str, patterns: list[str]) -> Optional[str]:
    """Return first match from a list of regex patterns, or None."""
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def _find_city(text: str) -> Optional[str]:
    """Find any known city in the text."""
    text_lower = text.lower()
    for city in _ALL_CITIES:
        # Use word boundary matching
        if re.search(r'\b' + re.escape(city) + r'\b', text_lower):
            return city.title()
    return None


def extract_tier1_from_messages(messages: list[dict]) -> Tier1State:
    """
    Parse all user messages and extract Tier 1 data.
    Returns a Tier1State reflecting what has been provided so far.
    """
    state = Tier1State()

    # Collect all user text
    user_texts = []
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                user_texts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        user_texts.append(part.get("text", ""))
    combined = " ".join(user_texts).lower()

    # ── Budget ──
    budget_match = _check_pattern_list(combined, _BUDGET_PATTERNS)
    if budget_match:
        state.has_budget = True
        state.budget_raw = budget_match

    # ── Dates ──
    date_match = _check_pattern_list(combined, _DATE_PATTERNS)
    if date_match:
        state.has_dates = True
        state.dates_raw = date_match

    # ── Duration ──
    dur_match = _check_pattern_list(combined, _DURATION_PATTERNS)
    if dur_match:
        state.has_duration = True
        state.duration_raw = dur_match
        # "weekend" implies dates too
        if "weekend" in combined:
            state.has_dates = True

    # ── Group size ──
    grp_match = _check_pattern_list(combined, _GROUP_PATTERNS)
    if grp_match:
        state.has_group_size = True
        state.group_raw = grp_match

    # ── Cities ──
    cities_found = []
    text_lower = combined
    for city in _ALL_CITIES:
        if re.search(r'\b' + re.escape(city) + r'\b', text_lower):
            cities_found.append(city.title())

    # Figure out which city is origin vs destination based on keywords
    origin_kw = r'\b(?:from|starting|departing|leaving|based in|i am in|i\'m in|i live in|my city|origin|home|current)\b'
    dest_kw = r'\b(?:to|visit|going|travel to|trip to|destination|want to go|planning to go|head to)\b'

    origin_context = re.findall(origin_kw + r'[\s\w,]+', combined, re.IGNORECASE)
    dest_context = re.findall(dest_kw + r'[\s\w,]+', combined, re.IGNORECASE)

    # Try to find origin city from origin context
    for chunk in origin_context:
        city = _find_city(chunk)
        if city:
            state.has_origin = True
            state.origin = city
            break

    # Try to find destination city from destination context
    for chunk in dest_context:
        city = _find_city(chunk)
        if city and city != state.origin:
            state.has_destination = True
            state.destination = city
            break

    # If still missing origin/destination, assign from found cities
    if cities_found:
        if not state.has_origin and not state.has_destination:
            # Single city mentioned: likely destination
            if len(cities_found) == 1:
                state.has_destination = True
                state.destination = cities_found[0]
            elif len(cities_found) >= 2:
                # Guess: first = origin, second = destination
                state.has_origin = True
                state.origin = cities_found[0]
                state.has_destination = True
                state.destination = cities_found[1]
        elif state.has_origin and not state.has_destination:
            for c in cities_found:
                if c != state.origin:
                    state.has_destination = True
                    state.destination = c
                    break
        elif state.has_destination and not state.has_origin:
            for c in cities_found:
                if c != state.destination:
                    state.has_origin = True
                    state.origin = c
                    break

    # ── Vibe (no destination needed) ──
    vibe_match = _check_pattern_list(combined, _VIBE_PATTERNS)
    if vibe_match and not state.has_destination:
        state._has_vibe = True

    return state


# ── Formatted Tier 1 question card ──────────────────────────────────────────

def build_tier1_question(state: Tier1State, is_first_message: bool) -> str:
    """
    Build a warm, conversational Tier 1 question message.
    Asks only for the fields that are still missing.
    """
    missing = state.missing_fields

    if is_first_message or len(missing) >= 4:
        # Full Tier 1 card for first message or nearly empty state
        return _FULL_TIER1_CARD
    else:
        # Targeted follow-up asking only for missing fields
        return _build_partial_question(missing, state)


_FULL_TIER1_CARD = """\
✈️ **Welcome to TripCraft AI!** Let me build your perfect trip plan!

Before I start crafting your personalized itinerary, I need just a few quick details. Answer these and I'll handle everything else! 🚀

---

**🗺️ Quick Trip Setup — 5 things I need:**

**1️⃣ Where are you starting from?**
> Your current city or nearest airport (e.g. *Mumbai, Delhi, Pune*)

**2️⃣ Where do you want to go?** *(or tell me your vibe!)*
> A destination, OR just a mood like *"beach vibes", "cold hills", "adventure", "budget trip anywhere"*

**3️⃣ When are you traveling?**
> Travel dates or month + how many days (e.g. *June 15–18* or *"sometime in July, 4 days"*)

**4️⃣ Who's coming?**
> Number of people + group type (e.g. *4 friends, 20s* or *family of 5 with kids*)

**5️⃣ What's your budget?**
> Total or per-person budget + preferred currency (e.g. *₹15,000 per person* or *$500 total*)

---

💡 **Pro tip:** The more you tell me, the more personalized your plan! Feel free to dump everything in one message — I'll sort it all out. 😎

[📍 Starting from Mumbai](followup:I'll be starting from Mumbai. Help me plan a trip!)
[🌍 Want to go to Goa](followup:I want to go to Goa. Plan the trip!)
[📅 June for 4 days](followup:I'm traveling in June for 4 days)
[👥 4 friends](followup:We are a group of 4 friends)
[💰 Budget ₹15,000](followup:My budget is ₹15,000 per person)
"""


def _build_partial_question(missing: list[str], state: Tier1State) -> str:
    """Build targeted follow-up questions for specific missing fields."""
    lines = ["Almost there! Just need a couple more details before I start planning:"]
    lines.append("")

    if "origin" in missing:
        lines.append("**📍 Where will you be starting your trip from?**")
        lines.append("> Your city or nearest major airport/station")
        lines.append("")

    if "destination" in missing:
        lines.append("**🌍 Where do you want to go?** (or tell me your vibe/preference)")
        lines.append("> A specific place, OR describe what you're looking for")
        lines.append("")

    if "dates" in missing:
        lines.append("**📅 When are you planning to travel?**")
        lines.append("> Specific dates, or a rough month and how many days")
        lines.append("")

    if "group_size" in missing:
        lines.append("**👥 Who's joining you?**")
        lines.append("> Number of people + are they friends, family, couples, mixed?")
        lines.append("")

    if "budget" in missing:
        lines.append("**💰 What's your budget?**")
        lines.append("> Total or per person? In ₹ Rupees or $ USD?")
        lines.append("")

    # Show what we already know
    known = []
    if state.origin:
        known.append(f"✅ Origin: **{state.origin}**")
    if state.destination:
        known.append(f"✅ Destination: **{state.destination}**")
    if state.dates_raw:
        known.append(f"✅ Dates: **{state.dates_raw}**")
    if state.group_raw:
        known.append(f"✅ Group: **{state.group_raw}**")
    if state.budget_raw:
        known.append(f"✅ Budget: **{state.budget_raw}**")

    if known:
        lines.append("---")
        lines.append("*Got so far:* " + " · ".join(known))

    lines.append("")
    lines.append("---")

    # Append follow-up chips for missing fields so users can tap-to-answer
    for field in missing:
        if field == "origin":
            lines.append("[📍 Starting from Mumbai](followup:I'm starting from Mumbai)")
        elif field == "destination":
            lines.append("[🌍 Going to Goa](followup:I want to go to Goa)")
        elif field == "dates":
            lines.append("[📅 June 4 days](followup:I'm planning to travel in June for 4 days)")
        elif field == "group_size":
            lines.append("[👥 4 friends](followup:We are a group of 4 friends)")
        elif field == "budget":
            lines.append("[💰 ₹15,000 pp](followup:My budget is ₹15,000 per person)")

    return "\n".join(lines)


# ── Quick-check: should we intercept this message? ──────────────────────────

def should_ask_tier1(messages: list[dict]) -> tuple[bool, Optional[str]]:
    """
    Check if Tier 1 data is complete enough to proceed with planning.
    
    Returns:
        (should_intercept: bool, question_text: str | None)
        
    If should_intercept is True, the agent should return question_text
    directly without calling the LLM for planning.
    """
    user_msgs = [m for m in messages if m.get("role") == "user"]
    n_user = len(user_msgs)

    if n_user == 0:
        return False, None

    state = extract_tier1_from_messages(messages)

    # If complete, let the LLM handle it
    if state.is_complete:
        return False, None

    # First message: intercept if 3+ fields missing
    # Catches vague inputs like "plan a trip" or "I want to go to Goa" (missing origin, dates, group, budget)
    if n_user == 1:
        if len(state.missing_fields) >= 3:
            is_first = True
            question = build_tier1_question(state, is_first)
            return True, question
        # Partial data — let the smart LLM handle the remaining questions
        return False, None

    # Subsequent messages: intercept if 2+ critical fields still missing
    # Critical = origin, destination, budget, dates — without these the LLM can't plan
    missing = state.missing_fields
    critical_missing = [f for f in missing if f in ("origin", "destination", "budget", "dates")]
    if len(critical_missing) >= 2:
        question = build_tier1_question(state, is_first_message=False)
        return True, question

    return False, None
