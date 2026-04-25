#!/usr/bin/env python3
"""
Crawl r/malaysia for scam/fraud posts using Playwright with Firefox.
Logs in as real user for full content access.
Analyzes suitability as a FraudMVP source.
"""
import asyncio
import json
import re
import sys
import os

# Add project to path
sys.path.insert(0, "/home/mssbai/Desktop/fraud-mvp")

SESSION_PATH = "/home/mssbai/Desktop/fraud-mvp/data/reddit_session.json"
OUTPUT_PATH = "/home/mssbai/Desktop/fraud-mvp/data/reddit_malaysia_scams.json"

# Scam search keywords for r/malaysia
SEARCH_QUERIES = [
    "scam",
    "penipu",
    "tipu",
    "fraud",
    "macau scam",
    "phishing",
    "ah long",
]

async def login_reddit(page):
    """Login to Reddit using email/password. Save session for reuse."""
    print("Logging into Reddit...")
    await page.goto("https://www.reddit.com/login/", timeout=60000)
    await page.wait_for_timeout(3000)
    
    # Fill login form
    username_input = page.locator('input[name="username"], input#loginUsername, input[type="text"]').first
    password_input = page.locator('input[name="password"], input#loginPassword, input[type="password"]').first
    
    await username_input.fill("themupkin@gmail.com")
    await password_input.fill("Bro99Peace")
    
    # Click login button
    login_btn = page.locator('button[type="submit"], button:has-text("Log In"), button:has-text("Sign in")').first
    await login_btn.click()
    
    # Wait for redirect after login
    await page.wait_for_timeout(8000)
    
    # Check if we're logged in
    current_url = page.url
    print(f"Post-login URL: {current_url}")
    
    # Save storage state for session persistence
    context = page.context
    await context.storage_state(path=SESSION_PATH)
    print(f"Session saved to {SESSION_PATH}")
    
    return True


async def search_and_extract(page, query, limit=15):
    """Search r/malaysia for a specific keyword and extract posts."""
    results = []
    
    search_url = f"https://www.reddit.com/r/malaysia/search/?q={query}&sort=new&restrict_sr=on&t=year"
    print(f"  Searching: '{query}'...")
    await page.goto(search_url, timeout=60000)
    await page.wait_for_timeout(5000)
    
    # Scroll to load more results
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, 1500)")
        await page.wait_for_timeout(2000)
    
    # Extract post links
    posts = await page.evaluate("""
        () => {
            const results = [];
            // Try multiple selectors for search results
            const selectors = [
                'a[href*="/r/malaysia/comments/"]',
                'div[data-testid="post-container"] a',
                'a[href^="https://www.reddit.com/r/malaysia/comments/"]',
                'search-telemetry-tracker a',
            ];
            
            const seen = new Set();
            for (const sel of selectors) {
                const elements = document.querySelectorAll(sel);
                elements.forEach(el => {
                    const href = el.href || el.getAttribute('href') || '';
                    const title = el.textContent?.trim() || '';
                    if (href.includes('/comments/') && !seen.has(href) && title.length > 5) {
                        seen.add(href);
                        results.push({ title: title.substring(0, 200), url: href });
                    }
                });
            }
            return results;
        }
    """)
    
    # If no posts found via JS, extract from HTML
    if not posts:
        content = await page.content()
        post_pattern = re.compile(r'href="(https://www\.reddit\.com/r/malaysia/comments/[^"]+)"', re.IGNORECASE)
        raw_links = list(set(post_pattern.findall(content)))[:limit]
        for link in raw_links:
            posts.append({"title": "Unknown", "url": link})
    
    # Visit each post to extract content
    phone_re = re.compile(r'(?:\+?6?01[0-9]\s*[-]?\s*[0-9]{3,4}\s*[-]?\s*[0-9]{4})', re.IGNORECASE)
    bank_re = re.compile(r'\b(\d{10,16})\b')
    wa_re = re.compile(r'(?:wa\.me/|whatsapp\.com/send\?phone=|wasap\.my/)(\d+)', re.IGNORECASE)
    url_re = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)
    
    posts_to_visit = posts[:limit]
    
    for i, post in enumerate(posts_to_visit):
        url = post.get("url", "")
        title = post.get("title", "Unknown")
        
        if not url:
            continue
            
        # Normalize URL to old.reddit.com for easier scraping
        old_url = url.replace("www.reddit.com", "old.reddit.com")
        
        try:
            await page.goto(old_url, timeout=30000)
            await page.wait_for_timeout(2000)
            
            # Extract post body + top comments
            content = await page.evaluate("""
                () => {
                    const postBody = document.querySelector('.expando .md');
                    const bodyText = postBody ? postBody.innerText : '';
                    
                    const comments = document.querySelectorAll('.comment .md');
                    let commentTexts = [];
                    comments.forEach((c, i) => {
                        if (i < 10) commentTexts.push(c.innerText);
                    });
                    
                    return { body: bodyText, comments: commentTexts.join('\\n') };
                }
            """) or {}
            
            full_text = f"{content.get('body', '')}\n{content.get('comments', '')}"
            
            # Also get the title from the page
            page_title = await page.evaluate("""
                () => {
                    const t = document.querySelector('a.title');
                    return t ? t.textContent.trim() : document.title;
                }
            """) or title
            
            # Extract entities
            phones = list(set(phone_re.findall(full_text)))
            banks = [b for b in list(set(bank_re.findall(full_text))) if len(b) >= 10]
            wa_links = list(set(wa_re.findall(full_text)))
            urls_found = [u for u in url_re.findall(full_text) if 'reddit.com' not in u and 'wikipedia.org' not in u]
            
            results.append({
                "search_query": query,
                "title": page_title[:150],
                "url": url,
                "phones": phones[:5],
                "bank_accounts": banks[:3],
                "whatsapp_links": wa_links,
                "urls_found": urls_found[:5],
                "content_preview": full_text[:1000],
                "content_length": len(full_text),
            })
            
            entity_str = ""
            if phones: entity_str += f" 📱{len(phones)}"
            if banks: entity_str += f" 🏦{len(banks)}"
            if wa_links: entity_str += f" 💬{len(wa_links)}"
            if urls_found: entity_str += f" 🔗{len(urls_found)}"
            
            print(f"    [{i+1}/{len(posts_to_visit)}] {page_title[:50]}...{entity_str}")
            
        except Exception as e:
            print(f"    [{i+1}] Error: {str(e)[:80]}")
            continue
    
    return results


