from __future__ import annotations

from pathlib import Path

from tests.fixtures.factory import make_digital_pdf, make_docx, make_invoice_image, make_scanned_pdf


def main(target: Path = Path("data/incoming")) -> None:
    target.mkdir(parents=True, exist_ok=True)
    make_digital_pdf(target / "digital_invoice.pdf")
    make_scanned_pdf(target / "scanned_invoice.pdf")
    make_docx(target / "invoice.docx")
    make_invoice_image(target / "invoice.png")
    (target / "corrupt.pdf").write_bytes(b"%PDF-corrupt synthetic fixture")


if __name__ == "__main__":
    main()
