"""Scraper Factory"""

from urllib.parse import urlparse
from .base import BaseScraper, GenericScraper, ScrapedJob
from .harmeejobs import HarmeeJobsScraper
from .afriwork import AfriworkScraper

try:
    from .effoysira import EffoySiraScraper
except ImportError:
    EffoySiraScraper = GenericScraper

try:
    from .kebenajobs import KebenaJobsScraper
except ImportError:
    KebenaJobsScraper = GenericScraper

try:
    from .abayjobs import AbayJobsScraper
except ImportError:
    AbayJobsScraper = GenericScraper

try:
    from .ethiojobs import EthioJobsScraper
except ImportError:
    EthioJobsScraper = GenericScraper

# NEW: Import HagereJobsScraper
try:
    from .hagerejobs import HagereJobsScraper
except ImportError:
    HagereJobsScraper = GenericScraper

try:
    from .geezjobs import GeezJobsScraper
except ImportError:
    GeezJobsScraper = GenericScraper

try:
    from .hahujobs import HahuJobsScraper
except ImportError:
    HahuJobsScraper = GenericScraper

try:
    from .reportervacancy import ReporterVacancyScraper
except ImportError:
    ReporterVacancyScraper = GenericScraper

SCRAPERS = {
    'harmeejobs.com': HarmeeJobsScraper,
    'afriworket.com': AfriworkScraper,
    'afriwork.com': AfriworkScraper,
    'effoysira.com': EffoySiraScraper,
    'kebenajobs.com': KebenaJobsScraper,
    'abayjobs.com': AbayJobsScraper,
    'ethiojobs.net': EthioJobsScraper,
    'hagerejobs.com': HagereJobsScraper,
    'geezjobs.com': GeezJobsScraper,
    'hahu.jobs': HahuJobsScraper,
    'reportervacancy.com': ReporterVacancyScraper,
}

def get_scraper(url: str) -> BaseScraper:
    """Get appropriate scraper"""
    try:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        for key, scraper_class in SCRAPERS.items():
            if key in domain or domain in key:
                return scraper_class()
    except:
        pass
    return GenericScraper()

__all__ = ['get_scraper', 'BaseScraper', 'GenericScraper', 'ScrapedJob',
           'HarmeeJobsScraper', 'AfriworkScraper', 'AbayJobsScraper',
           'EthioJobsScraper', 'HagereJobsScraper', 'GeezJobsScraper', 'HahuJobsScraper',
           'ReporterVacancyScraper']