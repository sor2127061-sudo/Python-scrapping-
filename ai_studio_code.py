from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from curl_cffi.requests import AsyncSession
import re
import random
from urllib.parse import urlparse
import asyncio

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
        
    session_cookies = cookies or cookie_vault.get(domain, {})

    async with AsyncSession(impersonate="chrome120") as session:
        for attempt in range(max_retries):
            try:
                response = await session.get(url, headers=headers, cookies=session_cookies, timeout=15, allow_redirects=allow_redirects)
                
                if response.cookies:
                    session_cookies.update(response.cookies.get_dict())
                    cookie_vault[domain] = session_cookies
                
                if response.status_code in [403, 429, 503]:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                    
                if return_raw_response:
                    return response
                return (response.text, session_cookies) if return_cookies else response.text
            except Exception as e:
                if attempt == max_retries - 1:
                    if return_raw_response: return None
                    return ("", session_cookies) if return_cookies else ""
                await asyncio.sleep(1)
                
    if return_raw_response: return None
    return ("", session_cookies) if return_cookies else ""

def extract_videos_from_html(html_block, base_domain):
    list_items = []
    if not html_block: return list_items
    
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
            if poster.startswith('/'): poster = base_domain + poster
            
        if url_match and title_match:
            video_url = url_match.group(1)
            if video_url.startswith('/'): video_url = base_domain + video_url
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            
            list_items.append({
                "url": video_url,
                "poster": poster,
                "title": title
            })
    return list_items

def extract_tags_by_label(html, label):
    tags = []
    block_match = re.search(f'{label}[\\s\\S]*?<\\/div>', html, re.IGNORECASE)
    if block_match:
        a_matches = re.finditer(r'<a[^>]*>([\s\S]*?)<\/a>', block_match.group(0), re.IGNORECASE)
        for match in a_matches:
            tags.append(re.sub(r'<[^>]+>', '', match.group(1)).strip())
    return tags

