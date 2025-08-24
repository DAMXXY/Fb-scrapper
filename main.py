from playwright.sync_api import sync_playwright

import csv

import os

import time

import re

Match any email

EMAIL_REGEX = r'[\w.-]+@[\w.-]+.\w+'

def get_safe_filename(base_name="emails", ext="csv"):

i = 0

while True:

    filename = f"{base_name}{'_' + str(i) if i else ''}.{ext}"

    if not os.path.exists(filename):

        return filename

    i += 1

def extract_emails(text):

return re.findall(EMAIL_REGEX, text)

def main():

filename = get_safe_filename()

with open(filename, "w", newline="", encoding="utf-8") as csv_file:

    writer = csv.writer(csv_file)

    writer.writerow(["Email", "Post Text"])



    with sync_playwright() as p:

        browser = p.chromium.launch(headless=False)

        context = browser.new_context()

        page = context.new_page()



        # Login manually

        page.goto("https://web.facebook.com/groups/618488976536093/search?q=%40gmail.com")

        print("\n[!] Login manually, navigate to the group, and search 'gmail.com'.")

        print("👉 When you're on the search results page and posts are visible, hit ENTER here to continue scraping.\n")

        input("[🟢] Ready? Press ENTER when the page is ready to scrape:")

        print("[*] Starting scraping...")



        scroll_count = 15

        for _ in range(scroll_count):

            try:

                # This selector works on Facebook group search results

                posts = page.locator("div[data-ad-preview='message']")

                count = posts.count()



                for i in range(count):

                    try:

                        post = posts.nth(i)

                        post.scroll_into_view_if_needed(timeout=10000)



                        # Expand caption

                        try:

                            see_more = post.locator("text=See more")

                            if see_more.is_visible():

                                see_more.click()

                                time.sleep(1)

                        except:

                            pass



                        text_content = post.inner_text(timeout=5000)

                        emails = extract_emails(text_content)



                        for email in emails:

                            writer.writerow([email, text_content])

                            print(f"[+] {email} added.")



                    except Exception as e:

                        print(f"Error processing post #{i}: {e}")



                # Scroll down

                page.mouse.wheel(0, 3000)

                time.sleep(3)



            except Exception as e:

                print(f"[X] Scrolling error: {e}")

                break



        print("[✔] Scraping finished.")

        browser.close()

if name == "main":

main()
