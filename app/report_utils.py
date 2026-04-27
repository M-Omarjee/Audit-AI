"""PDF generation for AuditAI clinical audit reports."""

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


# ------------------------------------------------------------------------
# Logo handling
# ------------------------------------------------------------------------
def resolve_logo_path() -> str | None:
    """Find an NHS logo image in /assets (PNG/JPG/JPEG)."""
    here = Path(__file__).resolve()
    project_root = here.parent.parent
    assets = project_root / "assets"
    for name in ["nhs.png", "nhs.jpg", "nhs.jpeg", "NHS.png", "NHS.jpg", "NHS.jpeg"]:
        p = assets / name
        if p.exists():
            return str(p)
    return None


def _draw_nhs_badge(c, x, y, w=3.2 * cm, h=1.2 * cm):
    """Fallback vector NHS-style badge if image not found."""
    NHS_BLUE = colors.HexColor("#005EB8")
    c.setFillColor(NHS_BLUE)
    c.setStrokeColor(NHS_BLUE)
    c.rect(x, y, w, h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    fs = h * 0.62
    c.setFont("Helvetica-Bold", fs)
    text = "NHS"
    tw = c.stringWidth(text, "Helvetica-Bold", fs)
    c.drawString(x + (w - tw) / 2.0, y + (h - fs) / 2.0 + 0.1 * cm, text)
    c.setFillColor(colors.black)


# ------------------------------------------------------------------------
# Drawing helpers
# ------------------------------------------------------------------------
def _centered_text(c, text, y, font="Helvetica-Bold", size=18):
    c.setFont(font, size)
    width, _ = A4
    x = (width - c.stringWidth(text, font, size)) / 2.0
    c.drawString(x, y, text)


def _draw_compliance_bar(c, x, y, width, height, pct: float):
    """Horizontal compliance bar — green/amber/red based on threshold."""
    pct = max(0.0, min(1.0, pct))
    # Track
    c.setFillColor(colors.HexColor("#E5E7EB"))
    c.setStrokeColor(colors.HexColor("#D1D5DB"))
    c.rect(x, y, width, height, fill=1, stroke=1)
    # Fill
    if pct >= 0.95:
        fill_colour = colors.HexColor("#16A34A")  # green
    elif pct >= 0.75:
        fill_colour = colors.HexColor("#F59E0B")  # amber
    else:
        fill_colour = colors.HexColor("#DC2626")  # red
    c.setFillColor(fill_colour)
    c.rect(x, y, width * pct, height, fill=1, stroke=0)
    c.setFillColor(colors.black)


def _wrap_text(c, text: str, font: str, size: float, max_width: float) -> list[str]:
    """Greedy word-wrap — returns list of lines that fit max_width."""
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if c.stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


# ------------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------------
def build_pdf(
    output_path: str,
    title: str,
    agg_dict: dict,
    n_records: int,
    recommendations: list[str] | None,
    author_name: str = "",
    author_grade: str = "",
    logo_path: str | None = None,
    topic: str | None = None,
    ai_source: str | None = None,
) -> str:
    """
    Build the audit PDF.

    Parameters
    ----------
    output_path : str
        Where to save the PDF.
    title : str
        Centred title text at the top.
    agg_dict : dict
        Must contain key 'overall' (float 0–1). Other keys are component names
        with their compliance fractions.
    n_records : int
        Total rows analysed.
    recommendations : list[str] | None
        Bullet list of recommendations.
    author_name, author_grade : str
        For the sign-off section.
    logo_path : str | None
        If None, auto-resolve from /assets.
    topic : str | None
        Audit topic detected (e.g. 'VTE risk assessment').
    ai_source : str | None
        'claude' or 'fallback' — controls the recommendations section header.

    Returns
    -------
    str
        Debug info about the logo source ('image:<path>', 'vector', or 'error:...').
    """
    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin = 2 * cm

    # ------------------------------------------------------------------
    # Header band with logo + title + timestamp
    # ------------------------------------------------------------------
    c.setFillColorRGB(0.95, 0.97, 1.0)
    c.rect(0, height - 3 * cm, width, 3 * cm, fill=1, stroke=0)
    c.setFillColor(colors.black)

    # Logo
    debug_logo = ""
    path = logo_path or resolve_logo_path()
    drew_logo = False
    if path:
        try:
            c.drawImage(
                ImageReader(path),
                margin,
                height - 2.5 * cm,
                width=3.2 * cm,
                height=1.2 * cm,
                preserveAspectRatio=True,
                mask="auto",
            )
            drew_logo = True
            debug_logo = f"image:{path}"
        except Exception as e:
            debug_logo = f"error:{e!s}"
    if not drew_logo:
        _draw_nhs_badge(c, margin, height - 2.5 * cm)
        if not debug_logo:
            debug_logo = "vector"

    # Title + timestamp
    _centered_text(c, title, height - 1.3 * cm, size=16)
    if topic:
        c.setFont("Helvetica-Oblique", 10)
        c.setFillColor(colors.HexColor("#475569"))
        sub_w = c.stringWidth(topic, "Helvetica-Oblique", 10)
        c.drawString((width - sub_w) / 2.0, height - 2.0 * cm, topic)
        c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    ts = datetime.now().strftime("%d %b %Y %H:%M")
    ts_w = c.stringWidth(ts, "Helvetica", 9)
    c.drawString(width - margin - ts_w, height - 2.5 * cm, ts)

    # ------------------------------------------------------------------
    # Summary block
    # ------------------------------------------------------------------
    y = height - 3.6 * cm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Summary")
    y -= 18

    overall = float(agg_dict.get("overall") or 0.0)
    c.setFont("Helvetica", 10)
    c.drawString(margin, y, f"Records analysed: {n_records}")
    y -= 14

    c.drawString(margin, y, f"Overall compliance: {overall * 100:.1f}%")
    y -= 8
    bar_width = width - 2 * margin
    _draw_compliance_bar(c, margin, y - 8, bar_width, 8, overall)
    y -= 24

    # ------------------------------------------------------------------
    # Per-component compliance with mini bars
    # ------------------------------------------------------------------
    component_items = [(k, v) for k, v in agg_dict.items() if k != "overall"]

    if component_items:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, y, "Component compliance")
        y -= 16

        c.setFont("Helvetica", 10)
        for label, value in component_items:
            value = float(value or 0.0)
            # Label on the left, percentage on the right, mini bar between
            c.drawString(margin, y, f"• {label}")
            pct_text = f"{value * 100:.1f}%"
            pct_w = c.stringWidth(pct_text, "Helvetica", 10)
            c.drawString(width - margin - pct_w, y, pct_text)
            # Mini bar below the line
            _draw_compliance_bar(c, margin + 0.2 * cm, y - 6, bar_width - 0.4 * cm, 4, value)
            y -= 18
            if y < margin + 100:
                c.showPage()
                y = height - margin
                c.setFont("Helvetica-Bold", 11)
                c.drawString(margin, y, "Component compliance (cont.)")
                y -= 16
                c.setFont("Helvetica", 10)

    y -= 8

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------
    if y < margin + 140:
        c.showPage()
        y = height - margin

    c.setFont("Helvetica-Bold", 12)
    rec_header = "Recommendations"
    if ai_source == "claude":
        rec_header += "  (AI-generated, NICE/RCP-grounded)"
    elif ai_source == "fallback":
        rec_header += "  (generic — API unavailable)"
    c.drawString(margin, y, rec_header)
    y -= 16

    c.setFont("Helvetica", 10)
    if not recommendations:
        recommendations = [
            "Maintain performance via induction teaching and monthly spot checks."
        ]

    text_max_width = width - 2 * margin - 0.5 * cm
    for r in recommendations:
        lines = _wrap_text(c, r, "Helvetica", 10, text_max_width)
        # First line gets the bullet
        c.drawString(margin, y, f"• {lines[0]}")
        y -= 14
        # Continuation lines indented
        for cont in lines[1:]:
            c.drawString(margin + 0.5 * cm, y, cont)
            y -= 14
        y -= 4
        if y < margin + 100:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica", 10)

    # ------------------------------------------------------------------
    # Author / sign-off
    # ------------------------------------------------------------------
    if y < margin + 100:
        c.showPage()
        y = height - margin

    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Author / sign-off")
    y -= 18

    c.setFont("Helvetica", 10)
    name_grade = f"Prepared by: {author_name}"
    if author_grade:
        name_grade += f"  ({author_grade})"
    c.drawString(margin, y, name_grade)
    y -= 24

    line_w = 6 * cm
    c.line(margin, y, margin + line_w, y)
    c.drawString(margin, y - 12, "Signature")
    c.line(margin + 8 * cm, y, margin + 8 * cm + line_w, y)
    c.drawString(margin + 8 * cm, y - 12, "Date")

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    footer_left = "Generated by AuditAI — Clinical Audit & QI Platform"
    footer_right = ts
    c.drawString(margin, margin / 2, footer_left)
    fr_w = c.stringWidth(footer_right, "Helvetica", 8)
    c.drawString(width - margin - fr_w, margin / 2, footer_right)
    c.setFillColor(colors.black)

    c.showPage()
    c.save()
    return debug_logo