@app.get("/")
async def api_router(action: str = Query(None), url: str = Query(None), q: str = Query(None), category: str = Query("most-popular/week"), page: int = Query(0)):
    
    if action == "custom_page" or action == "home":
        if action == "home":
            active_domain = random.choice(SUPPORTED_DOMAINS)
            target_url = f"{active_domain}/{category}/{page + 1}/"
        else:
            if not url: return JSONResponse(status_code=400, content={"error": "URL parameter is required for custom_page"})
            target_url = url
            
        base_domain = get_base_domain(target_url)
        html = await fetch_with_bypass(target_url)
        
        block = html
        if 'id="list_videos_common_videos_list_items"' in html:
            block = html.split('id="list_videos_common_videos_list_items"')[1]
            
        videos = extract_videos_from_html(block, base_domain)
        return {"scraped_url": target_url, "total_found": len(videos), "list": videos, "hasNext": len(videos) > 0}
        
    elif action == "search":
        if not q: return JSONResponse(status_code=400, content={"error": "Query 'q' is required"})
        active_domain = random.choice(SUPPORTED_DOMAINS)
        slug = re.sub(r'[^a-zA-Z0-9\s]', '', q).strip().replace(" ", "-").lower()
        
        tasks = []
        for i in range(1, 4):
            target_url = f"{active_domain}/search/{slug}/{i}/"
            tasks.append(fetch_with_bypass(target_url))
            
        results = await asyncio.gather(*tasks)
        all_videos = []
        
        for html in results:
            if not html: continue
            block = html
            if 'id="custom_list_videos_videos_list_search_result_items"' in html:
                block = html.split('id="custom_list_videos_videos_list_search_result_items"')[1]
            if 'id="list_videos_common_videos_list_items"' in block:
                block = block.split('id="list_videos_common_videos_list_items"')[1]
            videos = extract_videos_from_html(block, active_domain)
            all_videos.extend(videos)
            
        return {"list": all_videos}
        
    elif action == "load":
        if not url: return JSONResponse(status_code=400, content={"error": "URL is required"})
        base_domain = get_base_domain(url)
        html = await fetch_with_bypass(url)
        
        title_match = re.search(r'<h1[^>]*>([\s\S]*?)<\/h1>', html, re.IGNORECASE)
        full_title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""
        title = full_title.rsplit(" - ", 1)[0].strip() if " - " in full_title else full_title
        title = re.sub(r'^-|-$', '', title).strip()
        
        year = None
        possible_year = full_title[-4:]
        if possible_year.isdigit():
            year = int(possible_year)

        rating = None
        rating_match = re.search(r'<div[^>]*class=["\'][^"\']*rating[^"\']*["\'][^>]*>[\s\S]*?<span[^>]*>([\s\S]*?)%?<\/span>', html, re.IGNORECASE)
        if rating_match:
            try:
                percent = float(rating_match.group(1).replace('%', '').strip())
                rating = str(percent / 10)
            except:
                pass

        duration = None
        duration_match = re.search(r'Duration[\s\S]*?<em[^>]*>([\s\S]*?)<\/em>', html, re.IGNORECASE)
        if duration_match:
            parts = re.sub(r'<[^>]+>', '', duration_match.group(1)).strip().split(':')
            if len(parts) == 3:
                duration = (int(parts[0]) if parts[0].isdigit() else 0) * 60 + (int(parts[1]) if parts[1].isdigit() else 0)
            elif len(parts) >= 1:
                duration = int(parts[0]) if parts[0].isdigit() else 0

        poster_match = re.search(r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']|content=["\']([^"\']+)["\']\s+property=["\']og:image["\']', html, re.IGNORECASE)
        poster = next((m for m in poster_match.groups() if m), "") if poster_match else ""
        
        desc_match = re.search(r'Description:[\s\S]*?<em[^>]*>([\s\S]*?)<\/em>', html, re.IGNORECASE)
        description = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip() if desc_match else ""

        tags = extract_tags_by_label(html, "Categories:")
        actors = extract_tags_by_label(html, "Models:")
        
        recommendations = []
        rec_block_match = re.search(r'id=["\']list_videos_related_videos_items["\']([\s\S]*?)<div[^>]*class=["\'](?:clear|pagination|footer|bottom)["\']', html, re.IGNORECASE)
        rec_block = rec_block_match.group(1) if rec_block_match else ""
        if not rec_block and 'id="list_videos_related_videos_items"' in html:
            rec_block = html.split('id="list_videos_related_videos_items"')[1]
        
        if rec_block:
            recommendations = extract_videos_from_html(rec_block, base_domain)

        return {
            "title": title, 
            "url": url, 
            "poster": poster, 
            "year": year,
            "rating": rating,
            "duration": duration,
            "tags": tags, 
            "description": description,
            "actors": actors,
            "recommendations": recommendations
        }

    elif action == "links":
        if not url: return JSONResponse(status_code=400, content={"error": "URL is required"})
        base_domain = get_base_domain(url)
        html, cookies = await fetch_with_bypass(url, return_cookies=True)
        
        links = []
        source_matches = re.finditer(r'<source[^>]+src=["\']([^"\']+)["\'][^>]*>', html, re.IGNORECASE)
        
        tasks = []
        for match in source_matches:
            src_url = match.group(1).strip()
            if src_url.startswith('/'): src_url = base_domain + src_url
            
            label_match = re.search(r'label=["\']([^"\']+)["\']', match.group(0), re.IGNORECASE)
            quality = label_match.group(1) if label_match else "Auto"
            
            headers = {
                "Referer": url,
                "Origin": base_domain,
                "Sec-Fetch-Dest": "video",
                "Sec-Fetch-Mode": "no-cors"
            }
            tasks.append((quality, fetch_with_bypass(src_url, allow_redirects=False, custom_headers=headers, cookies=cookies, return_raw_response=True)))
            
        results = await asyncio.gather(*(t[1] for t in tasks))
        
        for i, res in enumerate(results):
            quality = tasks[i][0]
            if res:
                final_url = res.headers.get("location") or res.url
                links.append({"name": "FPV Server", "quality": quality, "url": final_url})
            
        if not links:
            iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if iframe_match:
                links.append({"name": "Embedded Source", "quality": "Auto", "url": iframe_match.group(1)})
                
        return {"links": links}

    else:
        return JSONResponse(status_code=400, content={"error": "Invalid Action. Use ?action=home|search|load|links|custom_page"})