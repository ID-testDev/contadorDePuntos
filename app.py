# app.py
import re
import streamlit as st
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

# -------------------- Constants --------------------
# Canonical team symbols (what we display and store)
TEAMS = {
    "❤️": "Gryffindor",
    "💚": "Slytherin",
    "💙": "Ravenclaw",
    "💛": "Hufflepuff",
}
TOP_POINTS = [1000, 900, 800, 700]
ABSENT_TOP_POINTS = 350
ANSWER_POINTS = 20

OWL = "🦉"
TOAD = "🐸"

OUTPUT_STYLES = {
    "Output A — Estilo Formato 1 (decorado)": "style1",
    "Output B — Estilo Formato 2 (medallas + mascotas + rondas)": "style2",
    "Output C — Casas en bloques (WhatsApp markdown)": "style3",
}

DASH_REGEX = r"[-‐‑‒–—−]"


HOUSE_BADGES = {
    "💛": ("🦡", "HUFFLEPUFF"),
    "💙": ("🦅", "RAVENCLAW"),
    "💚": ("🐍", "SLYTHERIN"),
    "❤️": ("🦁", "GRYFFINDOR"),
}

def fmt_commas(n: int) -> str:
    return f"{n:,}"


# -------------------- WhatsApp-safe normalization (future-proof) --------------------
# We deliberately do NOT remove ZWJ (\u200D) nor VS16 (\uFE0F) to avoid breaking compound emojis.
_INVISIBLES_MAP = dict.fromkeys(
    map(
        ord,
        [
            "\u200b",  # Zero Width Space
            "\u200c",  # ZWNJ
            "\u2060",  # Word Joiner
            "\ufeff",  # BOM / ZWNBSP
            "\u200e",  # LRM
            "\u200f",  # RLM
            "\u00a0",  # NBSP
        ],
    ),
    None,
)

def normalize_wa(s: str) -> str:
    """Normalize WhatsApp text: remove common invisible chars and normalize dash variants."""
    if s is None:
        return ""
    s = s.translate(_INVISIBLES_MAP)
    # Normalize many dash-like characters to ASCII hyphen '-'
    # Includes: hyphen, non-breaking hyphen, figure dash, en dash, em dash, minus sign
    s = s.translate(str.maketrans({
        "‐": "-",  # U+2010 hyphen
        "‑": "-",  # U+2011 non-breaking hyphen
        "‒": "-",  # U+2012 figure dash
        "–": "-",  # U+2013 en dash
        "—": "-",  # U+2014 em dash
        "−": "-",  # U+2212 minus sign
    }))
    return s

def strip_ws(s: str) -> str:
    """Remove all whitespace AFTER WhatsApp normalization."""
    s = normalize_wa(s)
    return re.sub(r"\s+", "", s).strip()

# -------------------- Team tokenization (handles ❤ vs ❤️ safely) --------------------
HEART_CHAR = "❤"          # U+2764
VS16 = "\ufe0f"           # Variation Selector-16
HEART_TEAM = "❤️"         # canonical display for Gryffindor

def iter_team_emojis(s: str):
    """
    Yield canonical team emojis found in s.
    Handles the common WhatsApp case where Gryffindor appears as ❤ (no VS16)
    or as ❤️ (❤ + VS16). We keep VS16 in general, but tokenize hearts safely.
    """
    s = normalize_wa(s)
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == HEART_CHAR:
            # consume optional VS16
            if i + 1 < len(s) and s[i + 1] == VS16:
                i += 2
            else:
                i += 1
            yield HEART_TEAM
            continue
        if ch in TEAMS and ch != HEART_TEAM:
            i += 1
            yield ch
            continue
        i += 1

def first_team_in_line(line: str) -> Optional[str]:
    for t in iter_team_emojis(line):
        return t
    return None

def only_team_emojis(s: str) -> List[str]:
    return list(iter_team_emojis(s))

def count_team_emojis(s: str) -> Dict[str, int]:
    counts = {e: 0 for e in TEAMS}
    for t in iter_team_emojis(s):
        counts[t] += 1
    return counts

def detect_multiplier_in_text(s: str) -> Tuple[int, List[str]]:
    """Detect x2/x3 markers in free text. Returns (multiplier, alerts). Case-insensitive.
    Supported: 'doble', 'dobles', 'x2', 'x 2' => 2; 'triple', 'triples', 'x3', 'x 3' => 3.
    If both appear, uses the max and emits an alert.
    """
    alerts: List[str] = []
    s_norm = normalize_wa(s or "")
    s_low = s_norm.lower()

    has2 = bool(re.search(r"\b(doble|dobles)\b", s_low)) or bool(re.search(r"\bx\s*2\b", s_low))
    has3 = bool(re.search(r"\b(triple|triples)\b", s_low)) or bool(re.search(r"\bx\s*3\b", s_low))

    if has2 and has3:
        alerts.append("Alerta: se detectaron marcadores de multiplicador x2 y x3 en la misma ronda; se tomará x3 por default.")
        return 3, alerts
    if has3:
        return 3, alerts
    if has2:
        return 2, alerts
    return 1, alerts


