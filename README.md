<p align="center">

  <!-- Core -->
  ![GitHub License](https://img.shields.io/github/license/H0NEYP0T-466/python-mastery?style=for-the-badge&color=brightgreen)
  ![GitHub Stars](https://img.shields.io/github/stars/H0NEYP0T-466/python-mastery?style=for-the-badge&color=yellow)
  ![GitHub Forks](https://img.shields.io/github/forks/H0NEYP0T-466/python-mastery?style=for-the-badge&color=blue)
  ![GitHub Issues](https://img.shields.io/github/issues/H0NEYP0T-466/python-mastery?style=for-the-badge&color=red)
  ![GitHub Pull Requests](https://img.shields.io/github/issues-pr/H0NEYP0T-466/python-mastery?style=for-the-badge&color=orange)
  ![Contributions Welcome](https://img.shields.io/badge/Contributions-Welcome-brightgreen?style=for-the-badge)

  <!-- Activity -->
  ![Last Commit](https://img.shields.io/github/last-commit/H0NEYP0T-466/python-mastery?style=for-the-badge&color=purple)
  ![Commit Activity](https://img.shields.io/github/commit-activity/m/H0NEYP0T-466/python-mastery?style=for-the-badge&color=teal)
  ![Repo Size](https://img.shields.io/github/repo-size/H0NEYP0T-466/python-mastery?style=for-the-badge&color=blueviolet)
  ![Code Size](https://img.shields.io/github/languages/code-size/H0NEYP0T-466/python-mastery?style=for-the-badge&color=indigo)

  <!-- Community -->
  ![Discussions](https://img.shields.io/github/discussions/H0NEYP0T-466/python-mastery?style=for-the-badge&color=blue)
  ![Documentation](https://img.shields.io/badge/Docs-Available-green?style=for-the-badge&logo=readthedocs&logoColor=white)
  ![Open Source Love](https://img.shields.io/badge/Open%20Source-%E2%9D%A4-red?style=for-the-badge)

</p>

<h1 align="center">Python Mastery</h1>

<p align="center">
  <em>45-day structured curriculum: 20 days of Python mastery + 25 days of FastAPI mastery. One concept per day, from mutable defaults and GIL threading to async event loops, deployment, and system design.</em>
</p>

---

## 🔗 Links

| Resource | Description |
|----------|-------------|
| [Issues](https://github.com/H0NEYP0T-466/python-mastery/issues) | Report bugs or request features |
| [Contributing](CONTRIBUTING.md) | How to contribute |
| [Code of Conduct](CODE_OF_CONDUCT.md) | Community guidelines |
| [Security](SECURITY.md) | Report vulnerabilities |

---

## 📑 Table of Contents

- [🚀 Installation](#-installation)
- [⚡ Usage](#-usage)
- [✨ Features](#-features)
- [📂 Folder Structure](#-folder-structure)
- [🛠 Tech Stack](#-tech-stack)
- [🤝 Contributing](#-contributing)
- [📜 License](#-license)
- [🛡 Security](#-security)
- [📏 Code of Conduct](#-code-of-conduct)

---

## 🚀 Installation

### Prerequisites

- [Git](https://git-scm.com/) for cloning the repository
- A Markdown editor ([Obsidian](https://obsidian.md/) recommended for wikilink support)

### Setup

```bash
# Clone the repository
git clone https://github.com/H0NEYP0T-466/python-mastery.git

# Navigate to the project
cd python-mastery

# Open in Obsidian (optional)
# Point your Obsidian vault to the cloned directory
```

---

## ⚡ Usage

This is a **documentation-based curriculum**. Each file is a self-contained lesson.

### How to Use

1. **One file per day.** Don't rush. The practice questions at the end are not optional, they are the point.
2. **Cross-links are wikilinks.** Click `[[like-this]]` to jump between related concepts across Python and FastAPI.
3. **`#status/new`** means the file is freshly written. Mark `#status/reviewed` after you have read and done the practice.
4. **Order matters.** Each day builds on the previous.

### Python Mastery (Days 1–20)

| Day | Topic |
|-----|-------|
| 1 | Basics: mutable defaults, `is` vs `==`, truthy/falsy, `for...else`, string interning |
| 2 | Data Structures and Complexity |
| 3 | Functions and Scope |
| 4 | OOP and Dunder Methods |
| 5 | Decorators |
| 6 | Generators and Iterators |
| 7 | Context Managers |
| 8 | Exception Handling |
| 9 | Modules and Packaging |
| 10 | File I/O |
| 11 | Typing and Type Hints |
| 12 | Testing with pytest |
| 13 | Virtual Envs and Dependency Management |
| 14 | Logging |
| 15 | Performance Profiling |
| 16 | GIL and Threading |
| 17 | Multiprocessing |
| 18 | Async/Await and Event Loop |
| 19 | Concurrency Patterns |
| 20 | Memory Management and GC |

### FastAPI Mastery (Days 1–25)

| Day | Topic |
|-----|-------|
| 1 | Request-Response Lifecycle |
| 2 | Routing and Params |
| 3 | Pydantic Models and Validation |
| 4 | Dependency Injection |
| 5 | Middleware |
| 6 | Error Handling and Exception Handlers |
| 7 | Env and Config Management |
| 8 | Project Folder Structure |
| 9 | Async Endpoints: When to Use |
| 10 | Background Tasks |
| 11 | Database Integration: Async ORM |
| 12 | Auth: OAuth2 JWT |
| 13 | Rate Limiting |
| 14 | Caching |
| 15 | Logging and Monitoring |
| 16 | Testing FastAPI |
| 17 | WebSockets |
| 18 | Streaming Responses |
| 19 | Cron and Scheduled Jobs |
| 20 | Background Workers: Queues |
| 21 | API Versioning |
| 22 | CORS and Security Headers |
| 23 | Inference Serving Patterns |
| 24 | System Design for APIs at Scale |
| 25 | Deployment: Docker + Uvicorn |

---

## ✨ Features

- **45 structured lessons** spanning Python core concepts and FastAPI production patterns
- **Deep-dive explanations** that go beyond syntax to cover why things work the way they do
- **Practical examples** with runnable code for every concept
- **Common mistakes and gotchas** section in each lesson to highlight pitfalls
- **Practice questions** with detailed answers at the end of each file
- **Wikilink cross-references** between related Python and FastAPI topics
- **Progress tracking** via Obsidian tags (`#status/new`, `#status/reviewed`)
- **Map of Content** in `index.md` for full navigation

---

## 📂 Folder Structure

```
python-mastery/
├── redemption/
│   ├── index.md                  # Map of Content
│   ├── python/                   # Python Mastery (Days 1-20)
│   │   ├── day01-basics.md
│   │   ├── day02-data-structures-and-complexity.md
│   │   ├── day03-functions-and-scope.md
│   │   ├── day04-oop-and-dunder-methods.md
│   │   ├── day05-decorators.md
│   │   ├── day06-generators-and-iterators.md
│   │   ├── day07-context-managers.md
│   │   ├── day08-exception-handling.md
│   │   ├── day09-modules-and-packaging.md
│   │   ├── day10-file-io.md
│   │   ├── day11-typing-and-type-hints.md
│   │   ├── day12-testing-with-pytest.md
│   │   ├── day13-virtual-envs-and-dependency-management.md
│   │   ├── day14-logging.md
│   │   ├── day15-performance-profiling.md
│   │   ├── day16-gil-and-threading.md
│   │   ├── day17-multiprocessing.md
│   │   ├── day18-async-await-and-event-loop.md
│   │   ├── day19-concurrency-patterns.md
│   │   └── day20-memory-management-and-gc.md
│   └── fastapi/                  # FastAPI Mastery (Days 1-25)
│       ├── day01-request-response-lifecycle.md
│       ├── day02-routing-and-params.md
│       ├── day03-pydantic-models-and-validation.md
│       ├── day04-dependency-injection.md
│       ├── day05-middleware.md
│       ├── day06-error-handling-and-exception-handlers.md
│       ├── day07-env-and-config-management.md
│       ├── day08-project-folder-structure.md
│       ├── day09-async-endpoints-when-to-use.md
│       ├── day10-background-tasks.md
│       ├── day11-database-integration-async-orm.md
│       ├── day12-auth-oauth2-jwt.md
│       ├── day13-rate-limiting.md
│       ├── day14-caching.md
│       ├── day15-logging-and-monitoring.md
│       ├── day16-testing-fastapi.md
│       ├── day17-websockets.md
│       ├── day18-streaming-responses.md
│       ├── day19-cron-and-scheduled-jobs.md
│       ├── day20-background-workers-queues.md
│       ├── day21-api-versioning.md
│       ├── day22-cors-and-security-headers.md
│       ├── day23-inference-serving-patterns.md
│       ├── day24-system-design-for-apis-at-scale.md
│       └── day25-deployment-docker-uvicorn.md
├── .gitignore
└── README.md
```

---

## 🛠 Tech Stack

### Documentation

![Markdown](https://img.shields.io/badge/Markdown-000000?style=for-the-badge&logo=markdown&logoColor=white)
![Obsidian](https://img.shields.io/badge/Obsidian-7C3AED?style=for-the-badge&logo=obsidian&logoColor=white)

### Topics Covered

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-20696F?style=for-the-badge&logo=uvicorn&logoColor=white)

---

<p align="center">Made with ❤ by <a href="https://github.com/H0NEYP0T-466">H0NEYP0T-466</a></p>
