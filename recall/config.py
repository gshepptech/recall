"""
Recall — shared constants.
Import from here instead of hardcoding values in search.py and db.py.
"""

import os

# Token budget per result slot (chars / CHARS_PER_TOKEN applied in search.py)
SNIPPET_LENGTHS = [500, 300, 200, 150, 150]

# Number of vector candidates fetched before re-ranking
VECTOR_SEARCH_K = 20

# Minimum query-relevance (0-1, the pure cosine+FTS blend) a result must clear to be
# returned. 0.0 = disabled — return best-effort matches as before. Raise this (tune with
# tests/eval_retrieval.py) to suppress weak matches instead of surfacing them as confident.
MIN_RELEVANCE = float(os.getenv('RECALL_MIN_RELEVANCE', '0.0'))

# Default role assigned to new tokens when none is specified
DEFAULT_TOKEN_ROLE = 'developer'
