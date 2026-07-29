#!/usr/bin/env python3
"""Generate sample.pdf - a document to try the editor's features on."""

import io
import math

import fitz

NAVY = (0.11, 0.20, 0.38)
GREY = (0.42, 0.46, 0.52)
ACCENT = (0.18, 0.44, 0.82)
RULE = (0.82, 0.85, 0.90)


def logo_png(size=220):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, size - 6, size - 6), fill=(47, 111, 208, 255))
    d.polygon([(size * 0.32, size * 0.62), (size * 0.47, size * 0.30),
               (size * 0.62, size * 0.52), (size * 0.72, size * 0.38),
               (size * 0.80, size * 0.70)], fill=(255, 255, 255, 235))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def chart_png(w=520, h=300):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), (247, 249, 252))
    d = ImageDraw.Draw(img)
    values = [42, 58, 51, 74, 66, 89, 95]
    labels = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"]
    pad, base = 44, h - 44
    bw = (w - pad * 2) / len(values) * 0.6
    step = (w - pad * 2) / len(values)
    for i in range(0, 101, 25):
        y = base - (base - 40) * i / 100
        d.line([(pad, y), (w - pad, y)], fill=(224, 229, 237), width=1)
        d.text((10, y - 6), f"{i}", fill=(130, 138, 150))
    for i, v in enumerate(values):
        x = pad + step * i + (step - bw) / 2
        top = base - (base - 40) * v / 100
        d.rounded_rectangle([x, top, x + bw, base], radius=4,
                            fill=(47, 111, 208) if i != 5 else (18, 184, 134))
        d.text((x + bw / 2 - 8, base + 8), labels[i], fill=(90, 98, 110))
    return img_bytes(img)


