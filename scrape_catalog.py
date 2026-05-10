"""
SHL Catalog Scraper — Individual Test Solutions only.
Run this ONCE locally to produce data/catalog.json.
Usage: python scrape_catalog.py
"""

import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://www.shl.com"
CATALOG_URL = "https://www.shl.com/solutions/products/product-catalog/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def get_all_catalog_pages():
    """Paginate through the catalog and collect all Individual Test Solution rows."""
    products = []
    start = 0
    page_size = 12  # SHL catalog loads 12 per page

    while True:
        url = f"{CATALOG_URL}?start={start}&type=1"  # type=1 = Individual Test Solutions
        print(f"Fetching: {url}")
        resp = SESSION.get(url, timeout=20)
        if resp.status_code != 200:
            print(f"  Got {resp.status_code}, stopping.")
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # SHL catalog uses a table or card grid
        rows = soup.select("tr.catalog-table-row") or soup.select("[class*='product-catalogue'] .custom-select__item")
        
        # Try the actual SHL table structure
        table_rows = soup.select("table tbody tr")
        if not table_rows:
            # Try card-based layout
            table_rows = soup.select(".product-catalogue__row, [class*='catalogue'] tr, [class*='product'] tr")

        if not table_rows:
            print(f"  No rows found at start={start}. Trying different selector...")
            # Dump first 2000 chars of html to understand structure
            print(resp.text[:3000])
            break

        found = 0
        for row in table_rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            # Extract product name and URL
            link = row.find("a")
            if not link:
                continue

            name = link.get_text(strip=True)
            href = link.get("href", "")
            if not href.startswith("http"):
                href = urljoin(BASE_URL, href)

            # Extract test types from colored badges/icons
            test_type_cells = cells[-1] if len(cells) > 1 else None
            test_types = []
            if test_type_cells:
                badges = test_type_cells.find_all(["span", "td", "div"])
                for b in badges:
                    cls = " ".join(b.get("class", []))
                    txt = b.get_text(strip=True)
                    if txt and len(txt) <= 3:
                        test_types.append(txt)

            # Remote/adaptive flags
            remote = any("remote" in c.get("class", []) for c in row.find_all(class_=True))
            adaptive = any("adaptive" in c.get("class", []) for c in row.find_all(class_=True))

            products.append({
                "name": name,
                "url": href,
                "test_types": test_types,
                "remote_testing": remote,
                "adaptive_irt": adaptive,
                "description": "",  # filled below
            })
            found += 1

        print(f"  Found {found} products (total so far: {len(products)})")
        if found == 0:
            break

        start += page_size
        time.sleep(1)  # polite crawling

    return products


def enrich_product(product: dict) -> dict:
    """Fetch individual product page to get description."""
    try:
        resp = SESSION.get(product["url"], timeout=15)
        if resp.status_code != 200:
            return product
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try common description selectors
        desc = ""
        for sel in [
            ".product-description", ".hero-description",
            "[class*='description']", "meta[name='description']",
            ".content-block p", "main p"
        ]:
            el = soup.select_one(sel)
            if el:
                if el.name == "meta":
                    desc = el.get("content", "")
                else:
                    desc = el.get_text(strip=True)
                if len(desc) > 30:
                    break

        product["description"] = desc[:500]
    except Exception as e:
        print(f"  Error enriching {product['name']}: {e}")
    return product


def scrape_with_pagination_params():
    """
    Alternative: SHL catalog uses query params like:
    ?start=0&type=1  (Individual Test Solutions = type 1)
    Iterates until no more products found.
    """
    all_products = []
    start = 0
    
    while True:
        # Try both known param patterns
        for url_pattern in [
            f"{CATALOG_URL}?start={start}&type=1&ajax=1",
            f"{CATALOG_URL}?start={start}&type=1",
        ]:
            resp = SESSION.get(url_pattern, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # SHL uses a specific class for product rows
            rows = (
                soup.select(".custom-select__list-item") or
                soup.select("tr[data-course-id]") or
                soup.select(".product-catalogue__row") or
                soup.select("table.custom-table tbody tr")
            )
            
            if rows:
                break
        else:
            print(f"No products at start={start}")
            break
        
        found_here = 0
        for row in rows:
            a = row.find("a", href=True)
            if not a:
                continue
            name = a.get_text(strip=True)
            href = a["href"]
            if not href.startswith("http"):
                href = urljoin(BASE_URL, href)
            
            all_products.append({
                "name": name,
                "url": href,
                "test_types": [],
                "remote_testing": False,
                "adaptive_irt": False,
                "description": "",
            })
            found_here += 1
        
        print(f"start={start}: {found_here} products")
        if found_here == 0:
            break
        start += 12
        time.sleep(0.8)
    
    return all_products


if __name__ == "__main__":
    print("=== SHL Catalog Scraper ===")
    print("Scraping Individual Test Solutions catalog...")
    
    products = get_all_catalog_pages()
    
    if not products:
        print("First method failed, trying alternative pagination...")
        products = scrape_with_pagination_params()
    
    if not products:
        print("ERROR: Could not scrape catalog. Check network access to shl.com.")
        print("Alternatively, manually download catalog CSV if SHL provides one.")
        exit(1)
    
    print(f"\nEnriching {len(products)} products with descriptions...")
    enriched = []
    for i, p in enumerate(products):
        print(f"  [{i+1}/{len(products)}] {p['name']}")
        enriched.append(enrich_product(p))
        time.sleep(0.5)
    
    output_path = "data/catalog.json"
    import os
    os.makedirs("data", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)
    
    print(f"\nSaved {len(enriched)} products to {output_path}")
