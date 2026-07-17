from sufe_qa.ingest.splitter import split_document

POLICY = """国家奖学金评审办法

第一条 为规范评审，制定本办法。奖励标准为每生每年8000元。
第二条 申请条件为热爱祖国、遵纪守法、成绩优异。
第三条 评审程序包括个人申请、学院初审、学校终审。
"""


def test_policy_splits_by_article():
    chunks = split_document(POLICY, "doc1", {"title": "国家奖学金评审办法"})
    assert len(chunks) == 4  # 前言(标题行) + 三条
    assert chunks[0].heading_path == ""
    assert chunks[1].heading_path == "第一条"
    assert "8000元" in chunks[1].text
    assert chunks[2].heading_path == "第二条"
    assert all(c.doc_id == "doc1" for c in chunks)
    assert [c.chunk_id for c in chunks] == ["doc1:0", "doc1:1", "doc1:2", "doc1:3"]


def test_plain_text_respects_max_chars():
    text = "这是一段没有结构的正文。" * 200  # ~2400 字
    chunks = split_document(text, "doc2", {}, max_chars=480, overlap=50)
    assert len(chunks) >= 5
    assert all(len(c.text) <= 480 + 50 for c in chunks)
    # 重叠: 相邻块共享尾部/首部片段
    assert chunks[0].text[-20:] in chunks[1].text


def test_metadata_propagated():
    chunks = split_document(POLICY, "doc3", {"title": "t", "category": "奖助学金"})
    assert all(c.metadata["category"] == "奖助学金" for c in chunks)
