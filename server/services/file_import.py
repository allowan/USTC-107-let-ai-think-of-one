"""Extract uploaded documents into editable text without saving the original file."""
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
SUPPORTED_EXTENSIONS = {'.txt', '.md', '.markdown', '.csv', '.json', '.pdf', '.docx'}


class FileImportError(ValueError):
    pass


def extract_file(filename: str, data: bytes) -> dict:
    filename = PurePosixPath(filename.replace('\\', '/')).name
    suffix = PurePosixPath(filename).suffix.lower()
    if not filename or suffix not in SUPPORTED_EXTENSIONS:
        raise FileImportError('不支持此文件格式，请选择 TXT、Markdown、CSV、JSON、PDF 或 DOCX 文件')
    if len(data) > MAX_FILE_BYTES:
        raise FileImportError('文件不能超过 10 MB')
    if not data:
        raise FileImportError('文件为空，请选择有内容的文件')
    if suffix == '.pdf':
        text = _pdf_text(data)
    elif suffix == '.docx':
        text = _docx_text(data)
    else:
        text = _decode_text(data)
    text = text.strip()
    if not text:
        raise FileImportError('未提取到文字。扫描版 PDF 或图片请先进行 OCR 文字识别后再导入')
    if len(text) > MAX_TEXT_CHARS:
        raise FileImportError('提取的文字超过 20 万字符，请拆分文件后上传')
    return {'filename': filename, 'source': filename, 'content': text, 'character_count': len(text)}


def _decode_text(data: bytes) -> str:
    encodings = ['utf-16'] if data.startswith((b'\xff\xfe', b'\xfe\xff')) else ['utf-8-sig', 'gb18030']
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            if any(ord(c) < 32 and c not in '\t\n\r' for c in text):
                raise FileImportError('文件包含非文本内容，请检查文件格式')
            return text
        except UnicodeDecodeError:
            pass
    raise FileImportError('无法识别文本编码，请将文件保存为 UTF-8 后重试')


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    if not data.startswith(b'%PDF-'):
        raise FileImportError('文件不是有效的 PDF')
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(''):
            raise FileImportError('PDF 已加密，请解密后重新上传')
        if len(reader.pages) > 200:
            raise FileImportError('PDF 超过 200 页，请拆分后上传')
        parts, total = [], 0
        for page in reader.pages:
            content = page.get_contents()
            if content and len(content.get_data()) > 10 * 1024 * 1024:
                raise FileImportError('PDF 页面过于复杂，请拆分或转为文本后上传')
            part = page.extract_text() or ''
            total += len(part)
            if total > MAX_TEXT_CHARS:
                raise FileImportError('提取的文字超过 20 万字符，请拆分文件后上传')
            parts.append(part)
        return '\n\n'.join(parts)
    except FileImportError:
        raise
    except Exception as exc:
        raise FileImportError('无法解析 PDF，文件可能已损坏或使用了不支持的加密方式') from exc


def _docx_text(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > 20 * 1024 * 1024:
                raise FileImportError('Word 文档内容过大，请拆分后上传')
            xml = archive.read(info)
        if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
            raise FileImportError('Word 文档包含不支持的 XML 声明')
        root = ElementTree.fromstring(xml)
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        parts = []
        for paragraph in root.iter(ns + 'p'):
            line = ''.join(n.text or '' if n.tag == ns + 't' else '\t' if n.tag == ns + 'tab' else '\n' if n.tag in {ns + 'br', ns + 'cr'} else '' for n in paragraph.iter())
            if line.strip():
                parts.append(line)
        return '\n'.join(parts)
    except FileImportError:
        raise
    except (BadZipFile, KeyError, ElementTree.ParseError, RuntimeError, OSError) as exc:
        raise FileImportError('无法解析 Word 文档，请确认上传的是有效的 DOCX 文件（不支持旧版 DOC）') from exc
