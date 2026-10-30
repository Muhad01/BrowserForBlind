# CIGHT-BROWSER

An AI-driven, voice-only web browser tailored for blind and low-vision users (NUST MCS Final Year Project).

The user speaks a goal; an AI Task Agent proposes one browser action at a time; each action is normalized, validated, and verified by a deterministic SafetyPolicy before a Playwright/Chromium executor runs it in the browser; progress and results are spoken back continuously. A logically separate Perception Agent describes the current page from a screenshot upon request.

## Architecture

- **Frontend**: Next.js + React + TypeScript web application with Zustand for modular domain state and the Web Speech API (`SpeechRecognition` for voice input, `speechSynthesis` for audio feedback) wrapped in accessible UI controls and `aria-live` regions.
- **Backend**: Django 5 + Django Channels (WebSockets via Daphne) with PostgreSQL as the authoritative source of truth. Redis acts as the channel layer and Celery task broker.
- **Execution & Safety**: Celery worker runs the browser automation loop using Playwright and Chromium. Every action is gated by a deterministic `SafetyPolicy` before execution.
- **AI**: Google Gemini (multimodal, model ID configurable via environment, defaulting to `gemini-2.5-flash`).

## Repository Structure

```
.
├── Backend/                 # Django ASGI backend, Celery worker, and safety services
│   ├── cight/               # Django project configuration (settings, ASGI, Celery)
│   ├── core/                # Domain app: models, enums, services, tests
│   ├── manage.py
│   └── pyproject.toml
├── Frontend/                # Next.js web application
├── docker-compose.dev.yml   # Local dev PostgreSQL and Redis
└── THIRD_PARTY_NOTICES.md   # Third-party software notices (browser-use, etc.)
```

## Security & Secrets

Never commit `.env` files. They are listed in `.gitignore`. Use `.env.example` as a template for local environment configuration.
