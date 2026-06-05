---
name: create-spreadsheets
description: Create Excel spreadsheets (.xlsx) with formulas, charts, and conditional formatting using openpyxl
version: "1.0"
trigger_keywords:
  - excel
  - spreadsheet
  - xlsx
  - openpyxl
  - workbook
  - worksheet
  - chart
  - formula
tools_required:
  - write_file
  - run_python
  - install_package
---

# Creating Spreadsheets Programmatically

`openpyxl` is the standard for reading and writing Excel .xlsx files with full support for formulas, charts, styles, and conditional formatting.

## Install
```
install_package("openpyxl")
```

## Basic Workbook

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active
ws.title = "Sales Report"

# Header row with bold + background color
headers = ["Month", "Revenue", "Expenses", "Profit"]
header_fill = PatternFill(fill_type="solid", fgColor="4472C4")
header_font = Font(bold=True, color="FFFFFF")

for col, header in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=header)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = Alignment(horizontal="center")

# Data rows
data = [
    ("Jan", 50000, 32000),
    ("Feb", 62000, 35000),
    ("Mar", 75000, 41000),
]
for row_idx, (month, rev, exp) in enumerate(data, 2):
    ws.cell(row=row_idx, column=1, value=month)
    ws.cell(row=row_idx, column=2, value=rev)
    ws.cell(row=row_idx, column=3, value=exp)
    # Formula: Profit = Revenue - Expenses
    ws.cell(row=row_idx, column=4, value=f"=B{row_idx}-C{row_idx}")

# Auto-fit column widths
for col in ws.columns:
    max_width = max(len(str(cell.value or "")) for cell in col)
    ws.column_dimensions[get_column_letter(col[0].column)].width = max_width + 4

wb.save("sales_report.xlsx")
```

## Adding a Chart

```python
from openpyxl.chart import BarChart, Reference

chart = BarChart()
chart.type = "col"
chart.title = "Monthly Revenue"
chart.y_axis.title = "Amount ($)"
chart.x_axis.title = "Month"

data_ref = Reference(ws, min_col=2, min_row=1, max_col=2, max_row=4)
cats_ref = Reference(ws, min_col=1, min_row=2, max_row=4)
chart.add_data(data_ref, titles_from_data=True)
chart.set_categories(cats_ref)
chart.shape = 4
ws.add_chart(chart, "F2")   # Place chart at cell F2

wb.save("sales_report.xlsx")
```

## Conditional Formatting

```python
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule

# Color scale: red → green based on values
rule = ColorScaleRule(
    start_type="min", start_color="FF0000",
    end_type="max",   end_color="00FF00",
)
ws.conditional_formatting.add("D2:D4", rule)
```

## Reading Existing Files

```python
from openpyxl import load_workbook

wb = load_workbook("existing.xlsx")
ws = wb["Sheet1"]
for row in ws.iter_rows(min_row=2, values_only=True):
    print(row)
```

## Pandas Integration (bulk data)

```python
import pandas as pd

df = pd.DataFrame({"Name": ["Alice", "Bob"], "Score": [95, 88]})
df.to_excel("output.xlsx", index=False, engine="openpyxl")
# Read back:
df2 = pd.read_excel("output.xlsx")
```

## Tips
- Use `data_only=True` in `load_workbook()` to read formula results instead of formulas
- Multiple sheets: `wb.create_sheet("Summary")`
- Freeze panes: `ws.freeze_panes = "A2"` (freezes row 1)
- Password protect: `wb.security.workbookPassword = "secret"`
