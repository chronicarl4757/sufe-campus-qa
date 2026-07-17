import pytest

from sufe_qa.ingest.parsers import parse_file, parse_html


def test_parse_html_extracts_text_and_title():
    html = """<html><head><title>关于开展2025年奖学金评审的通知</title></head>
    <body><article><p>各学院：现将评审安排通知如下。</p><p>申请条件如下。</p></article></body></html>"""
    doc = parse_html(html, "fallback")
    assert "申请条件" in doc.text
    assert "奖学金" in doc.title


def test_parse_pdf(tmp_path):
    import fitz

    p = tmp_path / "rule.pdf"
    d = fitz.open()
    page = d.new_page()
    # 默认 helv 字体不含 CJK 字形，需指定内置中文字体，否则写入的是乱码
    page.insert_text((72, 72), "第一条 本办法适用于全日制在校生。", fontname="china-s")
    d.save(str(p))
    d.close()
    doc = parse_file(p)
    assert "第一条" in doc.text
    assert doc.title == "rule"


def test_parse_docx(tmp_path):
    from docx import Document

    p = tmp_path / "notice.docx"
    d = Document()
    d.add_paragraph("推免工作将于九月启动。")
    d.save(str(p))
    doc = parse_file(p)
    assert "推免" in doc.text


def test_parse_md_passthrough(tmp_path):
    p = tmp_path / "note.md"
    p.write_text("# 学工指南\n内容正文。", encoding="utf-8")
    doc = parse_file(p)
    assert "学工指南" in doc.text
    assert doc.title == "学工指南"  # md 以首个一级标题为文档标题


def test_unsupported_suffix(tmp_path):
    p = tmp_path / "a.exe"
    p.write_bytes(b"x")
    with pytest.raises(ValueError, match="不支持"):
        parse_file(p)


def test_parse_html_gbk_fallback(tmp_path):
    html = "<html><head><title>奖学金通知</title></head><body><p>申请条件如下</p></body></html>"
    p = tmp_path / "gbk.html"
    p.write_bytes(html.encode("gb18030"))
    doc = parse_file(p)
    assert "申请条件" in doc.text


def test_parse_docx_includes_tables(tmp_path):
    from docx import Document

    p = tmp_path / "table.docx"
    d = Document()
    d.add_paragraph("标准如下：")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "国家奖学金"
    t.rows[0].cells[1].text = "8000元"
    d.save(str(p))
    doc = parse_file(p)
    assert "8000元" in doc.text


def test_corrupt_pdf_raises_parse_error(tmp_path):
    from sufe_qa.ingest.parsers import ParseError

    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not a pdf at all")
    with pytest.raises(ParseError):
        parse_file(p)
