import sys
import types

if sys.platform == "win32" and "pwd" not in sys.modules:
    # spython (imported via pbest) imports the POSIX-only `pwd` module at import time.
    sys.modules["pwd"] = types.ModuleType("pwd")
