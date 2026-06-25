import os
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
import time
import asyncio
import re
import sys
import pdfplumber
import fitz
import json
import threading
import http.server
import socketserver
from bs4 import BeautifulSoup
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google.antigravity import Agent, LocalAgentConfig

# Directory configuration
DROPZONE_DIR = "./dropzone"
OUTPUT_DIR = "."
CSS_FILE = "style.css"

def load_dotenv():
    """
    Manually load key-value pairs from .env file into os.environ.
    """
    if os.path.exists(".env"):
        print("[*] Loading environment variables from .env file...")
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip().strip("'\"")

def clean_markdown_html(text):
    """
    Cleans markdown formatting such as ```html ... ``` surrounding the HTML code.
    """
    text = text.strip()
    match = re.search(r"```html\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match_any = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match_any:
        return match_any.group(1).strip()
    return text

def prettify_body_content(html_string):
    """
    Format and prettify the HTML content using BeautifulSoup for pristine formatting.
    """
    try:
        soup = BeautifulSoup(html_string, "html.parser")
        return soup.prettify()
    except Exception as e:
        print(f"[*] Warning: Prettification failed ({e}). Returning raw HTML.")
        return html_string

def get_video_html(url):
    yt_match = re.search(r"(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^\"&?\/s]{11})", url, re.I)
    vimeo_match = re.search(r"(?:vimeo\.com\/)(\d+)", url, re.I)
    gd_match = re.search(r"drive\.google\.com\/file\/d\/([a-zA-Z0-9_-]+)", url, re.I)
    
    if yt_match:
        embed_url = f"https://www.youtube.com/embed/{yt_match.group(1)}"
        return f'<iframe src="{embed_url}" allowfullscreen></iframe>'
    elif vimeo_match:
        embed_url = f"https://player.vimeo.com/video/{vimeo_match.group(1)}"
        return f'<iframe src="{embed_url}" allowfullscreen></iframe>'
    elif gd_match:
        embed_url = f"https://drive.google.com/file/d/{gd_match.group(1)}/preview"
        return f'<iframe src="{embed_url}" allowfullscreen></iframe>'
    elif url.endswith('.mp4') or url.endswith('.webm') or url.endswith('.ogg') or '.mp4?' in url or '.webm?' in url:
        return f'<video src="{url}" controls></video>'
    else:
        return f'<iframe src="{url}" allowfullscreen></iframe>'

def run_offline_conversion(pdf_path):
    """
    Performs a rule-based PDF-to-HTML conversion entirely locally without any API keys,
    extracting text, tables, links, and images contextually using pdfplumber and PyMuPDF.
    """
    print("[*] Executing Offline rule-based PDF parsing...")
    
    media_dir = os.path.join(OUTPUT_DIR, "media")
    os.makedirs(media_dir, exist_ok=True)
    
    html_elements = []
    slot_counter = 0
    
    try:
        doc = fitz.open(pdf_path)
        pdf_plumber_doc = pdfplumber.open(pdf_path)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            plumber_page = pdf_plumber_doc.pages[page_num]
            
            page_height = page.rect.height
            page_width = page.rect.width
            
            header_limit = 65
            footer_limit = page_height - 65
            
            page_items = []
            
            # --- Extract tables using pdfplumber ---
            tables = plumber_page.find_tables()
            table_bboxes = []
            for t_idx, table in enumerate(tables):
                t_bbox = table.bbox
                if t_bbox[3] <= header_limit or t_bbox[0] >= footer_limit:
                    continue
                
                table_data = table.extract()
                if table_data and len(table_data) > 0 and len(table_data[0]) > 1:
                    page_items.append({
                        "type": "table",
                        "y0": t_bbox[1],
                        "bbox": t_bbox,
                        "data": table_data
                    })
                    table_bboxes.append(t_bbox)
            
            # --- Extract links using PyMuPDF ---
            links = page.get_links()
            for link in links:
                l_bbox = link.get("from")
                if not l_bbox:
                    continue
                lx0, ly0, lx1, ly1 = l_bbox.x0, l_bbox.y0, l_bbox.x1, l_bbox.y1
                
                if ly1 <= header_limit or ly0 >= footer_limit:
                    continue
                
                uri = link.get("uri")
                if uri:
                    page_items.append({
                        "type": "link",
                        "y0": ly0,
                        "bbox": (lx0, ly0, lx1, ly1),
                        "uri": uri
                    })
            
            # --- Extract text and image blocks using PyMuPDF dict ---
            page_dict = page.get_text("dict")
            for block_idx, block in enumerate(page_dict.get("blocks", [])):
                b_type = block.get("type")
                b_bbox = block.get("bbox")
                bx0, by0, bx1, by1 = b_bbox
                
                if by1 <= header_limit or by0 >= footer_limit:
                    continue
                
                if b_type == 1: # Image block
                    img_bytes = block.get("image")
                    img_ext = block.get("ext")
                    if img_bytes and img_ext:
                        img_filename = f"page_{page_num+1}_block_{block_idx}.{img_ext}"
                        img_path = os.path.join(media_dir, img_filename)
                        with open(img_path, "wb") as f:
                            f.write(img_bytes)
                        
                        relative_src = f"media/{img_filename}"
                        page_items.append({
                            "type": "image",
                            "y0": by0,
                            "bbox": b_bbox,
                            "src": relative_src
                        })
                        
                elif b_type == 0: # Text block
                    lines_text = []
                    for line in block.get("lines", []):
                        line_text = "".join([span["text"] for span in line.get("spans", [])])
                        lines_text.append(line_text)
                    full_text = "\n".join(lines_text).strip()
                    
                    if not full_text:
                        continue
                    
                    if re.match(r"^\d+$", full_text):
                        continue
                        
                    is_tbl = False
                    for t_bbox in table_bboxes:
                        ix0 = max(bx0, t_bbox[0])
                        iy0 = max(by0, t_bbox[1])
                        ix1 = min(bx1, t_bbox[2])
                        iy1 = min(by1, t_bbox[3])
                        if ix0 < ix1 and iy0 < iy1:
                            overlap_area = (ix1 - ix0) * (iy1 - iy0)
                            block_area = (bx1 - bx0) * (by1 - by0)
                            if block_area > 0 and (overlap_area / block_area) > 0.5:
                                is_tbl = True
                                break
                    if is_tbl:
                        continue
                    
                    page_items.append({
                        "type": "text",
                        "y0": by0,
                        "bbox": b_bbox,
                        "text": full_text
                    })
            
            # --- Sorting and contextual association ---
            page_items.sort(key=lambda x: x["y0"])
            page_links = [x for x in page_items if x["type"] == "link"]
            
            def check_overlap(boxA, boxB):
                ix0 = max(boxA[0], boxB[0])
                iy0 = max(boxA[1], boxB[1])
                ix1 = min(boxA[2], boxB[2])
                iy1 = min(boxA[3], boxB[3])
                if ix0 < ix1 and iy0 < iy1:
                    overlap_area = (ix1 - ix0) * (iy1 - iy0)
                    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
                    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
                    if areaA > 0 and areaB > 0:
                        return (overlap_area / min(areaA, areaB)) > 0.5
                return False
            
            for item in page_items:
                if item["type"] == "text":
                    for link in page_links:
                        if check_overlap(item["bbox"], link["bbox"]):
                            item["link"] = link["uri"]
                            break
            
            final_items = []
            for item in page_items:
                if item["type"] == "link":
                    is_associated = False
                    for other in page_items:
                        if other["type"] == "text" and other.get("link") == item["uri"]:
                            is_associated = True
                            break
                    if not is_associated:
                        final_items.append(item)
                else:
                    final_items.append(item)
            
            # --- Render sorted page items to HTML ---
            in_list = False
            list_tag = None
            
            heading_re = re.compile(r"^(\d+\.\d+\.\d+|\d+\.\d+|\d+)\s+")
            list_re = re.compile(r"^([●○\-•\*]|\d+\.)\s+(.*)")
            
            def close_list():
                nonlocal in_list, list_tag
                if in_list:
                    html_elements.append(f"</{list_tag}>")
                    in_list = False
                    list_tag = None
            
            i = 0
            while i < len(final_items):
                item = final_items[i]
                itype = item["type"]
                
                if itype == "table":
                    close_list()
                    table_data = item["data"]
                    html_elements.append("<table>")
                    if len(table_data) > 0:
                        html_elements.append("  <thead>")
                        html_elements.append("    <tr>")
                        for cell in table_data[0]:
                            cell_val = str(cell).strip() if cell is not None else ""
                            html_elements.append(f"      <th>{cell_val}</th>")
                        html_elements.append("    </tr>")
                        html_elements.append("  </thead>")
                    if len(table_data) > 1:
                        html_elements.append("  <tbody>")
                        for row in table_data[1:]:
                            html_elements.append("    <tr>")
                            for cell in row:
                                cell_val = str(cell).strip() if cell is not None else ""
                                html_elements.append(f"      <td>{cell_val}</td>")
                            html_elements.append("    </tr>")
                        html_elements.append("  </tbody>")
                    html_elements.append("</table>")
                    
                elif itype == "image":
                    close_list()
                    slot_counter += 1
                    html_elements.append(
                        f'<div class="ag-media-slot ag-image-slot has-media" id="slot-{slot_counter}">\n'
                        '    <div class="slot-placeholder" onclick="handleImageUpload(this.parentNode)">\n'
                        '        <span class="slot-icon">📷</span>\n'
                        '        <span class="slot-label">Click to Attach Image</span>\n'
                        '        <span class="slot-sublabel">Supported: PNG, JPG, GIF</span>\n'
                        '    </div>\n'
                        '    <div class="slot-preview">\n'
                        f'        <img src="{item["src"]}?v={int(time.time())}" alt="Attached Image">\n'
                        '        <div class="slot-controls">\n'
                        '            <button class="btn-control btn-change" onclick="handleImageUpload(this.closest(\'.ag-media-slot\'))">Change Image</button>\n'
                        '            <button class="btn-control btn-remove" onclick="removeMedia(this.closest(\'.ag-media-slot\'))">Remove</button>\n'
                        '        </div>\n'
                        '    </div>\n'
                        '</div>'
                    )
                    
                elif itype == "link":
                    close_list()
                    uri = item["uri"]
                    html_elements.append(f'<p><a href="{uri}" target="_blank">{uri}</a></p>')
                    
                elif itype == "text":
                    text_content = item["text"]
                    link_url = item.get("link")
                    
                    is_video_text = ".mp4" in text_content.lower() or ".mp 4" in text_content.lower() or "video:" in text_content.lower()
                    
                    if link_url and (is_video_text or "drive.google.com" in link_url or "youtube.com" in link_url or "youtu.be" in link_url or "vimeo.com" in link_url):
                        close_list()
                        slot_counter += 1
                        
                        video_preview_html = get_video_html(link_url)
                        
                        html_elements.append(f'<div class="video-caption">{text_content}</div>')
                        html_elements.append(
                            f'<div class="ag-media-slot ag-video-slot has-media" id="slot-{slot_counter}" data-video-url="{link_url}">\n'
                            '    <div class="slot-placeholder" onclick="handleVideoLink(this.parentNode)">\n'
                            '        <span class="slot-icon">🎥</span>\n'
                            '        <span class="slot-label">Click to Place Video Link</span>\n'
                            '        <span class="slot-sublabel">Supports: YouTube, Vimeo, direct MP4</span>\n'
                            '    </div>\n'
                            '    <div class="slot-preview">\n'
                            f'        {video_preview_html}\n'
                            '        <div class="slot-controls">\n'
                            '            <button class="btn-control btn-change" onclick="handleVideoLink(this.closest(\'.ag-media-slot\'))">Change Link</button>\n'
                            '            <button class="btn-control btn-remove" onclick="removeMedia(this.closest(\'.ag-media-slot\'))">Remove</button>\n'
                            '        </div>\n'
                            '    </div>\n'
                            '</div>'
                        )
                    else:
                        block_lines = text_content.split("\n")
                        for line in block_lines:
                            line = line.strip()
                            if not line:
                                continue
                            
                            list_match = list_re.match(line)
                            if list_match:
                                marker = list_match.group(1)
                                content = list_match.group(2).strip()
                                is_ordered = marker.endswith(".") and marker[:-1].isdigit()
                                expected_tag = "ol" if is_ordered else "ul"
                                
                                if not in_list or list_tag != expected_tag:
                                    close_list()
                                    html_elements.append(f"<{expected_tag}>")
                                    list_tag = expected_tag
                                    in_list = True
                                    
                                if link_url:
                                    html_elements.append(f'  <li><a href="{link_url}" target="_blank">{content}</a></li>')
                                else:
                                    html_elements.append(f"  <li>{content}</li>")
                                continue
                            
                            is_heading = False
                            heading_level = 2
                            if line.startswith("Level ") or heading_re.match(line):
                                is_heading = True
                                if line.startswith("Level ") or re.match(r"^\d+\.\s+", line):
                                    heading_level = 1
                                elif re.match(r"^\d+\.\d+\s+", line):
                                    heading_level = 2
                                else:
                                    heading_level = 3
                            elif len(line) < 70 and not line.endswith(".") and (line.isupper() or (line[0].isupper() and " " in line)):
                                is_heading = True
                                heading_level = 3
                                
                            if is_heading:
                                close_list()
                                html_elements.append(f"<h{heading_level}>{line}</h{heading_level}>")
                            else:
                                close_list()
                                if link_url:
                                    html_elements.append(f'<p><a href="{link_url}" target="_blank">{line}</a></p>')
                                else:
                                    html_elements.append(f"<p>{line}</p>")
                i += 1
                
            close_list()
            
        doc.close()
        pdf_plumber_doc.close()
        
    except Exception as e:
        print(f"[!] Error in offline parsing: {e}")
        return None

    body_html = "\n".join(html_elements)
    return body_html

async def run_agent_conversion(pdf_path):
    """
    Calls the google-antigravity SDK for Gemini-based translation.
    Converts first 5 pages to avoid rate limits.
    """
    print("[*] Initiating Antigravity SDK agent translation...")
    extracted_content = []
    
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        pages_to_process = min(total_pages, 5)
        print(f"[*] PDF has {total_pages} pages. Extracting first {pages_to_process} pages for LLM translation...")
        for page_num, page in enumerate(pdf.pages[:pages_to_process], start=1):
            extracted_content.append(f"\n--- Page {page_num} Content ---")
            text = page.extract_text()
            if text:
                extracted_content.append(text)
            
            tables = page.extract_tables()
            if tables:
                for t_idx, table in enumerate(tables, start=1):
                    extracted_content.append(f"\n[Table {t_idx} on Page {page_num}]")
                    for row in table:
                        row_cells = [str(cell).strip() if cell is not None else "" for cell in row]
                        extracted_content.append(" | ".join(row_cells))
                    extracted_content.append("[End of Table]\n")

    full_extracted_text = "\n".join(extracted_content).strip()
    if not full_extracted_text:
        raise ValueError("No text or tables found to translate.")

    # Configure google-antigravity Agent
    system_instructions = (
        "You are a Senior Front-End Developer at Exemplifi. "
        "Take extracted text and tables of a PDF and convert them into "
        "impeccable, semantic HTML5 tags that fit inside a document's main content body (<main>).\n\n"
        "Rules:\n"
        "1. Output ONLY the clean HTML5 tags. Do NOT include <html>, <head>, <body>, or <main> tags.\n"
        "2. Use appropriate semantic elements: <section>, <h1>, <h2>, <h3>, <p>, <ul>, <ol>, <li>.\n"
        "3. Map all tabular data structure back to clean, semantic tables using <table>, <thead>, <tbody>, etc.\n"
        "4. Place the following exact local interactive image slot at logical layout breakpoints:\n"
        '<div class="ag-image-slot" onclick="uploadImg(this)">Click to Add Image</div>\n'
        "Place at least 2-4 slots throughout the document.\n"
        "5. Output ONLY raw HTML code directly (no markdown blocks unless standard ```html)."
    )

    config = LocalAgentConfig(
        model="gemini-1.5-flash",
        system_instructions=system_instructions
    )

    async with Agent(config) as agent:
        prompt = (
            f"Please convert this PDF text content into semantic HTML5 layout with Exemplifi visual hierarchy. "
            f"Ensure you insert the interactive image slots at logical division points:\n\n"
            f"{full_extracted_text}"
        )
        response = await agent.chat(prompt)
        raw_html_body = await response.text()

    html_body = clean_markdown_html(raw_html_body)
    
    # Check if image slots were inserted; if not, inject a fallback
    if 'ag-image-slot' not in html_body:
        if '</h2>' in html_body:
            html_body = html_body.replace('</h2>', '</h2>\n<div class="ag-image-slot" onclick="uploadImg(this)">Click to Add Image</div>', 1)
        elif '</p>' in html_body:
            html_body = html_body.replace('</p>', '</p>\n<div class="ag-image-slot" onclick="uploadImg(this)">Click to Add Image</div>', 1)
        else:
            html_body += '\n<div class="ag-image-slot" onclick="uploadImg(this)">Click to Add Image</div>'

    return html_body

def parse_headings_and_add_ids(html_body):
    """
    Parses the generated HTML body, adds unique IDs to h1 and h2 headings,
    and returns the modified HTML body along with a list of sidebar links.
    """
    try:
        soup = BeautifulSoup(html_body, "html.parser")
        headings = soup.find_all(["h1", "h2", "h3"])
        
        sidebar_links = []
        seen_ids = set()
        
        for idx, heading in enumerate(headings):
            text = heading.get_text().strip()
            if not text:
                continue
                
            # Create a clean URL-friendly ID from header text
            # Strip digits, dots, spaces from start of title
            clean_text = text.lower()
            clean_text = re.sub(r"^[\d\.\-\s]+", "", clean_text)
            clean_id = re.sub(r"[^a-z0-9\-_]+", "-", clean_text).strip("-")
            
            if not clean_id:
                clean_id = f"section-{idx}"
                
            # Ensure unique IDs
            final_id = clean_id
            counter = 1
            while final_id in seen_ids:
                final_id = f"{clean_id}-{counter}"
                counter += 1
                
            seen_ids.add(final_id)
            heading["id"] = final_id
            
            # Filter which headings are listed in the sidebar:
            # Include H1, H2, and only numbered H3 (e.g. 1.1.1, 1.2.1)
            is_nav_heading = heading.name in ["h1", "h2"] or (heading.name == "h3" and (re.match(r"^(\d+\.\d+\.\d+|\d+\.\d+|\d+)\s+", text) or text.startswith("Level ")))
            if not is_nav_heading:
                continue

            # Label truncation for visual sidebar safety
            label = text
            if len(label) > 40:
                label = label[:37] + "..."
                
            sidebar_links.append({
                "text": label,
                "id": final_id,
                "level": heading.name
            })
            
        return str(soup), sidebar_links
    except Exception as e:
        print(f"[*] Warning: Heading parsing failed ({e}). Returning original content.")
        return html_body, []

async def process_pdf(pdf_path):
    print(f"\n[+] Processing PDF file: {pdf_path}")
    
    html_body = None
    
    # Bypassed Agent conversion for open-source offline processing
    print("[*] Running Offline python parser...")
    html_body = run_offline_conversion(pdf_path)

    if not html_body:
        print("[!] Error: Could not generate HTML content.")
        return

    # Prettify code
    html_body = prettify_body_content(html_body)

    # Determine document title
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    doc_title = base_name
    title_match = re.search(r"<h1>(.*?)</h1>", html_body, re.IGNORECASE)
    if title_match:
        doc_title = title_match.group(1).strip()

    # Parse headings and generate unique IDs for navigation anchors
    html_body, sidebar_links = parse_headings_and_add_ids(html_body)

    # Construct Sidebar navigation links
    sidebar_links_html = []
    for link in sidebar_links:
        link_class = f"sidebar-link level-{link['level']}"
        sidebar_links_html.append(
            f'                <li><a href="#{link["id"]}" class="{link_class}">{link["text"]}</a></li>'
        )
    
    sidebar_menu_content = "\n".join(sidebar_links_html)
    if not sidebar_menu_content:
        sidebar_menu_content = '                <li><a href="#" class="sidebar-link active-tab">No sections found</a></li>'

    # Wrap inside the corporate-branded HTML template
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{doc_title} - Webified Document</title>
    <link rel="stylesheet" href="style.css">
    <link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&display=swap" rel="stylesheet">
</head>
<body>
    <header class="site-header">
        <div class="header-container">
            <a href="#" class="logo">
                <img src="exemplifi_logo.png?v=2" alt="exemplifi" style="height: 36px; display: block; border-radius: 4px;">
            </a>
            <div class="admin-toggle-container">
                <span class="admin-toggle-label">Admin Mode</span>
                <label class="switch">
                    <input type="checkbox" id="adminToggle" onchange="toggleAdminMode(this.checked)">
                    <span class="slider"></span>
                </label>
            </div>
        </div>
    </header>

    <section class="hero-section">
        <div class="hero-content">
            <span class="eyebrow">AUTOMATED DOCUMENTATION</span>
            <h1>{doc_title}</h1>
            <p>This page was automatically generated from raw PDF source content using local python extraction.</p>
        </div>
    </section>

    <div class="doc-layout">
        <aside class="sidebar">
            <nav class="sidebar-nav">
                <div class="sidebar-header">
                    <h3>Documentation Menu</h3>
                </div>
                <ul class="sidebar-menu">
{sidebar_menu_content}
                </ul>
            </nav>
        </aside>

        <main class="main-content">
            <div class="content-container">
                {html_body}
            </div>
        </main>
    </div>

    <footer class="site-footer">
        <div class="footer-container">
            <div class="footer-brand">
                <img src="exemplifi_logo.png?v=2" alt="exemplifi" style="height: 48px; display: block; border-radius: 4px; margin-bottom: 1rem;">
                <p>End-to-End Government Website Design & Development</p>
                <p class="address">2563 Waverley Street, Palo Alto, CA 94301</p>
            </div>
            <div class="footer-links">
                <a href="tel:+16172337510">(617) 233-7510</a>
                <a href="mailto:contact@exemplifi.io">contact@exemplifi.io</a>
            </div>
        </div>
        <div class="footer-bottom">
            <p>&copy; 2026 Exemplifi. All rights reserved.</p>
        </div>
    </footer>

    <script>
        // Helper to toggle admin mode in UI
        function toggleAdminMode(isAdmin) {{
            if (isAdmin) {{
                document.body.classList.add('admin-mode');
                localStorage.setItem('adminMode', 'true');
            }} else {{
                document.body.classList.remove('admin-mode');
                localStorage.setItem('adminMode', 'false');
            }}
        }}

        // Helper to render image preview in a slot
        function renderImage(slotEl, src) {{
            const preview = slotEl.querySelector('.slot-preview');
            // Remove existing image if any
            const existingImg = preview.querySelector('img');
            if (existingImg) existingImg.remove();
            
            const img = document.createElement('img');
            img.src = src;
            img.alt = "Attached Image";
            preview.insertBefore(img, preview.firstChild);
            slotEl.classList.add('has-media');
        }}

        // Helper to render video player in a slot
        function renderVideo(slotEl, src) {{
            let embedUrl = "";
            const ytMatch = src.match(/(?:youtube\\.com\\/(?:[^\\/]+\\/.+\\/|(?:v|e(?:mbed)?)\\/|.*[?&]v=)|youtu\\.be\\/)([^"&?\\/\\s]{11})/i);
            const vimeoMatch = src.match(/(?:vimeo\\.com\\/)(\\d+)/i);
            const gdMatch = src.match(/drive\\.google\\.com\/file\/d\/([a-zA-Z0-9_-]+)/i);
            
            const preview = slotEl.querySelector('.slot-preview');
            // Remove existing player if any
            const existingMedia = preview.querySelector('iframe, video');
            if (existingMedia) existingMedia.remove();
            
            let mediaEl;
            if (ytMatch) {{
                embedUrl = `https://www.youtube.com/embed/${{ytMatch[1]}}`;
                mediaEl = document.createElement('iframe');
                mediaEl.src = embedUrl;
                mediaEl.allowFullscreen = true;
            }} else if (vimeoMatch) {{
                embedUrl = `https://player.vimeo.com/video/${{vimeoMatch[1]}}`;
                mediaEl = document.createElement('iframe');
                mediaEl.src = embedUrl;
                mediaEl.allowFullscreen = true;
            }} else if (gdMatch) {{
                embedUrl = `https://drive.google.com/file/d/${{gdMatch[1]}}/preview`;
                mediaEl = document.createElement('iframe');
                mediaEl.src = embedUrl;
                mediaEl.allowFullscreen = true;
            }} else if (src.endsWith('.mp4') || src.endsWith('.webm') || src.endsWith('.ogg') || src.includes('.mp4?') || src.includes('.webm?')) {{
                mediaEl = document.createElement('video');
                mediaEl.src = src;
                mediaEl.controls = true;
            }} else {{
                return;
            }}
            
            slotEl.dataset.videoUrl = src;
            preview.insertBefore(mediaEl, preview.firstChild);
            slotEl.classList.add('has-media');
        }}

        // Save slot configuration to Python server
        function saveMediaToServer(slotId, mediaType, src) {{
            const docTitle = document.title;
            fetch('/save-media', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{
                    docTitle: docTitle,
                    slotId: slotId,
                    type: mediaType,
                    src: src
                }})
            }}).then(res => {{
                if (!res.ok) console.error("Failed to save media to server");
            }}).catch(err => console.error("Error contacting save server:", err));
        }}

        // Interactive Image Slot Upload
        function handleImageUpload(slotEl) {{
            if (!document.body.classList.contains('admin-mode')) {{
                alert("Please enable Admin Mode to upload/change images.");
                return;
            }}
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'image/*';
            input.onchange = function(e) {{
                const file = e.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = function(evt) {{
                    renderImage(slotEl, evt.target.result);
                    saveMediaToServer(slotEl.id, 'image', evt.target.result);
                }};
                reader.readAsDataURL(file);
            }};
            input.click();
        }}

        // Interactive Video Link Attachment
        function handleVideoLink(slotEl) {{
            if (!document.body.classList.contains('admin-mode')) {{
                alert("Please enable Admin Mode to change video links.");
                return;
            }}
            const currentUrl = slotEl.dataset.videoUrl || "";
            const url = prompt("Please enter a video URL (YouTube, Vimeo, or direct MP4 link):", currentUrl);
            if (url === null) return; // Prompt cancelled
            const trimmedUrl = url.trim();
            if (!trimmedUrl) return;
            
            renderVideo(slotEl, trimmedUrl);
            saveMediaToServer(slotEl.id, 'video', trimmedUrl);
        }}

        // Remove media attachment
        function removeMedia(slotEl) {{
            if (!document.body.classList.contains('admin-mode')) {{
                alert("Please enable Admin Mode to remove media.");
                return;
            }}
            const preview = slotEl.querySelector('.slot-preview');
            const img = preview.querySelector('img');
            if (img) img.remove();
            const media = preview.querySelector('iframe, video');
            if (media) media.remove();
            delete slotEl.dataset.videoUrl;
            slotEl.classList.remove('has-media');
            
            // Save empty state to server
            saveMediaToServer(slotEl.id, null, null);
        }}

        // On DOM Load: Fetch media_data.json and fill slots, and configure Scroll Spy
        document.addEventListener('DOMContentLoaded', () => {{
            // Load Admin Mode state
            const adminModeEnabled = localStorage.getItem('adminMode') === 'true';
            const adminToggle = document.getElementById('adminToggle');
            if (adminToggle) {{
                adminToggle.checked = adminModeEnabled;
            }}
            toggleAdminMode(adminModeEnabled);

            const docTitle = document.title;
            fetch('media_data.json')
                .then(res => {{
                    if (res.ok) return res.json();
                    return {{}};
                }})
                .then(data => {{
                    const docData = data[docTitle] || {{}};
                    Object.keys(docData).forEach(slotId => {{
                        const slotEl = document.getElementById(slotId);
                        if (slotEl) {{
                            const media = docData[slotId];
                            if (media.type === 'image') {{
                                renderImage(slotEl, media.src);
                            }} else if (media.type === 'video') {{
                                renderVideo(slotEl, media.src);
                            }}
                        }}
                    }});
                }})
                .catch(err => console.log("No saved media data found.", err));

            // Scroll Spy logic
            const observerOptions = {{
                root: null,
                rootMargin: '-80px 0px -60% 0px',
                threshold: 0
            }};

            const observer = new IntersectionObserver((entries) => {{
                entries.forEach(entry => {{
                    if (entry.isIntersecting) {{
                        const id = entry.target.getAttribute('id');
                        if (!id) return;
                        
                        document.querySelectorAll('.sidebar-link').forEach(link => {{
                            link.classList.remove('active-tab');
                        }});
                        
                        const activeLink = document.querySelector(`.sidebar-link[href="#${{id}}"]`);
                        if (activeLink) {{
                            activeLink.classList.add('active-tab');
                        }}
                    }}
                }});
            }}, observerOptions);

            document.querySelectorAll('.main-content h1, .main-content h2, .main-content h3').forEach(heading => {{
                if (heading.getAttribute('id')) {{
                    observer.observe(heading);
                }}
            }});
        }});
    </script>
