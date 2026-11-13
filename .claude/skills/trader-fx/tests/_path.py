"""Puts the skill folder on sys.path so tests can `import data` etc."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
