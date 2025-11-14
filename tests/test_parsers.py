import os
import unittest
import importlib.util
from datetime import datetime

# load the wrapper module (no space in filename) so tests are stable
ROOT = os.path.dirname(os.path.dirname(__file__))
MODULE_PATH = os.path.join(ROOT, "web_scrapper.py")
_spec = importlib.util.spec_from_file_location("web_scraper_module", MODULE_PATH)
web_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(web_mod)

# functions under test (re-exported by wrapper)
extract_emails = web_mod.extract_emails
extract_post_id = web_mod.extract_post_id
extract_author_username = web_mod.extract_author_username
extract_author_id = web_mod.extract_author_id
extract_author_profile_href = web_mod.extract_author_profile_href
extract_post_date = web_mod.extract_post_date

# Minimal fake DOM / locator classes to simulate Playwright elements for parsers
class FakeElement:
    def __init__(self, attrs=None, text=""):
        self._attrs = attrs or {}
        self._text = text

    def get_attribute(self, name):
        return self._attrs.get(name)

    def inner_text(self, timeout=None):
        return self._text

    # support common selectors used by parsers
    def locator(self, selector):
        if selector == "a":
            return FakeLocator(self._attrs.get("_anchors", []))
        if selector == "abbr":
            return FakeLocator(self._attrs.get("_abbrs", []))
        if selector == "time":
            return FakeLocator(self._attrs.get("_times", []))
        if selector == "div[role='article']":
            return FakeLocator(self._attrs.get("_articles", []))
        return FakeLocator([])

class FakeLocator:
    def __init__(self, elements):
        self._elements = elements or []

    def count(self):
        return len(self._elements)

    def nth(self, i):
        return self._elements[i]

    @property
    def first(self):
        return self._elements[0] if self._elements else FakeElement()

    def locator(self, selector):
        if self._elements:
            return self._elements[0].locator(selector)
        return FakeLocator([])

