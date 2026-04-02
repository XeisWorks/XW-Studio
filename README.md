# XeisWorks Studio

PySide6 desktop application for XeisWorks music publishing business management.

## Features

- **Rechnungen:** Invoice processing, printing, fulfillment
- **Produkte:** Inventory management, Wix/sevDesk sync, print plans
- **CRM:** Customer management, deduplication, merge
- **Steuern:** UVA, payment clearing, expense auditing
- **Statistik:** Revenue analytics, charts, export
- **Layout:** PDF tools, cover creation, QR codes, watermarks
- **Provisionen:** Royalty calculations, article analysis
- **Reisekosten:** Travel cost management (embedded)
- **Marketing:** Content planning, social media (scaffold)
- **Notensatz:** Music notation tools (scaffold)

## Setup

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/XeisWorks/XW-Studio.git
cd XW-Studio

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Copy and configure environment
copy .env.example .env
# Edit .env with your credentials

# Run
python -m xw_studio
```

## Architecture

- **UI Framework:** PySide6 + qt-material
- **Database:** PostgreSQL on Railway
- **Printing:** QPrinter + PyMuPDF at 600 DPI
- **Config:** YAML defaults + .env secrets + DB settings
- **Auto-Update:** git pull + pip install at startup

## Development

```bash
# Run tests
pytest tests/

# Type checking
mypy src/

# Linting
ruff check src/
```
