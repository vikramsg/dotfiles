Here’s a **concise but practical gist of what pdfcpu can do**, including its **main capabilities, commands, syntax, and usage patterns** — so you can quickly decide how to use it. ([pdfcpu][1])

---

## 📌 What **pdfcpu** Is

**pdfcpu** is:

* A **PDF processor written in Go**.
* Available both as a **command-line tool (CLI)** and as a **Go library (API)**. ([GitHub][2])

It’s designed for **batch processing, automation, and scripting** of PDF operations with a rich set of features. ([pdfcpu][3])

---

## 🧠 Core Capabilities

### 📄 Document Creation

* Generate PDFs from **JSON descriptions** (text, images, tables, forms, layout). ([pdfcpu][4])
* Add **headers/footers**, text blocks, boxes, images, and tables. ([pdfcpu][4])

### 🛠️ Manipulation & Editing

* **Merge / split / collect / trim** pages. ([pdfcpu][3])
* **Rotate, crop, resize** pages. ([pdfcpu][3])
* **Stamp / watermark** with text, images, or other PDFs. ([pdfcpu][3])
* **Rearrange pages**: e.g., N-Up, grid, booklet. ([pdfcpu][3])
* **Optimize** PDFs by removing redundant fonts/images. ([pdfcpu][3])

### 🔐 Security

* **Encrypt / decrypt**, set **passwords and permissions**. ([pdfcpu][3])

### 📤 Extraction

* Extract **text, images, fonts, metadata, pages**. ([pdfcpu][3])

### 📋 Metadata & Structure

* Manage **bookmarks, annotations, keywords, viewer prefs, properties**. ([pdfcpu][3])

### 📊 Forms

* Create and **fill interactive forms** via JSON or CSV. ([pdfcpu][3])

### 🖼️ Import/Export

* **Import images** as PDF pages. ([pdfcpu][5])

### 🔍 Validation

* Validate PDFs (PDF 1.7 and basic PDF 2.0) for conformance. ([pdfcpu][3])

---

## 💻 CLI Usage Syntax

The basic structure for pdfcpu commands is:

```
pdfcpu <command> [flags] [arguments]
```

You can run:

```
pdfcpu help
```

to list all available commands and subcommands. ([pdfcpu][3])

---

## 🧰 Common Commands & Examples

> **Note:** For many operations, `pdfcpu help <command>` will show relevant flags.

### 🔍 Info & Validate

```bash
# Show PDF info
pdfcpu info file.pdf

# Validate structure
pdfcpu validate file.pdf
```

---

### 📌 Merge / Split

```bash
# Merge PDFs
pdfcpu merge output.pdf file1.pdf file2.pdf

# Split by pages count
pdfcpu split file.pdf .
```

---

### ⛏ Manipulate Pages

```bash
# Rotate pages
pdfcpu rotate -pages 1-3 file.pdf 90

# Crop pages
pdfcpu crop -pages 1-5 file.pdf "10 10 580 792"
```

---

### 💧 Optimize / Extract

```bash
# Optimize PDF size
pdfcpu optimize file.pdf

# Extract images
pdfcpu extract -mode=image file.pdf out_dir
```

---

### 🔐 Encryption

```bash
# Set user password
pdfcpu encrypt -upw secret file.pdf

# Remove password
pdfcpu decrypt -upw secret file.pdf
```

---

### 🆕 Create from JSON

Define document content in a JSON file (including tables, text, images):

```bash
pdfcpu create content.json output.pdf
```

This will produce a PDF with layout per JSON spec. ([pdfcpu][4])

---

### 📷 Import Images

```bash
pdfcpu import out.pdf img1.jpg img2.png
```

Each image becomes a PDF page. ([pdfcpu][5])

---

## 🎯 Go Library (API) Overview

If you use pdfcpu inside a Go program:

```go
import "github.com/pdfcpu/pdfcpu/pkg/api"

// Example: Merge PDFs programmatically
err := api.MergeCreateFile([]string{"in1.pdf", "in2.pdf"}, "out.pdf", nil)
```

You can also read, modify and write PDFs directly via API. ([DeepWiki][6])

---

## 🧾 Help & Discovery

* List all pdfcpu commands:

  ```bash
  pdfcpu help
  ```
* Learn flags for a specific command:

  ```bash
  pdfcpu help <command>
  ```

---

## 📌 Summary — Key Strengths

| Task                             | Supported                                   |
| -------------------------------- | ------------------------------------------- |
| Create PDF from structured input | ✅ (via JSON) ([pdfcpu][4])                  |
| Merge / split / rotate / crop    | ✅ ([pdfcpu][3])                             |
| Watermarks, stamps, forms        | ✅ ([pdfcpu][3])                             |
| Extract text/images              | ✅ ([pdfcpu][3])                             |
| Encryption / permission          | ✅ ([pdfcpu][3])                             |
| Direct Markdown → PDF            | ❌ (requires conversion first) ([pdfcpu][3]) |

---

If you want example JSON for a table or a ready-to-use script to create a PDF from JSON with table content, just tell me your table structure!

[1]: https://pdfcpu.io/about/command_set.html?utm_source=chatgpt.com "PDF processor api & cli | pdfcpu"
[2]: https://github.com/pdfcpu/pdfcpu?utm_source=chatgpt.com "GitHub - pdfcpu/pdfcpu: A PDF processor written in Go."
[3]: https://pdfcpu.io/getting_started/usage.html?utm_source=chatgpt.com "PDF processor api & cli | pdfcpu"
[4]: https://pdfcpu.io/create/create.html?utm_source=chatgpt.com "PDF processor api & cli | pdfcpu"
[5]: https://pdfcpu.io/generate/import.html?utm_source=chatgpt.com "PDF processor api & cli | pdfcpu"
[6]: https://deepwiki.com/pdfcpu/pdfcpu/2.3-api-usage-guide?utm_source=chatgpt.com "API Usage Guide | pdfcpu/pdfcpu | DeepWiki"