class ParsersTest(unittest.TestCase):
    # extract_emails
    def test_single_email(self):
        s = "Contact: alice@example.com"
        res = extract_emails(s)
        self.assertEqual(len(res), 1)
        self.assertIn("alice@example.com", res)

    def test_multiple_emails_and_dedup(self):
        s = "a@x.com b@x.com a@x.com"
        res = extract_emails(s)
        self.assertCountEqual(res, ["a@x.com", "b@x.com"])

    def test_obfuscated_emails(self):
        s = "contact bob [at] example [dot] com and carol at foo dot org"
        res = extract_emails(s)
        self.assertIn("bob@example.com", res)
        self.assertIn("carol@foo.org", res)

    def test_unusual_allowed_characters(self):
        s = "odd: !#$%&'*+/=?^_`{|}~-user+tag@sub-domain.example.co.uk"
        res = extract_emails(s)
        self.assertIn("!#$%&'*+/=?^_`{|}~-user+tag@sub-domain.example.co.uk", res)

    def test_malformed_and_invalid(self):
        s = "bad: user@@example..com, just text, @notvalid"
        res = extract_emails(s)
        self.assertEqual(res, [])

    def test_empty_input(self):
        self.assertEqual(extract_emails(""), [])
        self.assertEqual(extract_emails(None), [])

    # extract_post_id
    def test_post_id_from_data_ft_json(self):
        node = FakeElement(attrs={"data-ft": '{"top_level_post_id":"1234567890","x":1}'})
        self.assertEqual(extract_post_id(node), "1234567890")

    def test_post_id_from_story_fbid(self):
        a = FakeElement(attrs={"href": "https://www.facebook.com/permalink.php?story_fbid=222333444&id=999"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_post_id(node), "222333444")

    def test_post_id_from_posts_path(self):
        a = FakeElement(attrs={"href": "https://web.facebook.com/user/posts/555666777"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_post_id(node), "555666777")

    def test_post_id_from_fbid(self):
        a = FakeElement(attrs={"href": "https://facebook.com/?fbid=888999000"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_post_id(node), "888999000")

    def test_post_id_from_element_attrs(self):
        node = FakeElement(attrs={"id": "post_1234567_data"})
        self.assertEqual(extract_post_id(node), "1234567")

    def test_post_id_missing(self):
        node = FakeElement(attrs={})
        self.assertEqual(extract_post_id(node), "")

    # author username / id / href
    def test_extract_author_username_basic(self):
        a = FakeElement(attrs={"href": "https://web.facebook.com/jane.doe"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_username(node), "jane.doe")

    def test_extract_author_username_skip_groups(self):
        a = FakeElement(attrs={"href": "https://web.facebook.com/groups/12345"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_username(node), "")

    def test_extract_author_id_from_profile_php(self):
        a = FakeElement(attrs={"href": "https://facebook.com/profile.php?id=424242"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_id(node), "424242")

    def test_extract_author_id_from_data_hovercard(self):
        a = FakeElement(attrs={"data-hovercard": "/ajax/hovercard/user.php?id=555666777&foo=1"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_id(node), "555666777")

    def test_extract_author_profile_href_normalize_relative(self):
        a = FakeElement(attrs={"href": "/john.smith"})
        node = FakeElement(attrs={"_anchors": [a]})
        href = extract_author_profile_href(node)
        self.assertTrue(href.startswith("https://web.facebook.com/"))
        self.assertIn("john.smith", href)

    def test_extract_author_profile_href_skip_watch(self):
        a = FakeElement(attrs={"href": "https://web.facebook.com/watch/?v=12345"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_profile_href(node), "")

    # extract_post_date
    def test_extract_post_date_from_abbr_utime(self):
        ab = FakeElement(attrs={"data-utime": "1609459200"})
        node = FakeElement(attrs={"_abbrs": [ab]})
        dt = extract_post_date(node)
        self.assertTrue(dt.endswith("Z"))
        self.assertIn("2021-01-01", dt)

    def test_extract_post_date_from_time_datetime(self):
        tm = FakeElement(attrs={"datetime": "2020-12-31T23:59:00+0000"})
        node = FakeElement(attrs={"_times": [tm]})
        dt = extract_post_date(node)
        self.assertIn("2020-12-31T23:59:00", dt)

    def test_extract_post_date_from_anchor_title(self):
        a = FakeElement(attrs={"title": "Posted 2 hrs ago"})
        node = FakeElement(attrs={"_anchors": [a]})
        dt = extract_post_date(node)
        self.assertIn("2 hrs", dt)

    def test_extract_post_date_missing(self):
        node = FakeElement(attrs={})
        self.assertEqual(extract_post_date(node), "")

if __name__ == "__main__":
    unittest.main()
# filepath: c:\Users\Administrator\Documents\DEV BOX\WEB SCRAPPER\tests\test_parsers.py
import os
import unittest
import importlib.util
from datetime import datetime

# load the wrapper module (no space in filename) so tests are stable
ROOT = os.path.dirname(os.path.dirname(__file__))
MODULE_PATH = os.path.join(ROOT, "web_scrapper.py")
_spec = importlib.util.spec_from_file_location("web_scraper_module", MODULE_PATH)
web_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(web_mod)

# functions under test (re-exported by wrapper)
extract_emails = web_mod.extract_emails
extract_post_id = web_mod.extract_post_id
extract_author_username = web_mod.extract_author_username
extract_author_id = web_mod.extract_author_id
extract_author_profile_href = web_mod.extract_author_profile_href
extract_post_date = web_mod.extract_post_date

# Minimal fake DOM / locator classes to simulate Playwright elements for parsers
class FakeElement:
    def __init__(self, attrs=None, text=""):
        self._attrs = attrs or {}
        self._text = text

    def get_attribute(self, name):
        return self._attrs.get(name)

    def inner_text(self, timeout=None):
        return self._text

    # support common selectors used by parsers
    def locator(self, selector):
        if selector == "a":
            return FakeLocator(self._attrs.get("_anchors", []))
        if selector == "abbr":
            return FakeLocator(self._attrs.get("_abbrs", []))
        if selector == "time":
            return FakeLocator(self._attrs.get("_times", []))
        if selector == "div[role='article']":
            return FakeLocator(self._attrs.get("_articles", []))
        return FakeLocator([])

class FakeLocator:
    def __init__(self, elements):
        self._elements = elements or []

    def count(self):
        return len(self._elements)

    def nth(self, i):
        return self._elements[i]

    @property
    def first(self):
        return self._elements[0] if self._elements else FakeElement()

    def locator(self, selector):
        if self._elements:
            return self._elements[0].locator(selector)
        return FakeLocator([])

class ParsersTest(unittest.TestCase):
    # extract_emails
    def test_single_email(self):
        s = "Contact: alice@example.com"
        res = extract_emails(s)
        self.assertEqual(len(res), 1)
        self.assertIn("alice@example.com", res)

    def test_multiple_emails_and_dedup(self):
        s = "a@x.com b@x.com a@x.com"
        res = extract_emails(s)
        self.assertCountEqual(res, ["a@x.com", "b@x.com"])

    def test_obfuscated_emails(self):
        s = "contact bob [at] example [dot] com and carol at foo dot org"
        res = extract_emails(s)
        self.assertIn("bob@example.com", res)
        self.assertIn("carol@foo.org", res)

    def test_unusual_allowed_characters(self):
        s = "odd: !#$%&'*+/=?^_`{|}~-user+tag@sub-domain.example.co.uk"
        res = extract_emails(s)
        self.assertIn("!#$%&'*+/=?^_`{|}~-user+tag@sub-domain.example.co.uk", res)

    def test_malformed_and_invalid(self):
        s = "bad: user@@example..com, just text, @notvalid"
        res = extract_emails(s)
        self.assertEqual(res, [])

    def test_empty_input(self):
        self.assertEqual(extract_emails(""), [])
        self.assertEqual(extract_emails(None), [])

    # extract_post_id
    def test_post_id_from_data_ft_json(self):
        node = FakeElement(attrs={"data-ft": '{"top_level_post_id":"1234567890","x":1}'})
        self.assertEqual(extract_post_id(node), "1234567890")

    def test_post_id_from_story_fbid(self):
        a = FakeElement(attrs={"href": "https://www.facebook.com/permalink.php?story_fbid=222333444&id=999"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_post_id(node), "222333444")

    def test_post_id_from_posts_path(self):
        a = FakeElement(attrs={"href": "https://web.facebook.com/user/posts/555666777"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_post_id(node), "555666777")

    def test_post_id_from_fbid(self):
        a = FakeElement(attrs={"href": "https://facebook.com/?fbid=888999000"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_post_id(node), "888999000")

    def test_post_id_from_element_attrs(self):
        node = FakeElement(attrs={"id": "post_1234567_data"})
        self.assertEqual(extract_post_id(node), "1234567")

    def test_post_id_missing(self):
        node = FakeElement(attrs={})
        self.assertEqual(extract_post_id(node), "")

    # author username / id / href
    def test_extract_author_username_basic(self):
        a = FakeElement(attrs={"href": "https://web.facebook.com/jane.doe"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_username(node), "jane.doe")

    def test_extract_author_username_skip_groups(self):
        a = FakeElement(attrs={"href": "https://web.facebook.com/groups/12345"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_username(node), "")

    def test_extract_author_id_from_profile_php(self):
        a = FakeElement(attrs={"href": "https://facebook.com/profile.php?id=424242"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_id(node), "424242")

    def test_extract_author_id_from_data_hovercard(self):
        a = FakeElement(attrs={"data-hovercard": "/ajax/hovercard/user.php?id=555666777&foo=1"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_id(node), "555666777")

    def test_extract_author_profile_href_normalize_relative(self):
        a = FakeElement(attrs={"href": "/john.smith"})
        node = FakeElement(attrs={"_anchors": [a]})
        href = extract_author_profile_href(node)
        self.assertTrue(href.startswith("https://web.facebook.com/"))
        self.assertIn("john.smith", href)

    def test_extract_author_profile_href_skip_watch(self):
        a = FakeElement(attrs={"href": "https://web.facebook.com/watch/?v=12345"})
        node = FakeElement(attrs={"_anchors": [a]})
        self.assertEqual(extract_author_profile_href(node), "")

    # extract_post_date
    def test_extract_post_date_from_abbr_utime(self):
        ab = FakeElement(attrs={"data-utime": "1609459200"})
        node = FakeElement(attrs={"_abbrs": [ab]})
        dt = extract_post_date(node)
        self.assertTrue(dt.endswith("Z"))
        self.assertIn("2021-01-01", dt)

    def test_extract_post_date_from_time_datetime(self):
        tm = FakeElement(attrs={"datetime": "2020-12-31T23:59:00+0000"})
        node = FakeElement(attrs={"_times": [tm]})
        dt = extract_post_date(node)
        self.assertIn("2020-12-31T23:59:00", dt)

    def test_extract_post_date_from_anchor_title(self):
        a = FakeElement(attrs={"title": "Posted 2 hrs ago"})
        node = FakeElement(attrs={"_anchors": [a]})
        dt = extract_post_date(node)
        self.assertIn("2 hrs", dt)

    def test_extract_post_date_missing(self):
        node = FakeElement(attrs={})
        self.assertEqual(extract_post_date(node), "")

if __name__ == "__main__":
    unittest.main()