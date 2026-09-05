from io import BytesIO
from zipfile import ZipFile
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from server.services.file_import import extract_file, FileImportError, MAX_FILE_BYTES
from server.routes.personal_data import router


def test_chinese_encodings_and_filename():
    for encoding in ['utf-8-sig', 'utf-16', 'gb18030']:
        result = extract_file('C:\\fakepath\\课表.txt', '周五：网络安全'.encode(encoding))
        assert result['source'] == '课表.txt'
        assert result['content'] == '周五：网络安全'


@pytest.mark.parametrize('filename,data', [('bad.exe', b'content'), ('empty.txt', b''), ('bad.pdf', b'fake'), ('bad.docx', b'fake'), ('binary.txt', b'\x00\x01abc')])
def test_invalid_files(filename, data):
    with pytest.raises(FileImportError):
        extract_file(filename, data)


def test_text_and_file_limits():
    with pytest.raises(FileImportError, match='20 万'):
        extract_file('long.txt', b'a' * 200001)
    with pytest.raises(FileImportError, match='10 MB'):
        extract_file('large.txt', b'a' * (MAX_FILE_BYTES + 1))


def test_docx_paragraphs_and_tables():
    buf = BytesIO()
    with ZipFile(buf, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>课程</w:t><w:tab/><w:t>时间</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>周五</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    assert extract_file('sample.docx', buf.getvalue())['content'] == '课程\t时间\n周五'


def test_pdf_empty_and_encrypted():
    for encrypted in [False, True]:
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        if encrypted:
            writer.encrypt('password')
        buf = BytesIO()
        writer.write(buf)
        with pytest.raises(FileImportError, match='加密' if encrypted else '未提取到文字'):
            extract_file('sample.pdf', buf.getvalue())


def test_parse_route_does_not_write_to_rag():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post('/api/personal-data/parse-file', files={'file': ('notes.md', '# 文件上传验收\n星期五实验课'.encode())})
        assert response.status_code == 200
        assert response.json()['source'] == 'notes.md'
        assert '星期五实验课' in response.json()['content']
        assert client.post('/api/personal-data/parse-file', files={'file': ('x.txt', b'x' * (MAX_FILE_BYTES + 1))}).status_code == 413
        assert client.post('/api/personal-data/parse-file', files={'file': ('x.exe', b'bad')}).status_code == 400


def test_pdf_text_extraction():
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 30 100 Td (Campus file import verification) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    buf = BytesIO()
    writer.write(buf)
    assert 'Campus file import verification' in extract_file('valid.pdf', buf.getvalue())['content']
