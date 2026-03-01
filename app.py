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
}

# -------------------- WhatsApp-safe normalization --------------------
# WhatsApp-safe normalization (future-proof)
# We DO NOT remove ZWJ (\u200D) nor Variation Selector-16 (\uFE0F)
# to avoid breaking compound emojis.

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
    """Normalize WhatsApp text: remove invisibles, normalize dash variants."""
    if s is None:
        return ""
    s = s.translate(_INVISIBLES_MAP)
    # normalize common dash variants to ASCII hyphen
    s = s.replace("–", "-").replace("—", "-")
    return s

def strip_ws(s: str) -> str:
    """Remove all whitespace AFTER WhatsApp normalization."""
    s = normalize_wa(s)
    return re.sub(r"\s+", "", s).strip()

# -------------------- Helpers --------------------
def only_team_emojis(s: str) -> List[str]:
    s = normalize_wa(s)
    return [ch for ch in s if ch in TEAMS]

def count_team_emojis(s: str) -> Dict[str, int]:
    s = normalize_wa(s)
    counts = {e: 0 for e in TEAMS}
    for ch in s:
        if ch in TEAMS:
            counts[ch] += 1
    return counts

def fmt_thousands_dot(n: int) -> str:
    # 2060 -> "2.060"
    return f"{n:,}".replace(",", ".")

def fmt_output2_commas(n: int) -> str:
    # >= 10,000 -> "11,660"
    # < 10,000  -> "09,800" and "07,340"
    if n >= 10000:
        return f"{n:,}"
    s = f"{n:05d}"   # 9800 -> "09800"
    return f"{s[:-3]},{s[-3:]}"  # "09,800"

def medal_lines_sorted(totals: Dict[str, int]) -> List[Tuple[str, str, int]]:
    items = [(e, totals[e]) for e in TEAMS]
    items.sort(key=lambda x: (-x[1], x[0]))
    medals = ["🥇", "🥈", "🥉", "🏅"]
    out = []
    for i, (emoji, pts) in enumerate(items):
        out.append((medals[i] if i < len(medals) else "🏅", emoji, pts))
    return out

