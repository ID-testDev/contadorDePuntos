# app.py
import re
import streamlit as st
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

# -------------------- Constants --------------------
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

HOUSE_BADGES = {
    "💛": ("🦡", "HUFFLEPUFF"),
    "💙": ("🦅", "RAVENCLAW"),
    "💚": ("🐍", "SLYTHERIN"),
    "❤️": ("🦁", "GRYFFINDOR"),
}

# -------------------- WhatsApp-safe normalization (future-proof) --------------------
# We DO NOT remove ZWJ (\u200D) nor VS16 (\uFE0F) globally to avoid breaking compound emojis.
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
    """Remove common invisible chars and normalize dash variants."""
    if s is None:
        return ""
    s = s.translate(_INVISIBLES_MAP)
    s = s.replace("–", "-").replace("—", "-")
    return s

def strip_ws(s: str) -> str:
    s = normalize_wa(s)
    return re.sub(r"\s+", "", s).strip()

# -------------------- Team tokenization (❤ vs ❤️ safe) --------------------
HEART_CHAR = "❤"      # U+2764
VS16 = "\ufe0f"       # Variation Selector-16
HEART_TEAM = "❤️"     # canonical Gryffindor key

def iter_team_emojis(s: str):
    """
    Yield canonical team emojis found in s.
    Treats both ❤ and ❤️ as Gryffindor without removing VS16 globally.
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

def only_team_emojis(s: str) -> List[str]:
    return list(iter_team_emojis(s))

def count_team_emojis(s: str) -> Dict[str, int]:
    counts = {e: 0 for e in TEAMS}
    for t in iter_team_emojis(s):
        counts[t] += 1
    return counts

def first_team_in_line(line: str) -> Optional[str]:
    for t in iter_team_emojis(line):
        return t
    return None

# -------------------- Multiplier detection --------------------
MULT_RE = re.compile(r"(?i)\b(doble|dobles|triple|triples)\b|\bx\s*([23])\b")

def detect_multiplier_in_text(s: str) -> Tuple[int, List[str]]:
    """
    Detect x2/x3 markers in free text. Returns (multiplier, alerts).
    Supports: doble(s), triple(s), x2, x 2, x3, x 3. Case-insensitive.
    If both 2 and 3 appear, uses 3 and emits alert.
    """
    alerts: List[str] = []
    s_norm = normalize_wa(s or "")
    s_low = s_norm.lower()

    has2 = ("doble" in s_low) or bool(re.search(r"\bx\s*2\b", s_low))
    has3 = ("triple" in s_low) or bool(re.search(r"\bx\s*3\b", s_low))

    if has2 and has3:
        alerts.append("Alerta: se detectaron marcadores x2 y x3 en la misma ronda; se tomará x3 por default (puedes corregir en UI).")
        return 3, alerts
    if has3:
        return 3, alerts
    if has2:
        return 2, alerts
    return 1, alerts

def strip_multiplier_markers(s: str) -> str:
    """Remove multiplier keywords (doble/triple/x2/x3) from a line before counting emojis."""
    s_norm = normalize_wa(s or "")
    # remove words
    s_norm = re.sub(r"(?i)\b(doble|dobles|triple|triples)\b", "", s_norm)
    # remove x2 / x3 forms
    s_norm = re.sub(r"(?i)\bx\s*[23]\b", "", s_norm)
    return s_norm

# -------------------- Formatting helpers --------------------
def fmt_thousands_dot(n: int) -> str:
    return f"{n:,}".replace(",", ".")

def fmt_output2_commas(n: int) -> str:
    if n >= 10000:
        return f"{n:,}"
    s = f"{n:05d}"
    return f"{s[:-3]},{s[-3:]}"

def fmt_commas(n: int) -> str:
    return f"{n:,}"

def medal_lines_sorted(totals: Dict[str, int]) -> List[Tuple[str, str, int]]:
    items = [(e, totals[e]) for e in TEAMS]
    items.sort(key=lambda x: (-x[1], x[0]))
    medals = ["🥇", "🥈", "🥉", "🏅"]
    out: List[Tuple[str, str, int]] = []
    for i, (emoji, pts) in enumerate(items):
        out.append((medals[i] if i < len(medals) else "🏅", emoji, pts))
    return out

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
    raw_line: str               # format2 full line (after N.) or format3 answers line
    top_line: str               # format1 top or format3 top
    answer_lines: List[str]     # format1 additional lines
    is_annulled: bool = False
    detected_format: str = "format1"
    owls_in_line: List[OwlMeta] = field(default_factory=list)
    suggested_multiplier: int = 1

@dataclass
class ParsedGame:
    input_format: str
    title_line: str = ""
    rounds: List[RoundParsed] = field(default_factory=list)
    toads_prefill: Dict[str, ToadMeta] = field(default_factory=dict)
    owls_prefill_by_team: Dict[str, List[OwlMeta]] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)

# -------------------- Format detection --------------------
def detect_input_format(text: str) -> str:
    """Autodetect among format1, format2, format3."""
    text = normalize_wa(text)
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "format1"

    has_trivia_title = bool(re.match(r"^\s*Trivia\b", lines[0], flags=re.IGNORECASE))

    def line_starts_with_team(line: str) -> bool:
        s = normalize_wa(line).lstrip()
        return first_team_in_line(s[:10]) is not None

    has_toad_lines = any(line_starts_with_team(ln) and TOAD in normalize_wa(ln) for ln in lines[:30])

    # Format 3: headers like "1- ..."
    dash_headers = [i for i, ln in enumerate(lines) if re.match(r"^\s*\d+\s*-\s*", ln)]
    if dash_headers:
        return "format3"

    # Format 2: rounds like "1. ..." with lots of emojis on same line
    dot_rounds = [ln for ln in lines if re.match(r"^\s*\d+\.\s*", ln)]
    looks_like_single_line_rounds = False
    if dot_rounds:
        long_rounds = sum(1 for ln in dot_rounds if len(only_team_emojis(ln)) >= 10)
        looks_like_single_line_rounds = long_rounds >= max(1, len(dot_rounds) // 2)

    if has_trivia_title or has_toad_lines or looks_like_single_line_rounds:
        return "format2"

    return "format1"

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
        rounds.append(
            RoundParsed(
                num=cur_num,
                raw_line="",
                top_line=top_line,
                answer_lines=answer_lines,
                detected_format="format1",
                suggested_multiplier=1,
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

def parse_toad_lines_owner_sapo(lines: List[str]) -> Dict[str, ToadMeta]:
    """
    Parse lines like: '💛🐸 Dueño - Sapo'  (owner first, then sapo).
    Supports ❤/❤️ as Gryffindor.
    """
    toads: Dict[str, ToadMeta] = {}
    for ln in lines:
        s = normalize_wa(ln).strip()
        if not s:
            continue
        team = first_team_in_line(s[:4])
        if not team:
            continue
        if TOAD not in s[:4]:
            continue
        # remove first team token and 🐸 (they are 1 char each; team may be ❤+VS16 though)
        # easiest: drop first 2 visible symbols by removing first occurrence of team (❤ or ❤️) and then 🐸.
        # We'll just remove the first emoji token by slicing from first occurrence of 🐸.
        idx = s.find(TOAD)
        rest = s[idx + len(TOAD):].strip()
        if "-" in rest:
            left, right = rest.split("-", 1)
            owner = left.strip()
            name = right.strip()
            toads[team] = ToadMeta(team=team, owner=owner, name=name)
    return toads

def extract_owl_metas_from_round_line(round_num: int, line: str) -> Tuple[List[OwlMeta], List[str]]:
    alerts: List[str] = []
    metas: List[OwlMeta] = []

    raw = normalize_wa(line)
    owl_positions = [m.start() for m in re.finditer(re.escape(OWL), raw)]
    if not owl_positions:
        return metas, alerts

    if len(owl_positions) >= 4:
        alerts.append(
            f"Alerta: en la ronda {round_num} aparecen {len(owl_positions)} lechuzas; solo se tomarán en cuenta las primeras 2."
        )

    take_positions = owl_positions[:2]
    for pos in take_positions:
        # team must be immediately before owl; handle ❤ + VS16 by looking back one char only (works because owl is 1 char)
        if pos == 0:
            alerts.append(f"Alerta: en la ronda {round_num} se detectó 🦉 pero no se pudo identificar la casa (debe ir pegada antes del 🦉).")
            continue
        team_char = raw[pos - 1]
        # If team is ❤ and previous is VS16, owl would not be immediately after VS16 in this format; ignore complex case.
        team = HEART_TEAM if team_char == HEART_CHAR else (team_char if team_char in TEAMS else None)
        if not team:
            alerts.append(f"Alerta: en la ronda {round_num} se detectó 🦉 pero no se pudo identificar la casa (debe ir pegada antes del 🦉).")
            continue

        after = raw[pos + 1 :]
        nxt = None
        for i, ch in enumerate(after):
            # next team start
            if ch in TEAMS or ch == HEART_CHAR:
                nxt = i
                break
        meta_chunk = after[:nxt].strip() if nxt is not None else after.strip()

        if "-" not in meta_chunk:
            alerts.append(
                f"Alerta: en la ronda {round_num} no se encontró el separador '-' para la lechuza de {team}. Se esperaba 'Dueño - Nombre'."
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

    toads_prefill = parse_toad_lines_owner_sapo(before_rounds)

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

        sugg_mult, a_m = detect_multiplier_in_text(rest)
        alerts.extend([f"Ronda {rnum}: {x}" for x in a_m])

        rp = RoundParsed(
            num=rnum,
            raw_line=rest,
            top_line="",
            answer_lines=[],
            is_annulled=is_annulled,
            detected_format="format2",
            suggested_multiplier=sugg_mult,
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
    """
    Format 3:
    - Optional toads at top: 'Casa🐸 Dueño - Sapo'
    - Each round is 2 lines:
      header: 'N- <top>' (top may be empty or annulled)
      next line: answers (may include multiplier words like doble/triple or x2/x3)
    - Annulled: 'N- ❌' or 'N- //'
    """
    text = normalize_wa(text)
    raw_lines = [ln.rstrip("\n") for ln in text.splitlines()]
    lines = [ln for ln in raw_lines if ln.strip()]

    dash_re = re.compile(r"^\s*(\d+)\s*-\s*(.*)\s*$")

    # split toads vs rounds: find first dash header
    first_round_idx = None
    for i, ln in enumerate(lines):
        if dash_re.match(ln):
            first_round_idx = i
            break

    toad_lines = lines[:first_round_idx] if first_round_idx is not None else lines
    rounds_lines = lines[first_round_idx:] if first_round_idx is not None else []

    toads_prefill = parse_toad_lines_owner_sapo(toad_lines)

    rounds: List[RoundParsed] = []
    alerts: List[str] = []

    i = 0
    while i < len(rounds_lines):
        ln = rounds_lines[i]
        m = dash_re.match(ln)
        if not m:
            i += 1
            continue
        rnum = int(m.group(1))
        rest = normalize_wa(m.group(2)).strip()

        # Top line may be empty; if empty, take next line as top and the next after as answers (rare)
        top_line = rest
        answers_line = ""

        if top_line == "":
            # take next non-empty as top
            j = i + 1
            if j < len(rounds_lines):
                top_line = rounds_lines[j].strip()
                i = j
            else:
                top_line = ""
        # now answers is next non-empty line
        j = i + 1
        if j < len(rounds_lines) and not dash_re.match(rounds_lines[j]):
            answers_line = rounds_lines[j]
            i = j
        else:
            answers_line = ""

        # annulled?
        is_annulled = strip_ws(top_line) in {"//", "❌"}

        sugg_mult = 1
        if answers_line:
            sugg_mult, a_m = detect_multiplier_in_text(answers_line)
            alerts.extend([f"Ronda {rnum}: {x}" for x in a_m])

        rounds.append(
            RoundParsed(
                num=rnum,
                raw_line=answers_line,
                top_line=top_line,
                answer_lines=[],
                is_annulled=is_annulled,
                detected_format="format3",
                suggested_multiplier=sugg_mult,
            )
        )

        i += 1

    return ParsedGame(
        input_format="format3",
        title_line="",
        rounds=sorted(rounds, key=lambda x: x.num),
        toads_prefill=toads_prefill,
        owls_prefill_by_team={},
        alerts=alerts,
    )

def parse_format1(text: str) -> ParsedGame:
    rounds, alerts = parse_round_blocks_format1(text)
    return ParsedGame(input_format="format1", title_line="", rounds=sorted(rounds, key=lambda x: x.num), alerts=alerts)

def parse_game(text: str) -> ParsedGame:
    fmt = detect_input_format(text)
    if fmt == "format2":
        return parse_format2(text)
    if fmt == "format3":
        return parse_format3(text)
    return parse_format1(text)

# -------------------- Scoring --------------------
def score_round_format1(r: RoundParsed, multiplier: int, toad_bonus: Dict[str, bool]) -> Tuple[Dict[str, int], List[str]]:
    alerts: List[str] = []
    pts = {e: 0 for e in TEAMS}
    answers_count = {e: 0 for e in TEAMS}

    top_raw = strip_ws(r.top_line)
    if top_raw in {"//", "❌"}:
        r.is_annulled = True
    if r.is_annulled:
        return pts, alerts

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
            alerts.append(f"Alerta: en la ronda {r.num} la casa {emo} no aparece en el top. Se asumió ausente y se asignaron {ABSENT_TOP_POINTS} puntos.")
            pts[emo] += ABSENT_TOP_POINTS * multiplier
            absent.append(emo)

    for ln in r.answer_lines:
        raw_line = strip_multiplier_markers(ln)
        counts = count_team_emojis(raw_line)
        present_teams_in_line = [e for e, c in counts.items() if c > 0]
        if len(present_teams_in_line) >= 2:
            alerts.append(f"Alerta: en la ronda {r.num} hay una línea de respuestas con emojis mezclados: {ln.strip()}")
        for emo, c in counts.items():
            if c > 0:
                answers_count[emo] += c
                pts[emo] += (c * ANSWER_POINTS) * multiplier

    for emo in absent:
        if answers_count[emo] > 0:
            alerts.append(f"Alerta: en la ronda {r.num}, la casa {emo} tiene {answers_count[emo]} respuestas pero no aparece dentro del top (está marcada como ausente).")

    for emo, has in toad_bonus.items():
        if has:
            pts[emo] += ANSWER_POINTS * multiplier

    return pts, alerts

def score_round_format2(r: RoundParsed, multiplier: int, toad_bonus: Dict[str, bool]) -> Tuple[Dict[str, int], List[str]]:
    alerts: List[str] = []
    pts = {e: 0 for e in TEAMS}
    answers_count = {e: 0 for e in TEAMS}

    raw = strip_ws(r.raw_line)
    if raw in {"//", "❌"}:
        r.is_annulled = True
    if r.is_annulled:
        return pts, alerts

    s = strip_multiplier_markers(r.raw_line)
    seen_top: List[str] = []
    for emo in iter_team_emojis(s):
        if emo not in seen_top and len(seen_top) < 4:
            seen_top.append(emo)
            pts[emo] += TOP_POINTS[len(seen_top) - 1] * multiplier
        else:
            answers_count[emo] += 1
            pts[emo] += ANSWER_POINTS * multiplier

    for emo in TEAMS:
        if (emo not in seen_top) and (answers_count[emo] == 0):
            pts[emo] += ABSENT_TOP_POINTS * multiplier

    for emo, has in toad_bonus.items():
        if has:
            pts[emo] += ANSWER_POINTS * multiplier

    return pts, alerts

def score_round_format3(r: RoundParsed, multiplier: int, toad_bonus: Dict[str, bool]) -> Tuple[Dict[str, int], List[str]]:
    alerts: List[str] = []
    pts = {e: 0 for e in TEAMS}
    answers_count = {e: 0 for e in TEAMS}

    top_raw = strip_ws(r.top_line)
    if top_raw in {"//", "❌"}:
        r.is_annulled = True
    if r.is_annulled:
        return pts, alerts

    # top: should be 4 unique houses; if repeats/missing -> alert + treat missing as absent 350
    present = []
    seen = set()
    for emo in iter_team_emojis(r.top_line):
        if emo in seen:
            alerts.append(f"Alerta: en la ronda {r.num} el top repite {emo}. Se tomó solo la primera aparición.")
            continue
        seen.add(emo)
        present.append(emo)

    # assign points by position (no compaction)
    for i, emo in enumerate(present[:4]):
        pts[emo] += TOP_POINTS[i] * multiplier

    # if fewer than 4, treat missing teams as absent 350 and alert
    if len(present) < 4:
        missing = [e for e in TEAMS if e not in present]
        alerts.append(f"Alerta: en la ronda {r.num} el top tiene menos de 4 casas. Se consideraron ausentes: {' '.join(missing)}.")
        for emo in missing:
            pts[emo] += ABSENT_TOP_POINTS * multiplier

    # answers line: all emojis are answers (20 each), but if a team never appears anywhere (top+answers) => NOT absent,
    # because in format3 absence is defined by not appearing in round at all; we follow same rule: if team absent entirely => 350.
    ans_line = strip_multiplier_markers(r.raw_line)
    counts = count_team_emojis(ans_line)
    for emo, c in counts.items():
        if c > 0:
            answers_count[emo] += c
            pts[emo] += c * ANSWER_POINTS * multiplier

    # absent by total absence in top and answers
    for emo in TEAMS:
        if emo not in present and answers_count[emo] == 0:
            # only add if not already added as missing top due to invalid top
            # (if top invalid and we already added ABSENT_TOP_POINTS, don't double)
            if pts[emo] == 0:
                pts[emo] += ABSENT_TOP_POINTS * multiplier

    for emo, has in toad_bonus.items():
        if has:
            pts[emo] += ANSWER_POINTS * multiplier

    return pts, alerts

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

def clean_round_line_for_output2_format2(r: RoundParsed) -> str:
    s = normalize_wa(r.raw_line)
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
        if ch == OWL:
            out.append(OWL)
            i += 1
            while i < len(s):
                nxt = s[i]
                if nxt == HEART_CHAR or nxt in TEAMS:
                    break
                i += 1
            continue
        i += 1
    return "".join(out)

def render_style2(title_line: str, totals: Dict[str, int], toads_cfg: Dict[str, Dict], owls_cfg: Dict[str, Dict], rounds: List[RoundParsed]) -> str:
    title = title_line.strip() if title_line.strip() else "Trivia"
    lines = [title, ""]
    for medal, emo, pts in medal_lines_sorted(totals):
        lines.append(f"{medal}{emo} {fmt_output2_commas(pts)}")
    lines.append("")

    # Mascotas
    for team_emo in TEAMS:
        cfg = toads_cfg.get(team_emo)
        if not cfg or not cfg.get("enabled"):
            continue
        owner = (cfg.get("owner") or "").strip()
        name = (cfg.get("name") or "").strip()
        start_round = int(cfg.get("start_round", 1))
        suffix = "" if start_round == 1 else f" (Desde la ronda {start_round})"
        lines.append(f"{team_emo}{TOAD} {owner} - {name}{suffix}")

    for team_emo in TEAMS:
        cfg = owls_cfg.get(team_emo)
        if not cfg or not cfg.get("enabled"):
            continue
        owner = (cfg.get("owner") or "").strip()
        name = (cfg.get("name") or "").strip()
        used_rounds = sorted(set([int(x) for x in (cfg.get("rounds_used") or [])]))
        for rn in used_rounds:
            lines.append(f"{team_emo}{OWL} {owner} - {name} (Ronda {rn})")

    # Rounds
    for r in rounds:
        if r.detected_format == "format2":
            cleaned = clean_round_line_for_output2_format2(r)
            lines.append(f"{r.num}. {cleaned}")
        else:
            # For other formats, just show original top/answers structure minimally
            if r.detected_format == "format3":
                lines.append(f"{r.num}- {strip_ws(r.top_line) if r.top_line else ''}")
                if r.raw_line:
                    lines.append(strip_ws(strip_multiplier_markers(r.raw_line)))
            else:
                lines.append(f"{r.num}. {strip_ws(r.top_line)}")
    return "\n".join(lines).strip() + "\n"

def render_style3(totals: Dict[str, int]) -> str:
    # House blocks, descending by points
    items = [(e, totals[e]) for e in TEAMS]
    items.sort(key=lambda x: (-x[1], x[0]))
    out_lines: List[str] = []
    for emo, pts in items:
        animal, name = HOUSE_BADGES.get(emo, ("", TEAMS[emo].upper()))
        out_lines.append(f"_{emo}{animal}{name}{animal}{emo}_")
        out_lines.append(f"> {fmt_commas(pts)} Puntos.")
        out_lines.append("")  # blank line
    return "\n".join(out_lines).rstrip() + "\n"

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="Contador Puntos ID", layout="centered")
st.title("🧮 Contador de puntos — Imperius Draconis")

default_text = """💛🐸 Dueño - Sapo
"""

text = st.text_area("Pega aquí el texto de la dinámica", value=default_text, height=340)

if st.button("Detectar + Configurar"):
    parsed = parse_game(text)
    st.session_state["parsed"] = parsed
    st.session_state["raw_text"] = text

parsed: Optional[ParsedGame] = st.session_state.get("parsed")

if parsed:
    st.info(f"Input detectado: **{parsed.input_format.upper()}**")

    if parsed.alerts:
        with st.expander("Alertas detectadas al parsear (informativas)", expanded=False):
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
            # prefill from detection
            default_idx = 0 if r.suggested_multiplier == 1 else (1 if r.suggested_multiplier == 2 else 2)
            mult_label = st.selectbox(
                f"Ronda {r.num} — Valor",
                options=["Normal (x1)", "Doble (x2)", "Triple (x3)"],
                index=default_idx,
                key=f"mult_{r.num}",
            )
            mult = 1 if "x1" in mult_label else (2 if "x2" in mult_label else 3)
            mult_map[r.num] = mult

    st.divider()
    st.subheader("🐸 Sapos")
    st.caption("Se prellenan si vienen en el texto. El sapo suma +1 respuesta (20 pts) desde la ronda elegida; no cuenta en rondas anuladas.")
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
    st.caption("Solo se usan en Formato 2 por ahora (si aparecen en el texto se prellenan).")
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
                used = st.multiselect("¿En qué ronda(s) se usó?", options=round_nums, default=sorted(set(owls_cfg[team_emo]["rounds_used"])), key=f"owl_rounds_{team_emo}")
                owls_cfg[team_emo].update({"owner": owner, "name": name, "rounds_used": used})

    st.divider()
    st.subheader("🖨️ Output")
    output_choice = st.selectbox("Formato de output", options=list(OUTPUT_STYLES.keys()), index=0)

    if st.button("Calcular"):
        totals = {e: 0 for e in TEAMS}
        calc_alerts: List[str] = []

        def toad_bonus_for_round(rnum: int, is_annulled: bool) -> Dict[str, bool]:
            if is_annulled:
                return {e: False for e in TEAMS}
            bonuses = {}
            for emo in TEAMS:
                cfg = toads_cfg.get(emo, {})
                if cfg.get("enabled"):
                    bonuses[emo] = rnum >= int(cfg.get("start_round", 1))
                else:
                    bonuses[emo] = False
            return bonuses

        for r in rounds:
            mult = mult_map.get(r.num, 1)
            bonus = toad_bonus_for_round(r.num, r.is_annulled)

            if parsed.input_format == "format1":
                pts, a = score_round_format1(r, mult, bonus)
            elif parsed.input_format == "format2":
                pts, a = score_round_format2(r, mult, bonus)
            else:
                pts, a = score_round_format3(r, mult, bonus)

            for emo in TEAMS:
                totals[emo] += pts[emo]
            calc_alerts.extend(a)

        if calc_alerts:
            with st.expander("Alertas", expanded=True):
                for a in calc_alerts:
                    st.warning(a)

        style_key = OUTPUT_STYLES[output_choice]
        if style_key == "style1":
            out = render_style1(parsed.title_line, totals)
        elif style_key == "style2":
            out = render_style2(parsed.title_line, totals, toads_cfg, owls_cfg, rounds)
        else:
            out = render_style3(totals)

        st.divider()
        st.subheader("✅ Resultado")
        st.code(out, language=None)