def strip_multiplier_markers(s: str) -> str:
    """Remove multiplier keywords (doble/triple/x2/x3) from a line before counting emojis or rendering cleaned rounds."""
    s_norm = normalize_wa(s or "")
    s_norm = re.sub(r"(?i)\b(doble|dobles|triple|triples)\b", "", s_norm)
    s_norm = re.sub(r"(?i)\bx\s*[23]\b", "", s_norm)
    return s_norm

# -------------------- Formatting --------------------
def fmt_thousands_dot(n: int) -> str:
    return f"{n:,}".replace(",", ".")

def fmt_output2_commas(n: int) -> str:
    if n >= 10000:
        return f"{n:,}"
    s = f"{n:05d}"
    return f"{s[:-3]},{s[-3:]}"

def medal_lines_sorted(totals: Dict[str, int]) -> List[Tuple[str, str, int]]:
    items = [(e, totals[e]) for e in TEAMS]
    items.sort(key=lambda x: (-x[1], x[0]))
    medals = ["🥇", "🥈", "🥉", "🏅"]
    out: List[Tuple[str, str, int]] = []
    for i, (emoji, pts) in enumerate(items):
        out.append((medals[i] if i < 4 else "🏅", emoji, pts))
    return out

# -------------------- Input format detection --------------------

