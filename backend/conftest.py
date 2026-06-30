"""Pytest bootstrap.

Put the backend root on sys.path so tests can import `extractors.*`,
`services.*`, and `config` exactly the way the running app does.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
