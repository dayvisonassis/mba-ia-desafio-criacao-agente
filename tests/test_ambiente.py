# tests/test_ambiente.py
import sys
import google.adk

def test_versoes():
    assert google.adk.__version__ == "2.12.0"
    assert sys.version_info[:2] >= (3, 12)
