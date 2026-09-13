# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## 🔒 Reporting a Vulnerability

We take the security of IchikaBot seriously. If you discover a vulnerability or security issue:

1. **Do not open a public GitHub issue.**
2. Report the vulnerability privately by opening a [GitHub Security Advisory](https://github.com/kei-kochiya/IchikaBot/security/advisories) or contacting the maintainer directly.
3. Include details regarding:
   - Type of issue (e.g. command injection, token exposure, buffer overflow)
   - Step-by-step instructions to reproduce
   - Potential impact

We will investigate and respond as quickly as possible.

---

## 🛡️ Best Practices for Bot Hosting

- **Never commit your `.env` file** or paste your bot token in public channels.
- Run IchikaBot using an unprivileged user (as configured in the official `Dockerfile`).
- Keep your dependencies updated using `pip install -U -r requirements.txt`.
