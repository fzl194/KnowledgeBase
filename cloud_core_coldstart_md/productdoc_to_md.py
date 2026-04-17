from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

import chardet
from bs4 import BeautifulSoup, Comment, NavigableString, Tag


@dataclass
class TopicRecord:
    topic_id: str
    parent_id: str
    txt: str
    topic_path: List[str]
    url: str
    html_abs_path: str
    html_rel_path: str
    md_rel_path: str
    exists: bool
    file_type: str = ""  # html | pdf
    mode: str = ""  # html | index | stub


class HtmlToMarkdownConverter:
    """
    单个 HTML -> Markdown 转换器。

    设计要点：
    1. 直接遍历 DOM，避免先压缩成自定义中间结构导致语义丢失。
    2. 图片等本地资源支持复制到 md 附近的 page.assets 目录。
    3. 本地 html 链接在有映射表时可重写成对应 md 链接。
    4. 复杂 table (rowspan/colspan) 不硬转 markdown，直接保留原始 HTML。
    5. assets 目录按需创建，避免空白 .assets 文件夹。
    """

    BLOCK_TAGS = {
        "article", "section", "div", "main", "body", "header", "footer", "nav",
        "p", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
        "pre", "blockquote", "figure", "figcaption",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "hr", "details", "dl", "dt", "dd",
    }

    INLINE_TAGS = {
        "a", "span", "strong", "b", "em", "i", "code", "img", "br",
        "sub", "sup", "small", "mark", "u", "s", "del", "ins", "label",
    }

    RAW_HTML_TAGS = {"svg", "math", "iframe", "object", "embed", "canvas"}

    def __init__(
        self,
        log_message: Callable[[str], None] = print,
        copy_non_image_link_targets: bool = False,
    ) -> None:
        self.log_message = log_message
        self.copy_non_image_link_targets = copy_non_image_link_targets
        self._source_html_path: Optional[Path] = None
        self._output_md_path: Optional[Path] = None
        self._page_assets_dir: Optional[Path] = None
        self._html_abs_to_md_abs: Dict[str, str] = {}
        self._copied_assets: Dict[str, str] = {}

    def convert_file(
        self,
        html_file: str,
        md_file: str,
        html_abs_to_md_abs: Optional[Dict[str, str]] = None,
    ) -> None:
        html_text = self.read_text_auto(html_file)
        markdown, _ = self.convert_html_string(
            html_text,
            source_html_path=html_file,
            output_md_path=md_file,
            html_abs_to_md_abs=html_abs_to_md_abs,
        )
        Path(md_file).parent.mkdir(parents=True, exist_ok=True)
        Path(md_file).write_text(markdown, encoding="utf-8")
        self._cleanup_empty_assets_dir()

    def convert_html_string(
        self,
        html_text: str,
        source_html_path: Optional[str] = None,
        output_md_path: Optional[str] = None,
        html_abs_to_md_abs: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, bool]:
        self._source_html_path = Path(source_html_path).resolve() if source_html_path else None
        self._output_md_path = Path(output_md_path).resolve() if output_md_path else None
        self._page_assets_dir = self._output_md_path.with_suffix(".assets") if self._output_md_path else None
        self._html_abs_to_md_abs = html_abs_to_md_abs or {}
        self._copied_assets = {}

        soup = BeautifulSoup(html_text, "html.parser")
        self._cleanup_soup(soup)
        root = soup.body if soup.body else soup
        md = self._render_children(root).strip()
        md = self._post_process_markdown(md)
        meaningful = self.is_meaningful_html(html_text)
        return md + ("\n" if md else ""), meaningful

    @staticmethod
    def read_text_auto(file_path: str) -> str:
        encodings = [
            "utf-8", "gb18030", "gbk", "gb2312",
            "utf-16", "big5", "windows-1252", "iso-8859-1", "ascii",
        ]
        raw = Path(file_path).read_bytes()
        try:
            detected = chardet.detect(raw)
            if detected and detected.get("encoding") and (detected.get("confidence") or 0) >= 0.7:
                try:
                    return raw.decode(detected["encoding"])
                except Exception:
                    pass
        except Exception:
            pass

        for enc in encodings:
            try:
                return raw.decode(enc)
            except Exception:
                continue

        for enc in ("utf-8", "gb18030", "gbk"):
            try:
                return raw.decode(enc, errors="ignore")
            except Exception:
                continue

        raise ValueError(f"无法读取文件编码: {file_path}")

    def is_meaningful_html(self, html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "html.parser")
        self._cleanup_soup(soup)
        body = soup.body if soup.body else soup

        if body.find(["table", "img", "pre", "code", "ul", "ol", "blockquote", "svg", "math"]):
            return True

        text = body.get_text("\n", strip=True)
        lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
        lines = [x for x in lines if x]
        if not lines:
            return False

        title_candidates = []
        if soup.title and soup.title.get_text(strip=True):
            title_candidates.append(soup.title.get_text(strip=True))
        h1 = body.find("h1")
        if h1 and h1.get_text(" ", strip=True):
            title_candidates.append(h1.get_text(" ", strip=True))

        filtered = []
        for line in lines:
            if line in title_candidates:
                continue
            if re.search(r"版权所有|copyright", line, re.I):
                continue
            filtered.append(line)

        if not filtered:
            return False

        visible_text = "\n".join(filtered).strip()
        return len(visible_text) >= 20

    @staticmethod
    def _tag_marker(tag: Optional[Tag]) -> str:
        if not isinstance(tag, Tag):
            return ""
        cls = " ".join(tag.get("class", []) or [])
        tag_id = tag.get("id", "") or ""
        tag_name = getattr(tag, "name", "") or ""
        return f"{tag_name} {cls} {tag_id}".lower()

    def _cleanup_soup(self, soup: BeautifulSoup) -> None:
        for tag in soup.find_all(["script", "style", "noscript", "template"]):
            tag.decompose()

        for comment in soup.find_all(string=lambda x: isinstance(x, Comment)):
            comment.extract()

        remove_markers = [
            "footernavbar", "copyright", "bottomnavbtn", "copyrightbottombar",
            "breadcrumb", "toolbar", "navbtn", "footer", "headernav", "topnav",
        ]

        to_remove = []
        for tag in soup.find_all(True):
            if tag is None or getattr(tag, "attrs", None) is None:
                continue
            marker = self._tag_marker(tag)
            if any(x in marker for x in remove_markers):
                to_remove.append(tag)

        for tag in to_remove:
            if tag is None or getattr(tag, "attrs", None) is None:
                continue
            tag.decompose()

    def _post_process_markdown(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def _render_children(self, parent: Tag, indent: int = 0) -> str:
        parts: List[str] = []
        for child in parent.children:
            rendered = self._render_node(child, indent=indent)
            if rendered:
                parts.append(rendered)
        return "".join(parts)

    def _render_node(self, node, indent: int = 0) -> str:
        if isinstance(node, NavigableString):
            text = self._normalize_ws(str(node))
            return text if text else ""
        if not isinstance(node, Tag):
            return ""

        name = (getattr(node, "name", "") or "").lower()

        if name in self.RAW_HTML_TAGS:
            return str(node).strip() + "\n\n"

        if re.fullmatch(r"h[1-6]", name):
            level = int(name[1])
            text = self._render_inline(node).strip()
            return f"{'#' * level} {text}\n\n" if text else ""

        if name == "p":
            text = self._render_inline(node).strip()
            return f"{text}\n\n" if text else ""

        if name == "ul":
            return self._render_list(node, ordered=False, indent=indent) + "\n"
        if name == "ol":
            return self._render_list(node, ordered=True, indent=indent) + "\n"

        if name == "pre":
            return self._render_pre(node)

        if name == "blockquote":
            inner = self._render_children(node).strip() or self._render_inline(node).strip()
            if not inner:
                return ""
            quoted = "\n".join(
                f"> {line}" if line.strip() else ">"
                for line in inner.splitlines()
            )
            return quoted + "\n\n"

        if name == "table":
            return self._render_table(node)

        if name == "img":
            img = self._render_inline(node).strip()
            return f"{img}\n\n" if img else ""

        if name == "hr":
            return "---\n\n"

        if name == "figure":
            return self._render_figure(node)

        if name == "details":
            return self._render_details(node)

        if name in {"dl", "dt", "dd"}:
            return self._render_definition_like(node)

        if name == "li":
            text = self._render_inline(node).strip()
            return f"- {text}\n" if text else ""

        if name in {"div", "section", "article", "main", "body", "header", "footer", "nav", "thead", "tbody", "tfoot", "tr", "td", "th"}:
            return self._render_children(node, indent=indent)

        if name in self.INLINE_TAGS:
            return self._render_inline(node)

        if self._has_block_child(node):
            return self._render_children(node, indent=indent)
        return self._render_inline(node)

    def _render_inline(self, node) -> str:
        if isinstance(node, NavigableString):
            return self._normalize_ws(str(node))
        if not isinstance(node, Tag):
            return ""

        name = (getattr(node, "name", "") or "").lower()
        if name == "br":
            return "<br>"

        if name in {"strong", "b"}:
            inner = self._render_inline_children(node).strip()
            return f"**{inner}**" if inner else ""

        if name in {"em", "i"}:
            inner = self._render_inline_children(node).strip()
            return f"*{inner}*" if inner else ""

        if name == "code":
            if node.parent and getattr(node.parent, "name", "").lower() == "pre":
                return node.get_text()
            return self._wrap_inline_code(node.get_text(strip=False))

        if name == "a":
            href = (node.get("href") or "").strip()
            text = self._render_inline_children(node).strip() or href
            if not href:
                return text
            rewritten = self._rewrite_href(href)
            return f"[{text}]({rewritten})"

        if name == "img":
            src = (node.get("src") or "").strip()
            alt = (node.get("alt") or "").strip()
            title = (node.get("title") or "").strip()
            if not src:
                return alt
            rewritten = self._rewrite_src(src)
            if title:
                return f'![{alt}]({rewritten} "{title}")'
            return f"![{alt}]({rewritten})"

        return self._render_inline_children(node)

    def _render_inline_children(self, parent: Tag) -> str:
        parts: List[str] = []
        for child in parent.children:
            if isinstance(child, NavigableString):
                txt = self._normalize_ws(str(child))
                if txt:
                    parts.append(txt)
            elif isinstance(child, Tag):
                child_name = (getattr(child, "name", "") or "").lower()
                if child_name in self.BLOCK_TAGS and child_name not in {"td", "th"}:
                    block_text = self._render_node(child).strip()
                    if block_text:
                        if parts and not parts[-1].endswith(" "):
                            parts.append(" ")
                        parts.append(block_text)
                        parts.append(" ")
                else:
                    inline = self._render_inline(child)
                    if inline:
                        parts.append(inline)
        text = "".join(parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *<br> *", "<br>", text)
        return text.strip()

    def _render_list(self, list_tag: Tag, ordered: bool, indent: int = 0) -> str:
        lines: List[str] = []
        items = list_tag.find_all("li", recursive=False)
        for idx, li in enumerate(items, start=1):
            bullet = f"{idx}." if ordered else "-"
            prefix = "  " * indent + bullet + " "
            first_text, nested_blocks = self._split_li_content(li, indent=indent)
            lines.append(prefix + first_text if first_text else prefix.rstrip())
            for block in nested_blocks:
                block = block.rstrip("\n")
                if not block:
                    continue
                lines.append(self._indent_text(block, "  " * (indent + 1)))
        return "\n".join(lines).rstrip() + "\n"

    def _split_li_content(self, li: Tag, indent: int = 0) -> Tuple[str, List[str]]:
        inline_parts: List[str] = []
        nested_blocks: List[str] = []

        for child in li.children:
            if isinstance(child, NavigableString):
                txt = self._normalize_ws(str(child))
                if txt:
                    inline_parts.append(txt)
                continue
            if not isinstance(child, Tag):
                continue

            name = (getattr(child, "name", "") or "").lower()
            if name in {"ul", "ol"}:
                nested_blocks.append(self._render_node(child, indent=indent + 1).rstrip())
            elif name == "pre":
                nested_blocks.append(self._render_pre(child).rstrip())
            elif name == "table":
                nested_blocks.append(self._render_table(child).rstrip())
            elif name == "blockquote":
                nested_blocks.append(self._render_node(child).rstrip())
            elif name == "p":
                txt = self._render_inline(child).strip()
                if txt:
                    if not inline_parts:
                        inline_parts.append(txt)
                    else:
                        nested_blocks.append(txt)
            elif self._has_block_child(child):
                nested_blocks.append(self._render_children(child, indent=indent + 1).rstrip())
            else:
                txt = self._render_inline(child).strip()
                if txt:
                    inline_parts.append(txt)

        first_text = re.sub(r"[ \t]+", " ", " ".join(inline_parts)).strip()
        return first_text, nested_blocks

    def _render_pre(self, pre: Tag) -> str:
        code_tag = pre.find("code")
        code_text = code_tag.get_text("\n", strip=False) if code_tag else pre.get_text("\n", strip=False)
        code_text = code_text.rstrip("\n")
        lang = self._extract_code_language(code_tag if isinstance(code_tag, Tag) else pre)
        fence = "```" if "```" not in code_text else "````"
        return f"{fence}{lang}\n{code_text}\n{fence}\n\n"

    @staticmethod
    def _extract_code_language(tag: Optional[Tag]) -> str:
        if not isinstance(tag, Tag):
            return ""
        classes = tag.get("class", []) or []
        for c in classes:
            c = c.lower()
            if c.startswith("language-"):
                return c[len("language-"):]
            if c.startswith("lang-"):
                return c[len("lang-"):]
        return ""

    def _render_table(self, table: Tag) -> str:
        if self._table_has_span(table):
            return str(table).strip() + "\n\n"

        rows: List[List[str]] = []
        trs = table.find_all("tr")
        for tr in trs:
            cells = tr.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            row = [self._render_table_cell(cell) for cell in cells]
            rows.append(row)

        if not rows:
            return ""

        max_cols = max(len(r) for r in rows)
        rows = [r + [""] * (max_cols - len(r)) for r in rows]

        first_tr = trs[0] if trs else None
        first_is_header = False
        if first_tr:
            first_cells = first_tr.find_all(["th", "td"], recursive=False)
            first_is_header = bool(first_cells) and all(((getattr(c, "name", "") or "").lower() == "th") for c in first_cells)

        header = rows[0]
        body = rows[1:] if len(rows) > 1 else []
        if not first_is_header:
            body = rows[1:] if len(rows) > 1 else []
        sep = ["---"] * max_cols
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(sep) + " |",
        ]
        for row in body:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines) + "\n\n"

    def _render_table_cell(self, cell: Tag) -> str:
        parts: List[str] = []
        for child in cell.children:
            if isinstance(child, NavigableString):
                txt = self._normalize_ws(str(child))
                if txt:
                    parts.append(txt)
            elif isinstance(child, Tag):
                name = (getattr(child, "name", "") or "").lower()
                if name in {"ul", "ol"}:
                    items = []
                    for li in child.find_all("li", recursive=False):
                        item = self._render_inline(li).strip()
                        if item:
                            items.append(f"- {item}")
                    if items:
                        parts.append("<br>".join(items))
                elif name == "pre":
                    code = child.get_text(" ", strip=True)
                    if code:
                        parts.append(self._wrap_inline_code(code))
                elif name == "br":
                    parts.append("<br>")
                else:
                    inline = self._render_inline(child)
                    if inline:
                        parts.append(inline)

        text = "".join(parts)
        text = re.sub(r"[ \t]+", " ", text).strip()
        return text.replace("|", r"\|")

    @staticmethod
    def _table_has_span(table: Tag) -> bool:
        for cell in table.find_all(["td", "th"]):
            if str(cell.get("rowspan", "1")) != "1":
                return True
            if str(cell.get("colspan", "1")) != "1":
                return True
        return False

    def _render_figure(self, figure: Tag) -> str:
        parts: List[str] = []
        for child in figure.children:
            if isinstance(child, Tag) and ((getattr(child, "name", "") or "").lower() == "figcaption"):
                caption = self._render_inline(child).strip()
                if caption:
                    parts.append(f"*{caption}*")
            else:
                rendered = self._render_node(child).strip()
                if rendered:
                    parts.append(rendered)
        return ("\n\n".join(parts) + "\n\n") if parts else ""

    def _render_details(self, details: Tag) -> str:
        summary = details.find("summary", recursive=False)
        lines: List[str] = []
        if summary:
            title = self._render_inline(summary).strip()
            if title:
                lines.append(f"**{title}**")
        for child in details.children:
            if child is summary:
                continue
            rendered = self._render_node(child).strip()
            if rendered:
                lines.append(rendered)
        return ("\n\n".join(lines).strip() + "\n\n") if lines else ""

    def _render_definition_like(self, node: Tag) -> str:
        node_name = (getattr(node, "name", "") or "").lower()
        if node_name == "dt":
            txt = self._render_inline(node).strip()
            return f"- **{txt}**\n" if txt else ""
        if node_name == "dd":
            txt = self._render_children(node).strip() or self._render_inline(node).strip()
            return f"  {txt}\n" if txt else ""
        return self._render_children(node)

    @staticmethod
    def _normalize_ws(text: str) -> str:
        text = text.replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _has_block_child(self, tag: Tag) -> bool:
        for child in tag.children:
            if isinstance(child, Tag) and ((getattr(child, "name", "") or "").lower() in self.BLOCK_TAGS):
                return True
        return False

    @staticmethod
    def _indent_text(text: str, prefix: str) -> str:
        lines = text.splitlines()
        return "\n".join((prefix + line) if line.strip() else line for line in lines)

    @staticmethod
    def _wrap_inline_code(text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        return f"``{text}``" if "`" in text else f"`{text}`"

    def _rewrite_href(self, href: str) -> str:
        kind = self._classify_url(href)
        if kind in {"empty", "remote", "anchor"}:
            return href

        local_path, anchor = self._resolve_local_path_with_anchor(href)
        if not local_path or not self._output_md_path:
            return href

        local_key = str(local_path)
        suffix = local_path.suffix.lower()

        if suffix in {".html", ".htm"} and local_key in self._html_abs_to_md_abs:
            target_md = Path(self._html_abs_to_md_abs[local_key])
            rel = os.path.relpath(target_md, self._output_md_path.parent)
            rel = Path(rel).as_posix()
            return rel + (f"#{anchor}" if anchor else "")

        if self.copy_non_image_link_targets and local_path.exists():
            copied = self._copy_asset(local_path)
            rel = os.path.relpath(copied, self._output_md_path.parent)
            rel = Path(rel).as_posix()
            return rel + (f"#{anchor}" if anchor else "")

        if local_path.exists():
            rel = os.path.relpath(local_path, self._output_md_path.parent)
            rel = Path(rel).as_posix()
            return rel + (f"#{anchor}" if anchor else "")

        self.log_message(f"链接目标不存在，保留原链接: {href}")
        return href

    def _rewrite_src(self, src: str) -> str:
        kind = self._classify_url(src)
        if kind in {"empty", "remote", "anchor"}:
            return src
        if not self._output_md_path:
            return src
        local_path, anchor = self._resolve_local_path_with_anchor(src)
        if not local_path or not local_path.exists():
            self.log_message(f"资源不存在，保留原路径: {src}")
            return src
        copied = self._copy_asset(local_path)
        rel = os.path.relpath(copied, self._output_md_path.parent)
        rel = Path(rel).as_posix()
        return rel + (f"#{anchor}" if anchor else "")

    @staticmethod
    def _classify_url(url: str) -> str:
        if not url or not url.strip():
            return "empty"
        url = url.strip()
        if url.startswith("#"):
            return "anchor"
        lowered = url.lower()
        if lowered.startswith("//"):
            return "remote"
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https", "mailto", "tel", "javascript", "data"}:
            return "remote"
        if parsed.scheme == "file":
            return "local"
        if parsed.scheme:
            return "remote"
        return "local"

    def _resolve_local_path_with_anchor(self, url: str) -> Tuple[Optional[Path], str]:
        if not self._source_html_path:
            return None, ""
        parsed = urlparse(url)
        anchor = parsed.fragment or ""
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path)).resolve()
            return path, anchor
        relative = unquote(parsed.path or "")
        resolved = (self._source_html_path.parent / relative).resolve()
        return resolved, anchor

    def _copy_asset(self, src_path: Path) -> Path:
        assert self._page_assets_dir is not None
        src_key = str(src_path)
        if src_key in self._copied_assets:
            return Path(self._copied_assets[src_key])

        self._page_assets_dir.mkdir(parents=True, exist_ok=True)

        safe_name = self._safe_filename(src_path.name, max_len=80)
        target = self._page_assets_dir / safe_name
        if target.exists():
            if self._same_file(src_path, target):
                self._copied_assets[src_key] = str(target)
                return target
            stem = target.stem
            suffix = target.suffix
            idx = 2
            while True:
                candidate = self._page_assets_dir / f"{stem}_{idx}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
                idx += 1
        shutil.copy2(src_path, target)
        self._copied_assets[src_key] = str(target)
        return target

    def _cleanup_empty_assets_dir(self) -> None:
        if self._page_assets_dir and self._page_assets_dir.exists():
            try:
                next(self._page_assets_dir.iterdir())
            except StopIteration:
                self._page_assets_dir.rmdir()

    @staticmethod
    def _same_file(a: Path, b: Path) -> bool:
        try:
            return a.samefile(b)
        except Exception:
            return False

    @staticmethod
    def _safe_filename(name: str, max_len: int = 80) -> str:
        raw = name or "untitled"
        safe = re.sub(r'[<>:"/\\|?*]+', '_', raw)
        safe = re.sub(r"\s+", " ", safe).strip().rstrip(". ")
        if not safe:
            safe = "untitled"

        if len(safe) <= max_len:
            return safe

        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
        keep = max_len - 9
        keep = max(keep, 20)
        return f"{safe[:keep]}_{digest}"


