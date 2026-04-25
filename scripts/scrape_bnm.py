#!/usr/bin/env python3
"""
Scrape BNM FCA List — Minimal, targeted approach.
Waits specifically for the table element, then extracts data.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_PATH = Path("/home/mssbai/Desktop/fraud-mvp/data/bnm_consumer_alert_list.json")


async def scrape_bnm():
    from playwright.async_api import async_playwright

    all_records = []

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        print("Loading BNM FCA List...", flush=True)
        
        # Use wait_until="networkidle" for JS-heavy page
        await page.goto(
            "https://www.bnm.gov.my/financial-consumer-alert-list",
            wait_until="networkidle",
            timeout=90000
        )
        
        # Wait for table to appear
        print("Waiting for table to render...", flush=True)
        try:
            await page.wait_for_selector("table", timeout=30000)
            print("Table found!", flush=True)
        except Exception:
            print("Table not found, trying page content...", flush=True)
            content = await page.content()
            Path("/home/mssbai/Desktop/fraud-mvp/data/bnm_debug.html").write_text(content)
            print(f"Page content saved to bnm_debug.html ({len(content)} chars)", flush=True)

        # Click "All" filter if available
        try:
            all_link = page.get_by_text("All").first
            await all_link.click(timeout=5000)
            print("Clicked 'All' filter", flush=True)
            await page.wait_for_timeout(5000)
        except Exception:
            print("No 'All' filter found, proceeding with default view", flush=True)

        # Scroll to load lazy content
        for _ in range(15):
            await page.evaluate("window.scrollBy(0, 500)")
            await page.wait_for_timeout(500)

        # Scroll back to top
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(2000)

        # Extract all table data
        print("Extracting table data...", flush=True)
        records = await page.evaluate("""
            () => {
                const results = [];
                const tables = document.querySelectorAll('table');
                for (const table of tables) {
                    const headers = [];
                    const ths = table.querySelectorAll('thead th, tr:first-child th');
                    ths.forEach(th => headers.push(th.textContent.trim()));
                    
                    const rows = table.querySelectorAll('tbody tr, tr:not(:first-child)');
                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (cells.length === 0) continue;
                        
                        const row_data = {};
                        cells.forEach((cell, i) => {
                            const key = headers[i] || `col_${i}`;
                            const link = cell.querySelector('a');
                            row_data[key] = {
                                text: cell.textContent.trim(),
                                href: link ? link.href : null
                            };
                        });
                        if (Object.keys(row_data).length > 0) {
                            results.push(row_data);
                        }
                    }
                }
                return results;
            }
        """)
        
        print(f"Extracted {len(records)} records from current view", flush=True)
        all_records.extend(records)

        # Try pagination — click Next until no more
        page_count = 1
        while page_count < 100:  # Safety limit
            try:
                next_btns = page.locator('a.next, li.next a, .pagination .next a, a[aria-label="Next"], a[rel="next"]')
                count = await next_btns.count()
                if count == 0:
                    break
                
                next_btn = next_btns.first
                is_visible = await next_btn.is_visible()
                if not is_visible:
                    break
                
                # Check if disabled
                is_disabled = await next_btn.evaluate("""
                    el => el.classList.contains('disabled') || 
                          el.getAttribute('aria-disabled') === 'true' || 
                          el.parentElement.classList.contains('disabled') ||
                          el.classList.contains('paginate_button_disabled')
                """)
                if is_disabled:
                    break
                
                await next_btn.click()
                page_count += 1
                await page.wait_for_timeout(3000)
                
                # Extract records from new page
                new_records = await page.evaluate("""
                    () => {
                        const results = [];
                        const tables = document.querySelectorAll('table');
                        for (const table of tables) {
                            const headers = [];
                            const ths = table.querySelectorAll('thead th, tr:first-child th');
                            ths.forEach(th => headers.push(th.textContent.trim()));
                            const rows = table.querySelectorAll('tbody tr, tr:not(:first-child)');
                            for (const row of rows) {
                                const cells = row.querySelectorAll('td');
                                if (cells.length === 0) continue;
                                const row_data = {};
                                cells.forEach((cell, i) => {
                                    const key = headers[i] || `col_${i}`;
                                    const link = cell.querySelector('a');
                                    row_data[key] = {
                                        text: cell.textContent.trim(),
                                        href: link ? link.href : null
                                    };
                                });
                                if (Object.keys(row_data).length > 0) results.push(row_data);
                            }
                        }
                        return results;
                    }
                """)
                
                print(f"  Page {page_count}: {len(new_records)} records", flush=True)
                all_records.extend(new_records)
                
            except Exception as e:
                print(f"  Pagination ended: {e}", flush=True)
                break

        # Save page content for debugging
        content = await page.content()
        Path("/home/mssbai/Desktop/fraud-mvp/data/bnm_debug.html").write_text(content)
        
        await browser.close()

    # Deduplicate records
    seen = set()
    unique_records = []
    for r in all_records:
        key = json.dumps(r, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            unique_records.append(r)

    return {
        "source": "Bank Negara Malaysia - Financial Consumer Alert List",
        "url": "https://www.bnm.gov.my/financial-consumer-alert-list",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(unique_records),
        "pages_scraped": page_count,
        "data": unique_records,
    }


if __name__ == "__main__":
    result = asyncio.run(scrape_bnm())

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"  BNM FCA List — Scrape Complete")
    print(f"{'='*60}")
    print(f"Total records:   {result['total_records']}")
    print(f"Pages scraped:    {result['pages_scraped']}")
    print(f"Saved to:         {OUTPUT_PATH}")

    # Entity type breakdown
    entity_types = {}
    for r in result['data']:
        name_dict = list(r.values())[0] if r else {}
        name = name_dict.get('text', 'Unknown') if isinstance(name_dict, dict) else str(name_dict)
        if "(Facebook" in name:
            entity_types["Facebook"] = entity_types.get("Facebook", 0) + 1
        elif "WhatsApp" in name or "Whatsapp" in name:
            entity_types["WhatsApp"] = entity_types.get("WhatsApp", 0) + 1
        elif "(Telegram" in name:
            entity_types["Telegram"] = entity_types.get("Telegram", 0) + 1
        elif "(potential clone entity)" in name:
            entity_types["Clone Entity"] = entity_types.get("Clone Entity", 0) + 1
        elif "(Website)" in name:
            entity_types["Website"] = entity_types.get("Website", 0) + 1
        elif "(App)" in name:
            entity_types["App"] = entity_types.get("App", 0) + 1
        else:
            entity_types["Company/Other"] = entity_types.get("Company/Other", 0) + 1

    print(f"\nEntity type breakdown:")
    for etype, count in sorted(entity_types.items(), key=lambda x: x[1], reverse=True):
        print(f"  {etype}: {count}")

    print(f"\n--- First 10 records ---")
    for r in result['data'][:10]:
        print(json.dumps(r, indent=2, ensure_ascii=False)[:200])
        print()