async def main():
    from playwright.async_api import async_playwright
    
    all_results = []
    
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        
        # Try to load existing session first
        context = None
        if os.path.exists(SESSION_PATH):
            print(f"Loading saved session from {SESSION_PATH}...")
            try:
                context = await browser.new_context(storage_state=SESSION_PATH)
            except Exception as e:
                print(f"Session load failed: {e}")
                context = None
        
        if not context:
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
        
        page = await context.new_page()
        
        # Check if logged in
        await page.goto("https://www.reddit.com/r/malaysia/", timeout=60000)
        await page.wait_for_timeout(3000)
        
        logged_in = await page.evaluate("""
            () => {
                // Check for user menu / logged-in indicators
                const userMenu = document.querySelector('[data-testid="user-dropdown"], .HeaderProfile');
                const loginLink = document.querySelector('a[href*="/login"]');
                return !!userMenu || !loginLink;
            }
        """)
        
        if not logged_in:
            print("Not logged in — authenticating...")
            await login_reddit(page)
        else:
            print("Already logged in (session restored)")
        
        # Search for scam-related posts
        print(f"\n{'='*50}")
        print(f"  CRAWLING r/malaysia for scam content")
        print(f"{'='*50}\n")
        
        for query in SEARCH_QUERIES:
            results = await search_and_extract(page, query, limit=10)
            all_results.extend(results)
            print(f"  → {len(results)} posts extracted for '{query}'\n")
        
        # Deduplicate by URL
        seen_urls = set()
        unique_results = []
        for r in all_results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                unique_results.append(r)
        
        await browser.close()
    
    # Save results
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(unique_results, f, ensure_ascii=False, indent=2)
    
    # Analysis summary
    total_phones = sum(len(r['phones']) for r in unique_results)
    total_banks = sum(len(r['bank_accounts']) for r in unique_results)
    total_wa = sum(len(r['whatsapp_links']) for r in unique_results)
    total_urls = sum(len(r['urls_found']) for r in unique_results)
    posts_with_entities = sum(1 for r in unique_results if r['phones'] or r['bank_accounts'] or r['whatsapp_links'])
    posts_with_content = sum(1 for r in unique_results if r.get('content_length', 0) > 50)
    
    print(f"\n{'='*50}")
    print(f"  CRAWL COMPLETE — r/malaysia")
    print(f"{'='*50}")
    print(f"Total posts scraped:    {len(unique_results)}")
    print(f"Posts with content:     {posts_with_content}")
    print(f"Posts with entities:    {posts_with_entities}")
    print(f"Phone numbers found:    {total_phones}")
    print(f"Bank accounts found:    {total_banks}")
    print(f"WhatsApp links found:   {total_wa}")
    print(f"Suspicious URLs found:  {total_urls}")
    print(f"Data saved to: {OUTPUT_PATH}")
    
    # Suitability analysis
    print(f"\n{'='*50}")
    print(f"  SOURCE SUITABILITY ANALYSIS")
    print(f"{'='*50}")
    
    entity_rate = posts_with_entities / max(len(unique_results), 1) * 100
    content_rate = posts_with_content / max(len(unique_results), 1) * 100
    
    print(f"Entity extraction rate: {entity_rate:.1f}%")
    print(f"Content availability:   {content_rate:.1f}%")
    
    if entity_rate >= 20:
        verdict = "HIGH — Rich source of actionable scam data"
    elif entity_rate >= 5:
        verdict = "MEDIUM — Useful for scam type intelligence, limited raw entities"
    else:
        verdict = "LOW — Mostly discussion, few extractable entities"
    
    print(f"\nVerdict: {verdict}")
    
    # Print posts with entities
    print(f"\n--- Posts with extractable entities ---")
    for r in unique_results:
        if r['phones'] or r['bank_accounts'] or r['whatsapp_links']:
            print(f"  📌 {r['title'][:70]}")
            if r['phones']: print(f"     📱 Phones: {r['phones']}")
            if r['bank_accounts']: print(f"     🏦 Banks: {r['bank_accounts']}")
            if r['whatsapp_links']: print(f"     💬 WA: {r['whatsapp_links']}")
            if r['urls_found']: print(f"     🔗 URLs: {r['urls_found'][:3]}")


if __name__ == "__main__":
    asyncio.run(main())