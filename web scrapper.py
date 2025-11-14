from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import argparse, csv, os, re, sys, time, urllib.parse

DEFAULT_TIMEOUT = 30000  # milliseconds

def get_non_colliding_filename(base_name, directory=None):
    """
    Return a filename in `directory` that does not collide with existing files.
    Examples:
      emails.csv -> emails.csv (if not exists)
      emails.csv -> emails_1.csv, emails_2.csv, ...
    """
    if directory is None:
        directory = os.path.dirname(os.path.abspath(__file__)) or os.getcwd()
    base, ext = os.path.splitext(base_name)
    candidate = os.path.join(directory, base + ext)
    if not os.path.exists(candidate):
        return candidate
    i = 1
    while True:
        candidate = os.path.join(directory, f"{base}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1

def extract_emails(text):
    """
    Extract a wide range of email forms from free text:
    - standard emails (user+tag@sub.domain.tld)
    - quoted local parts
    - common obfuscations: user[at]domain[dot]com, user(at)domain(dot)com, user at domain dot com
    - variants with extra punctuation / HTML entities / zero-width spaces

    Strategy:
    - Normalize text (HTML-unescape, remove zero-width spaces).
    - First collect obvious candidates via a liberal regex.
    - Collect obfuscated candidates via dedicated patterns.
    - Normalize candidate strings (replace dot/at tokens) and strip surrounding punctuation.
    - Validate each candidate against a stricter validation regex before returning.
    """
    if not text:
        return []

    import html as _html

    # normalize common nuisances
    s = _html.unescape(text)
    s = s.replace('\u200b', '')  # remove zero-width spaces
    s = s.replace('\u00A0', ' ')  # non-breaking spaces -> space

    # validator: reasonably strict but practical (allows + addressing, quoted local parts)
    strict_re = re.compile(
        r'^(?:"[^"]+"|[A-Za-z0-9!#$%&\'*+/=?^_`{|}~\.-]{1,64})@'
        r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+'
        r'[A-Za-z]{2,63}$',
        flags=re.IGNORECASE
    )

    # liberal finder for typical emails (captures many candidates, cleaned later)
    liberal_re = re.compile(r'(?:"[^"]+"|[A-Za-z0-9!#$%&\'*+/=?^_`{|}~\.-]{1,64})@[\w\.-]{3,255}', flags=re.IGNORECASE)

    # obfuscated patterns (user [at] domain [dot] com, user(at)domain(dot)com, user at domain dot com)
    obf_re = re.compile(
        r'(?P<local>["\w.+%&\'*+/=\-]{1,64})\s*(?:@|\[at\]|\(at\)|\s+at\s+|\sat\s)\s*'
        r'(?P<dom>[\w\-.]+(?:\s*(?:\.|\[dot\]|\(dot\)|\s+dot\s+|\sdot\s+)\s*[\w\-.]+)+)',
        flags=re.IGNORECASE
    )

    candidates = set()

    # 1) direct liberal matches
    for m in liberal_re.finditer(s):
        cand = m.group(0)
        # strip surrounding punctuation
        cand = cand.strip(" \t\n\r\f\v<>\"'()[]{}:,;")
        candidates.add(cand)

    # 2) obfuscated matches -> normalize dot tokens
    for m in obf_re.finditer(s):
        local = m.group("local").strip('"')
        dom_raw = m.group("dom")
        dom = re.sub(r'(\s*(?:\[dot\]|\(dot\)|\s+dot\s+|\sdot\s+)\s*)', '.', dom_raw, flags=re.IGNORECASE)
        dom = re.sub(r'\s+', '', dom)
        cand = f"{local}@{dom}"
        candidates.add(cand)

    # 3) loose-word forms like "name at domain dot com" where local and domain are simple tokens
    # limit to short sequences to avoid false positives
    word_at_re = re.compile(r'\b([A-Za-z0-9.+%&\'*+/=\-]{1,64})\s+at\s+([A-Za-z0-9\-]{1,63}(?:\s+dot\s+[A-Za-z0-9\-]{1,63}){1,4})\b', flags=re.IGNORECASE)
    for m in word_at_re.finditer(s):
        local = m.group(1)
        dom_raw = m.group(2)
        dom = re.sub(r'\s+dot\s+', '.', dom_raw, flags=re.IGNORECASE)
        cand = f"{local}@{dom}"
        candidates.add(cand)

    # normalize candidates and validate
    cleaned = set()
    for cand in candidates:
        if not cand or len(cand) > 320:
            continue
        # remove surrounding angle brackets, punctuation
        cand = cand.strip(" \t\n\r\f\v<>\"'()[]{};,:")
        # replace common tokens inside candidate if present
        cand = re.sub(r'\[dot\]|\(dot\)|\s+dot\s+|\sdot\s+', '.', cand, flags=re.IGNORECASE)
        cand = re.sub(r'\[at\]|\(at\)|\s+at\s+|\sat\s', '@', cand, flags=re.IGNORECASE)
        # remove accidental trailing punctuation
        cand = cand.rstrip('.,;:')
        # collapse multiple dots
        cand = re.sub(r'\.{2,}', '.', cand)
        # lowercase domain part for consistency (keep local-case as-is but we'll lower entire string)
        cand = cand.strip()
        cand_l = cand.lower()
        # final validation with strict_re
        if strict_re.match(cand_l):
            cleaned.add(cand_l)

    # return deterministic sorted list
    return sorted(cleaned)

def get_first_post_link(post):
    try:
        anchors = post.locator("a")
        for i in range(anchors.count()):
            try:
                href = anchors.nth(i).get_attribute("href")
            except Exception:
                href = None
            if not href:
                continue
            href = href.split('?')[0]
            if href.startswith("/"):
                href = "https://web.facebook.com" + href
            if "facebook.com" in href:
                return href
    except Exception:
        pass
    return ""

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start-url", default="https://web.facebook.com/groups/618488976536093/search?q=%40gmail.com")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--edge-profile", default="", help="optional path to Edge user data dir to reuse login")
    p.add_argument("--max-per-file", type=int, default=1000, help="max emails per CSV file before rotating")
    args = p.parse_args()

    # choose a non-colliding filename in the script folder
    base_dir = os.path.dirname(os.path.abspath(__file__)) or os.getcwd()
    outfn = get_non_colliding_filename("emails_basic.csv", directory=base_dir)
    seen = set()

    with sync_playwright() as pw:
        browser_ctx = None
        using_persistent = False
        try:
            # Prefer Edge persistent profile. If --edge-profile omitted, try common Edge path.
            edge_default = os.path.expanduser(r"C:\Users\Administrator\AppData\Local\Microsoft\Edge\User Data")
            profile_path = args.edge_profile or (edge_default if os.path.exists(edge_default) else "")

            if profile_path:
                print(f"[*] Launching Edge persistent context using profile: {profile_path}")
                browser_ctx = pw.chromium.launch_persistent_context(user_data_dir=profile_path,
                                                                    headless=args.headless,
                                                                    channel="msedge")
                using_persistent = True
                pages = getattr(browser_ctx, "pages", []) or []
                page = pages[0] if pages else browser_ctx.new_page()
            else:
                print("[*] No Edge profile found/provided — launching ephemeral Chromium context")
                browser = pw.chromium.launch(headless=args.headless, channel="msedge")
                browser_ctx = browser.new_context()
                page = browser_ctx.new_page()
        except Exception as e:
            print("Failed to launch browser/context:", e)
            return

        try:
            page.goto(args.start_url, timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
        except Exception:
            pass

        if sys.stdin.isatty():
            print("[!] If not logged in, log in on the opened browser and then press ENTER here.")
            try:
                input("[🟢] Ready? Press ENTER to start extraction:")
            except Exception:
                pass
        else:
            time.sleep(2)

        # wait for posts
        try:
            page.wait_for_selector("div[data-ad-preview='message'], article", timeout=DEFAULT_TIMEOUT)
        except Exception:
            pass

        posts_selector = "div[data-ad-preview='message'], article"
        posts = page.locator(posts_selector)
        total = 0
        # prepare rotating output files
        file_prefix = os.path.splitext(outfn)[0]  # "emails_basic"
        max_per_file = int(args.max_per_file or 1000)
        file_index = 1
        file_count_in_file = 0

        def open_new_file(idx):
            fn = f"{file_prefix}_{idx}.csv"
            fobj = open(fn, "w", newline="", encoding="utf-8")
            w = csv.writer(fobj)
            w.writerow(["Email", "Source", "PostLink"])
            print(f"[*] Writing to {fn}")
            return fobj, w, fn

        fobj, writer, current_fn = open_new_file(file_index)

        last_index = 0
        scroll_attempts = 0
        max_scrolls = 200
        no_new_rounds = 0

        print("[*] Scanning posts and scrolling to load more. Press Ctrl+C to stop.")
        while scroll_attempts < max_scrolls:
            try:
                # refresh locator and count
                posts = page.locator(posts_selector)
                try:
                    count = posts.count()
                except Exception:
                    count = 0

                if count <= last_index:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0

                # prepare new_found flag for this iteration
                new_found = False

                # debug: show progress each iteration (shows before processing new posts)
                print(f"[*] progress: total_posts={count} scanned_until={last_index} no_new_rounds={no_new_rounds} scroll_attempts={scroll_attempts}")

                for i in range(last_index, count):
                    try:
                        post = posts.nth(i)
                        # attempt to expand caption "See more" inside the post up to a few times
                        for _ in range(4):
                            try:
                                btns = post.locator("text=/see more/i")
                                if btns.count():
                                    try:
                                        btns.first.click()
                                        page.wait_for_timeout(400)  # allow UI to expand
                                    except Exception:
                                        break
                                else:
                                    break
                            except Exception:
                                break

                        # retrieve visible caption/text
                        try:
                            text = post.inner_text(timeout=2500) or ""
                        except Exception:
                            text = ""

                        emails = extract_emails(text)
                        link = get_first_post_link(post)
                        for e in emails:
                            if e in seen:
                                continue
                            # rotate file if needed
                            if file_count_in_file >= max_per_file:
                                try:
                                    fobj.close()
                                except Exception:
                                    pass
                                file_index += 1
                                fobj, writer, current_fn = open_new_file(file_index)
                                file_count_in_file = 0
                            seen.add(e)
                            writer.writerow([e, "post", link])
                            file_count_in_file += 1
                            total += 1
                            new_found = True
                            print(f"[+] {e} -> {link} (saved to {current_fn})")
                    except Exception:
                        continue

                last_index = max(last_index, count)

                # if we found new emails recently, reset scroll attempts heuristic
                if new_found:
                    scroll_attempts = 0

                # stop when we've had a few rounds with nothing new and we've scrolled enough
                if no_new_rounds >= 5:
                    # perform a scroll to try load more
                    try:
                        page.mouse.wheel(0, 3000)
                    except Exception:
                        try:
                            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                        except Exception:
                            pass
                    time.sleep(1.0)
                    scroll_attempts += 1
                    # be much more patient; allow more scroll attempts before stopping
                    if scroll_attempts >= 60:
                        break
                else:
                    # small pause to allow lazy-load
                    time.sleep(0.6)

            except KeyboardInterrupt:
                print("[!] Interrupted by user.")
                break
            except Exception:
                # best-effort continue
                try:
                    page.mouse.wheel(0, 2000)
                except Exception:
                    pass
                time.sleep(0.8)
                continue

        # end while
        print(f"[*] Found {len(seen)} unique emails so far.")
        print(f"[*] Extraction complete. {total} unique emails saved across {file_index} file(s).")
        try:
            fobj.close()
        except Exception:
            pass

        try:
            if using_persistent:
                print("[*] Persistent context left open for your session.")
            else:
                page.close()
                browser_ctx.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
