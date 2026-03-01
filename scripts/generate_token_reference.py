#!/usr/bin/env python3
"""Generate M4E Token Quick Reference PDF from database.

Reads all token data from the DB and renders a 2-page reference PDF
matching the layout of the original v7 Token Reference.

Usage:
    python scripts/generate_token_reference.py [--output PATH] [--version N]
"""
import argparse
import sqlite3
from collections import defaultdict, OrderedDict
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("ERROR: fpdf2 is required. Install with: pip install fpdf2")
    raise SystemExit(1)

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "m4e.db"

# ── Page 1: Rules preamble (unchanged from v7) ──
RULES_PREAMBLE = [
    "A model can only have one instance of each type of token at a time.",
    "Same-crew duplicate: the model does not gain the token.",
    "Different-crew duplicate: the model first removes its current version of the token.",
    'Tokens like Aura (Concealment) and Aura (Hazardous) are considered to have the same name.',
    "Tokens are always friendly to the crew that controlled their application and enemy to all other crews.",
    "If a token references friendly or enemy models in its effects, it refers to models friendly or enemy to the token itself, not the model it is applied to.",
    'When a token\u2019s effects reference \u201cthis model\u201d they are referring to the model the token is currently applied to.',
    "Neutral effects (e.g., hazardous terrain placed during Encounter Setup) give the affected model an enemy token.",
    '\u201cCanceled\u201d tokens: the new token is gained and then both tokens are immediately removed.',
    "Damage dealt from a token is affected by any effects referring to the token.",
    "If a token does not state when it is removed, it stays on the model for the remainder of the game unless removed by another effect.",
    "End-phase tokens gained during the end phase do not resolve that effect until the next end phase.",
    "Whenever a token resolves, perform all portions of the token, unless otherwise stated.",
]

# ── Basic token ordering by section ──
BASIC_SECTIONS = OrderedDict([
    ("\u25a0 REMOVE BY CHOICE \u2014 Before a duel, player decides whether to spend", [
        "Adaptable", "Focused", "Insight",
    ]),
    ("\u25a0 REMOVE WHEN TRIGGERED \u2014 Removed automatically by a specific in-game event", [
        "Distracted", "Entranced", "Impact", "Shielded",
    ]),
    ("\u25a0 REMOVE AT END OF ACTIVATION \u2014 Removed when the affected model finishes its activation", [
        "Craven", "Fast", "Hastened", "Slow", "Staggered", "Stunned",
    ]),
    ("\u25a0 REMOVE DURING END PHASE \u2014 Effect resolves, then token is removed at end of turn", [
        "Adversary", "Bolstered", "Burning", "Injured",
    ]),
    ("\u25a0 PERSISTENT \u2014 No self-removal; stays until another game effect removes it", [
        "Poison", "Summon",
    ]),
])

AURA_TOKENS_ORDER = [
    "Aura (Binding)", "Aura (Concealment)", "Aura (Fire)", "Aura (Fumes)",
    "Aura (Hazardous)", "Aura (Negligent)", "Aura (Poison)", "Aura (Staggered)",
]

# ── Keyword token ordering (alphabetical, matching v7) ──
KEYWORD_TOKENS_ORDER = [
    "Abandoned", "Aetheric Surge", "Analyzed", "Backtrack", "Badge", "Balm",
    "Blight", "Blood", "Bog Spirit", "Bounty", "Brilliance", "Broodling",
    "Challenged", "Chi", "Convert", "Death", "Drift", "Exposed", "Familia",
    "Flicker", "Fragile Ego", "Fright", "Frozen Solid", "Glowy", "Glutted",
    "Graft", "Greedy", "Hidden", "Hunger", "Improvised Part", "Incurable",
    "Instinct", "Interesting Parts", "Life", "New Blood", "Numb", "Paranoia",
    "Parasite", "Perforated", "Promoted", "Reload", "Replica", "Research Bar",
    "Shame", "Sin", "Spirit", "Spiritual Chains", "Suppressed", "Voyage",
]

# Resource tokens marked with dagger
RESOURCE_TOKENS = {"Blood", "Spirit"}

