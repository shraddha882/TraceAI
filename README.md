# TraceAI

### AI-Powered Production Incident Investigator & Code Review Agent

TraceAI is a Django-based engineering tool that helps developers investigate production incidents and review code by combining **logs, traces, database signals, deployment changes, and deterministic analysis** into actionable findings.

It also provides an automated **Code Review Agent** that analyzes Python code and identifies potential bugs, security issues, performance problems, and other code-quality concerns.

## ✨ Key Features

### 🔍 Production Incident Investigation

* Analyze production incidents using:

  * Application logs
  * Database metrics and signals
  * Distributed traces
  * Deployment changes
* Correlate evidence across multiple sources.
* Generate RCA hypotheses based on deterministic analysis.
* Track evidence and investigation history.
* Generate persistent RCA reports through background jobs.

### 🤖 AI-Assisted RCA

* Optional OpenAI-powered explanation of existing RCA hypotheses.
* AI works as an explanation layer rather than replacing deterministic analysis.
* AI references are validated before being displayed.
* Static RCA analysis continues to work without an API key.

### 👨‍💻 Automated Code Review

* Analyze Python source code for common issues.
* Detect potential:

  * Bugs
  * Security vulnerabilities
  * Performance problems
  * Resource leaks
  * SQL-related issues
* Review GitHub pull requests and save review reports.
* Background workers process long-running reviews.

### 🔐 Workspace & Access Control

* User registration and authentication.
* User-owned reviews, incidents, jobs and reports.
* Staff-based access for legacy records and administration.
* CSRF-protected authentication flows.

## 🏗️ Architecture

```text
                    ┌─────────────────────┐
                    │      Django UI      │
                    │ HTML + Tailwind CSS │
                    │   Vanilla JS        │
                    └──────────┬──────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
      ┌───────▼────────┐               ┌────────▼────────┐
      │  Code Review   │               │ Incident Engine │
      │     Agent      │               │                 │
      └───────┬────────┘               └────────┬────────┘
              │                                 │
      ┌───────▼────────┐        ┌───────────────┼───────────────┐
      │ Static Analysis│        │               │               │
      └────────────────┘     Logs            DB/SQL         Traces
                                      │
                                      ▼
                              Deployment Changes
                                      │
                                      ▼
                              RCA Rule Engine
                                      │
                                      ▼
                              Optional AI Layer
```

## 🛠️ Tech Stack

* **Backend:** Python, Django, Django REST Framework
* **Frontend:** HTML, Tailwind CSS, Vanilla JavaScript
* **Database:** PostgreSQL
* **Code Analysis:** Python-based static analysis
* **AI:** OpenAI Responses API (optional)
* **Background Processing:** Django management-command worker
* **Authentication:** Django authentication & permissions
* **Version Control Integration:** GitHub

## 📂 Project Structure

```text
TraceAI/
├── code_review/       # Automated code & PR review
├── incidents/         # Incident investigation & RCA
├── core/              # Authentication & workspace access
├── traceai/           # Django project configuration
├── examples/          # Synthetic incident & code-review examples
├── manage.py
├── requirements.txt
├── .env.example
└── README.md
```

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/shraddha882/TraceAI.git
cd TraceAI
```

### 2. Create a virtual environment

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Configure environment variables

```powershell
Copy-Item .env.example .env
```

Configure your PostgreSQL credentials in `.env`.

### 4. Run migrations

```powershell
.\venv\Scripts\python.exe manage.py migrate
```

### 5. Run the application

```powershell
.\venv\Scripts\python.exe manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/code-review/
http://127.0.0.1:8000/incidents/
```

### 6. Run tests

```powershell
.\venv\Scripts\python.exe manage.py test
```

## ⚙️ Background Worker

Long-running PR reviews and RCA report generation can be processed using the background worker:

```powershell
.\venv\Scripts\python.exe manage.py run_review_worker
```

Jobs are persisted in PostgreSQL and can survive worker restarts.

## 🧪 Demo

TraceAI includes synthetic examples for demonstrating incident investigation and code review without requiring real production data.

For example:

```powershell
.\venv\Scripts\python.exe manage.py create_demo_incident --username YOUR_USERNAME
```

The repository also contains example code and synthetic evidence under `examples/`.

## 🤖 Optional AI Configuration

AI-assisted RCA explanations are optional.

Configure:

```text
OPENAI_API_KEY=your_key
TRACEAI_AI_MODEL=gpt-5
```

The deterministic RCA engine remains available even when AI is disabled or unavailable.

## 🔒 Security

* Secrets are loaded through environment variables.
* `.env` files are excluded from Git.
* User-owned data is isolated by workspace ownership.
* Synthetic examples are used instead of real production evidence.
* AI requests use bounded inputs and do not replace deterministic analysis.

## 📌 Project Status

TraceAI is an actively developed engineering project focused on **production debugging, automated code analysis, and AI-assisted root-cause investigation**.

---

**Built with Python, Django, PostgreSQL and AI-assisted engineering workflows.**
