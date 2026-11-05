"""Generic, role-agnostic PDF cover-letter generator for required file inputs."""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COVER_LETTER_PDF = ROOT / "private" / "Mohamed_Ahmed-Cover_Letter.pdf"


def build_generic_cover_letter_text(profile: dict[str, Any] | None = None, item: dict[str, Any] | None = None) -> str:
    """Return a clean, abstract, non-role-specific cover letter text."""
    identity = (profile or {}).get("identity", {}) if isinstance((profile or {}).get("identity"), dict) else {}
    full_name = str(identity.get("full_name") or "Mohamed Ahmed Mahmoud").strip()
    email = str(identity.get("email") or "hazalkoomjobseeker@gmail.com").strip()
    location = str(identity.get("location") or "Cairo, Egypt").strip()
    links = (profile or {}).get("links", {}) if isinstance((profile or {}).get("links"), dict) else {}
    portfolio = str(links.get("portfolio") or "https://mohamed-ahmed-five.vercel.app/").strip()
    github = str(links.get("github") or "https://github.com/hazalkoom").strip()
    linkedin = str(links.get("linkedin") or "https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/").strip()

    lines = [
        f"{full_name}",
        f"{location} | {email}",
        f"Portfolio: {portfolio}",
        f"GitHub: {github}",
        f"LinkedIn: {linkedin}",
        "",
        "Dear Hiring Team,",
        "",
        "I am submitting my application to join your engineering and technology organization. "
        "I focus on building reliable, maintainable software systems, writing automated tests, "
        "and taking ownership of deliverables from requirements through deployment.",
        "",
        "In my day-to-day work, I value clean architecture, thorough problem-solving, clear "
        "documentation, and collaborative communication across both local and distributed teams. "
        "I adapt quickly to existing workflows and technology stacks while maintaining high "
        "standards for quality and reliability.",
        "",
        "Thank you for your time and consideration. I look forward to discussing how I can "
        "contribute to your team.",
        "",
        "Sincerely,",
        f"{full_name}",
    ]
    return "\n".join(lines)


def _escape_pdf_text(text: str) -> str:
    cleaned = text.encode("ascii", errors="replace").decode("ascii")
    return cleaned.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_minimal_pdf(text: str, output_path: Path) -> Path:
    """Write a valid single-page PDF 1.4 document with Helvetica 11pt text using stdlib only."""
    wrapped_lines: list[str] = []
    for raw_line in (text or "").splitlines():
        if not raw_line.strip():
            wrapped_lines.append("")
        else:
            wrapped_lines.extend(textwrap.wrap(raw_line, width=82) or [""])

    stream_cmds = ["BT", "/F1 11 Tf", "54 738 Td", "15 TL"]
    for line in wrapped_lines[:44]:
        stream_cmds.append(f"({_escape_pdf_text(line)}) Tj")
        stream_cmds.append("T*")
    stream_cmds.append("ET")
    content_bytes = "\n".join(stream_cmds).encode("ascii")

    objects: list[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        f"5 0 obj\n<< /Length {len(content_bytes)} >>\nstream\n".encode("ascii") + content_bytes + b"\nendstream\nendobj\n",
    ]

    header = b"%PDF-1.4\n"
    body = bytearray(header)
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(body))
        body.extend(obj)

    xref_offset = len(body)
    xref_lines = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"]
    for off in offsets:
        xref_lines.append(f"{off:010d} 00000 n \n")
    trailer = (
        "".join(xref_lines)
        + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    body.extend(trailer)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes(body))
    return output_path.resolve()


def generate_generic_cover_letter_pdf(
    profile: dict[str, Any] | None = None,
    item: dict[str, Any] | None = None,
    output_path: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Generate and return the path to a generic PDF cover letter."""
    if output_path:
        target = Path(output_path)
    elif output_dir:
        target = Path(output_dir) / "Mohamed_Ahmed_Cover_Letter.pdf"
    else:
        target = DEFAULT_COVER_LETTER_PDF
    text = build_generic_cover_letter_text(profile, item)
    return write_minimal_pdf(text, target)
