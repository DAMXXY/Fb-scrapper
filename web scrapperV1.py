from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import argparse, csv, os, re, sys, time, urllib.parse

DEFAULT_TIMEOUT = 10000

def extract_emails(text):
    if not text:
        return []
    local_part = r'(?:\"[^\"]+\"|[A-Za-z0-9!#$%&\'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&\'*+/=?^_`{|}~-]+)*)'
    domain_part = r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}'
    full_email_re = re.compile(rf'^{local_part}@{domain_part}$', flags=re.IGNORECASE)
    simple_re = re.compile(rf'{local_part}@{domain_part}', flags=re.IGNORECASE)

    emails = set()
    for m in simple_re.finditer(text):
        cand = m.group(0).strip()
        if full_email_re.match(cand):
            emails.add(cand.lower())

    # handle basic obfuscation like "user [at] domain [dot] com"
    obf = re.compile(r'([\w.+-]+)\s*(?:@|\[at\]|\(at\)|\s+at\s+)\s*([\w\-.]+\s*(?:\.|\[dot\]|\(dot\)|\s+dot\s+)\s*[\w\-.]+)+', flags=re.IGNORECASE)
    for m in obf.finditer(text):
        local = m.group(1).strip().strip('"')
        dom = m.group(2)
        dom = re.sub(r'(\s*(?:\[dot\]|\(dot\)|\s+dot\s+)\s*)', '.', dom, flags=re.IGNORECASE)
        dom = re.sub(r'\s+', '', dom)
        cand = f"{local}@{dom}"
        if full_email_re.match(cand):
            emails.add(cand.lower())

    return sorted(emails)

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

    outfn = "emails_basic.csv"
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