def detect_input_format(text: str) -> str:
    """Autodetect among format1, format2, format3."""
    text = normalize_wa(text)
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "format1"

    has_trivia_title = bool(re.match(r"^\s*Trivia\b", lines[0], flags=re.IGNORECASE))

    def line_starts_with_team(line: str) -> bool:
        s = normalize_wa(line).lstrip()
        return first_team_in_line(s[:8]) is not None

    has_toad_lines = any(line_starts_with_team(ln) and TOAD in normalize_wa(ln) for ln in lines[:20])

    # --- Format 3 signal: many headers like "1- ..."
    dash_headers = [i for i, ln in enumerate(lines) if re.match(r"^\s*\d+\s*-\s*", ln)]
    if dash_headers:
        # Heuristic: if at least one dash header is followed by a non-empty line with team emojis, treat as format3
        good = 0
        for idx in dash_headers[:10]:
            ln = lines[idx]
            rest = re.sub(r"^\s*\d+\s*-\s*", "", ln).strip()
            if first_team_in_line(rest) is not None or strip_ws(rest) in {"//", "❌"}:
                good += 1
                continue
            # If no top on same line, check next non-empty line
            j = idx + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and (first_team_in_line(lines[j]) is not None or strip_ws(lines[j]) in {"//", "❌"}):
                good += 1
        if good >= 1:
            return "format3"

    # --- Format 2 signals
    round_lines = [ln for ln in lines if re.match(r"^\s*\d+\.\s*", ln)]
    looks_like_single_line_rounds = False
    if round_lines:
        long_rounds = sum(1 for ln in round_lines if len(only_team_emojis(ln)) >= 10)
        looks_like_single_line_rounds = long_rounds >= max(1, len(round_lines) // 2)

    if has_trivia_title or has_toad_lines or looks_like_single_line_rounds:
        return "format2"

    return "format1"

    has_trivia_title = bool(re.match(r"^\s*Trivia\b", lines[0], flags=re.IGNORECASE))

    def line_starts_with_team(line: str) -> bool:
        s = normalize_wa(line).lstrip()
        return first_team_in_line(s[:6]) is not None

    has_toad_lines = any(line_starts_with_team(ln) and TOAD in normalize_wa(ln) for ln in lines[:15])

    round_lines = [ln for ln in lines if re.match(r"^\s*\d+\.\s*", ln)]
    looks_like_single_line_rounds = False
    if round_lines:
        long_rounds = sum(1 for ln in round_lines if len(only_team_emojis(ln)) >= 10)
        looks_like_single_line_rounds = long_rounds >= max(1, len(round_lines) // 2)

    if has_trivia_title or has_toad_lines or looks_like_single_line_rounds:
        return "format2"
    return "format1"

# -------------------- Data models --------------------
@dataclass
class OwlMeta:
    team: str
    owner: str
    name: str
    round_num: int

@dataclass
class ToadMeta:
    team: str
    owner: str
    name: str

@dataclass
class RoundParsed:
    num: int
    raw_line: str               # format2: line after "N."
    top_line: str               # format1: line 1 after "N."
    answer_lines: List[str]     # format1: lines after top
    is_annulled: bool = False
    detected_format: str = "format1"
    detected_multiplier: int = 1  # 1=normal, 2=doble/x2, 3=triple/x3 (prefill; UI can override)
    owls_in_line: List[OwlMeta] = field(default_factory=list)

@dataclass
class ParsedGame:
    input_format: str
    title_line: str = ""
    rounds: List[RoundParsed] = field(default_factory=list)
    toads_prefill: Dict[str, ToadMeta] = field(default_factory=dict)
    owls_prefill_by_team: Dict[str, List[OwlMeta]] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)

# -------------------- Parsers --------------------
def parse_round_blocks_format1(text: str) -> Tuple[List[RoundParsed], List[str]]:
    alerts: List[str] = []
    text = normalize_wa(text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    header_re = re.compile(r"^\s*(\d+)\.\s*(.*)\s*$")

    rounds: List[RoundParsed] = []
    cur_num: Optional[int] = None
    cur_lines: List[str] = []

    def flush():
        nonlocal cur_num, cur_lines
        if cur_num is None:
            return
        clean = [normalize_wa(ln) for ln in cur_lines if ln.strip()]
        top_line = clean[0] if clean else ""
        answer_lines = clean[1:] if len(clean) > 1 else []
        # Detect multiplier markers anywhere inside this round (top or answers)
        joined = " ".join(clean)
        sugg_mult, a_m = detect_multiplier_in_text(joined)
        for msg in a_m:
            alerts.append(f"Ronda {cur_num}: {msg}")
        rounds.append(
            RoundParsed(
                num=cur_num,
                raw_line="",
                top_line=top_line,
                answer_lines=answer_lines,
                detected_format="format1",
                suggested_multiplier=sugg_mult,
            )
        )

    for ln in lines:
        ln = normalize_wa(ln)
        m = header_re.match(ln)
        if m:
            flush()
            cur_num = int(m.group(1))
            rest = normalize_wa(m.group(2)).strip()
            cur_lines = []
            if rest:
                cur_lines.append(rest)
        else:
            if cur_num is None:
                continue
            if ln.strip() == "":
                continue
            cur_lines.append(ln)
    flush()
    return rounds, alerts

def parse_toad_lines_format2(lines: List[str]) -> Dict[str, ToadMeta]:
    toads: Dict[str, ToadMeta] = {}
    for ln in lines:
        s = normalize_wa(ln).strip()
        if not s:
            continue

        team = first_team_in_line(s[:6])
        pos_toad = s.find(TOAD)
        if not team or pos_toad == -1 or pos_toad > 6:
            continue

        rest = s[pos_toad + 1 :].strip()
        if "-" not in rest:
            continue
        left, right = rest.split("-", 1)
        owner = left.strip()
        name = right.strip()
        toads[team] = ToadMeta(team=team, owner=owner, name=name)
    return toads

def _team_before_owl(raw: str, owl_pos: int) -> Optional[str]:
    """Get canonical team immediately before 🦉 handling ❤ + VS16."""
    if owl_pos <= 0:
        return None
    prev = raw[owl_pos - 1]
    if prev in TEAMS and prev != HEART_TEAM:
        return prev
    if prev == HEART_CHAR:
        return HEART_TEAM
    if prev == VS16 and owl_pos >= 2 and raw[owl_pos - 2] == HEART_CHAR:
        return HEART_TEAM
    return None

def _team_starts_at(txt: str, idx: int) -> bool:
    if idx >= len(txt):
        return False
    ch = txt[idx]
    if ch == HEART_CHAR:
        return True
    return ch in TEAMS and ch != HEART_TEAM

def extract_owl_metas_from_round_line(round_num: int, line: str) -> Tuple[List[OwlMeta], List[str]]:
    alerts: List[str] = []
    metas: List[OwlMeta] = []

    raw = normalize_wa(line)
    owl_positions = [m.start() for m in re.finditer(re.escape(OWL), raw)]
    if not owl_positions:
        return metas, alerts

    if len(owl_positions) >= 4:
        alerts.append(
            f"Alerta: en la ronda {round_num} aparecen {len(owl_positions)} lechuzas; "
            f"solo se tomarán en cuenta las primeras 2."
        )

    for pos in owl_positions[:2]:
        team = _team_before_owl(raw, pos)
        if not team:
            alerts.append(
                f"Alerta: en la ronda {round_num} se detectó 🦉 pero no se pudo identificar la casa "
                f"(debe ir pegada antes del 🦉)."
            )
            continue

        after = raw[pos + 1 :]

        nxt = None
        for i in range(len(after)):
            if _team_starts_at(after, i):
                nxt = i
                break

        meta_chunk = after[:nxt].strip() if nxt is not None else after.strip()

        if "-" not in meta_chunk:
            alerts.append(
                f"Alerta: en la ronda {round_num} no se encontró el separador '-' para la lechuza de {team}. "
                f"Se esperaba algo como 'Dueño - Nombre'."
            )
            owner = meta_chunk.strip()
            name = ""
        else:
            left, right = meta_chunk.split("-", 1)
            owner = left.strip()
            name = right.strip()

        metas.append(OwlMeta(team=team, owner=owner, name=name, round_num=round_num))

    return metas, alerts

def parse_format2(text: str) -> ParsedGame:
    text = normalize_wa(text)
    raw_lines = [ln.rstrip("\n") for ln in text.splitlines()]
    nonempty = [ln for ln in raw_lines if ln.strip()]

    title = nonempty[0].strip() if nonempty else ""
    round_header_re = re.compile(r"^\s*(\d+)\.\s*(.*)\s*$")

    before_rounds: List[str] = []
    round_lines: List[str] = []
    in_rounds = False
    for ln in nonempty[1:]:
        ln = normalize_wa(ln)
        if round_header_re.match(ln):
            in_rounds = True
        if not in_rounds:
            before_rounds.append(ln)
        else:
            round_lines.append(ln)

    toads_prefill = parse_toad_lines_format2(before_rounds)

    rounds: List[RoundParsed] = []
    alerts: List[str] = []
    owls_by_team: Dict[str, List[OwlMeta]] = {e: [] for e in TEAMS}

    for ln in round_lines:
        m = round_header_re.match(ln)
        if not m:
            continue
        rnum = int(m.group(1))
        rest = normalize_wa(m.group(2)).strip()

        is_annulled = strip_ws(rest) in {"//", "❌"}
        rp = RoundParsed(
            num=rnum,
            raw_line=rest,
            top_line="",
            answer_lines=[],
            is_annulled=is_annulled,
            detected_format="format2",
        )

        if not is_annulled:
            metas, a2 = extract_owl_metas_from_round_line(rnum, rest)
            rp.owls_in_line = metas
            alerts.extend(a2)
            for meta in metas:
                owls_by_team[meta.team].append(meta)

        rounds.append(rp)

    owls_prefill_by_team = {t: lst for t, lst in owls_by_team.items() if lst}

    return ParsedGame(
        input_format="format2",
        title_line=title,
        rounds=sorted(rounds, key=lambda x: x.num),
        toads_prefill=toads_prefill,
        owls_prefill_by_team=owls_prefill_by_team,
        alerts=alerts,
    )


def parse_format3(text: str) -> ParsedGame:
    """Format 3:
    - Optional toad lines at start: <TEAM><🐸> Dueño - Sapo
    - Each round uses TWO lines:
        N- <TOP>          (or N- ❌ / N- // for annulled)
        <ANSWERS>         (all extra responses; may include 'doble/dobles/triple/triples/x2/x3')
    """
    text = normalize_wa(text)
    raw_lines = [ln.rstrip("\n") for ln in text.splitlines()]
    nonempty = [ln for ln in raw_lines if ln.strip()]

    # No explicit title in format3; keep blank
    title = ""

    header_re = re.compile(r"^\s*(\d+)\s*-\s*(.*)\s*$")

    before_rounds: List[str] = []
    round_blocks: List[Tuple[int, str, Optional[str]]] = []  # (num, top_part, answers_line)
    i = 0
    in_rounds = False

    while i < len(nonempty):
        ln = normalize_wa(nonempty[i])
        m = header_re.match(ln)
        if not m and not in_rounds:
            before_rounds.append(ln)
            i += 1
            continue
        if m:
            in_rounds = True
            rnum = int(m.group(1))
            rest = normalize_wa(m.group(2)).strip()

            # Determine top line (can be on same line or next line)
            top_line = rest
            # Annulled if rest is ❌ or //
            if strip_ws(top_line) in {"//", "❌"}:
                round_blocks.append((rnum, top_line, None))
                i += 1
                continue

            if first_team_in_line(top_line) is None and strip_ws(top_line) not in {"//", "❌"}:
                # take next line as top if current has no top
                j = i + 1
                if j < len(nonempty):
                    top_line = normalize_wa(nonempty[j]).strip()
                    i = j  # advance
                else:
                    top_line = ""
            # answers line is next non-empty after top
            j = i + 1
            answers_line = None
            if j < len(nonempty):
                # if next is another header, answers missing
                if not header_re.match(nonempty[j]):
                    answers_line = normalize_wa(nonempty[j]).strip()
            round_blocks.append((rnum, top_line, answers_line))
            # advance: if we consumed answers_line, skip it
            if answers_line is not None:
                i = j + 1
            else:
                i += 1
            continue
        # If we're in_rounds but line doesn't match header, skip
        i += 1

    toads_prefill = parse_toad_lines_format2(before_rounds)

    rounds: List[RoundParsed] = []
    alerts: List[str] = []

    for (rnum, top_line, answers_line) in round_blocks:
        is_annulled = strip_ws(top_line) in {"//", "❌"}
        rp = RoundParsed(
            num=rnum,
            raw_line="",  # unused for format3
            top_line=top_line,
            answer_lines=[answers_line] if (answers_line is not None and answers_line.strip()) else [],
            is_annulled=is_annulled,
            detected_format="format3",
        )
        if not is_annulled:
            # detect multiplier in answers line
            mul, a2 = detect_multiplier_in_text(answers_line or "")
            rp.detected_multiplier = mul
            # Attach round context to alerts
            for a in a2:
                alerts.append(f"Alerta (ronda {rnum}): {a}")
        rounds.append(rp)

    return ParsedGame(
        input_format="format3",
        title_line=title,
        rounds=sorted(rounds, key=lambda x: x.num),
        toads_prefill=toads_prefill,
        owls_prefill_by_team={},  # lechuzas aún no definidas para formato3
        alerts=alerts,
    )

def parse_format1(text: str) -> ParsedGame:
    rounds, alerts = parse_round_blocks_format1(text)
    return ParsedGame(input_format="format1", title_line="", rounds=sorted(rounds, key=lambda x: x.num), alerts=alerts)

def parse_game(text: str) -> ParsedGame:
    fmt = detect_input_format(text)
    return parse_format2(text) if fmt == "format2" else parse_format1(text)

# -------------------- Scoring --------------------
def score_round_format1(r: RoundParsed, multiplier: int, toad_bonus: Dict[str, bool]) -> Tuple[Dict[str, int], List[str], Dict[str, int]]:
    alerts: List[str] = []
    pts = {e: 0 for e in TEAMS}
    answers_count = {e: 0 for e in TEAMS}

    top_raw = strip_ws(strip_multiplier_markers(r.top_line))
    if top_raw in {"//", "❌"}:
        r.is_annulled = True

    if r.is_annulled:
        return pts, alerts, answers_count

    present: List[str] = []
    absent: List[str] = []

    if "//" in top_raw:
        left, right = top_raw.split("//", 1)
        present = only_team_emojis(left)
        absent = only_team_emojis(right)
    elif "❌" in top_raw:
        left, right = top_raw.split("❌", 1)
        present = only_team_emojis(left)
        absent = only_team_emojis(right)
    else:
        present = only_team_emojis(top_raw)

    used_present: List[str] = []
    for i, emo in enumerate(present):
        if emo in used_present:
            alerts.append(f"Alerta: en la ronda {r.num} el top repite {emo}. Se tomó solo la primera aparición para el top.")
            continue
        used_present.append(emo)
        if i < len(TOP_POINTS):
            pts[emo] += TOP_POINTS[i] * multiplier

    for emo in absent:
        pts[emo] += ABSENT_TOP_POINTS * multiplier

    for emo in TEAMS:
        if emo not in used_present and emo not in absent:
            alerts.append(
                f"Alerta: en la ronda {r.num} la casa {emo} no aparece en el top. "
                f"Se asumió ausente y se asignaron {ABSENT_TOP_POINTS} puntos."
            )
            pts[emo] += ABSENT_TOP_POINTS * multiplier
            absent.append(emo)

    for ln in r.answer_lines:
        counts = count_team_emojis(strip_multiplier_markers(ln))
        present_teams_in_line = [e for e, c in counts.items() if c > 0]
        if len(present_teams_in_line) >= 2:
            alerts.append(f"Alerta: en la ronda {r.num} hay una línea de respuestas con emojis mezclados: {ln.strip()}")
        for emo, c in counts.items():
            if c > 0:
                answers_count[emo] += c
                pts[emo] += (c * ANSWER_POINTS) * multiplier

    for emo in absent:
        if answers_count[emo] > 0:
            alerts.append(
                f"Alerta: en la ronda {r.num}, la casa {emo} tiene {answers_count[emo]} respuestas "
                f"pero no aparece dentro del top (está marcada como ausente)."
            )

    for emo, has in toad_bonus.items():
        if has:
            answers_count[emo] += 1
            pts[emo] += ANSWER_POINTS * multiplier

    return pts, alerts, answers_count

def score_round_format2(r: RoundParsed, multiplier: int, toad_bonus: Dict[str, bool]) -> Tuple[Dict[str, int], List[str], Dict[str, int]]:
    alerts: List[str] = []
    pts = {e: 0 for e in TEAMS}
    answers_count = {e: 0 for e in TEAMS}

    raw = strip_ws(r.raw_line)
    if raw in {"//", "❌"}:
        r.is_annulled = True
    if r.is_annulled:
        return pts, alerts, answers_count

def score_round_format3(
    r: RoundParsed,
    multiplier: int,
    toad_bonus: Dict[str, bool],
) -> Tuple[Dict[str, int], List[str], Dict[str, int]]:
    """Format 3 scoring: top_line gives ordered top, answer_lines[0] is all extra answers."""
    alerts: List[str] = []
    pts = {e: 0 for e in TEAMS}
    answers_count = {e: 0 for e in TEAMS}

    top_raw = strip_ws(strip_multiplier_markers(r.top_line))
    if top_raw in {"//", "❌"}:
        r.is_annulled = True
    if r.is_annulled:
        return pts, alerts, answers_count

    # Top: first unique teams in order found in top_line.
    present: List[str] = []
    seen: List[str] = []
    for emo in iter_team_emojis(r.top_line):
        if emo in seen:
            alerts.append(f"Alerta: en la ronda {r.num} el top repite {emo}. Se tomó solo la primera aparición para el top.")
            continue
        seen.append(emo)
        present.append(emo)

    # Assign points (no compaction; unused discarded)
    for i, emo in enumerate(present):
        if i < len(TOP_POINTS):
            pts[emo] += TOP_POINTS[i] * multiplier

    # Teams missing in top => absent 350 (and alert)
    absent: List[str] = []
    for emo in TEAMS:
        if emo not in seen:
            absent.append(emo)
            pts[emo] += ABSENT_TOP_POINTS * multiplier
            alerts.append(
                f"Alerta: en la ronda {r.num} la casa {emo} no aparece en el top. Se asumió ausente y se asignaron {ABSENT_TOP_POINTS} puntos."
            )

    # Answers line(s): each team emoji is +20
    for ln in r.answer_lines:
        counts = count_team_emojis(strip_multiplier_markers(ln))
        for emo, c in counts.items():
            if c > 0:
                answers_count[emo] += c
                pts[emo] += (c * ANSWER_POINTS) * multiplier

    # Absent team having answers -> alert
    for emo in absent:
        if answers_count[emo] > 0:
            alerts.append(
                f"Alerta: en la ronda {r.num}, la casa {emo} tiene {answers_count[emo]} respuestas "
                f"pero no aparece dentro del top (está marcada como ausente)."
            )

    # Toad bonus (only if not annulled)
    for emo, has in toad_bonus.items():
        if has:
            answers_count[emo] += 1
            pts[emo] += ANSWER_POINTS * multiplier

    return pts, alerts, answers_count

    seen_top: List[str] = []
    for team in iter_team_emojis(r.raw_line):
        if team not in seen_top and len(seen_top) < 4:
            seen_top.append(team)
            pts[team] += TOP_POINTS[len(seen_top) - 1] * multiplier
        else:
            answers_count[team] += 1
            pts[team] += ANSWER_POINTS * multiplier

    for emo in TEAMS:
        if (emo not in seen_top) and (answers_count[emo] == 0):
            pts[emo] += ABSENT_TOP_POINTS * multiplier

    for emo, has in toad_bonus.items():
        if has:
            answers_count[emo] += 1
            pts[emo] += ANSWER_POINTS * multiplier

    owl_count = normalize_wa(r.raw_line).count(OWL)
    if owl_count >= 4:
        alerts.append(f"Alerta: en la ronda {r.num} aparecen {owl_count} lechuzas; solo se tomarán en cuenta las primeras 2.")

    return pts, alerts, answers_count

# -------------------- Output renderers --------------------
def render_style1(title: str, totals: Dict[str, int]) -> str:
    items = [(e, totals[e]) for e in TEAMS]
    items.sort(key=lambda x: (-x[1], x[0]))

    header = "˖ ׁ ֶָ֪ 💫̸१ׁ꤫• 𝔻𝕀ℕ𝔸-𝕄𝕀ℂ𝔸⁕ ׅ۬ 𝅄"
    if title.strip():
        header = f"{title.strip()}\n\n{header}"
    sep = "╌ׄ╌╌ׄ╌╌ׄ╌╌ׄ╌╌ׄ╌╌ׄ╌╌ׄ╌ׄ"

    lines = [header, sep]
    for emo, pts in items:
        lines.append(f"⤿　⃝{emo} ᝢ {fmt_thousands_dot(pts)} ˙ ᜔• ")
    return "\n".join(lines)

def clean_round_line_for_output2(r: RoundParsed) -> str:
    s = strip_multiplier_markers(r.raw_line)
    s = normalize_wa(s)
    if strip_ws(s) in {"//", "❌"}:
        return strip_ws(s)

    out: List[str] = []
    i = 0
    while i < len(s):
        ch = s[i]

        # team tokens
        if ch == HEART_CHAR:
            if i + 1 < len(s) and s[i + 1] == VS16:
                i += 2
            else:
                i += 1
            out.append(HEART_TEAM)
            continue
        if ch in TEAMS and ch != HEART_TEAM:
            out.append(ch)
            i += 1
            continue

        # owl token
        if ch == OWL:
            out.append(OWL)
            i += 1
            while i < len(s) and not _team_starts_at(s, i):
                i += 1
            continue

        i += 1

    return "".join(out)

def render_style2(
    title_line: str,
    totals: Dict[str, int],
    toads_cfg: Dict[str, Dict],
    owls_cfg: Dict[str, Dict],
    rounds: List[RoundParsed],
) -> str:
    title = title_line.strip() if title_line.strip() else "Trivia"
    lines = [title, ""]

    for medal, emo, pts in medal_lines_sorted(totals):
        lines.append(f"{medal}{emo} {fmt_output2_commas(pts)}")
    lines.append("")

    # toads
    for team_emo in TEAMS:
        cfg = toads_cfg.get(team_emo)
        if not cfg or not cfg.get("enabled"):
            continue
        owner = (cfg.get("owner") or "").strip()
        name = (cfg.get("name") or "").strip()
        start_round = int(cfg.get("start_round", 1))
        suffix = "" if start_round == 1 else f" (Desde la ronda {start_round})"
        lines.append(f"{team_emo}{TOAD} {owner} - {name}{suffix}")

    # owls
    for team_emo in TEAMS:
        cfg = owls_cfg.get(team_emo)
        if not cfg or not cfg.get("enabled"):
            continue
        owner = (cfg.get("owner") or "").strip()
        name = (cfg.get("name") or "").strip()
        used_rounds = cfg.get("rounds_used", []) or []
        used_rounds = sorted(set([int(x) for x in used_rounds])) if used_rounds else []
        for rn in used_rounds:
            lines.append(f"{team_emo}{OWL} {owner} - {name} (Ronda {rn})")

    for r in rounds:
        cleaned = clean_round_line_for_output2(r)
        lines.append(f"{r.num}. {cleaned}")

    return "\n".join(lines).strip() + "\n"

def render_style3(totals: Dict[str, int]) -> str:
    """WhatsApp-friendly blocks, ordered by points desc.
    Example:
    _💛🦡HUFFLEPUFF🦡💛_
    > 13,120 Puntos.
    """
    items = [(e, totals[e]) for e in TEAMS]
    items.sort(key=lambda x: (-x[1], x[0]))

    blocks: List[str] = []
    for team_emo, pts in items:
        mascot, name = HOUSE_BADGES.get(team_emo, ("", TEAMS[team_emo].upper()))
        # WhatsApp markdown: underscores for italic, blockquote for points
        blocks.append(f"_{team_emo}{mascot}{name}{mascot}{team_emo}_")
        blocks.append(f"> {fmt_commas(pts)} Puntos.")
        blocks.append("")  # blank line between blocks

    return "\n".join(blocks).rstrip() + "\n"


# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="Contador Puntos ID", layout="centered")
st.title("🧮 Contador de puntos — Imperius Draconis")

st.markdown(
    """
### Instrucciones rápidas

**Casas**
- ❤️ Gryffindor, 💚 Slytherin, 💙 Ravenclaw, 💛 Hufflepuff

**Formato 1**
- `N.`
- 1ª línea = **Top** (1000/900/800/700; si falta 4º se pierde ese puntaje)
- Luego 0–4 líneas de respuestas extra (20 c/u)
- Ausentes en top: `//` o `❌` ⇒ **350** (y si están ausentes, no deberían tener respuestas extra)

**Formato 2**
- (Opcional) título `Trivia ...`
- (Opcional) sapos: `Casa🐸 Dueño - Sapo`
- Cada ronda en **una sola línea** `N. ...`
- Top = **primeras 4 casas únicas**; repeticiones cuentan como respuestas (20 c/u)
- Lechuzas: `Casa🦉 Dueño - Lechuza` (hasta 3 por ronda; se registran las primeras 2)

**Formato 3**
- (Opcional) sapos: `Casa🐸 Dueño - Sapo`
- Cada ronda son **2 líneas**:
  - `N- TOP`
  - `RESPUESTAS...` (20 c/u)

**Ronda anulada (cualquier formato)**
- `N. ❌`, `N. //`, `N- ❌` o `N- //` ⇒ **0 puntos para todas** y el sapo **no cuenta**.

**Multiplicadores**
- Puedes escribir `doble/dobles`, `triple/triples`, `x2`, `x3` (en cualquier parte).
- Se detecta y se **prellena**, pero **la UI manda**.
"""
)

default_text = """Nombre de la dinámica
💚🐸 Panda - Pando
"""

text = st.text_area("Pega aquí el texto de la dinámica", value=default_text, height=320)

if st.button("Detectar + Configurar"):
    parsed = parse_game(text)
    st.session_state["parsed"] = parsed
    st.session_state["raw_text"] = text

parsed: Optional[ParsedGame] = st.session_state.get("parsed")

if parsed:
    st.info(f"Input detectado: **{parsed.input_format.upper()}**")

    if parsed.alerts:
        with st.expander("Alertas detectadas al parsear (informativas)", expanded=True):
            for a in parsed.alerts:
                st.warning(a)

    rounds = parsed.rounds
    if not rounds:
        st.error("No se detectaron rondas.")
        st.stop()

    round_nums = [r.num for r in rounds]

    st.divider()
    st.subheader("⚙️ Configuración por ronda")
    mult_map: Dict[int, int] = {}
    cols = st.columns(2)
    for idx, r in enumerate(rounds):
        with cols[idx % 2]:
            mult_label = st.selectbox(
                f"Ronda {r.num} — Valor",
                options=["Normal (x1)", "Doble (x2)", "Triple (x3)"],
                index=({0:0,1:0,2:1,3:2}.get(getattr(r, "detected_multiplier", 1), 0)),
                key=f"mult_{r.num}",
            )
            mult = 1 if "x1" in mult_label else (2 if "x2" in mult_label else 3)
            mult_map[r.num] = mult

    st.divider()
    st.subheader("🐸 Sapos")
    st.caption("Se prellenan en Formato 2, pero puedes editar. El sapo suma +1 respuesta (20 pts) desde la ronda elegida; no cuenta en rondas anuladas.")

    toads_cfg = {e: {"enabled": False, "owner": "", "name": "", "start_round": 1} for e in TEAMS}
    for team, meta in parsed.toads_prefill.items():
        toads_cfg[team]["enabled"] = True
        toads_cfg[team]["owner"] = meta.owner
        toads_cfg[team]["name"] = meta.name

    for team_emo in TEAMS:
        with st.expander(f"{team_emo} {TEAMS[team_emo]}", expanded=toads_cfg[team_emo]["enabled"]):
            enabled = st.checkbox("Mandó sapo", value=toads_cfg[team_emo]["enabled"], key=f"toad_en_{team_emo}")
            toads_cfg[team_emo]["enabled"] = enabled
            if enabled:
                owner = st.text_input("Dueño", value=toads_cfg[team_emo]["owner"], key=f"toad_owner_{team_emo}")
                name = st.text_input("Nombre del sapo", value=toads_cfg[team_emo]["name"], key=f"toad_name_{team_emo}")

                opts = ["Desde el inicio"] + [f"Desde la ronda {rn}" for rn in round_nums[1:]]
                pick = st.selectbox("¿Desde qué ronda cuenta?", options=opts, index=0, key=f"toad_start_{team_emo}")
                start_round = 1 if pick == "Desde el inicio" else int(re.findall(r"\d+", pick)[0])
                toads_cfg[team_emo].update({"owner": owner, "name": name, "start_round": start_round})

    st.divider()
    st.subheader("🦉 Lechuzas")
    st.caption("Se detectan en Formato 2 y se prellenan; 1 lechuza por casa por dinámica. Edita si hace falta.")

    owls_cfg = {e: {"enabled": False, "owner": "", "name": "", "rounds_used": []} for e in TEAMS}
    for team, metas in parsed.owls_prefill_by_team.items():
        if metas:
            owls_cfg[team]["enabled"] = True
            owls_cfg[team]["owner"] = metas[0].owner
            owls_cfg[team]["name"] = metas[0].name
            owls_cfg[team]["rounds_used"] = [m.round_num for m in metas]

    for team_emo in TEAMS:
        with st.expander(f"{team_emo} {TEAMS[team_emo]}", expanded=owls_cfg[team_emo]["enabled"]):
            enabled = st.checkbox("Usó lechuza", value=owls_cfg[team_emo]["enabled"], key=f"owl_en_{team_emo}")
            owls_cfg[team_emo]["enabled"] = enabled
            if enabled:
                owner = st.text_input("Dueño", value=owls_cfg[team_emo]["owner"], key=f"owl_owner_{team_emo}")
                name = st.text_input("Nombre de la lechuza", value=owls_cfg[team_emo]["name"], key=f"owl_name_{team_emo}")
                used = st.multiselect(
                    "¿En qué ronda(s) se usó?",
                    options=round_nums,
                    default=sorted(set(owls_cfg[team_emo]["rounds_used"])) if owls_cfg[team_emo]["rounds_used"] else [],
                    key=f"owl_rounds_{team_emo}",
                )
                owls_cfg[team_emo].update({"owner": owner, "name": name, "rounds_used": used})

    validation_alerts: List[str] = []
    for team_emo in TEAMS:
        if owls_cfg[team_emo]["enabled"] and len(set(owls_cfg[team_emo]["rounds_used"])) > 1:
            validation_alerts.append(
                f"Alerta: la casa {team_emo} aparece con lechuza en múltiples rondas ({sorted(set(owls_cfg[team_emo]['rounds_used']))}). "
                f"Regla: máximo 1 uso por casa por dinámica; revisa si es correcto."
            )

    st.divider()
    st.subheader("🖨️ Output")
    output_choice = st.selectbox("Formato de output", options=list(OUTPUT_STYLES.keys()), index=1)

    if st.button("Calcular"):
        totals = {e: 0 for e in TEAMS}
        calc_alerts: List[str] = []

        def toad_bonus_for_round(rnum: int, is_annulled: bool) -> Dict[str, bool]:
            if is_annulled:
                return {e: False for e in TEAMS}
            bonuses: Dict[str, bool] = {}
            for emo in TEAMS:
                cfg = toads_cfg.get(emo, {})
                bonuses[emo] = bool(cfg.get("enabled")) and (rnum >= int(cfg.get("start_round", 1)))
            return bonuses

        for r in rounds:
            mult = mult_map.get(r.num, 1)
            bonus = toad_bonus_for_round(r.num, r.is_annulled)

            if parsed.input_format == "format1":
                pts, a, _ = score_round_format1(r, mult, bonus)
            elif parsed.input_format == "format2":
                pts, a, _ = score_round_format2(r, mult, bonus)
            else:
                pts, a, _ = score_round_format3(r, mult, bonus)

            for emo in TEAMS:
                totals[emo] += pts[emo]
            calc_alerts.extend(a)

        all_alerts = parsed.alerts + validation_alerts + calc_alerts
        if all_alerts:
            with st.expander("Alertas", expanded=True):
                for a in all_alerts:
                    st.warning(a)

        style_key = OUTPUT_STYLES[output_choice]
        if style_key == "style1":
            out = render_style1(parsed.title_line, totals)
        elif style_key == "style2":
            out = render_style2(
                title_line=parsed.title_line,
                totals=totals,
                toads_cfg=toads_cfg,
                owls_cfg=owls_cfg,
                rounds=rounds,
            )
        else:
            out = render_style3(totals)

        st.divider()
        st.subheader("✅ Resultado")
        st.code(out, language=None)

        st.subheader("Totales (debug rápido)")
        for emo in ["❤️", "💚", "💙", "💛"]:
            st.write(f"{emo} {TEAMS[emo]}: **{fmt_thousands_dot(totals[emo])}**")
