---
name: pdf-processor
description: A skill for processing PDFs, including creation, merging, and info extraction.
---

# PDF Processor

I help you manipulate and create PDF files using the `pdfcpu` tool.

## What I do

### 1. Create PDF from JSON
You can generate complex PDFs with text, images, and tables using a JSON configuration.
```bash
pdfcpu create content.json output.pdf
```

**JSON Schema for Table:**
(Note: pdfcpu does not support comments in JSON files. Remove them before use.)
```json
{
  "pages": { // Define content per page
    "1": {
      "content": {
        "table": [
          {
            "rows": 4, // Total number of rows including header
            "cols": 2, // Total number of columns
            "colWidths": [60, 40], // Relative column widths (percentage)
            "width": 400, // Total table width in points
            "anchor": "center", // Table positioning (center, left, right, etc.)
            "lheight": 20, // Line height for cells
            "border": {
              "width": 1, // Border thickness
              "col": "#000000" // Border color in Hex
            },
            "values": [ // Array of row data
               ["Expense", "Amount"],
               ["Uber", "$50"],
               ["Meal", "$30"],
               ["Hotel", "$120"]
            ],
            "font": {
               "name": "Helvetica", // Font family
               "size": 12 // Font size in points
            }
          }
        ]
      }
    }
  }
}
```

### 2. Merge PDFs
Combine multiple PDF files into one.
```bash
pdfcpu merge output.pdf file1.pdf file2.pdf
```

### 3. PDF Info & Validation
Get metadata or validate the structure of a PDF.
```bash
pdfcpu info file.pdf
pdfcpu validate file.pdf
```

### 4. Other Operations
- **Rotate:** `pdfcpu rotate file.pdf 90`
- **Split:** `pdfcpu split file.pdf out_dir`
- **Extract Images:** `pdfcpu extract -mode=image file.pdf out_dir`

## Validation

Always verify your operations
1. Make sure the PDF was created.
2. Make sure the PDF has the correct contents.
3. Read the PDF and make sure it is consistent with the requirements.

## When to use me
Use this skill when you need to automate PDF generation, 
especially when it involves tables or merging documents for reports. 
Always use `pdfcpu help <command>` to explore more specific flags and options.
