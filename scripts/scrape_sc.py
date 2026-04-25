#!/usr/bin/env python3
"""
Scrape SC Investor Alert List — Extract ALL entities from rendered HTML.
SC uses itemsPerPage: 2000, so all data is already in the page.
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_PATH = Path("/home/mssbai/Desktop/fraud-mvp/data/sc_investor_alert_list.json")


async def scrape_sc():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        print("Loading SC Investor Alert List...", flush=True)
        await page.goto("https://www.sc.com.my/investor-alert-list", wait_until="networkidle", timeout=90000)
        await page.wait_for_timeout(8000)

        # Click "All" tab if available to show all entities
        print("Looking for 'All' filter...", flush=True)
        try:
            all_btn = page.locator("text=All").first
            if await all_btn.is_visible(timeout=5000):
                await all_btn.click()
                print("  Clicked 'All' filter", flush=True)
                await page.wait_for_timeout(5000)
        except Exception:
            print("  No 'All' filter found", flush=True)

        # Scroll extensively to load all items
        print("Scrolling to load all items...", flush=True)
        prev_count = 0
        for i in range(30):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
            # Check if more items loaded
            count = await page.evaluate("""
                () => document.querySelectorAll('[class*="alert"], [class*="entity"], [class*="name"], [class*="card"]').length
            """)
            if count == prev_count and i > 5:
                break
            prev_count = count

        # Wait for rendering to complete
        await page.wait_for_timeout(5000)

        # Extract all text content from the investor alert section
        print("Extracting entities from rendered page...", flush=True)
        all_data = await page.evaluate("""
            () => {
                const results = [];
                
                // Method 1: Look for structured entity cards/items
                // SC uses specific card/list structures for each entity
                const selectors = [
                    '.x-component', '.x-panel', '.x-grid-row', '.x-dataview-item',
                    '[class*="alert-item"]', '[class*="entity-item"]',
                    '[class*="investor-alert"]', '[class*="unauthorised"]',
                    '.card', '.list-group-item',
                ];
                
                for (const sel of selectors) {
                    const items = document.querySelectorAll(sel);
                    if (items.length > 10) {
                        items.forEach(item => {
                            const text = item.innerText.trim();
                            if (text.length > 5) {
                                const links = [];
                                item.querySelectorAll('a').forEach(a => {
                                    if (a.href && a.href.includes('http')) {
                                        links.push({ text: a.textContent.trim(), href: a.href });
                                    }
                                });
                                results.push({
                                    raw_text: text.substring(0, 1000),
                                    links: links,
                                    source: sel
                                });
                            }
                        });
                        if (results.length > 10) break;
                    }
                }
                
                // Method 2: If structured extraction didn't work, get all visible text blocks
                if (results.length <= 10) {
                    // Get main content area
                    const main = document.querySelector('main, [role="main"], .content, .main-content, #content');
                    if (main) {
                        // Split by double newlines to get entity blocks
                        const blocks = main.innerText.split('\\n\\n').filter(b => b.trim().length > 10);
                        blocks.forEach(block => {
                            const links = [];
                            // Find links within the main content area
                            main.querySelectorAll('a').forEach(a => {
                                if (a.href && a.href.includes('http') && !a.href.includes('sc.com.my/investor-alert')) {
                                    links.push({ text: a.textContent.trim(), href: a.href });
                                }
                            });
                            results.push({
                                raw_text: block.trim().substring(0, 1000),
                                links: links.filter(l => block.includes(l.text)),
                                source: 'text_block'
                            });
                        });
                    }
                }
                
                return results;
            }
        """)

        print(f"  Method 1/2: {len(all_data)} items extracted", flush=True)

        # Method 3: Extract from the full inner text — most reliable for JS-rendered content
        # SC typically shows: number. Entity Name (type) - Website: url
        full_text = await page.evaluate("() => document.body.innerText")
        
        # Save full text for parsing
        Path("/home/mssbai/Desktop/fraud-mvp/data/sc_full_text.txt").write_text(full_text, encoding="utf-8")
        
        # Parse entity names from the full text
        # SC format: "Entity Name (Facebook page)" or "Entity Name (Website)" or just "Entity Name"
        # Also: "Potential clone entity – Company Name"
        
        # Find the investor alert section in the text
        alert_start = full_text.lower().find("investor alert list")
        if alert_start == -1:
            alert_start = full_text.lower().find("unauthorised")
        
        alert_text = full_text[alert_start:] if alert_start >= 0 else full_text

        # Extract entities using regex
        # Pattern 1: "Number. Entity Name (type) Website: url"
        # Pattern 2: "Entity Name (potential clone entity - Target)"
        # Pattern 3: Standalone company names
        
        entities = []
        
        # Look for numbered list items (SC uses: "1. Entity Name")
        numbered = re.findall(r'(?:^|\n)\s*(\d+)\.\s+(.+?)(?=\n\s*\d+\.|\n\n|\Z)', alert_text, re.DOTALL)
        for num, text in numbered:
            text = text.strip()
            if len(text) > 2 and not text.startswith(('Navigation', 'Home', 'Search', 'Filter', 'Sort', 'Page')):
                entities.append({"index": int(num), "raw_text": text})
        
        # If no numbered list, look for entity-like lines
        if not entities:
            # Try splitting by newlines and filtering
            lines = alert_text.split('\n')
            for line in lines:
                line = line.strip()
                # Skip short lines, navigation, UI elements
                if len(line) < 3:
                    continue
                if any(skip in line.lower() for skip in ['navigation', 'home', 'search', 'filter', 'page', 'copyright', 'facebook twitter', 'linkedin', 'instagram', 'youtube', 'wechat', 'scroll', 'back to top']):
                    continue
                # Entity lines typically contain company names, (Facebook), (Website), etc.
                if re.search(r'(?:Facebook|Telegram|WhatsApp|Website|App|clone entity|potential clone|unauthorised|investment)', line, re.IGNORECASE):
                    entities.append({"raw_text": line})
                elif re.match(r'^[A-Z][A-Za-z0-9\s&\-\.]+$', line) and len(line) > 3:
                    entities.append({"raw_text": line})

        await browser.close()

    return {
        "source": "Securities Commission Malaysia - Investor Alert List",
        "url": "https://www.sc.com.my/investor-alert-list",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "structured_items": len(all_data),
        "parsed_entities": len(entities),
        "data": entities if entities else all_data,
        "full_text_length": len(full_text),
    }


if __name__ == "__main__":
    result = asyncio.run(scrape_sc())

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"  SC Investor Alert List — Scrape Complete")
    print(f"{'='*60}")
    print(f"Structured items:  {result['structured_items']}")
    print(f"Parsed entities:    {result['parsed_entities']}")
    print(f"Full text length:   {result['full_text_length']} chars")
    print(f"Saved to:          {OUTPUT_PATH}")

    # Print first 10 entities
    print(f"\n--- First 10 entities ---")
    for e in result['data'][:10]:
        text = e.get('raw_text', e.get('text', str(e)))
        print(f"  {text[:120]}")