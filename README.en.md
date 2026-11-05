# WhatsApp Sender Engine 🚀

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.46+-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)](https://playwright.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success?style=for-the-badge)]()

**Professional, decoupled WhatsApp Web automation engine for bulk messaging featuring biomechanical human typing simulation, stochastic anti-ban protection (Box-Muller jitter), resilient session persistence, and high-performance streaming spreadsheet ingestion.**

[🇧🇷 Português](README.md) • [🇺🇸 English](README.en.md)

</div>

---

## 📌 Why WhatsApp Sender Engine?

Most bulk WhatsApp senders in the market fail due to structural flaws:
1. **Immediate Meta Bans:** Dispatches with static, robotic intervals (e.g., exactly every 5 seconds) or headless injections without real keystroke emulation trigger anti-spam heuristics rapidly.
2. **Phone Number Corruption:** Microsoft Excel frequently converts long digits into scientific notation (`6.299E+10`), drops Brazilian 9th digits, or truncates characters during CSV parsing.
3. **Out-of-Memory Freezes:** Standard libraries load entire spreadsheets into RAM, causing crashes when lists exceed 5,000 rows.
4. **Repeated Logouts:** Inability to persist browser sessions, forcing users to rescan the QR Code on every restart.

The **WhatsApp Sender Engine** was built from first principles to solve these issues permanently, combining an asynchronous **FastAPI** backend, **Playwright Chromium Stealth** automation, and a modern, reactive desktop web interface.

---

## ✨ Key Features

### 🛡️ 1. Stochastic Anti-Ban Protection (Box-Muller Jitter)
- **Rhythmic Signature Elimination:** Inter-message delays are sampled from a truncated Gaussian distribution via the Box-Muller transform within $[10\text{s}, 25\text{s}]$, eliminating robotic periodic intervals.
- **Fat-Tail Anomaly Injection:** A probabilistic long-tail delay (15s to 40s) is injected periodically to disrupt machine learning cadence classifiers.
- **Intelligent Batch Pauses:** Configurable periodic cooldowns (e.g., 2 to 5 minutes) every batch of 20 dispatched messages.

### ⌨️ 2. Biomechanical Human Typing Simulation
- **Realistic Inter-Keystroke Intervals (IKI):** Typing velocity dynamically mirrors human WPM distributions with natural cognitive pauses on strong punctuation (`.`, `?`, `!`) and weak delimiters (`,`, `;`).
- **Micro-Typo & Auto-Correction Emulation:** Occasional accidental strikes on adjacent QWERTY keys, followed by cognitive realization pauses, `Backspace` presses, and accurate corrections.
- **Multi-Line Premature Send Prevention:** All line breaks (`\n`) strictly utilize `Shift+Enter` within WhatsApp Web's contenteditable compose box, preserving structured multi-paragraph templates.

### 📊 3. Rigorous E.164 Brazilian Phone Sanitization
- **Full Anatel Area Code Validation:** Validates against all 67 official Brazilian DDD codes, rejecting malformed or nonexistent prefixes.
- **9th Digit Preservation & Recovery:** Automatically restores missing 9th digits for mobile numbers (`62994912937` $\rightarrow$ `5562994912937`), cleans carrier selection codes (CSPs: 015, 021), and strips long-distance leading zeros.
- **Excel Float Shielding:** Comprehensive handling prevents scientific notation truncations.
- **Deterministic Deduplication:** *First-Wins* algorithm eliminates repeated numbers while intelligently merging secondary custom variables.
- **Low-Memory Streaming Parser:** Reads `.xlsx`, `.csv`, and `.txt` files in streaming mode ($O(1)$ memory footprint, $<15\text{MB}$ RAM for lists $>50,000$ contacts).

### 🌐 4. WhatsApp Web Automation with Playwright Stealth
- **Persistent Session Storage (`userDataDir`):** Preserves cookies, LocalStorage, and IndexedDB across application restarts; scan the QR Code once and stay authenticated.
- **Anti-Automation Evasion:** Operates with Chromium flags (`--disable-blink-features=AutomationControlled`), authentic Chrome Windows User-Agent, and stealth scripts.
- **Error Modal Resilience:** Automatically detects and dismisses the "Phone number shared via url is invalid" popup (`div[role="dialog"] button:has-text("OK")`), tagging the contact as `FAILED` and continuing the queue without interruption.

### 📝 5. Recursive Spintax & Attachment Support
- **Recursive Multi-Level Spintax:** Generates unique variations for every message (`{Hello|Hi|Greetings} {name}!`) to prevent template fingerprinting.
- **Dynamic Variable Interpolation:** Injects `{nome}`, `{telefone}`, `{empresa}`, `{valor}`, and custom table columns.
- **Multimedia & Document Attachments:** Supports sending images, videos, PDFs, and Office documents with custom captions.

### 📈 6. Real-Time SSE Telemetry & Executive Reporting
- **Server-Sent Events (SSE) Channel:** Real-time metrics streaming covering progress, messages per minute (MPM), and stochastic ETA calculations.
- **One-Click Export:**
  - **Excel (`.xlsx`):** Formats phone numbers explicitly as Text (`@`) to avoid spreadsheet truncation, accompanied by an *Executive Summary* KPI tab.
  - **CSV (`.csv`):** Universal export with `utf-8-sig` encoding (BOM) and semicolon (`;`) delimiter for instant opening in Microsoft Excel without character encoding issues.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph UI ["User Interface (Desktop / Web)"]
        HTML["HTML5 / Tailwind Dashboard"]
        JS["app.js (Reactive Controller)"]
        SSE["SSE Channel (Live Telemetry)"]
    end

    subgraph Core ["Server Core (FastAPI)"]
        API["FastAPI REST Endpoints"]
        CS["ContactService (E.164 & Streaming)"]
        DS["DispatcherService (FSM & Anti-Ban Queue)"]
        RS["ReportingService (Auditing & Exports)"]
    end

    subgraph Automation ["Browser Automation Layer"]
        PW["Playwright Persistent Context"]
        Stealth["playwright-stealth"]
        WA["WhatsApp Web (Official Chromium)"]
    end

    HTML <--> JS
    JS <--> API
    SSE <-- API
    API --> CS
    API --> DS
    API --> RS
    DS --> PW
    PW --> Stealth --> WA
```

---

## 🚀 Installation & Setup

### Prerequisites
- **Python 3.10+** (Python 3.12 recommended)
- **Google Chrome** or installed Chromium dependencies

### 1. Clone the Repository
```bash
git clone https://github.com/4pixeltechBR/whatsapp-sender-engine.git
cd whatsapp-sender-engine
```

### 2. Create and Activate Virtual Environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure Environment Variables (Optional)
```bash
cp .env.example .env
```

---

## 💻 Running the Application

### Option 1: Quick Windows Launcher (1-Click)
Double click:
```text
Iniciar_WhatsApp_Sender.bat
```

### Option 2: Command Line
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

Open your web browser and navigate to:
👉 **`http://127.0.0.1:8765`**

---

## 🧪 Test Suite & Quality Assurance

The codebase includes comprehensive unit, integration, and adversarial stress tests:

```bash
# Run all unit and integration tests
pytest -v

# Run the Tier 5 Adversarial Stress Harness (10k rows, concurrency locks, fast aborts)
python tests/adversarial_tier5_harness.py

# Run the 5-Agent Systematic Multi-Agent Audit
python tests/systematic_teamwork_audit.py
```

---

## 📂 Project Structure

```text
whatsapp_sender_engine/
├── app/
│   ├── core/
│   │   ├── config.py         # Global settings and path definitions
│   │   └── constants.py      # State machine enums & Anatel DDD set
│   ├── models/
│   │   └── schemas.py        # Pydantic validation schemas
│   ├── services/
│   │   ├── browser_service.py     # Playwright Chromium engine
│   │   ├── contact_service.py     # Streaming, E.164 sanitization & deduplication
│   │   ├── dispatcher_service.py  # Anti-ban queue, biomechanical typing & Spintax
│   │   └── reporting_service.py   # SSE telemetry and Excel/CSV export
│   ├── static/
│   │   ├── css/styles.css    # Modern responsive styling & dark mode
│   │   ├── js/app.js         # Reactive client application & SSE logic
│   │   └── index.html        # Comprehensive desktop UI
│   └── main.py               # FastAPI server and endpoints
├── data/                     # Persistent local storage (git-ignored)
│   ├── session/              # Playwright browser profile (IndexedDB)
│   ├── uploads/              # Uploaded sheets and media attachments
│   └── reports/              # Generated reports
├── tests/                    # Complete test suites and audit harnesses
├── .env.example              # Environment template
├── .gitignore                # Session and credential leak prevention
├── Iniciar_WhatsApp_Sender.bat # Quick launcher for Windows
├── LICENSE                   # MIT License
├── README.md                 # Portuguese documentation
├── README.en.md              # English documentation
└── requirements.txt          # Production dependencies
```

---

## 📄 License

Distributed under the **MIT** License. See [`LICENSE`](LICENSE) for more details.

Crafted with excellence by **[4Pixel Tech](https://github.com/4pixeltechBR)**.