def img_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def build(path="sample.pdf"):
    doc = fitz.open()

    # ---------------------------------------------------------------- page 1
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(0, 0, 595, 132), fill=NAVY, color=None)
    page.insert_image(fitz.Rect(48, 32, 108, 92), stream=logo_png())
    page.insert_text((126, 66), "Northwind Analytics", fontname="hebo",
                     fontsize=23, color=(1, 1, 1))
    page.insert_text((126, 90), "Quarterly Performance Review",
                     fontname="helv", fontsize=12, color=(0.75, 0.82, 0.93))
    page.insert_text((126, 110), "Prepared 14 March 2024  ·  Reference NW-2024-Q1",
                     fontname="helv", fontsize=9, color=(0.62, 0.71, 0.86))

    y = 182
    page.insert_text((48, y), "Executive Summary", fontname="hebo",
                     fontsize=15, color=NAVY)
    page.draw_line(fitz.Point(48, y + 9), fitz.Point(547, y + 9), color=RULE,
                   width=1)
    body = (
        "Revenue grew 18.4% year over year, driven mainly by the enterprise "
        "segment and a stronger renewal rate in EMEA. Gross margin improved by "
        "220 basis points as infrastructure costs fell following the migration "
        "completed in November. Operating expenses remained flat despite "
        "headcount growth of eleven people across engineering and support.\n\n"
        "The board asked us to flag three risks. First, concentration: our top "
        "five customers now represent 34% of recurring revenue. Second, the "
        "renewal cliff in Q4 covering 62 mid-market accounts. Third, currency "
        "exposure on the sterling contracts signed last spring."
    )
    page.insert_textbox(fitz.Rect(48, y + 22, 547, y + 190), body,
                        fontname="tiro", fontsize=10.5, color=(0.16, 0.19, 0.24),
                        lineheight=1.45)

    y = 402
    page.insert_text((48, y), "Key Figures", fontname="hebo", fontsize=15,
                     color=NAVY)
    page.draw_line(fitz.Point(48, y + 9), fitz.Point(547, y + 9), color=RULE,
                   width=1)
    rows = [("Total revenue", "$14,280,000", "+18.4%"),
            ("Recurring revenue", "$11,940,000", "+22.1%"),
            ("Gross margin", "72.6%", "+2.2 pts"),
            ("Net retention", "114%", "+6 pts"),
            ("Customers", "1,284", "+143")]
    ty = y + 34
    page.draw_rect(fitz.Rect(48, ty - 16, 547, ty + 4), fill=(0.94, 0.96, 0.99),
                   color=None)
    for label, col in (("Metric", 56), ("Value", 300), ("Change", 440)):
        page.insert_text((col, ty - 2), label, fontname="hebo", fontsize=9,
                         color=GREY)
    ty += 22
    for name, value, delta in rows:
        page.insert_text((56, ty), name, fontname="helv", fontsize=10.5,
                         color=(0.16, 0.19, 0.24))
        page.insert_text((300, ty), value, fontname="hebo", fontsize=10.5,
                         color=(0.10, 0.13, 0.18))
        good = not delta.startswith("-")
        page.insert_text((440, ty), delta, fontname="helv", fontsize=10.5,
                         color=(0.07, 0.55, 0.35) if good else (0.72, 0.15, 0.13))
        page.draw_line(fitz.Point(48, ty + 8), fitz.Point(547, ty + 8),
                       color=(0.93, 0.94, 0.96), width=0.7)
        ty += 26

    page.insert_text((48, 806), "Northwind Analytics · Confidential",
                     fontname="helv", fontsize=8, color=GREY)
    page.insert_text((520, 806), "Page 1", fontname="helv", fontsize=8,
                     color=GREY)

    # ---------------------------------------------------------------- page 2
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 72), "Segment Performance", fontname="hebo",
                     fontsize=17, color=NAVY)
    page.draw_line(fitz.Point(48, 84), fitz.Point(547, 84), color=RULE, width=1)
    page.insert_image(fitz.Rect(48, 104, 547, 392), stream=chart_png())
    page.insert_text((48, 416), "Figure 1 — Revenue by quarter ($M)",
                     fontname="tiit", fontsize=9, color=GREY)

    notes = (
        "Enterprise accounted for 61% of new bookings, up from 48% a year "
        "earlier. The mid-market motion slowed in February when we paused "
        "outbound to retrain the team on the new pricing model; early March "
        "figures suggest that gap is closing.\n\n"
        "Support satisfaction held at 4.6 out of 5 across 9,400 tickets. "
        "Median first response fell to 47 minutes from 82 minutes."
    )
    page.insert_textbox(fitz.Rect(48, 448, 547, 580), notes, fontname="tiro",
                        fontsize=10.5, color=(0.16, 0.19, 0.24), lineheight=1.45)

    page.draw_rect(fitz.Rect(48, 600, 547, 700), fill=(0.96, 0.98, 0.94),
                   color=(0.72, 0.84, 0.62), width=1)
    page.insert_text((64, 626), "Recommendation", fontname="hebo", fontsize=11,
                     color=(0.18, 0.38, 0.16))
    page.insert_textbox(
        fitz.Rect(64, 636, 531, 690),
        "Approve the proposed hiring plan for Q2 and revisit the enterprise "
        "discount schedule before the June renewal window opens.",
        fontname="helv", fontsize=10, color=(0.20, 0.30, 0.18), lineheight=1.4)

    page.insert_text((48, 806), "Northwind Analytics · Confidential",
                     fontname="helv", fontsize=8, color=GREY)
    page.insert_text((520, 806), "Page 2", fontname="helv", fontsize=8, color=GREY)

    # ------------------------------------------------------ page 3 (a form)
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 72), "Reviewer Sign-off", fontname="hebo",
                     fontsize=17, color=NAVY)
    page.draw_line(fitz.Point(48, 84), fitz.Point(547, 84), color=RULE, width=1)
    page.insert_textbox(
        fitz.Rect(48, 100, 547, 148),
        "Complete the fields below, then sign at the bottom of the page. "
        "Use the Edit Text tool to correct anything above, or the Redact tool "
        "to remove sensitive figures before circulating.",
        fontname="tiro", fontsize=10.5, color=(0.16, 0.19, 0.24), lineheight=1.4)

    fields = [("reviewer_name", "Reviewer name", 180, fitz.PDF_WIDGET_TYPE_TEXT, ""),
              ("reviewer_role", "Role", 226, fitz.PDF_WIDGET_TYPE_TEXT, ""),
              ("review_date", "Date reviewed", 272, fitz.PDF_WIDGET_TYPE_TEXT, ""),
              ("department", "Department", 318, fitz.PDF_WIDGET_TYPE_COMBOBOX, "")]
    for name, label, y, ftype, value in fields:
        page.insert_text((48, y + 15), label, fontname="helv", fontsize=10,
                         color=(0.28, 0.32, 0.38))
        w = fitz.Widget()
        w.field_name = name
        w.field_type = ftype
        w.rect = fitz.Rect(190, y, 500, y + 24)
        w.field_value = value
        w.fill_color = (0.97, 0.98, 1.0)
        w.border_color = (0.72, 0.77, 0.85)
        w.border_width = 1
        w.text_fontsize = 10
        if ftype == fitz.PDF_WIDGET_TYPE_COMBOBOX:
            w.choice_values = ["Finance", "Operations", "Engineering", "Sales"]
        page.add_widget(w)

    for name, label, y in [("approved", "I approve this report", 366),
                           ("followup", "Requires follow-up discussion", 396)]:
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        w.rect = fitz.Rect(190, y, 206, y + 16)
        w.field_value = False
        page.add_widget(w)
        page.insert_text((216, y + 12), label, fontname="helv", fontsize=10,
                         color=(0.28, 0.32, 0.38))

    w = fitz.Widget()
    w.field_name = "comments"
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_flags = 4096                      # multiline
    w.rect = fitz.Rect(190, 430, 500, 520)
    w.fill_color = (0.97, 0.98, 1.0)
    w.border_color = (0.72, 0.77, 0.85)
    w.border_width = 1
    w.text_fontsize = 10
    page.add_widget(w)
    page.insert_text((48, 445), "Comments", fontname="helv", fontsize=10,
                     color=(0.28, 0.32, 0.38))

    page.draw_line(fitz.Point(190, 600), fitz.Point(430, 600),
                   color=(0.55, 0.60, 0.68), width=0.8)
    page.insert_text((190, 616), "Signature", fontname="helv", fontsize=8.5,
                     color=GREY)
    page.insert_text((48, 596), "Sign here", fontname="helv", fontsize=10,
                     color=(0.28, 0.32, 0.38))

    page.insert_text((48, 806), "Northwind Analytics · Confidential",
                     fontname="helv", fontsize=8, color=GREY)
    page.insert_text((520, 806), "Page 3", fontname="helv", fontsize=8, color=GREY)

    # ------------------------------------------- page 4 (landscape, rotated)
    page = doc.new_page(width=842, height=595)
    page.insert_text((48, 70), "Appendix A — Raw Data", fontname="hebo",
                     fontsize=16, color=NAVY)
    page.draw_line(fitz.Point(48, 82), fitz.Point(794, 82), color=RULE, width=1)
    cols = ["Region", "Q1", "Q2", "Q3", "Q4", "Total", "YoY"]
    data = [
        ["North America", "3,120", "3,480", "3,610", "3,940", "14,150", "+16%"],
        ["EMEA", "2,240", "2,410", "2,690", "2,980", "10,320", "+24%"],
        ["APAC", "1,180", "1,320", "1,410", "1,590", "5,500", "+31%"],
        ["LATAM", "480", "520", "560", "610", "2,170", "+12%"],
    ]
    x0, y0, cw = 48, 118, 106
    page.draw_rect(fitz.Rect(x0, y0 - 16, x0 + cw * len(cols), y0 + 4),
                   fill=(0.94, 0.96, 0.99), color=None)
    for i, c in enumerate(cols):
        page.insert_text((x0 + 8 + cw * i, y0 - 2), c, fontname="hebo",
                         fontsize=9.5, color=GREY)
    yy = y0 + 26
    for row in data:
        for i, cell in enumerate(row):
            page.insert_text((x0 + 8 + cw * i, yy), cell, fontname="helv",
                             fontsize=10, color=(0.16, 0.19, 0.24))
        page.draw_line(fitz.Point(x0, yy + 8),
                       fitz.Point(x0 + cw * len(cols), yy + 8),
                       color=(0.93, 0.94, 0.96), width=0.7)
        yy += 27

    page.insert_text((48, 560), "Northwind Analytics · Confidential",
                     fontname="helv", fontsize=8, color=GREY)
    page.insert_text((760, 560), "Page 4", fontname="helv", fontsize=8, color=GREY)

    doc.set_metadata({
        "title": "Quarterly Performance Review",
        "author": "Northwind Analytics",
        "subject": "Q1 2024 results",
        "keywords": "quarterly, revenue, review",
    })
    doc.set_toc([
        [1, "Executive Summary", 1],
        [1, "Segment Performance", 2],
        [2, "Recommendation", 2],
        [1, "Reviewer Sign-off", 3],
        [1, "Appendix A — Raw Data", 4],
    ])
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"
    print("Wrote", build(out))
