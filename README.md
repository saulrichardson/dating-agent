# Concierge

Python environment setup for Playwright automation.

## Setup

1. Create a virtual environment:
```bash
python3 -m venv venv
```

2. Activate the virtual environment:
```bash
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

**Important:** Always activate the virtual environment before running the script:

```bash
source venv/bin/activate
python test_bumble_playwright.py
```

## Deactivate

When you're done, deactivate the virtual environment:
```bash
deactivate
```

