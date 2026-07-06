from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
import re
import random
from urllib.parse import urlparse
import asyncio
import time

app = FastAPI()

SUPPORTED_DOMAINS = [
    "https://www.1porn.tv", 
    "https://www.freepornvideos.xxx",
    "https://www.omg.xxx", 
    "https://www.fullvideos.xxx"
]

cookie_vault = {}

def get_base_domain(url):
    try:
        parsed_uri = urlparse(url)
        return f"{parsed_uri.scheme}://{parsed_uri.netloc}"
    except:
        return SUPPORTED_DOMAINS[0]

async def fetch_with_bypass(url, max_retries=3, allow_redirects=True, custom_headers=None, cookies=None, return_cookies=False, return_raw_response=False):
    domain = get_base_domain(url)
    
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": domain,
        "Upgrade-Insecure-Requests": "1"
    }
    if custom_headers:
        headers.update(custom_headers)

    current_time = time.time()
    session_data = cookie_vault.get(domain, {})
    
    if session_data and (current_time - session_data.get('time', 0)) > 300:
        session_cookies = {}
    else:
        session_cookies = session_data.get('cookies', {})
        
    if cookies: 
        session_cookies = cookies

    async with AsyncSession(impersonate="chrome120") as session:
        for attempt in range(max_retries):
            try:
                response = await session.get(url, headers=headers, cookies=session_cookies, timeout=15, allow_redirects=allow_redirects)
                
                if response.cookies:
                    session_cookies.update(response.cookies.get_dict())
                    cookie_vault[domain] = {'cookies': session_cookies, 'time': time.time()}
                
                if response.status_code in [403, 429, 503]:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                    
                if return_raw_response:
                    return response
                return (response.text, session_cookies) if return_cookies else response.text
            except Exception:
                if attempt == max_retries - 1:
                    if return_raw_response: return None
                    return ("", session_cookies) if return_cookies else ""
                await asyncio.sleep(1)
                
    if return_raw_response: return None
    return ("", session_cookies) if return_cookies else ""

# 🛡️ DUAL-ENGINE PARSER: Selectolax (Primary) + Regex (Backup)
def extract_videos_from_html(html_block, base_domain, container_selector=None):
    list_items = []
    if not html_block: 
        return list_items

    tree = HTMLParser(html_block)
    
    # 🟢 STEP 1: Try with Selectolax
    items = tree.css(f"{container_selector} div.item") if container_selector else tree.css("div.item")
    
    if items:
        for item in items:
            a_tag = item.css_first("a")
            if not a_tag: 
                continue
            
            video_url = a_tag.attributes.get("href", "")
            if video_url.startswith('/'): 
                video_url = base_domain + video_url
            
            title_tag = item.css_first("strong.title")
            title = title_tag.text(strip=True) if title_tag else a_tag.attributes.get("title", "")
            
            img_tag = item.css_first("img")
            poster = ""
            if img_tag:
                attrs = img_tag.attributes
                if "data-src" in attrs: 
                    poster = attrs["data-src"]
                elif "data-lazy-src" in attrs: 
                    poster = attrs["data-lazy-src"]
                elif "srcset" in attrs: 
                    poster = attrs["srcset"].split(" ")[0]
                else: 
                    poster = attrs.get("src", "")
                
            if poster.startswith('/'): 
                poster = base_domain + poster
            
            if video_url and title:
                list_items.append({"url": video_url, "poster": poster, "title": title})
        
        if list_items: 
            return list_items

    # 🔴 STEP 2: Backup - Regex
    chunks = re.split(r'<div[^>]*class=["\'][^"\']*item[^"\']*["\']', html_block, flags=re.IGNORECASE)
    for chunk in chunks[1:]:
        url_match = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', chunk, re.IGNORECASE)
        title_match = re.search(r'<strong[^>]*class=["\']title["\'][^>]*>([\s\S]*?)<\/strong>', chunk, re.IGNORECASE)
        if not title_match: 
            title_match = re.search(r'title=["\']([^"\']+)["\']', chunk, re.IGNORECASE)
        
        img_match = re.search(r'data-src=["\']([^"\']+)["\']|data-lazy-src=["\']([^"\']+)["\']|srcset=["\']([^"\'\s]+)|src=["\']([^"\']+)["\']', chunk, re.IGNORECASE)
        poster = ""
        if img_match:
            poster = next((m for m in img_match.groups() if m), "")
            if poster.startswith('/'): 
                poster = base_domain + poster
            
        if url_match and title_match:
            video_url = url_match.group(1)
            if video_url.startswith('/'): 
                video_url = base_domain + video_url
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            list_items.append({"url": video_url, "poster": poster, "title": title})
            
    return list_items

