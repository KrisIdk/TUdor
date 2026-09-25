"""
Next.js React Server Components (RSC) DOM Stitcher & Markdown Converter.
Extracts content from streamed <div id="S:X"> chunks and converts it to
clean, token-efficient semantic Markdown for AI decoder models like Laya.
"""

import re
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup, Tag, NavigableString
from crawler.bulgarian_nlp import normalize_bulgarian_text


class RSCParser:
    """Parses Next.js RSC streaming HTML pages and transforms them to clean Markdown and structured text."""

    def __init__(self):
        pass

    def stitch_rsc_dom(self, html_content: str) -> BeautifulSoup:
        """
        Detects Next.js streaming chunks (<div id="S:X">) and stitches them
        into their corresponding <template id="B:X"> placeholder positions,
        or replaces the skeleton loader container if present.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Collect all streaming chunks
        streamed_chunks: Dict[str, Tag] = {}
        for s_div in soup.find_all('div', id=re.compile(r'^S:\d+')):
            chunk_id = s_div.get('id', '')
            streamed_chunks[chunk_id] = s_div

        # If no streaming chunks found, return soup as is
        if not streamed_chunks:
            return soup

        # Find templates matching B:X
        for b_template in soup.find_all('template', id=re.compile(r'^B:\d+')):
            b_id = b_template.get('id', '')
            corresponding_s_id = b_id.replace('B:', 'S:')
            if corresponding_s_id in streamed_chunks:
                s_div = streamed_chunks[corresponding_s_id]
                # Extract children of s_div and replace b_template
                # s_div may contain clean markup
                new_container = soup.new_tag('div', **{'class': 'stitched-rsc-chunk'})
                for child in list(s_div.contents):
                    new_container.append(child.extract())
                b_template.replace_with(new_container)

        # In cases where the main container only contained skeleton placeholders,
        # ensure all non-stitched S:X content is also preserved in main content
        main_tag = soup.find('main')
        if main_tag:
            # Remove skeleton pulse animations
            for skeleton in main_tag.find_all(class_=re.compile(r'animate-pulse')):
                skeleton.decompose()

        return soup

    def clean_soup(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Removes scripts, styles, SVGs, modals, cookies notices and noisy elements."""
        for tag_name in ['script', 'style', 'svg', 'noscript', 'iframe']:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Remove header/footer navigational clutter when extracting article/main content
        for selector in ['nav', 'header', 'footer', '.cookie-banner', '#cookie-notice']:
            for tag in soup.select(selector):
                tag.decompose()

        return soup

    def element_to_markdown(self, element: Tag, base_url: str = "https://tu-sofia.bg") -> str:
        """Recursively converts an HTML element into clean semantic Markdown."""
        lines: List[str] = []

        def _traverse(node, depth=0):
            if isinstance(node, NavigableString):
                text = str(node)
                if text.strip():
                    return normalize_bulgarian_text(text)
                return " " if text else ""

            if not isinstance(node, Tag):
                return ""

            tag_name = node.name.lower()

            # Skip hidden elements that weren't stitched
            if node.get('hidden') is not None and not node.get('id', '').startswith('S:'):
                return ""

            if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(tag_name[1])
                text = normalize_bulgarian_text(node.get_text(separator=' ', strip=True))
                if text:
                    return f"\n\n{'#' * level} {text}\n\n"
                return ""

            elif tag_name == 'p':
                inner = "".join(_traverse(child, depth + 1) for child in node.children)
                inner = normalize_bulgarian_text(inner)
                return f"\n\n{inner}\n\n" if inner else ""

            elif tag_name == 'ul':
                items = []
                for li in node.find_all('li', recursive=False):
                    li_text = "".join(_traverse(c, depth + 1) for c in li.children)
                    li_text = normalize_bulgarian_text(li_text)
                    if li_text:
                        items.append(f"- {li_text}")
                return "\n" + "\n".join(items) + "\n" if items else ""

            elif tag_name == 'ol':
                items = []
                for idx, li in enumerate(node.find_all('li', recursive=False), 1):
                    li_text = "".join(_traverse(c, depth + 1) for c in li.children)
                    li_text = normalize_bulgarian_text(li_text)
                    if li_text:
                        items.append(f"{idx}. {li_text}")
                return "\n" + "\n".join(items) + "\n" if items else ""

            elif tag_name == 'table':
                # Convert table to GitHub flavored markdown table
                rows = []
                for tr in node.find_all('tr'):
                    cells = []
                    for td in tr.find_all(['td', 'th']):
                        cell_text = normalize_bulgarian_text(td.get_text(separator=' ', strip=True))
                        cell_text = cell_text.replace('|', '\\|')
                        cells.append(cell_text)
                    if cells:
                        rows.append(cells)
                if not rows:
                    return ""
                max_cols = max(len(r) for r in rows)
                # Pad rows
                padded_rows = [r + [''] * (max_cols - len(r)) for r in rows]
                md_table = "\n\n| " + " | ".join(padded_rows[0]) + " |\n"
                md_table += "| " + " | ".join(['---'] * max_cols) + " |\n"
                for r in padded_rows[1:]:
                    md_table += "| " + " | ".join(r) + " |\n"
                return md_table + "\n"

            elif tag_name == 'a':
                href = node.get('href', '').strip()
                link_text = "".join(_traverse(c, depth + 1) for c in node.children)
                link_text = normalize_bulgarian_text(link_text)
                if not link_text:
                    return ""
                if href.startswith('/'):
                    href = base_url.rstrip('/') + href
                return f"[{link_text}]({href})"

            elif tag_name in ['strong', 'b']:
                inner = "".join(_traverse(c, depth + 1) for c in node.children)
                inner = normalize_bulgarian_text(inner)
                return f"**{inner}**" if inner else ""

            elif tag_name in ['em', 'i']:
                inner = "".join(_traverse(c, depth + 1) for c in node.children)
                inner = normalize_bulgarian_text(inner)
                return f"*{inner}*" if inner else ""

            elif tag_name == 'br':
                return "\n"

            elif tag_name in ['div', 'section', 'article', 'main']:
                chunks = [_traverse(child, depth + 1) for child in node.children]
                return "".join(chunks)

            else:
                chunks = [_traverse(child, depth + 1) for child in node.children]
                return "".join(chunks)

        raw_md = _traverse(element)
        # Collapse multiple empty lines
        cleaned_md = re.sub(r'\n{3,}', '\n\n', raw_md)
        return cleaned_md.strip()

    def parse_page_to_markdown(self, html_content: str, base_url: str = "https://tu-sofia.bg") -> Tuple[str, str]:
        """Stitches RSC, cleans markup, and converts to (title, markdown)."""
        soup = self.stitch_rsc_dom(html_content)
        
        # Clean non-content tags including svgs first so svg titles don't pollute page title
        soup = self.clean_soup(soup)

        # Get page title (ignoring social media titles)
        title = ""
        for title_tag in soup.find_all('title'):
            t_text = normalize_bulgarian_text(title_tag.get_text())
            if t_text.lower() not in ['facebook', 'instagram', 'youtube', 'linkedin', 'twitter', 'x', '']:
                title = t_text
                break

        if not title:
            h1 = soup.find('h1')
            if h1:
                title = normalize_bulgarian_text(h1.get_text())

        # Target main content or body
        target = soup.find('main') or soup.find('article') or soup.find('body')
        if not target:
            target = soup

        markdown = self.element_to_markdown(target, base_url=base_url)
        # Strip Next.js RSC streaming markers
        markdown = re.sub(r'(\$\?|\$/|/\$|\$\$)+', '', markdown)
        return title, markdown