class ProductDocMarkdownExporter:
    """
    全量产品文档导出器：
    - 解析 resources/navi.xml
    - 递归遍历全部 topic
    - 生成目录结构化 markdown
    - 空白/占位 HTML 自动转索引页
    - 输出 html -> md 映射表（json/csv）
    """

    def __init__(
        self,
        extracted_root: str,
        output_root: str,
        log_message: Callable[[str], None] = print,
        copy_non_image_link_targets: bool = False,
    ) -> None:
        self.extracted_root = Path(extracted_root).resolve()
        self.resources_root = self.extracted_root / "resources"
        self.navi_xml_path = self.resources_root / "navi.xml"
        self.output_root = Path(output_root).resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.log_message = log_message
        self.converter = HtmlToMarkdownConverter(
            log_message=log_message,
            copy_non_image_link_targets=copy_non_image_link_targets,
        )

        self._used_md_rel_paths: set[str] = set()
        self._records: List[TopicRecord] = []
        self._html_abs_to_md_abs: Dict[str, str] = {}
        self._record_by_id: Dict[str, TopicRecord] = {}
        self._children_by_id: Dict[str, List[str]] = {}

    def export_all(self) -> List[TopicRecord]:
        root = self._parse_navi_xml()
        self._records = self._collect_topic_records(root)
        self._record_by_id = {r.topic_id: r for r in self._records if r.topic_id}
        self._html_abs_to_md_abs = {
            r.html_abs_path: str((self.output_root / r.md_rel_path).resolve())
            for r in self._records if r.exists and r.html_abs_path
        }

        self._convert_all_records(self._records)
        self._write_mapping_files(self._records)
        self.log_message(
            f"导出完成：共 {len(self._records)} 个 topic，存在 HTML {sum(r.exists for r in self._records)} 个。"
        )
        return self._records

    def _parse_navi_xml(self) -> ET.Element:
        if not self.navi_xml_path.exists():
            raise FileNotFoundError(f"navi.xml 不存在: {self.navi_xml_path}")
        content = HtmlToMarkdownConverter.read_text_auto(str(self.navi_xml_path)).strip()
        if content.startswith("\ufeff"):
            content = content[1:]
        root = ET.fromstring(content)
        if root.tag != "topics":
            self.log_message(f"警告：XML 根节点不是 topics，而是 {root.tag}")
        return root

    def _collect_topic_records(self, root: ET.Element) -> List[TopicRecord]:
        records: List[TopicRecord] = []
        for topic in root.findall("topic"):
            self._walk_topic(topic, [], "", records)
        return records

    def _walk_topic(
        self,
        topic: ET.Element,
        parents: List[str],
        parent_id: str,
        records: List[TopicRecord],
    ) -> None:
        txt = (topic.get("txt") or topic.get("id") or "untitled").strip()
        topic_id = (topic.get("id") or self._pseudo_topic_id(parents + [txt], topic.get("url") or "")).strip()
        url = (topic.get("url") or "").strip()
        topic_path = parents + [txt]

        file_type = self._detect_file_type(url)
        html_abs = self._resolve_topic_html_abs(url) if file_type == "html" else ""
        pdf_abs = self._resolve_topic_pdf_abs(url) if file_type == "pdf" else ""
        html_rel = self._safe_relpath(html_abs, self.extracted_root) if html_abs else ""
        pdf_rel = self._safe_relpath(pdf_abs, self.extracted_root) if pdf_abs else ""

        if file_type == "pdf":
            md_rel = self._build_unique_pdf_rel_path(topic_path, topic_id=topic_id)
        else:
            md_rel = self._build_unique_md_rel_path(topic_path, topic_id=topic_id)

        exists = bool(pdf_abs and Path(pdf_abs).exists()) if file_type == "pdf" else bool(html_abs and Path(html_abs).exists())

        records.append(
            TopicRecord(
                topic_id=topic_id,
                parent_id=parent_id,
                txt=txt,
                topic_path=topic_path,
                url=url,
                html_abs_path=pdf_abs if file_type == "pdf" else html_abs,
                html_rel_path=pdf_rel if file_type == "pdf" else html_rel,
                md_rel_path=md_rel,
                exists=exists,
                file_type=file_type,
                mode="",
            )
        )

        if parent_id:
            self._children_by_id.setdefault(parent_id, []).append(topic_id)
        self._children_by_id.setdefault(topic_id, [])

        for child in topic.findall("topic"):
            self._walk_topic(child, topic_path, topic_id, records)

    @staticmethod
    def _pseudo_topic_id(topic_path: List[str], url: str) -> str:
        base = " / ".join(topic_path) + "|" + url
        return hashlib.md5(base.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _detect_file_type(url: str) -> str:
        if not url:
            return "html"
        url_lower = url.lower()
        if url_lower.endswith(".pdf"):
            return "pdf"
        return "html"

    def _resolve_topic_html_abs(self, url: str) -> str:
        if not url:
            return ""
        path = (self.resources_root / url).resolve()
        return str(path)

    def _resolve_topic_pdf_abs(self, url: str) -> str:
        if not url:
            return ""
        path = (self.resources_root / url).resolve()
        return str(path)

    def _build_unique_pdf_rel_path(self, topic_path: List[str], topic_id: str = "") -> str:
        dir_limits = [40, 28, 20]
        leaf_limits = [60, 40, 28]

        for dir_limit, leaf_limit in zip(dir_limits, leaf_limits):
            safe_parts = [self._safe_filename(p, max_len=dir_limit) for p in topic_path[:-1]]
            leaf_base = self._safe_filename(topic_path[-1], max_len=leaf_limit)
            if topic_id:
                short_id = topic_id[-8:] if len(topic_id) > 8 else topic_id
                leaf_base = f"{leaf_base}_{short_id}"
            rel = (Path(*safe_parts) / f"{leaf_base}.pdf") if safe_parts else Path(f"{leaf_base}.pdf")
            rel_str = rel.as_posix()

            abs_candidate = str((self.output_root / rel).resolve())
            if len(rel_str) <= 180 and len(abs_candidate) <= 240:
                return self._dedupe_rel_path(rel)

        safe_parts = [self._safe_filename(p, max_len=16) for p in topic_path[:-1]]
        digest = hashlib.md5(" / ".join(topic_path).encode("utf-8")).hexdigest()[:10]
        leaf_base = self._safe_filename(topic_path[-1], max_len=18)
        rel = (Path(*safe_parts) / f"{leaf_base}_{digest}.pdf") if safe_parts else Path(f"{leaf_base}_{digest}.pdf")
        return self._dedupe_rel_path(rel)

    def _build_unique_md_rel_path(self, topic_path: List[str], topic_id: str = "") -> str:
        """
        生成 md 相对路径：
        - 保留目录结构
        - 每一级目录名和文件名做截断
        - 路径过长时，逐步压缩目录名和叶子名
        """
        dir_limits = [40, 28, 20]
        leaf_limits = [60, 40, 28]

        for dir_limit, leaf_limit in zip(dir_limits, leaf_limits):
            safe_parts = [self._safe_filename(p, max_len=dir_limit) for p in topic_path[:-1]]
            leaf_base = self._safe_filename(topic_path[-1], max_len=leaf_limit)
            if topic_id:
                short_id = topic_id[-8:] if len(topic_id) > 8 else topic_id
                leaf_base = f"{leaf_base}_{short_id}"
            rel = (Path(*safe_parts) / f"{leaf_base}.md") if safe_parts else Path(f"{leaf_base}.md")
            rel_str = rel.as_posix()

            abs_candidate = str((self.output_root / rel).resolve())
            if len(rel_str) <= 180 and len(abs_candidate) <= 240:
                return self._dedupe_rel_path(rel)

        # 极端情况下直接用 hash 叶子名兜底
        safe_parts = [self._safe_filename(p, max_len=16) for p in topic_path[:-1]]
        digest = hashlib.md5(" / ".join(topic_path).encode("utf-8")).hexdigest()[:10]
        leaf_base = self._safe_filename(topic_path[-1], max_len=18)
        rel = (Path(*safe_parts) / f"{leaf_base}_{digest}.md") if safe_parts else Path(f"{leaf_base}_{digest}.md")
        return self._dedupe_rel_path(rel)

    def _dedupe_rel_path(self, rel: Path) -> str:
        rel_str = rel.as_posix()
        if rel_str not in self._used_md_rel_paths:
            self._used_md_rel_paths.add(rel_str)
            return rel_str

        base = rel.with_suffix("")
        suffix = rel.suffix
        idx = 2
        while True:
            candidate = Path(str(base) + f"_{idx}" + suffix)
            candidate_str = candidate.as_posix()
            if candidate_str not in self._used_md_rel_paths:
                self._used_md_rel_paths.add(candidate_str)
                return candidate_str
            idx += 1

    def _convert_all_records(self, records: Iterable[TopicRecord]) -> None:
        for rec in records:
            md_path = self.output_root / rec.md_rel_path
            md_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                if rec.file_type == "pdf":
                    self._handle_pdf_record(rec, md_path)
                    continue

                html_text = ""
                meaningful = False
                if rec.exists and rec.html_abs_path:
                    html_text = self.converter.read_text_auto(rec.html_abs_path)
                    meaningful = self.converter.is_meaningful_html(html_text)

                child_recs = [self._record_by_id[cid] for cid in self._children_by_id.get(rec.topic_id, []) if cid in self._record_by_id]

                if rec.exists and meaningful:
                    markdown, _ = self.converter.convert_html_string(
                        html_text,
                        source_html_path=rec.html_abs_path,
                        output_md_path=str(md_path),
                        html_abs_to_md_abs=self._html_abs_to_md_abs,
                    )
                    md_path.write_text(markdown, encoding="utf-8")
                    self.converter._cleanup_empty_assets_dir()
                    rec.mode = "html"
                else:
                    pass
                    # reason = "源 HTML 无正文内容" if rec.exists else "源 HTML 不存在"
                    # markdown = self._build_index_or_stub_markdown(rec, child_recs, reason)
                    # md_path.write_text(markdown, encoding="utf-8")
                    # rec.mode = "index" if child_recs else "stub"
            except Exception as exc:
                self.log_message(f"转换失败: {rec.html_abs_path or rec.url} -> {md_path} | {exc}")

        self._cleanup_empty_asset_dirs()

    def _handle_pdf_record(self, rec: TopicRecord, md_path: Path) -> None:
        if rec.exists and rec.html_abs_path:
            pdf_src = Path(rec.html_abs_path)
            if pdf_src.exists():
                shutil.copy2(pdf_src, md_path)
                rec.mode = "pdf"
            else:
                rec.mode = "stub"
        else:
            rec.mode = "stub"

    def _build_index_or_stub_markdown(
        self,
        rec: TopicRecord,
        child_recs: List[TopicRecord],
        reason: str,
    ) -> str:
        lines = [f"# {rec.txt}", ""]

        if child_recs:
            lines.append(f"> 本页未抽取到有效正文，已根据导航目录生成索引页。原因：{reason}。")
            lines.append("")
            lines.append("## 子章节")
            lines.append("")
            current_dir = (self.output_root / rec.md_rel_path).parent
            for child in child_recs:
                child_abs = (self.output_root / child.md_rel_path).resolve()
                rel = Path(os.path.relpath(child_abs, current_dir)).as_posix()
                lines.append(f"- [{child.txt}]({rel})")
            lines.append("")
        else:
            lines.append(f"> 本页未抽取到有效正文。原因：{reason}。")
            lines.append("")
            if rec.url:
                lines.append(f"原始入口：`{rec.url}`")
                lines.append("")

        return "\n".join(lines).strip() + "\n"

    def _cleanup_empty_asset_dirs(self) -> None:
        for assets_dir in sorted(self.output_root.rglob("*.assets"), key=lambda p: len(p.parts), reverse=True):
            if assets_dir.is_dir():
                try:
                    next(assets_dir.iterdir())
                except StopIteration:
                    try:
                        assets_dir.rmdir()
                    except OSError:
                        pass

    def _write_mapping_files(self, records: List[TopicRecord]) -> None:
        json_path = self.output_root / "html_to_md_mapping.json"
        csv_path = self.output_root / "html_to_md_mapping.csv"

        json_data = []
        for rec in records:
            item = asdict(rec)
            item["topic_path_text"] = " / ".join(rec.topic_path)
            item["md_abs_path"] = str((self.output_root / rec.md_rel_path).resolve())
            item["child_count"] = len(self._children_by_id.get(rec.topic_id, []))
            json_data.append(item)
        json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")

        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "topic_id",
                    "parent_id",
                    "txt",
                    "topic_path_text",
                    "url",
                    "html_abs_path",
                    "html_rel_path",
                    "md_rel_path",
                    "md_abs_path",
                    "exists",
                    "mode",
                    "child_count",
                ],
            )
            writer.writeheader()
            for rec in records:
                writer.writerow(
                    {
                        "topic_id": rec.topic_id,
                        "parent_id": rec.parent_id,
                        "txt": rec.txt,
                        "topic_path_text": " / ".join(rec.topic_path),
                        "url": rec.url,
                        "html_abs_path": rec.html_abs_path,
                        "html_rel_path": rec.html_rel_path,
                        "md_rel_path": rec.md_rel_path,
                        "md_abs_path": str((self.output_root / rec.md_rel_path).resolve()),
                        "exists": rec.exists,
                        "mode": rec.mode,
                        "child_count": len(self._children_by_id.get(rec.topic_id, [])),
                    }
                )

    @staticmethod
    def _safe_relpath(path_str: str, start: Path) -> str:
        try:
            return Path(os.path.relpath(path_str, start)).as_posix()
        except Exception:
            return path_str

    @staticmethod
    def _safe_filename(name: str, max_len: int = 80) -> str:
        raw = name or "untitled"
        safe = re.sub(r'[<>:"/\\|?*]+', '_', raw)
        safe = re.sub(r"\s+", " ", safe).strip().rstrip(". ")
        if not safe:
            safe = "untitled"

        if len(safe) <= max_len:
            return safe

        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
        keep = max_len - 9
        keep = max(keep, 20)
        return f"{safe[:keep]}_{digest}"


