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
    r'\b\d{2,6}\s*(?:per\s+person|pp|each|total)\b',
    r'\b(?:low|medium|mid|high|tight|small|big)\s+budget\b',
    r'\b(?:cheap|expensive|affordable|luxur(?:y|ious)|budget[- ]?friendly)\b',
    r'\bunder\s+(?:₹|rs\.?|\$)?\s*[\d,]+',
]

# Date patterns
_DATE_PATTERNS = [
    r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b',
    r'\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b',
    r'\b(?:next|this|end of|mid|beginning of|start of|early|late)\s+(?:week|month|weekend|monday|tuesday|wednesday|thursday|friday|january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)',
    r'\b\d{4}-\d{2}-\d{2}\b',
    r'\btoday\b|\btomorrow\b|\bweekend\b',
    r'\b(?:2025|2026|2027)\b',
    r'\bin\s+(?:a\s+)?(?:few|couple|2|3)\s+(?:weeks?|months?)\b',
    r'\b(?:around|about|sometime)\s+(?:in\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b',
    r'\bnext\s+(?:month|week|year|weekend)\b',
    r'\b(?:flexible|anytime|asap|soon|no fixed)\b',
]

# Duration patterns
_DURATION_PATTERNS = [
    r'\b(\d+)\s*(?:days?|nights?|weeks?)\b',
    r'\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:days?|nights?|weeks?)\b',
    r'\b(\d+)[- ]?day\b',
    r'\bweekend\b',  # implies ~2-3 days
    r'\b(?:couple|few)\s+(?:of\s+)?(?:days?|nights?|weeks?)\b',
    r'\blong\s+weekend\b',
    r'\b(?:a|one)\s+week\b',
    r'\bhalf\s+(?:a\s+)?week\b',
    r'\b(?:short|quick)\s+trip\b',
]

