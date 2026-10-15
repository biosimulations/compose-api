import sys
import types

if sys.platform == "win32" and "pwd" not in sys.modules:
    # spython (imported through pbest) imports the POSIX-only `pwd` module at import time, and tests/conftest.py imports
    # the server's fixtures, which import pbest. That happens while pytest loads tests/conftest.py, before any
    # tests/cli/conftest.py, so the stub has to exist first: this package's __init__ is the earliest place. It only
    # acts on Windows, where only the CLI platform matrix runs (.github/workflows/cli-platforms.yml); no test calls
    # into `pwd` there, and spython uses it only inside functions the CLI tests never reach.
    sys.modules["pwd"] = types.ModuleType("pwd")