def extract_hdx_file(hdx_path: str) -> str:
    """
    解压 HDX/HWICS 文件到 output/extracted_xxx
    """
    if not os.path.exists(hdx_path):
        raise FileNotFoundError(f"文档文件不存在: {hdx_path}")

    hdx_filename = os.path.splitext(os.path.basename(hdx_path))[0]
    base_dir = os.path.dirname(os.path.abspath(hdx_path))

    output_base_dir = os.path.join(base_dir, "output")
    os.makedirs(output_base_dir, exist_ok=True)

    extract_dir = os.path.join(output_base_dir, f"extracted_{hdx_filename}")

    if os.path.exists(extract_dir) and os.listdir(extract_dir):
        hdx_mtime = os.path.getmtime(hdx_path)
        extract_mtime = os.path.getmtime(extract_dir)
        if hdx_mtime <= extract_mtime:
            print(f"检测到现有解压目录，直接使用: {extract_dir}")
            return extract_dir
        print("检测到文档文件已更新，重新解压...")

    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir, exist_ok=True)

    try:
        print(f"开始解压文档: {os.path.basename(hdx_path)}")
        with zipfile.ZipFile(hdx_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        print(f"文档解压完成: {extract_dir}")
        return extract_dir
    except zipfile.BadZipFile as exc:
        raise ValueError("文件不是有效的 ZIP 格式") from exc


def main(hdx_file: str) -> None:
    extract_dir = extract_hdx_file(hdx_file)

    hdx_filename = os.path.splitext(os.path.basename(hdx_file))[0]
    base_dir = os.path.dirname(os.path.abspath(hdx_file))
    output_root = os.path.join(base_dir, "output", hdx_filename)
    os.makedirs(output_root, exist_ok=True)

    exporter = ProductDocMarkdownExporter(
        extracted_root=extract_dir,
        output_root=output_root,
    )
    exporter.export_all()

    print(f"Markdown 输出完成，结果目录: {output_root}")


if __name__ == "__main__":
    hdx_file = "UDG_Product_Documentation_CH_20.15.2.hwics"
    main(hdx_file)