"""Compatibility entry: there is one release build implementation."""
from build_portable import main
if __name__=="__main__":
    raise SystemExit(main())
