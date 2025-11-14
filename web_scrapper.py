import importlib.util
import os

# Load the original "web scrapper.py" module (keeps filename with space intact)
_here = os.path.dirname(__file__)
_src_path = os.path.join(_here, "web scrapper.py")
_spec = importlib.util.spec_from_file_location("web_scraper_orig", _src_path)
_web_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_web_mod)

# Re-export parsing/extraction helpers with a friendly module name (no spaces)
extract_emails = _web_mod.extract_emails
get_safe_filename = _web_mod.get_safe_filename
extract_post_id = _web_mod.extract_post_id
extract_author_username = _web_mod.extract_author_username
extract_author_id = _web_mod.extract_author_id
extract_author_profile_href = _web_mod.extract_author_profile_href
extract_post_date = _web_mod.extract_post_date
get_gender_for_profile = _web_mod.get_gender_for_profile
load_cache = _web_mod.load_cache
save_cache = _web_mod.save_cache

__all__ = [
    "extract_emails",
    "get_safe_filename",
    "extract_post_id",
    "extract_author_username",
    "extract_author_id",
    "extract_author_profile_href",
    "extract_post_date",
    "get_gender_for_profile",
    "load_cache",
    "save_cache",
]