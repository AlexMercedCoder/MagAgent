---
name: create-word-docs
description: Create, format, and populate Microsoft Word (.docx) documents programmatically using python-docx and docxtpl
version: "1.0"
trigger_keywords:
  - docx
  - word document
  - word doc
  - report
  - letter
  - python-docx
  - docxtpl
tools_required:
  - write_file
  - run_python
  - install_package
---

# Creating Word Documents Programmatically

Use `python-docx` for building documents from scratch, and `docxtpl` when filling in Jinja2 templates.

## Quick Install Check
```python
# Agent should check first
import importlib
has_docx = importlib.util.find_spec("docx") is not None
```
If missing, use the `install_package` tool: `install_package("python-docx")`

## python-docx — Build from Scratch

```python
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# Title
title = doc.add_heading("Project Report", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER

# Styled paragraph
para = doc.add_paragraph()
run = para.add_run("Executive Summary")
run.bold = True
run.font.size = Pt(14)
doc.add_paragraph("This report summarizes Q3 findings...")

# Table
table = doc.add_table(rows=1, cols=3)
table.style = "Table Grid"
hdr = table.rows[0].cells
hdr[0].text, hdr[1].text, hdr[2].text = "Name", "Role", "Score"
for name, role, score in [("Alice", "Dev", 95), ("Bob", "QA", 88)]:
    row = table.add_row().cells
    row[0].text, row[1].text, row[2].text = name, role, str(score)

# Image
doc.add_picture("chart.png", width=Inches(5))

doc.save("output.docx")
print("Saved output.docx")
```

## docxtpl — Jinja2 Template Fill

```python
from docxtpl import DocxTemplate

tpl = DocxTemplate("template.docx")   # Word doc with {{ placeholders }}
context = {
    "client_name": "Acme Corp",
    "date": "2026-06-05",
    "items": [
        {"description": "Widget A", "qty": 10, "price": 9.99},
        {"description": "Widget B", "qty": 5,  "price": 14.99},
    ],
}
tpl.render(context)
tpl.save("invoice.docx")
```

Template syntax inside .docx file:
- `{{ variable }}` — simple substitution
- `{% for item in items %}...{% endfor %}` — loop over table rows
- `{% if condition %}...{% endif %}` — conditional content

## Common Patterns

### Headers and Footers
```python
from docx.oxml.ns import qn
section = doc.sections[0]
header = section.header
header.paragraphs[0].text = "Confidential | MagAgent Report"
```

### Page Breaks
```python
doc.add_page_break()
```

### Bullet Lists
```python
doc.add_paragraph("First point", style="List Bullet")
doc.add_paragraph("Second point", style="List Bullet")
doc.add_paragraph("Sub-point", style="List Bullet 2")
```

## When to Use What
- **python-docx**: Building documents dynamically from data (reports, letters, contracts)
- **docxtpl**: User has a Word template with branding/layout that you fill with data
- **fpdf2**: Simpler PDF output when Word isn't needed
