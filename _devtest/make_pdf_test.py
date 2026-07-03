# -*- coding: utf-8 -*-
"""בודק שהחילוץ החכם קורא טור ימני לפני שמאלי (PDF סינתטי דו-טורי)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def build_twocol_pdf(pdf_path: Path) -> Path:
    """יוצר PDF סינתטי דו-טורי עם שכבת טקסט - לשימוש גם בבדיקות השרת."""
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>"
    )
    content = (
        b"BT /F1 12 Tf 350 700 Td (RightColA RightColB) Tj 0 -20 TD (RightColC RightColD) Tj ET\n"
        b"BT /F1 12 Tf 50 700 Td (LeftColA LeftColB) Tj 0 -20 TD (LeftColC LeftColD) Tj ET\n"
    )
    objs.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + o + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\nstartxref\n"
    out += str(xref_pos).encode() + b"\n%%EOF\n"
    pdf_path.write_bytes(bytes(out))
    return pdf_path


def main() -> int:
    pdf_path = build_twocol_pdf(Path(__file__).parent / "twocol.pdf")

    from backend.extractors import pdf_extractor

    res = pdf_extractor.extract(pdf_path, allow_ocr=False)
    text = "\n".join(p.text for p in res.pages)
    print("EXTRACTED:")
    print(text)
    ra = text.find("RightColA")
    rc = text.find("RightColC")
    la = text.find("LeftColA")
    if ra == -1 or la == -1:
        print("FAIL: missing columns")
        return 1
    if not (ra < rc < la):
        print(f"FAIL: order wrong (RightColA={ra}, RightColC={rc}, LeftColA={la})")
        return 1
    print("OK: right column extracted before left column")
    return 0


if __name__ == "__main__":
    sys.exit(main())