# ── Keyword associations (manually curated from crew card analysis) ──
# These map tokens to the keywords whose crew reference cards define them.
AURA_KEYWORDS = {
    "Aura (Binding)": "Marshal, Tormented",
    "Aura (Concealment)": "Multi-keyword",
    "Aura (Fire)": "Wildfire, Ancestor",
    "Aura (Fumes)": "Experimental",
    "Aura (Hazardous)": "Multi-keyword",
    "Aura (Negligent)": "Elite, Woe",
    "Aura (Poison)": "Tri-Chi",
    "Aura (Staggered)": "Angler",
}

KEYWORD_TOKEN_KEYWORDS = {
    "Abandoned": "Forgotten",
    "Aetheric Surge": "Mercenary",
    "Analyzed": "\u2014",
    "Backtrack": "Performer, Obliteration",
    "Badge": "Frontier",
    "Balm": "Monk",
    "Blight": "Plague",
    "Blood": "Family, Guard, Mercenary, Tormented",
    "Bog Spirit": "Swampfiend",
    "Bounty": "Frontier",
    "Brilliance": "Honeypot",
    "Broodling": "Brood",
    "Challenged": "Cavalier, Infamous",
    "Chi": "Monk",
    "Convert": "Revenant",
    "Death": "Seeker",
    "Drift": "Angler",
    "Exposed": "Frontier",
    "Familia": "Family",
    "Flicker": "Nightmare, Obliteration, Oni, Revenant",
    "Fragile Ego": "Woe",
    "Fright": "Nightmare",
    "Frozen Solid": "Savage",
    "Glowy": "Wizz-Bang",
    "Glutted": "Sooey, Brood",
    "Graft": "Experimental",
    "Greedy": "Ancestor",
    "Hidden": "Frontier, Cavalier",
    "Hunger": "December, Returned",
    "Improvised Part": "Ampersand",
    "Incurable": "Family, Returned",
    "Instinct": "Chimera",
    "Interesting Parts": "Experimental",
    "Life": "Seeker",
    "New Blood": "Family",
    "Numb": "Savage",
    "Paranoia": "Woe",
    "Parasite": "Cadmus",
    "Perforated": "Family, Kin",
    "Promoted": "Guard",
    "Reload": "Apex, Family",
    "Replica": "Wastrel",
    "Research Bar": "EVS",
    "Shame": "Syndicate",
    "Sin": "Crossroads",
    "Spirit": "Ancestor, Oni, Swampfiend, Urami",
    "Spiritual Chains": "Urami",
    "Suppressed": "Witch Hunter, Fae",
    "Voyage": "EVS",
}


