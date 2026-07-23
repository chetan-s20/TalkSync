import pytest
import sys

if __name__ == "__main__":
    ret = pytest.main(["-v", "tests/"])
    sys.exit(ret)
