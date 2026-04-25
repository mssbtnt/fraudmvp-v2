#!/usr/bin/env python3
"""
Scrape SC Investor Alert List — ExtJS-aware extraction.
Uses Playwright to wait for full rendering, then extracts grid data.
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
        await page.goto("https://www.sc.com.my/investor-alert-list", wait_until="networkidle", timeout=120000)
        await page.wait_for_timeout(10000)

        # Wait for the grid to render
        print("Waiting for grid to render...", flush=True)
        try:
            await page.wait_for_selector("td.x-grid-cell", timeout=30000)
            print("Grid cells found!", flush=True)
        except Exception:
            print("Grid cells not found, trying alternate selectors...", flush=True)

        # Try clicking "All" to show all items
        try:
            # ExtJS paging toolbar usually has a "All" or refresh button
            all_btn = page.locator("text=All").first
            await all_btn.click(timeout=3000)
            print("Clicked 'All'", flush=True)
            await page.wait_for_timeout(5000)
        except Exception:
            pass

        # Scroll down multiple times to trigger lazy rendering
        print("Scrolling to load all data...", flush=True)
        for _ in range(20):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)

        # Now extract data using the ExtJS grid structure
        print("Extracting grid data...", flush=True)
        records = await page.evaluate("""
            () => {
                const results = [];
                
                // Method 1: ExtJS grid cells
                const cells = document.querySelectorAll('td.x-grid-cell');
                if (cells.length > 10) {
                    // Group cells by row
                    const rows = new Map();
                    cells.forEach(cell => {
                        const row = cell.closest('tr') || cell.parentElement.closest('tr');
                        const rowId = row ? row.getAttribute('data-recordid') || row.getAttribute('id') || Math.random() : 'unknown';
                        if (!rows.has(rowId)) {
                            rows.set(rowId, []);
                        }
                        const text = cell.textContent.trim();
                        const link = cell.querySelector('a');
                        const href = link ? link.href : null;
                        rows.get(rowId).push({ text, href });
                    });
                    
                    rows.forEach((cells, rowId) => {
                        if (cells.length > 0 && cells.some(c => c.text.length > 2)) {
                            const entry = {};
                            cells.forEach((c, i) => {
                                entry[`col_${i}`] = { text: c.text, href: c.href };
                            });
                            results.push(entry);
                        }
                    });
                }
                
                // Method 2: If grid cells failed, use dataview items
                if (results.length === 0) {
                    const items = document.querySelectorAll('.x-dataview-item, .x-component[data-recordid]');
                    items.forEach(item => {
                        const text = item.textContent.trim();
                        if (text.length > 5) {
                            const links = [];
                            item.querySelectorAll('a').forEach(a => {
                                if (a.href) links.push({ text: a.textContent.trim(), href: a.href });
                            });
                            results.push({ raw_text: text, links: links });
                        }
                    });
                }
                
                // Method 3: If still nothing, extract from the main content area
                if (results.length === 0) {
                    // Get all text content from the grid body
                    const gridBody = document.querySelector('.x-grid-body, .x-panel-body, .x-container');
                    if (gridBody) {
                        const text = gridBody.innerText;
                        return { type: 'raw_text', data: text, count: 0 };
                    }
                }
                
                return { type: 'structured', data: results, count: results.length };
            }
        """)

        # If we got raw text, we'll need to parse it differently
        if isinstance(records, dict) and records.get('type') == 'raw_text':
            raw_text = records['data']
            print(f"Got raw text: {len(raw_text)} chars", flush=True)
            Path("/home/mssbai/Desktop/fraud-mvp/data/sc_grid_text.txt").write_text(raw_text, encoding="utf-8")
            records = []
        elif isinstance(records, dict) and records.get('type') == 'structured':
            records = records['data']
            print(f"Got {len(records)} structured records from grid", flush=True)
        elif isinstance(records, list):
            print(f"Got {len(records)} records from grid", flush=True)

        # Get total record count if available
        total_count = await page.evaluate("""
            () => {
                // ExtJS displays total count in toolbar
                const displayEl = document.querySelector('.x-toolbar-item.x-toolbar-text, .x-toolbar .x-toolbar-text');
                if (displayEl) return displayEl.textContent.trim();
                // Or in a counter
                const counter = document.querySelector('[class*="total"], [class*="count"]');
                if (counter) return counter.textContent.trim();
                return null;
            }
        """)
        print(f"Total count display: {total_count}", flush=True)

        await browser.close()

    return records


if __name__ == "__main__":
    records = asyncio.run(scrape_sc())

    if not records:
        print("No records extracted!")
        # Try parsing the raw text file instead
        raw_path = Path("/home/mssbai/Desktop/fraud-mvp/data/sc_grid_text.txt")
        if raw_path.exists():
            print("Parsing raw text file instead...")
            # Will be processed in a separate step
    else:
        print(f"\nExtracted {len(records)} records")

        # Save
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"Saved to {OUTPUT_PATH}")

        # Print sample
        for r in records[:5]:
            print(json.dumps(r, indent=2, ensure_ascii=False)[:200])