def detect_input_format(text: str) -> str:
    text = normalize_wa(text)
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "format1"

    has_toad_lines = any(ln.strip().startswith(tuple(TEAMS.keys())) and TOAD in ln for ln in lines[:12])
    has_trivia_title = bool(re.match(r"^\s*Trivia\b", lines[0], flags=re.IGNORECASE))

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
    raw_line: str               # for format2 (text after "N.")
    top_line: str               # for format1 (line 1 after "N.")
    answer_lines: List[str]     # for format1 (0..many lines)
    is_annulled: bool = False
    detected_format: str = "format1"
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
        rounds.append(
            RoundParsed(
                num=cur_num,
                raw_line="",
                top_line=top_line,
                answer_lines=answer_lines,
                detected_format="format1",
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
    # lines like: "💚🐸 Panda - Pando"
    toads: Dict[str, ToadMeta] = {}
    for ln in lines:
        s = normalize_wa(ln).strip()
        if not s:
            continue
        if len(s) < 2:
            continue
        if s[0] in TEAMS and TOAD in s[:3]:
            team = s[0]
            # remove leading "💚🐸"
            rest = s[2:].strip()
            if "-" in rest:
                left, right = rest.split("-", 1)
                owner = left.strip()
                name = right.strip()
                toads[team] = ToadMeta(team=team, owner=owner, name=name)
    return toads

def extract_owl_metas_from_round_line(round_num: int, line: str) -> Tuple[List[OwlMeta], List[str]]:
    """
    Extract up to first 2 owl metas (attack/defense).
    Pattern: <TEAM><🦉><owner>-<name> ... then continues with more emojis.
    Owner/name are extracted from substring after 🦉 up to next TEAM emoji (or end).
    """
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

    take_positions = owl_positions[:2]

    for pos in take_positions:
        # team should be immediately before owl
        if pos == 0 or raw[pos - 1] not in TEAMS:
            alerts.append(
                f"Alerta: en la ronda {round_num} se detectó 🦉 pero no se pudo identificar la casa "
                f"(debe ir pegada antes del 🦉)."
            )
            continue

        team = raw[pos - 1]

        after = raw[pos + 1 :]
        nxt = None
        for i, ch in enumerate(after):
            if ch in TEAMS:
                nxt = i
                break
        meta_chunk = after[:nxt].strip() if nxt is not None else after.strip()

        # meta_chunk already normalized (dashes too)
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

def parse_format1(text: str) -> ParsedGame:
    rounds, alerts = parse_round_blocks_format1(text)
    return ParsedGame(
        input_format="format1",
        title_line="",
        rounds=sorted(rounds, key=lambda x: x.num),
        alerts=alerts,
    )

def parse_game(text: str) -> ParsedGame:
    fmt = detect_input_format(text)
    if fmt == "format2":
        return parse_format2(text)
    return parse_format1(text)

# -------------------- Scoring --------------------
def score_round_format1(
    r: RoundParsed,
    multiplier: int,
    toad_bonus: Dict[str, bool],
) -> Tuple[Dict[str, int], List[str], Dict[str, int]]:
    alerts: List[str] = []
    pts = {e: 0 for e in TEAMS}
    answers_count = {e: 0 for e in TEAMS}

    top_raw = strip_ws(r.top_line)
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

    # Assign top points to present in order (no compaction; unused points discarded)
    used_present: List[str] = []
    for i, emo in enumerate(present):
        if emo in used_present:
            alerts.append(
                f"Alerta: en la ronda {r.num} el top repite {emo}. "
                f"Se tomó solo la primera aparición para el top."
            )
            continue
        used_present.append(emo)
        if i < len(TOP_POINTS):
            pts[emo] += TOP_POINTS[i] * multiplier

    # Absent points
    for emo in absent:
        pts[emo] += ABSENT_TOP_POINTS * multiplier

    # If some teams are neither in present nor absent, treat as absent (weird in format1) and alert
    for emo in TEAMS:
        if emo not in used_present and emo not in absent:
            alerts.append(
                f"Alerta: en la ronda {r.num} la casa {emo} no aparece en el top. "
                f"Se asumió ausente y se asignaron {ABSENT_TOP_POINTS} puntos."
            )
            pts[emo] += ABSENT_TOP_POINTS * multiplier
            absent.append(emo)

    # Answers lines (0..many)
    for ln in r.answer_lines:
        raw_line = normalize_wa(ln)
        counts = count_team_emojis(raw_line)

        present_teams_in_line = [e for e, c in counts.items() if c > 0]
        if len(present_teams_in_line) >= 2:
            alerts.append(
                f"Alerta: en la ronda {r.num} hay una línea de respuestas con emojis mezclados: {ln.strip()}"
            )

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

def score_round_format2(
    r: RoundParsed,
    multiplier: int,
    toad_bonus: Dict[str, bool],
) -> Tuple[Dict[str, int], List[str], Dict[str, int]]:
    alerts: List[str] = []
    pts = {e: 0 for e in TEAMS}
    answers_count = {e: 0 for e in TEAMS}

    raw = strip_ws(r.raw_line)
    if raw in {"//", "❌"}:
        r.is_annulled = True

    if r.is_annulled:
        return pts, alerts, answers_count

    # top from first unique occurrence; further occurrences are answers
    seen_top: List[str] = []
    s = normalize_wa(r.raw_line)

    for ch in s:
        if ch not in TEAMS:
            continue
        if ch not in seen_top and len(seen_top) < 4:
            seen_top.append(ch)
            pts[ch] += TOP_POINTS[len(seen_top) - 1] * multiplier
        else:
            answers_count[ch] += 1
            pts[ch] += ANSWER_POINTS * multiplier

    # Teams not present at all => absent 350
    for emo in TEAMS:
        if (emo not in seen_top) and (answers_count[emo] == 0):
            pts[emo] += ABSENT_TOP_POINTS * multiplier

    # Toad bonus (only if not annulled)
    for emo, has in toad_bonus.items():
        if has:
            answers_count[emo] += 1
            pts[emo] += ANSWER_POINTS * multiplier

    # Owl count rule: 1..3 allowed; >=4 should warn
    owl_count = s.count(OWL)
    if owl_count >= 4:
        alerts.append(
            f"Alerta: en la ronda {r.num} aparecen {owl_count} lechuzas; solo se tomarán en cuenta las primeras 2."
        )

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
    """
    Remove owl owner/name inside the round; keep team emoji + 🦉 evidence, remove spaces.
    Example: "4. 💛🦉Serelith - Juli💚..." -> "💛🦉💚..."
    """
    s = normalize_wa(r.raw_line)

    if strip_ws(s) in {"//", "❌"}:
        return strip_ws(s)

    out: List[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in TEAMS:
            out.append(ch)
            i += 1
            continue
        if ch == OWL:
            out.append(OWL)
            i += 1
            # skip metadata until next team emoji or end
            while i < len(s) and s[i] not in TEAMS:
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

    # Ranking
    for medal, emo, pts in medal_lines_sorted(totals):
        lines.append(f"{medal}{emo} {fmt_output2_commas(pts)}")
    lines.append("")

    # Mascotas (toads then owls)
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
        used_rounds = cfg.get("rounds_used", []) or []
        used_rounds = sorted(set([int(x) for x in used_rounds])) if used_rounds else []
        for rn in used_rounds:
            lines.append(f"{team_emo}{OWL} {owner} - {name} (Ronda {rn})")

    # Rounds (cleaned)
    for r in rounds:
        cleaned = clean_round_line_for_output2(r)
        lines.append(f"{r.num}. {cleaned}")

    return "\n".join(lines).strip() + "\n"

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="Contador ID", layout="centered")
st.title("🧮 Contador de puntos — ID")

default_text = """Pega aquí tu dinámica
"""

text = st.text_area("Pega aquí el texto de la dinámica", value=default_text, height=320)

if st.button("Detectar + Configurar"):
    parsed = parse_game(text)
    st.session_state["parsed"] = parsed
    st.session_state["raw_text"] = text

parsed: Optional[ParsedGame] = st.session_state.get("parsed")
raw_text: str = st.session_state.get("raw_text", text)

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
                index=0,
                key=f"mult_{r.num}",
            )
            mult = 1 if "x1" in mult_label else (2 if "x2" in mult_label else 3)
            mult_map[r.num] = mult

    st.divider()
    st.subheader("🐸 Sapos")
    st.caption(
        "Se prellenan en Formato 2, pero puedes editar. El sapo suma +1 respuesta (20 pts) desde la ronda elegida; "
        "no cuenta en rondas anuladas."
    )

    toads_cfg = {e: {"enabled": False, "owner": "", "name": "", "start_round": 1} for e in TEAMS}

    # Prefill
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
                default_idx = 0
                start_round = 1

                pick = st.selectbox("¿Desde qué ronda cuenta?", options=opts, index=default_idx, key=f"toad_start_{team_emo}")
                if pick == "Desde el inicio":
                    start_round = 1
                else:
                    start_round = int(re.findall(r"\d+", pick)[0])

                toads_cfg[team_emo].update({"owner": owner, "name": name, "start_round": start_round})

    st.divider()
    st.subheader("🦉 Lechuzas")
    st.caption(
        "Se detectan en Formato 2 y se prellenan; 1 lechuza por casa por dinámica. Edita si hace falta."
    )

    owls_cfg = {e: {"enabled": False, "owner": "", "name": "", "rounds_used": []} for e in TEAMS}

    # Prefill from parsed owls
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

    # Validate: 1 owl per house per dynamic; if multiple rounds selected, warn.
    validation_alerts: List[str] = []
    for team_emo in TEAMS:
        if owls_cfg[team_emo]["enabled"] and len(set(owls_cfg[team_emo]["rounds_used"])) > 1:
            validation_alerts.append(
                f"Alerta: la casa {team_emo} aparece con lechuza en múltiples rondas ({sorted(set(owls_cfg[team_emo]['rounds_used']))}). "
                f"Regla: máximo 1 uso por casa por dinámica; revisa si es correcto."
            )

    st.divider()
    st.subheader("🖨️ Output")
    output_choice = st.selectbox("Formato de output", options=list(OUTPUT_STYLES.keys()), index=0)

    if st.button("Calcular"):
        calc_alerts: List[str] = []
        totals = {e: 0 for e in TEAMS}

        def toad_bonus_for_round(rnum: int, is_annulled: bool) -> Dict[str, bool]:
            if is_annulled:
                return {e: False for e in TEAMS}
            bonuses: Dict[str, bool] = {}
            for emo in TEAMS:
                cfg = toads_cfg.get(emo, {})
                if cfg.get("enabled"):
                    start = int(cfg.get("start_round", 1))
                    bonuses[emo] = (rnum >= start)
                else:
                    bonuses[emo] = False
            return bonuses

        for r in rounds:
            mult = mult_map.get(r.num, 1)
            bonus = toad_bonus_for_round(r.num, r.is_annulled)

            if parsed.input_format == "format1":
                pts, a, _ = score_round_format1(r, mult, bonus)
            else:
                pts, a, _ = score_round_format2(r, mult, bonus)

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
        else:
            out = render_style2(
                title_line=parsed.title_line,
                totals=totals,
                toads_cfg=toads_cfg,
                owls_cfg=owls_cfg,
                rounds=rounds,
            )

        st.divider()
        st.subheader("✅ Resultado")
        st.code(out, language=None)

        st.subheader("Totales (debug rápido)")
        for emo in ["❤️", "💚", "💙", "💛"]:
            st.write(f"{emo} {TEAMS[emo]}: **{fmt_thousands_dot(totals[emo])}**")