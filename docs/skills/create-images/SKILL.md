---
name: create-images
description: Generate, manipulate, and export images using Pillow (PIL) and matplotlib for charts/plots
version: "1.0"
trigger_keywords:
  - image
  - pillow
  - PIL
  - matplotlib
  - chart
  - plot
  - PNG
  - JPG
  - thumbnail
  - resize
  - watermark
  - graph
  - visualization
tools_required:
  - write_file
  - run_python
  - install_package
---

# Creating and Manipulating Images Programmatically

Two primary tools: **Pillow** for image manipulation and **matplotlib** for charts/plots.

## Pillow — Image Manipulation

```python
# install_package("Pillow")
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Create a new image from scratch
img = Image.new("RGB", (800, 400), color=(30, 30, 46))  # Dark background
draw = ImageDraw.Draw(img)

# Draw shapes
draw.rectangle([50, 50, 750, 350], outline=(99, 102, 241), width=3)
draw.ellipse([100, 100, 200, 200], fill=(167, 139, 250))

# Add text
draw.text((400, 200), "MagAgent", fill=(255, 255, 255), anchor="mm")

# Load and manipulate an existing image
photo = Image.open("input.jpg")
photo = photo.resize((640, 480))                    # Resize
photo = photo.rotate(90, expand=True)              # Rotate
photo = photo.filter(ImageFilter.SHARPEN)          # Filter
photo = photo.convert("L")                         # Grayscale
photo.save("output.jpg", quality=90)

# Crop
box = (100, 100, 400, 300)  # (left, top, right, bottom)
cropped = photo.crop(box)
cropped.save("cropped.jpg")

# Thumbnail (preserves aspect ratio)
photo.thumbnail((256, 256))
photo.save("thumb.png")
```

## Watermarking

```python
from PIL import Image, ImageDraw, ImageFont
import os

def add_watermark(input_path: str, output_path: str, text: str = "CONFIDENTIAL"):
    img = Image.open(input_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size
    draw.text(
        (w // 2, h // 2), text,
        fill=(255, 0, 0, 80),    # Semi-transparent red
        anchor="mm",
    )
    watermarked = Image.alpha_composite(img, overlay).convert("RGB")
    watermarked.save(output_path)

add_watermark("document_scan.jpg", "watermarked.jpg", "DRAFT")
```

## matplotlib — Charts and Plots

```python
# install_package("matplotlib")
import matplotlib
matplotlib.use("Agg")   # Non-interactive backend — REQUIRED for server/agent use
import matplotlib.pyplot as plt
import numpy as np

# Bar chart
fig, ax = plt.subplots(figsize=(10, 6))
months = ["Jan", "Feb", "Mar", "Apr", "May"]
revenue = [50000, 62000, 75000, 68000, 90000]
bars = ax.bar(months, revenue, color="#6366F1", edgecolor="#4338CA")
ax.set_title("Monthly Revenue", fontsize=16, fontweight="bold")
ax.set_ylabel("Revenue ($)")
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
for bar, val in zip(bars, revenue):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 500,
            f"${val:,}", ha="center", va="bottom", fontsize=10)
plt.tight_layout()
plt.savefig("revenue_chart.png", dpi=150, bbox_inches="tight")
plt.close()
```

## Common Chart Types

```python
# Line plot
plt.plot(x, y, color="#6366F1", linewidth=2, marker="o")

# Pie chart
plt.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)

# Scatter plot
plt.scatter(x, y, c=colors, s=sizes, alpha=0.7)

# Heatmap (requires seaborn)
import seaborn as sns
sns.heatmap(matrix, annot=True, cmap="coolwarm")

# Always save instead of show for non-interactive use:
plt.savefig("output.png", dpi=150, bbox_inches="tight")
plt.close()   # Free memory
```

## Image Format Reference
| Format | Use Case |
|---|---|
| PNG | Lossless, transparency, screenshots |
| JPEG | Photos, lossy compression |
| WebP | Web delivery, good compression |
| SVG | Vector graphics (not Pillow — use cairosvg) |
| GIF | Simple animations (use imageio for video-to-gif) |
