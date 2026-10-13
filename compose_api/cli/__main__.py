"""`python -m compose_api.cli`, the same program as the installed `compose-api` command."""

from compose_api.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