def extract_tags_by_label(html, tree, label):
    tags = []
    # Selectolax First
    for node in tree.css("div, span, p"):
        if label in node.text(strip=False):
            for a in node.css("a"):
                tags.append(a.text(strip=True))
            if tags: 
                return list(dict.fromkeys(tags))

    # Regex Backup
    block_match = re.search(f'{label}[\\s\\S]*?</div>', html, re.IGNORECASE)
    if block_match:
        a_matches = re.finditer(r'<a[^>]*>([\s\S]*?)<\/a>', block_match.group(0), re.IGNORECASE)
        for match in a_matches:
            tags.append(re.sub(r'<[^>]+>', '', match.group(1)).strip())
    return tags

async def fetch_search_with_delay(url, delay_ms):
    await asyncio.sleep(delay_ms / 1000.0)
    return await fetch_with_bypass(url)

@app.get("/")
async def api_router(
    action: str = Query(None), 
    url: str = Query(None), 
    path: str = Query(None), # This handles the custom path fetch
    q: str = Query(None), 
    category: str = Query("most-popular/week"), 
    page: int = Query(0)
):
    if action in ["custom", "home"]:
        if action == "home":
            active_domain = random.choice(SUPPORTED_DOMAINS)
            target_url = f"{active_domain}/{category}/{page + 1}/"
        else:
            target_url = url
            # The custom path logic is perfectly mapped here
            if not target_url and path:
                active_domain = random.choice(SUPPORTED_DOMAINS)
                target_url = f"{active_domain}{path}" if path.startswith('/') else f"{active_domain}/{path}"
                
            if not target_url: 
                return JSONResponse(status_code=400, content={"error": "URL or Path parameter is required for custom action"})
            
        base_domain = get_base_domain(target_url)
        html = await fetch_with_bypass(target_url)
        
        videos = extract_videos_from_html(html, base_domain, container_selector="#list_videos_common_videos_list_items")
        return {"scraped_url": target_url, "total_found": len(videos), "list": videos, "hasNext": len(videos) > 0}

    elif action == "search":
        if not q: 
            return JSONResponse(status_code=400, content={"error": "Query 'q' is required"})
        active_domain = random.choice(SUPPORTED_DOMAINS)
        slug = re.sub(r'[^a-zA-Z0-9\s]', '', q).strip().replace(" ", "-").lower()
        
        tasks = []
        for i in range(1, 4):
            target_url = f"{active_domain}/search/{slug}/{i}/"
            delay = random.uniform(10, 50)
            tasks.append(fetch_search_with_delay(target_url, delay))
            
        results = await asyncio.gather(*tasks)
        all_videos = []
        
        for html in results:
            if not html: 
                continue
            videos = extract_videos_from_html(html, active_domain, container_selector="#custom_list_videos_videos_list_search_result_items")
            if not videos:
                videos = extract_videos_from_html(html, active_domain, container_selector="#list_videos_common_videos_list_items")
            all_videos.extend(videos)
            
        return {"list": all_videos}

    elif action == "load":
        if not url: 
            return JSONResponse(status_code=400, content={"error": "URL is required"})
        base_domain = get_base_domain(url)
        html = await fetch_with_bypass(url)
        tree = HTMLParser(html)

        # 1. Title
        title_node = tree.css_first("div.headline > h1")
        full_title = title_node.text(strip=True) if title_node else ""
        if not full_title:
            title_match = re.search(r'<h1[^>]*>([\s\S]*?)<\/h1>', html, re.IGNORECASE)
            full_title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""
            
        title = full_title.rsplit(" - ", 1)[0].strip() if " - " in full_title else full_title
        title = re.sub(r'^-|-$', '', title).strip()

        # 2. Year
        year = None
        possible_year = full_title[-4:]
        if possible_year.isdigit(): 
            year = int(possible_year)

        # 3. Rating
        rating, rating_node = None, tree.css_first("div.rating span")
        raw_rating = rating_node.text(strip=True) if rating_node else ""
        if not raw_rating:
            rating_match = re.search(r'<div[^>]*class=["\'][^"\']*rating[^"\']*["\'][^>]*>[\s\S]*?<span[^>]*>([\s\S]*?)%?<\/span>', html, re.IGNORECASE)
            raw_rating = rating_match.group(1).strip() if rating_match else ""
            
        try:
            if raw_rating: 
                rating = str(float(raw_rating.replace('%', '').strip()) / 10)
        except Exception: 
            pass

        # 4. Duration
        duration = None
        raw_duration = ""
        for span in tree.css("span"):
            if "Duration" in span.text():
                em = span.css_first("em")
                if em: 
                    raw_duration = em.text(strip=True)
                
        if not raw_duration:
            duration_match = re.search(r'Duration[\s\S]*?<em[^>]*>([\s\S]*?)<\/em>', html, re.IGNORECASE)
            raw_duration = re.sub(r'<[^>]+>', '', duration_match.group(1)).strip() if duration_match else ""

        if raw_duration:
            parts = raw_duration.split(':')
            if len(parts) == 3: 
                hours = int(parts[0]) if parts[0].isdigit() else 0
                minutes = int(parts[1]) if parts[1].isdigit() else 0
                duration = hours * 60 + minutes
            elif len(parts) == 2: 
                duration = int(parts[0]) if parts[0].isdigit() else 0
            elif len(parts) >= 1: 
                duration = int(parts[0]) if parts[0].isdigit() else 0

        # 5. Poster
        poster_node = tree.css_first("meta[property='og:image']")
        poster = poster_node.attributes.get("content", "") if poster_node else ""
        if not poster:
            poster_match = re.search(r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']|content=["\']([^"\']+)["\']\s+property=["\']og:image["\']', html, re.IGNORECASE)
            poster = next((m for m in poster_match.groups() if m), "") if poster_match else ""

        # 6. Description
        desc = ""
        for div in tree.css("div"):
            if "Description:" in div.text():
                em = div.css_first("em")
                if em: 
                    desc = em.text(strip=True)
        if not desc:
            desc_match = re.search(r'Description:[\s\S]*?<em[^>]*>([\s\S]*?)<\/em>', html, re.IGNORECASE)
            desc = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip() if desc_match else ""

        tags = extract_tags_by_label(html, tree, "Categories:")
        actors = extract_tags_by_label(html, tree, "Models:")
        recommendations = extract_videos_from_html(html, base_domain, container_selector="div#list_videos_related_videos_items")

        return {
            "title": title, "url": url, "poster": poster, "year": year,
            "rating": rating, "duration": duration, "tags": tags, 
            "description": desc, "actors": actors, "recommendations": recommendations
        }

    elif action == "links":
        if not url: 
            return JSONResponse(status_code=400, content={"error": "URL is required"})
        base_domain = get_base_domain(url)
        html, cookies = await fetch_with_bypass(url, return_cookies=True)
        
        links = []
        tree = HTMLParser(html)
        sources = tree.css("video source")
        
        source_data = []
        if sources:
            for src in sources:
                src_url = src.attributes.get("src", "").strip()
                if src_url.startswith('/'): 
                    src_url = base_domain + src_url
                quality = src.attributes.get("label", "Auto")
                source_data.append((quality, src_url))
        else:
            # 🚨 BUG FIXED HERE: [^]* replaced with [^>]*
            for match in re.finditer(r'<source[^>]+src=["\']([^"\']+)["\'][^>]*>', html, re.IGNORECASE):
                src_url = match.group(1).strip()
                if src_url.startswith('/'): 
                    src_url = base_domain + src_url
                label_match = re.search(r'label=["\']([^"\']+)["\']', match.group(0), re.IGNORECASE)
                quality = label_match.group(1) if label_match else "Auto"
                source_data.append((quality, src_url))

        tasks = []
        for quality, src_url in source_data:
            headers = {"Referer": url, "Origin": base_domain, "Sec-Fetch-Dest": "video", "Sec-Fetch-Mode": "no-cors"}
            tasks.append((quality, fetch_with_bypass(src_url, allow_redirects=False, custom_headers=headers, cookies=cookies, return_raw_response=True)))
            
        results = await asyncio.gather(*(t[1] for t in tasks))

        for i, res in enumerate(results):
            quality = tasks[i][0]
            if res:
                final_url = res.headers.get("location") or str(res.url)
                links.append({"name": "FPV Server", "quality": quality, "url": final_url})
            
        if not links:
            iframe = tree.css_first("iframe")
            if iframe and iframe.attributes.get("src"):
                links.append({"name": "Embedded Source", "quality": "Auto", "url": iframe.attributes.get("src")})
            else:
                iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
                if iframe_match: 
                    links.append({"name": "Embedded Source", "quality": "Auto", "url": iframe_match.group(1)})
                
        return {"links": links}

    else:
        return JSONResponse(status_code=400, content={"error": "Invalid Action. Use ?action=home|search|load|links|custom"})
