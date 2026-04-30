"""PyInstaller entry point for the braindump backend binary.

PyInstaller needs a plain script, not a module:function reference.
This shim imports braindump's actual CLI runner and delegates to it.
"""

from braindump.main import run

if __name__ == "__main__":
    run()
