#!/usr/bin/env python3
"""
Crawl r/malaysia_scams using Playwright + old.reddit.com (HTML-based, no JS required).
Extracts post titles, content, phone numbers, bank accounts, WhatsApp links.
"""
import asyncio
import json
import re
import sys

async def crawl_reddit():
    from playwright.async_api import async_playwright
    
    results = []
    
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        
        # Use old.reddit.com which renders as plain HTML (no JS wall)
        print("Navigating to r/malaysia_scams (old.reddit)...")
        await page.goto("https://old.reddit.com/r/malaysia_scams/new/", timeout=60000)
        await page.wait_for_timeout(3000)
        
        # Extract all post links from the listing page
        posts = await page.evaluate("""
            () => {
                const results = [];
                const things = document.querySelectorAll('#siteTable .thing.link');
                things.forEach(thing => {
                    const titleEl = thing.querySelector('a.title');
                    const urlEl = thing.querySelector('a.comments');
                    if (titleEl) {
                        results.push({
                            title: titleEl.textContent.trim(),
                            post_url: titleEl.href,
                            comments_url: urlEl ? urlEl.href : '',
                        });
                    }
                });
                return results;
            }
        """)
        
        print(f"Found {len(posts)} posts on listing page")
        
        # Regex patterns for scam indicators
        phone_re = re.compile(r'(?:\+?6?01[0-9]\s*[-]?\s*[0-9]{3,4}\s*[-]?\s*[0-9]{4})', re.IGNORECASE)
        bank_re = re.compile(r'\b(\d{10,16})\b')
        wa_re = re.compile(r'(?:wa\.me/|whatsapp\.com/send\?phone=|wasap\.my/)(\d+)', re.IGNORECASE)
        url_re = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)
        
        posts_to_visit = posts[:25]
        print(f"\nVisiting {len(posts_to_visit)} posts...")
        
        for i, post in enumerate(posts_to_visit):
            url = post.get("post_url", "")
            title = post.get("title", "Unknown")
            
            # Skip external links (news articles) — we only want self-posts
            if url and "reddit.com" not in url:
                results.append({
                    "index": i + 1,
                    "title": title,
                    "url": url,
                    "is_self": False,
                    "phones": [],
                    "bank_accounts": [],
                    "whatsapp_links": [],
                    "content": "",
                })
                print(f"  [{i+1}/{len(posts_to_visit)}] {title[:60]}... (external)")
                continue
            
            # Visit the comments page instead (always reddit.com)
            comments_url = post.get("comments_url", "")
            if not comments_url:
                comments_url = url
            
            try:
                await page.goto(comments_url, timeout=30000)
                await page.wait_for_timeout(2000)
                
                # Extract the post body + comments
                content = await page.evaluate("""
                    () => {
                        const postBody = document.querySelector('.expando .md');
                        const bodyText = postBody ? postBody.innerText : '';
                        
                        const comments = document.querySelectorAll('.comment .md');
                        let commentText = '';
                        comments.forEach(c => {
                            commentText += c.innerText + '\\n';
                        });
                        
                        return { body: bodyText, comments: commentText };
                    }
                """) or {}
                
                full_text = f"{content.get('body', '')}\n{content.get('comments', '')}"
                
                # Extract entities
                phones = list(set(phone_re.findall(full_text)))
                banks = [b for b in list(set(bank_re.findall(full_text))) if len(b) >= 10]
                wa_links = list(set(wa_re.findall(full_text)))
                
                results.append({
                    "index": i + 1,
                    "title": title,
                    "url": comments_url,
                    "is_self": True,
                    "phones": phones[:5],
                    "bank_accounts": banks[:3],
                    "whatsapp_links": wa_links,
                    "content": full_text[:2000],
                })
                
                entity_str = ""
                if phones: entity_str += f" 📱{len(phones)}"
                if banks: entity_str += f" 🏦{len(banks)}"
                if wa_links: entity_str += f" 💬{len(wa_links)}"
                
                print(f"  [{i+1}/{len(posts_to_visit)}] {title[:55]}...{entity_str}")
                
            except Exception as e:
                print(f"  [{i+1}] Error: {e}")
                results.append({
                    "index": i + 1,
                    "title": title,
                    "url": comments_url,
                    "is_self": True,
                    "phones": [],
                    "bank_accounts": [],
                    "whatsapp_links": [],
                    "content": f"ERROR: {e}",
                })
        
        await browser.close()
    
    return results


if __name__ == "__main__":
    data = asyncio.run(crawl_reddit())
    
    output_path = "/home/mssbai/Desktop/fraud-mvp/data/reddit_malaysia_scams.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*50}")
    print(f"  CRAWL COMPLETE")
    print(f"{'='*50}")
    print(f"Posts scraped: {len(data)}")
    
    self_posts = [d for d in data if d.get('is_self')]
    total_phones = sum(len(p['phones']) for p in data)
    total_banks = sum(len(p['bank_accounts']) for p in data)
    total_wa = sum(len(p['whatsapp_links']) for p in data)
    
    print(f"Self-posts (with content): {len(self_posts)}")
    print(f"Phone numbers found: {total_phones}")
    print(f"Bank accounts found: {total_banks}")
    print(f"WhatsApp links found: {total_wa}")
    print(f"Data saved to: {output_path}")
    
    print(f"\n--- Posts with entities ---")
    for p in data:
        if p['phones'] or p['bank_accounts'] or p['whatsapp_links']:
            print(f"  [{p['index']}] {p['title'][:70]}")
            if p['phones']: print(f"      📱 Phones: {p['phones']}")
            if p['bank_accounts']: print(f"      🏦 Banks: {p['bank_accounts']}")
            if p['whatsapp_links']: print(f"      💬 WA: {p['whatsapp_links']}")