</body>
</html>
"""

    # Save final HTML page
    output_filename = f"{base_name}.html"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_html)
        print(f"[+] Success! Corporate HTML file generated: {output_path}")
    except Exception as e:
        print(f"[!] Error writing final output: {e}")

def parse_multipart_file(headers, rfile):
    content_type = headers.get('Content-Type', '')
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part.split("=", 1)[1].encode('utf-8')
    if not boundary:
        return None, None
    
    content_length = int(headers.get('Content-Length', 0))
    body = rfile.read(content_length)
    
    boundary_marker = b'--' + boundary
    parts = body.split(boundary_marker)
    
    for part in parts:
        if b'filename="' in part:
            header_data_split = part.split(b'\r\n\r\n', 1)
            if len(header_data_split) < 2:
                continue
            header_part, content_part = header_data_split
            
            fn_match = re.search(r'filename="([^"]+)"', header_part.decode('utf-8', errors='ignore'))
            if fn_match:
                filename = fn_match.group(1)
                if content_part.endswith(b'\r\n'):
                    content_part = content_part[:-2]
                if content_part.endswith(b'--'):
                    content_part = content_part[:-2]
                    if content_part.endswith(b'\r\n'):
                        content_part = content_part[:-2]
                return filename, content_part
    return None, None

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/save-media":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                doc_title = data.get("docTitle")
                slot_id = data.get("slotId")
                media_type = data.get("type")
                media_src = data.get("src")
                
                json_path = os.path.join(OUTPUT_DIR, "media_data.json")
                media_store = {}
                if os.path.exists(json_path):
                    try:
                        with open(json_path, "r", encoding="utf-8") as f:
                            media_store = json.load(f)
                    except Exception:
                        media_store = {}
                
                if doc_title not in media_store:
                    media_store[doc_title] = {}
                    
                if media_type is None:
                    # Remove slot config if null
                    if slot_id in media_store[doc_title]:
                        del media_store[doc_title][slot_id]
                else:
                    media_store[doc_title][slot_id] = {
                        "type": media_type,
                        "src": media_src
                    }
                    
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(media_store, f, indent=2)
                    
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "success"}')
            except Exception as e:
                print(f"[!] Error saving media: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f'{{"error": "{str(e)}"}}'.encode('utf-8'))
        elif self.path == "/upload":
            try:
                filename, file_bytes = parse_multipart_file(self.headers, self.rfile)
                if not filename or not file_bytes:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error": "Invalid file upload data"}')
                    return
                
                if not filename.lower().endswith(".pdf"):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error": "Only PDF documents are supported"}')
                    return
                
                os.makedirs(DROPZONE_DIR, exist_ok=True)
                pdf_path = os.path.join(DROPZONE_DIR, filename)
                with open(pdf_path, "wb") as f:
                    f.write(file_bytes)
                
                print(f"[*] Custom HTTP Server received upload: {filename}. Converting PDF...")
                asyncio.run(process_pdf(pdf_path))
                
                import urllib.parse
                base_name = os.path.splitext(filename)[0]
                html_url = f"/{urllib.parse.quote(base_name)}.html"
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                
                resp_data = {
                    "status": "success",
                    "fileName": filename,
                    "htmlUrl": html_url,
                    "title": base_name
                }
                self.wfile.write(json.dumps(resp_data).encode('utf-8'))
            except Exception as e:
                print(f"[!] Upload parsing error: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f'{{"error": "{str(e)}"}}'.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def start_web_server():
    socketserver.TCPServer.allow_reuse_address = True
    handler = CustomHTTPRequestHandler
    try:
        with socketserver.TCPServer(("", 8081), handler) as httpd:
            print("[+] Custom HTTP Server listening on port 8081...")
            httpd.serve_forever()
    except Exception as e:
        print(f"[!] Web server failed to start: {e}")

class PDFDropzoneHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.lower().endswith(".pdf"):
            print(f"\n[*] New file detected: {os.path.basename(event.src_path)}. Waiting 1 second for write buffer...")
            time.sleep(1.0)
            asyncio.run(process_pdf(event.src_path))

def main():
    load_dotenv()
    os.makedirs(DROPZONE_DIR, exist_ok=True)
    
    # Start Custom HTTP Web Server Thread
    server_thread = threading.Thread(target=start_web_server, daemon=True)
    server_thread.start()
    
    print("=" * 60)
    print("           EXEMPLIFI PDF-TO-HTML AUTOMATION SERVICE")
    print("=" * 60)
    print(f"[*] Dropzone Folder : {os.path.abspath(DROPZONE_DIR)}")
    print(f"[*] CSS Visual Theme: {os.path.abspath(CSS_FILE)}")
    print(f"[*] Output Directory: {os.path.abspath(OUTPUT_DIR)}")
    print("[*] Monitoring dropzone. Drag and drop any PDF to convert...")
    print("Press Ctrl+C to exit.")
    print("-" * 60)

    # Process any pre-existing PDF files in the dropzone on startup
    print("[*] Checking for existing files in dropzone...")
    for entry in os.scandir(DROPZONE_DIR):
        if entry.is_file() and entry.name.lower().endswith(".pdf"):
            print(f"[*] Found pre-existing PDF on startup: {entry.name}")
            try:
                asyncio.run(process_pdf(entry.path))
            except Exception as e:
                print(f"[!] Error processing startup PDF {entry.name}: {e}")

    event_handler = PDFDropzoneHandler()
    observer = Observer()
    observer.schedule(event_handler, path=DROPZONE_DIR, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Stopping pipeline server...")
        observer.stop()
    observer.join()
    print("[*] Pipeline server stopped.")

if __name__ == "__main__":
    main()