def load_tokens(db_path):
    """Load all tokens from the database."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    tokens = {}
    for row in conn.execute("SELECT * FROM tokens ORDER BY name"):
        tokens[row["name"]] = dict(row)
    conn.close()
    return tokens


class TokenReferencePDF(FPDF):
    """Custom FPDF subclass for the token reference layout."""

    def __init__(self):
        super().__init__(orientation="P", unit="pt", format="letter")
        self.set_auto_page_break(auto=False)
        # Margins matching v7
        self.l_margin = 18
        self.r_margin = 20
        self.t_margin = 33

    @property
    def content_width(self):
        return self.w - self.l_margin - self.r_margin

    def _set_font_regular(self, size):
        self.set_font("DejaVuSans", "", size)

    def _set_font_bold(self, size):
        self.set_font("DejaVuSans", "B", size)

    def _set_font_italic(self, size):
        self.set_font("DejaVuSans", "I", size)

    # ── Drawing helpers ──

    def _draw_section_header(self, text, y=None):
        """Dark gray section header bar."""
        if y is not None:
            self.set_y(y)
        self.set_fill_color(60, 60, 60)
        self.set_text_color(255, 255, 255)
        self._set_font_bold(5.8)
        self.set_x(self.l_margin)
        self.cell(self.content_width, 10, f"  {text}", border=1, new_x="LMARGIN", new_y="NEXT", fill=True)
        self.set_text_color(0, 0, 0)

    def _draw_table_header(self, cols, y=None):
        """Light gray table header row."""
        if y is not None:
            self.set_y(y)
        self.set_fill_color(220, 220, 220)
        self._set_font_bold(5.8)
        self.set_x(self.l_margin)
        x = self.l_margin
        for text, width in cols:
            self.set_xy(x, self.get_y())
            self.cell(width, 10, f"  {text}", border=1, fill=True)
            x += width
        self.ln(10)

    def _draw_basic_token_row(self, name, text, cancels_text=None):
        """Draw a basic token row (name | text) with wrapped text."""
        name_w = 60
        text_w = self.content_width - name_w

        self._set_font_regular(6.3)

        # Build display text
        display = text
        if cancels_text:
            display += f" (Canceled by {cancels_text})"

        # Calculate height needed
        lines = self._count_lines(display, text_w - 4)
        row_h = max(10, lines * 7.5)

        y_start = self.get_y()

        # Name cell
        self.set_xy(self.l_margin, y_start)
        self._set_font_bold(6.3)
        self.cell(name_w, row_h, f"  {name}", border=1)

        # Text cell with wrapping
        self.set_xy(self.l_margin + name_w, y_start)
        self._set_font_regular(6.3)
        self._multi_cell_in_box(text_w, row_h, display, border=1)

        self.set_y(y_start + row_h)

    def _draw_aura_row(self, name, keywords, text):
        """Draw an aura token row (name | keywords | text)."""
        name_w = 90
        kw_w = 62
        text_w = self.content_width - name_w - kw_w
        line_h = 7

        self._set_font_regular(6.3)

        # Calculate height
        text_lines = self._count_lines(text, text_w - 4)
        kw_lines = self._count_lines(keywords, kw_w - 4)
        lines = max(text_lines, kw_lines)
        row_h = max(10, lines * line_h + 2)

        y_start = self.get_y()

        # Name
        self.set_xy(self.l_margin, y_start)
        self._set_font_bold(6.3)
        self.cell(name_w, row_h, f"  {name}", border=1)

        # Keywords
        self.set_xy(self.l_margin + name_w, y_start)
        self._set_font_regular(5.8)
        self._multi_cell_in_box(kw_w, row_h, keywords, border=1, line_h=line_h)

        # Text
        self.set_xy(self.l_margin + name_w + kw_w, y_start)
        self._set_font_regular(6.3)
        self._multi_cell_in_box(text_w, row_h, text, border=1, line_h=line_h)

        self.set_y(y_start + row_h)

    def _draw_keyword_row(self, name, keywords, text, is_resource=False):
        """Draw a keyword token row on page 2."""
        name_w = 72
        kw_w = 58
        text_w = self.content_width - name_w - kw_w

        font_size = 5.8
        line_h = 6.5

        self._set_font_regular(font_size)

        # Calculate height
        text_lines = self._count_lines(text, text_w - 4)
        kw_lines = self._count_lines(keywords, kw_w - 4)
        lines = max(text_lines, kw_lines)
        row_h = max(9, lines * line_h + 2)

        y_start = self.get_y()

        # Name (bold, with dagger for resource tokens)
        self.set_xy(self.l_margin, y_start)
        self._set_font_bold(font_size)
        display_name = f"{name} \u2020" if is_resource else name
        self.cell(name_w, row_h, f"  {display_name}", border=1)

        # Keywords
        self.set_xy(self.l_margin + name_w, y_start)
        self._set_font_regular(font_size)
        self._multi_cell_in_box(kw_w, row_h, keywords, border=1, line_h=line_h)

        # Text
        self.set_xy(self.l_margin + name_w + kw_w, y_start)
        self._set_font_regular(font_size)
        self._multi_cell_in_box(text_w, row_h, text, border=1, line_h=line_h)

        self.set_y(y_start + row_h)

    def _multi_cell_in_box(self, w, h, text, border=1, line_h=7):
        """Write wrapped text within a fixed-height bordered cell."""
        x = self.get_x()
        y = self.get_y()

        # Draw the border box
        if border:
            self.rect(x, y, w, h)

        # Write text with padding
        padding = 2
        self.set_xy(x + padding, y + 1)
        self.multi_cell(w - 2 * padding, line_h, text, border=0)

    def _count_lines(self, text, width):
        """Estimate number of lines needed for text at current font."""
        if not text:
            return 1
        # Handle embedded newlines by counting lines per paragraph
        total_lines = 0
        for paragraph in text.split("\n"):
            if not paragraph.strip():
                total_lines += 1
                continue
            words = paragraph.split(" ")
            para_lines = 1
            current_line = ""
            for word in words:
                test = f"{current_line} {word}".strip()
                if self.get_string_width(test) > width:
                    para_lines += 1
                    current_line = word
                else:
                    current_line = test
            total_lines += para_lines
        return max(1, total_lines)

    # ── Page builders ──

    def build_page1(self, tokens):
        """Build page 1: basic tokens + aura tokens."""
        self.add_page()

        # Title
        self._set_font_bold(9.8)
        self.set_xy(self.l_margin, self.t_margin)
        self.cell(self.content_width, 12, "MALIFAUX 4E \u2014 TOKEN QUICK REFERENCE",
                  align="C", new_x="LMARGIN", new_y="NEXT")

        # Subtitle
        self._set_font_italic(5.8)
        self.cell(self.content_width, 8,
                  "Rules source: Comprehensive Rules Guide (9.10.2025 Draft 2) & Crew Reference Cards",
                  align="C", new_x="LMARGIN", new_y="NEXT")

        # Rules preamble
        for rule in RULES_PREAMBLE:
            self._set_font_bold(6.3)
            bullet = "\u2022"
            bullet_w = self.get_string_width(bullet) + 2
            self.set_x(self.l_margin)
            self.cell(bullet_w, 7.5, bullet)
            self._set_font_regular(6.3)
            self.multi_cell(self.content_width - bullet_w, 7.5, rule, new_x="LMARGIN")

        self.ln(2)

        # Section header
        self._set_font_bold(6.9)
        self.set_fill_color(220, 220, 220)
        self.set_x(self.l_margin)
        y_before = self.get_y()
        self.cell(self.content_width, 10, "  BASIC MALIFAUX TOKENS ", border=1, fill=True)
        # Add subtitle text inline
        self.set_xy(self.l_margin + self.get_string_width("  BASIC MALIFAUX TOKENS ") + 2, y_before)
        self._set_font_regular(5.8)
        self.cell(0, 10, "Defined in Comprehensive Rules")
        self.set_y(y_before + 10)

        # Basic token sections
        for section_header, token_names in BASIC_SECTIONS.items():
            self._draw_section_header(section_header)
            for tname in token_names:
                tok = tokens.get(tname, {})
                # Strip "Canceled by X." from rules_text since we handle it separately
                rules = tok.get("rules_text", "")
                cancels = tok.get("cancels")
                # Remove trailing "Canceled by X." from DB text
                import re
                rules = re.sub(r"\s*Canceled by \w+\.\s*$", "", rules)
                self._draw_basic_token_row(tname, rules, cancels)

        self.ln(2)

        # Aura tokens section
        self._set_font_bold(6.9)
        self.set_fill_color(220, 220, 220)
        self.set_x(self.l_margin)
        y_before = self.get_y()
        self.cell(self.content_width, 10, "  AURA TOKENS ", border=1, fill=True)
        self.set_xy(self.l_margin + self.get_string_width("  AURA TOKENS ") + 2, y_before)
        self._set_font_regular(5.8)
        self.cell(0, 10, 'All share the name \u201cAura.\u201d One per model. New replaces old. Removed during end phase.')
        self.set_y(y_before + 10)

        # Aura header
        self._draw_table_header([
            ("Token", 90), ("Keywords", 62),
            ("Effect (from Crew Cards)", self.content_width - 90 - 62),
        ])

        # Aura rows
        for aname in AURA_TOKENS_ORDER:
            tok = tokens.get(aname, {})
            kw = AURA_KEYWORDS.get(aname, "")
            self._draw_aura_row(aname, kw, tok.get("rules_text", ""))

        # Footer
        self.ln(2)
        self._set_font_italic(5.0)
        self.set_x(self.l_margin)
        self.cell(self.content_width, 6,
                  "Malifaux 4th Edition \u2014 Token Quick Reference \u2014 Page 1 \u2014 "
                  "Rules source: Comprehensive Rules Guide (9.10.2025 Draft 2)",
                  align="C")

    def build_page2(self, tokens):
        """Build page 2: keyword & crew-specific tokens."""
        self.add_page()

        # Title
        self._set_font_bold(9.8)
        self.set_xy(self.l_margin, self.t_margin)
        self.cell(self.content_width, 12,
                  "MALIFAUX 4E \u2014 KEYWORD & CREW-SPECIFIC TOKENS",
                  align="C", new_x="LMARGIN", new_y="NEXT")

        # Subtitles
        self._set_font_italic(5.8)
        self.cell(self.content_width, 7,
                  "Effects defined on crew reference cards \u2014 Verbatim rules text from crew card token definitions",
                  align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(self.content_width, 7,
                  "Effects defined on keyword reference cards (crew card backs). "
                  "\u2020 = Resource token (spent/removed by specific abilities). "
                  "Bold token names = cross-references.",
                  align="C", new_x="LMARGIN", new_y="NEXT")

        # Section header
        self._set_font_bold(6.9)
        self.set_fill_color(220, 220, 220)
        self.set_x(self.l_margin)
        y_before = self.get_y()
        self.cell(self.content_width, 10, "  KEYWORD & CREW-SPECIFIC TOKENS ", border=1, fill=True)
        self.set_xy(self.l_margin + self.get_string_width("  KEYWORD & CREW-SPECIFIC TOKENS ") + 2, y_before)
        self._set_font_regular(5.8)
        self.cell(0, 10, f"{len(KEYWORD_TOKENS_ORDER)} tokens from crew reference cards")
        self.set_y(y_before + 10)

        # Table header
        name_w = 72
        kw_w = 58
        text_w = self.content_width - name_w - kw_w
        self._draw_table_header([
            ("Token", name_w), ("Keywords", kw_w),
            ("Effect (from Crew Cards)", text_w),
        ])

        # Keyword token rows
        for tname in KEYWORD_TOKENS_ORDER:
            tok = tokens.get(tname, {})
            kw = KEYWORD_TOKEN_KEYWORDS.get(tname, "")
            is_res = tname in RESOURCE_TOKENS
            text = tok.get("rules_text", "")
            # Strip "Canceled by X." suffix — handle via parenthetical
            import re
            cancels = tok.get("cancels")
            text = re.sub(r"\s*Canceled by \w+\.\s*$", "", text)
            if cancels:
                text += f" (Canceled by {cancels})"
            self._draw_keyword_row(tname, kw, text, is_resource=is_res)

        # Footer
        self.ln(2)
        self._set_font_italic(5.0)
        self.set_x(self.l_margin)
        basic_count = sum(len(v) for v in BASIC_SECTIONS.values())
        aura_count = len(AURA_TOKENS_ORDER)
        kw_count = len(KEYWORD_TOKENS_ORDER)
        total = basic_count + aura_count + kw_count
        self.cell(self.content_width, 6,
                  f"Malifaux 4th Edition \u2014 {basic_count} basic tokens, "
                  f"{aura_count} aura tokens, {kw_count} keyword tokens "
                  f"({total} total) \u2014 \u2020 = resource token \u2014 Page 2 \u2014 V8",
                  align="C")


def main():
    parser = argparse.ArgumentParser(description="Generate M4E Token Quick Reference PDF")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output file path (default: Downloads/M4E_Token_Reference_v8_BW.pdf)")
    parser.add_argument("--version", type=int, default=8,
                        help="Version number (default: 8)")
    parser.add_argument("--db", type=str, default=str(DB_PATH),
                        help="Database path")
    args = parser.parse_args()

    if args.output:
        output = Path(args.output)
    else:
        output = Path.home() / "Downloads" / f"M4E_Token_Reference_v{args.version}_BW.pdf"

    print(f"Loading tokens from {args.db}...")
    tokens = load_tokens(args.db)
    print(f"  Loaded {len(tokens)} tokens")

    print("Generating PDF...")
    pdf = TokenReferencePDF()
    fonts_dir = Path(__file__).resolve().parent.parent / "fonts"
    pdf.add_font("DejaVuSans", "", fname=str(fonts_dir / "DejaVuSans.ttf"))
    pdf.add_font("DejaVuSans", "B", fname=str(fonts_dir / "DejaVuSans-Bold.ttf"))
    pdf.add_font("DejaVuSans", "I", fname=str(fonts_dir / "DejaVuSans-Oblique.ttf"))

    pdf.build_page1(tokens)
    pdf.build_page2(tokens)

    pdf.output(str(output))
    print(f"  Written to {output}")
    print(f"  Pages: {pdf.pages_count}")


if __name__ == "__main__":
    main()
