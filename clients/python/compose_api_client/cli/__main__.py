"""Run the command-line client as `python -m compose_api_client.cli`."""

import sys

from compose_api_client.cli.commands import main

if __name__ == "__main__":
    sys.exit(main())
