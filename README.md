# Browser for Blind

An AI-powered, voice-driven web browser for blind and visually impaired users.

Instead of reading a screen, the user tells the browser what they want to do — *"open my email and read the latest message"*, *"book a ticket for Saturday"* — and an AI agent navigates the web on their behalf, then narrates the results back.

## How it works

- **Server** — a Python backend runs an AI browser agent together with a Chromium browser for each user (with persistent profiles). The agent reads pages, clicks, types and fills forms to complete the user's task.
- **Clients** — lightweight desktop and mobile apps. They take voice input and play back spoken narration. All of the browsing happens on the server.

## Repository structure

```
.
├── Backend/    # Python server and AI browser agent (built on the open-source browser-use library)
└── Frontend/   # Client applications (desktop / mobile)
```

## Getting started (Backend)

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
cd Backend
uv sync
uvx playwright install chromium --with-deps
```

Create `Backend/.env` with the API key for your LLM provider (see `Backend/.env.example`), for example:

```bash
MISTRAL_API_KEY=your-key
```

Never commit `.env` files. They are already listed in `.gitignore`.

## Developer

Developed by **[Muhad01](https://github.com/Muhad01)** as a Final Year Project.

## Acknowledgements

The backend agent builds on [browser-use](https://github.com/browser-use/browser-use) (MIT License). See [Backend/LICENSE](Backend/LICENSE).
