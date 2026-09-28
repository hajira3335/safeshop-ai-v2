---
title: SafeShop AI
emoji: 🛡️
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# SafeShop AI backend (v2)

Checks a screenshot of an online product listing and returns a fake-risk report.

- `GET /health` shows whether the AI key is set.
- `POST /analyze` (multipart form): `image` (required), `product_name`, `description`, `entered_price` (optional).

Set the secret `GEMINI_API_KEY` in **Settings → Variables and secrets**. Free key: https://aistudio.google.com