# Group size patterns
_GROUP_PATTERNS = [
    r'\b(\d+)\s*(?:people|persons?|friends?|members?|travelers?|of us|pax)\b',
    r'\b(?:solo|alone|by myself|just me|myself|only me)\b',
    r'\b(?:couple|two of us|just the two|just us two|me and my (?:friend|wife|husband|partner|bf|gf|girlfriend|boyfriend))\b',
    r'\b(?:family|group|team|squad|crew|gang|us|we are|we\'re)\b',
    r'\bjust us\b',
    r'\bwith\s+(?:my\s+)?(?:friends?|family|wife|husband|partner|kids?|children)\b',
    r'\b(?:me\s+and|and\s+me)\b',
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
    if not isinstance(text, str):
        return None
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
    
    last_question = None
    
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if content is None:
            content = ""
        elif not isinstance(content, str) and not isinstance(content, list):
            content = str(content)
        
        # Flatten content if list
        if isinstance(content, list):
            content = " ".join([p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"])
        
        if role == "assistant":
            text = content.lower()
            if "starting from" in text or "start from" in text or "origin" in text:
                last_question = "origin"
            elif "want to go" in text or "destination" in text:
                last_question = "destination"
            elif "when" in text or "dates" in text or "traveling" in text:
                last_question = "dates"
            elif "who" in text or "group" in text or "joining" in text:
                last_question = "group_size"
            elif "budget" in text:
                last_question = "budget"
            else:
                last_question = None
                
        elif role == "user":
            text = content.lower()
            
            # Extract cities
            cities_found = []
            for city in _ALL_CITIES:
                if re.search(r'\b' + re.escape(city) + r'\b', text):
                    cities_found.append(city.title())
            
            # Context-sensitive extraction based on the last question asked
            if last_question == "origin" and cities_found:
                state.has_origin = True
                state.origin = cities_found[0]
            elif last_question == "destination" and cities_found:
                state.has_destination = True
                state.destination = cities_found[0]
            elif last_question == "destination" and any(re.search(pat, text) for pat in _VIBE_PATTERNS):
                state._has_vibe = True
            elif last_question == "dates" and any(re.search(pat, text) for pat in _DATE_PATTERNS + _DURATION_PATTERNS):
                state.has_dates = True
                if any(re.search(pat, text) for pat in _DURATION_PATTERNS):
                    state.has_duration = True
            elif last_question == "group_size" and (any(re.search(pat, text) for pat in _GROUP_PATTERNS) or re.search(r'\b\d{1,2}\b', text)):
                state.has_group_size = True
            elif last_question == "budget" and (any(re.search(pat, text) for pat in _BUDGET_PATTERNS) or re.search(r'\b\d{3,7}\b', text)):
                state.has_budget = True

            # Global pattern matchers (fallbacks/first turn)
            if not state.has_budget:
                budget_match = _check_pattern_list(text, _BUDGET_PATTERNS)
                if budget_match:
                    state.has_budget = True
                    state.budget_raw = budget_match
            if not state.has_dates:
                date_match = _check_pattern_list(text, _DATE_PATTERNS)
                if date_match:
                    state.has_dates = True
                    state.dates_raw = date_match
            if not state.has_duration:
                dur_match = _check_pattern_list(text, _DURATION_PATTERNS)
                if dur_match:
                    state.has_duration = True
                    state.duration_raw = dur_match
                    # Duration implies enough date info — user gave temporal context
                    state.has_dates = True
            if not state.has_group_size:
                grp_match = _check_pattern_list(text, _GROUP_PATTERNS)
                if grp_match:
                    state.has_group_size = True
                    state.group_raw = grp_match
                    
            if cities_found:
                has_origin_kw = any(w in text for w in ["from", "starting", "departing", "leaving", "origin"])
                has_dest_kw = any(w in text for w in ["to", "visit", "going", "trip to", "destination"])
                
                if has_origin_kw:
                    state.has_origin = True
                    state.origin = cities_found[0]
                elif has_dest_kw:
                    state.has_destination = True
                    state.destination = cities_found[0]
                else:
                    if not state.has_origin and not state.has_destination:
                        if len(cities_found) == 1:
                            if last_question == "origin":
                                state.has_origin = True
                                state.origin = cities_found[0]
                            else:
                                state.has_destination = True
                                state.destination = cities_found[0]
                        else:
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

            # Vibe check fallback
            if not state.has_destination and not state._has_vibe:
                if _check_pattern_list(text, _VIBE_PATTERNS):
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


def is_greeting(text: str) -> bool:
    """Check if the text is a simple greeting."""
    if not isinstance(text, str):
        return False
    clean = re.sub(r'[^\w\s]', '', text.strip().lower())
    greetings = {
        "hi", "hello", "hey", "hola", "greetings", "good morning", 
        "good afternoon", "good evening", "yo", "wassup", "sup", 
        "hey there", "hi there", "hello there"
    }
    return clean in greetings


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

    # Fail-safe turn count: if the user has replied 2+ times to details questions
    # and we are still missing fields, bypass interception and let the smart LLM
    # ask for details or plan directly to avoid infinite looping.
    if n_user > 2:
        return False, None

    # Check if the latest user message is just a greeting
    last_user_content = user_msgs[-1].get("content")
    if last_user_content is None:
        last_user_content = ""
    if isinstance(last_user_content, str):
        if is_greeting(last_user_content):
            return False, None
    elif isinstance(last_user_content, list):
        text_parts = [
            p.get("text", "") for p in last_user_content 
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        text_content = " ".join(text_parts)
        if is_greeting(text_content):
            return False, None

    # Extract clean text from latest user message for intent detection
    latest_text = ""
    if isinstance(last_user_content, str):
        latest_text = last_user_content.lower()
    elif isinstance(last_user_content, list):
        latest_text = " ".join([p.get("text", "") for p in last_user_content if isinstance(p, dict) and p.get("type") == "text"]).lower()

    state = extract_tier1_from_messages(messages)

    # If complete, let the LLM handle it
    if state.is_complete:
        return False, None

    # First message: only intercept if they are explicitly asking for a trip/planning
    # AND they have almost all fields missing.
    if n_user == 1:
        # Check for trip planning intent keywords
        intent_keywords = ["plan", "trip", "travel", "itinerary", "vacation", "holiday", "visit", "go to", "tour"]
        has_intent = any(kw in latest_text for kw in intent_keywords)
        
        # Also check if they triggered one of our followup suggestions (which contain 'followup:')
        is_followup_chip = "followup:" in latest_text or "starting from" in latest_text or "want to go" in latest_text
        
        if (has_intent or is_followup_chip) and len(state.missing_fields) >= 4:
            is_first = True
            question = build_tier1_question(state, is_first)
            return True, question

    # Subsequent messages: never intercept, let the highly intelligent LLM converse naturally!
    return False, None
