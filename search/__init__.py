"""Group 2 search over the prepared bill sections.

    from search import Searcher
    searcher = Searcher.from_database()          # loads intermediate.sections once
    for r in searcher.search("Can I make my bank delete my data?", k=5):
        print(r.rank, r.citation, r.heading, r.source_url)
"""

from .corpus import Section, load_sections
from .engine import METHODS, SearchResult, Searcher

__all__ = ["METHODS", "SearchResult", "Searcher", "Section", "load_sections"]
