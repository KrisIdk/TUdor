# ТУдор (TUdor) & Laya Knowledge Engine

**ТУдор** is an AI assistant and knowledge retrieval system designed specifically for the **Technical University of Sofia (ТУ - София)**. It bridges semantic information retrieval (powered by **Laya**) with a conversational LLM (via **Ollama / `gemma4:e2b`**) to deliver accurate, grounded, hallucination-free answers about university admissions, faculties, curricula, leadership, tuition fees, contacts, and campus facilities.

---

## 🚀 Features

- **Grounded AI Assistant**: Integrates Laya's semantic knowledge decoder with local LLM synthesis (`gemma4:e2b`).
- **Bulgarian NLP Pipeline**: Custom transliteration (BDS standard), Cyrillic normalization, and TU-specific acronym / alias resolution (e.g., `ФКСТ`, `FKST`, `КСУ`, `ФЕТТ`).
- **Rich Knowledge Base**: Structured data covering all faculties, departments, degree curricula, admissions calendar, tuition fees, and administrative contacts.
- **REST API & Web UI**: Multi-threaded server providing clean API endpoints (`/api/chat`, `/api/search`, `/api/faculty`, `/api/admissions`, `/api/curriculum`, `/api/contacts`, `/api/schemas`) and a responsive web application.
- **Automated Test Suite**: Comprehensive unit tests validating NLP parsing, acronym expansion, tool payload formatting, and domain queries.

---

## 📁 Project Structure

```text
TUdor/
├── app/                      # Web interface and server
│   ├── app.js               # Frontend chat and UI interactions
│   ├── index.html           # Main web application page
│   ├── server.py            # Multi-threaded HTTP server & REST API
│   └── style.css            # UI stylesheet
├── crawler/                  # Knowledge extraction & NLP utilities
│   ├── bulgarian_nlp.py     # Transliteration, normalization & acronym mapping
│   ├── rsc_parser.py        # HTML/RSC content parsing
│   └── tu_crawler.py        # Web scraper for TU Sofia resources
├── data/                     # Structured knowledge base files
│   ├── tu_sofia_kb.json     # Main knowledge graph / content
│   └── tu_sofia_map.json    # Campus map & location data
├── knowledge/                # Raw markdown documentation by faculty & department
├── tests/                    # Automated unit tests
│   └── test_laya_tools.py   # Test suite for Laya tools and Bulgarian NLP
├── laya_tools.py             # Knowledge retrieval engine & tool schema definitions
└── requirements.txt          # Python dependencies
```

---

## 🛠️ Setup & Installation

### 1. Requirements

- Python 3.10+
- (Optional, for LLM chat) [Ollama](https://ollama.com/) with the model `gemma4:e2b`:
  ```bash
  ollama pull gemma4:e2b
  ```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 🧪 Running Tests

Run the test suite to verify NLP, tools, and retrieval:

```bash
python tests/test_laya_tools.py
```

Or via unittest:

```bash
python -m unittest discover tests
```

---

## 🌐 Running the Web Application

Start the TUdor server on port 8080 (or specify a custom port as an argument):

```bash
python app/server.py 8080
```

Once running, open your browser and navigate to:
```
http://localhost:8080/
```
