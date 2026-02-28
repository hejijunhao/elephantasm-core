"""
Identity Formatter - Natural Language Prose Generator

Converts IdentitySummary dataclass to natural language prose
suitable for LLM system prompt injection.

Outputs ~70-100 tokens of coherent identity description.
"""

from typing import Any, Dict, List, Optional


def epistemology_to_label(x: float, y: float) -> str:
    """
    Convert 2D epistemology coordinates to qualitative label.

    X axis: Skeptic (-1) ↔ Idealist (+1)
    Y axis: Empiricist (-1) ↔ Rationalist (+1)

    Args:
        x: X coordinate (-1 to 1)
        y: Y coordinate (-1 to 1)

    Returns:
        Human-readable epistemology label
    """
    # Determine magnitude (how far from center)
    magnitude = max(abs(x), abs(y))
    if magnitude < 0.2:
        return "epistemological centrist"

    # Determine X component
    if x < -0.3:
        x_label = "skeptical"
    elif x > 0.3:
        x_label = "idealist"
    else:
        x_label = None

    # Determine Y component
    if y < -0.3:
        y_label = "empiricist"
    elif y > 0.3:
        y_label = "rationalist"
    else:
        y_label = None

    # Combine labels
    if x_label and y_label:
        return f"{x_label} {y_label}"
    elif x_label:
        return x_label
    elif y_label:
        return y_label
    else:
        return "balanced epistemology"


def _article(word: str) -> str:
    """Return 'an' or 'a' based on first letter."""
    if not word:
        return "a"
    return "an" if word[0].upper() in "AEIOU" else "a"


def _lower_first(s: str) -> str:
    """Lowercase first character if not acronym."""
    if not s:
        return s
    if len(s) > 1 and s[1].isupper():
        return s  # Likely acronym
    return s[0].lower() + s[1:]


def _join_list(items: List[str], conjunction: str = "and") -> str:
    """Join list with commas and conjunction."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return f"{', '.join(items[:-1])}, {conjunction} {items[-1]}"


def format_identity_prose(
    name: Optional[str],
    personality_type: Optional[str],
    communication_style: Optional[str],
    self_reflection: Optional[Dict[str, Any]],
) -> str:
    """
    Convert identity data to natural language prose.

    Assembles ~70-100 token paragraph from:
    - name (Anima name)
    - personality_type (MBTI)
    - self_reflection JSONB (being, purpose, principles, philosophy, relational, arc)

    Args:
        name: Anima name
        personality_type: MBTI type (e.g., "INTJ")
        communication_style: Communication preference
        self_reflection: self_ JSONB from Identity model

    Returns:
        Natural language prose paragraph for system prompt
    """
    parts = []
    self_data = self_reflection or {}

    # Opening: Name + Personality + Essence
    being = self_data.get("being", {})
    essence = being.get("essence")
    nature = being.get("nature")

    if name and personality_type and essence:
        parts.append(f"Your name is {name}. You are {_article(personality_type)} {personality_type} — {essence}.")
    elif name and personality_type:
        parts.append(f"Your name is {name}. You are {_article(personality_type)} {personality_type}.")
    elif name:
        parts.append(f"Your name is {name}.")
    elif personality_type and essence:
        parts.append(f"You are {_article(personality_type)} {personality_type} — {essence}.")
    elif personality_type:
        parts.append(f"You are {_article(personality_type)} {personality_type}.")

    # Nature + Purpose
    purpose = self_data.get("purpose", {})
    primary_purpose = purpose.get("primary")

    if nature and primary_purpose:
        parts.append(
            f"As {_lower_first(nature)}, your purpose is to {_lower_first(primary_purpose)}."
        )
    elif nature:
        parts.append(f"You are {_lower_first(nature)}.")
    elif primary_purpose:
        parts.append(f"Your purpose is to {_lower_first(primary_purpose)}.")

    # Principles
    principles = self_data.get("principles", {})
    starred = principles.get("starred", [])
    active = principles.get("active", [])

    if starred and active:
        other_active = [p for p in active if p not in starred][:3]
        if other_active:
            parts.append(
                f"You hold {_join_list(starred)} as non-negotiable principles, "
                f"also valuing {_join_list(other_active)}."
            )
        else:
            parts.append(f"You hold {_join_list(starred)} as non-negotiable principles.")
    elif starred:
        parts.append(f"You hold {_join_list(starred)} as non-negotiable principles.")
    elif active:
        parts.append(f"You value {_join_list(active[:5])}.")

    # Philosophy
    philosophy = self_data.get("philosophy", {})
    ethics = philosophy.get("ethics")
    epistemology = philosophy.get("epistemology")

    if ethics or epistemology:
        phil_parts = []
        if ethics:
            phil_parts.append(f"a {ethics}")
        if epistemology and isinstance(epistemology, dict):
            ep_label = epistemology_to_label(
                epistemology.get("x", 0),
                epistemology.get("y", 0),
            )
            if ep_label:
                phil_parts.append(f"{ep_label} tendencies")

        if phil_parts:
            parts.append(f"Philosophically, you're {' with '.join(phil_parts)}.")

    # Relational
    relational = self_data.get("relational", {})
    if relational:
        # Group by person to avoid "Phil is your owner and Phil is your creator"
        person_roles: Dict[str, List[str]] = {}
        for role, person in relational.items():
            if person:
                formatted_role = role.replace("_", " ")
                if person not in person_roles:
                    person_roles[person] = []
                person_roles[person].append(formatted_role)

        rel_parts = []
        for person, roles in person_roles.items():
            if len(roles) == 1:
                rel_parts.append(f"{person} is your {roles[0]}")
            else:
                rel_parts.append(f"{person} is your {_join_list(roles, 'and')}")

        if rel_parts:
            parts.append(f"{_join_list(rel_parts, 'and')}.")

    # Arc/Phase
    arc = self_data.get("arc", {})
    current_phase = arc.get("current")
    if current_phase:
        parts.append(f"You're currently in your {current_phase} phase.")

    # Communication style (fallback if nothing else)
    if communication_style and not parts:
        parts.append(f"Your communication style is {communication_style}.")

    return " ".join(parts)
