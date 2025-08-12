# Contributing

Thanks for your interest in contributing!

## Getting started
- Use Python 3.10+.
- Create a virtualenv and install dependencies: `pip install -r requirements.txt`.
- Copy `.env.example` to `.env` and set required keys.
- Initialize DB: `python -m alembic upgrade head`.
- Log in at least one account: `python -m app.cli.login`.
- Run API and worker in two terminals.

## Code style
- Run `ruff check app workers` and fix reported issues.
- Run `black app workers` to format code.
- Keep changes focused and add small comments where logic may be non-obvious.

## Tests
- If you change public behavior, add minimal tests or a smoke script.

## Pull Requests
- Describe the change and rationale.
- Include screenshots for UI changes.
- Ensure CI passes (lint + format check).

## Security
- Do not include real session files or secrets. `.env`, `sessions/`, and `app.db` are ignored by `.gitignore`.

## License
- By contributing, you agree your contributions will be licensed under the MIT License.
