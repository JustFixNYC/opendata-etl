# Contributing to opendata-etl

Thank you for helping improve this project.

## License

By contributing, you agree that your contributions are licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0), the same license as the framework. See `LICENSE`.

## Workflow

1. Open an issue or discussion before large changes when possible.
2. Use focused pull requests that match an agreed scope.
3. Run local checks before pushing:

   ```bash
   python3 -m compileall pipeline api
   python3 -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))"
   ```

   On some systems the `python` shim is not installed; use `python3` consistently if needed.

4. Do not commit secrets, tokens, or real deployment credentials. Source access is configured via **named credential references** resolved outside the repo (see `README.md`).

## Definition repositories

Dataset and API definitions live in **separate repositories** (for example `nycdb2`). Changes to the definition contract or example layouts should stay aligned with the master plan steps for schemas and loaders.
