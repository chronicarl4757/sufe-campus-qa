from sufe_qa.crawler.crawl import Seed, extract_links, load_seeds


def _seed() -> Seed:
    return Seed(
        name="t",
        list_url="https://www.sufe.edu.cn/notice/list.htm",
        link_selector="ul.news_list li a",
        url_prefix="https://www.sufe.edu.cn/",
        category="学工事务",
        publisher="上海财经大学",
        max_pages=2,
    )


def test_extract_links_filters_prefix_and_dedups():
    html = """<ul class="news_list">
      <li><a href="/notice/1.htm">通知一</a></li>
      <li><a href="/notice/1.htm">通知一(重复)</a></li>
      <li><a href="https://evil.com/x">外部</a></li>
      <li><a href="/notice/2.htm">通知二</a></li>
      <li><a href="/notice/3.htm">通知三(超max_pages)</a></li>
    </ul>"""
    links = extract_links(html, _seed())
    assert links == ["https://www.sufe.edu.cn/notice/1.htm", "https://www.sufe.edu.cn/notice/2.htm"]


def test_load_seeds(tmp_path):
    y = tmp_path / "seeds.yaml"
    y.write_text(
        """seeds:
  - name: a
    list_url: "https://www.sufe.edu.cn/x/list.htm"
    link_selector: "li a"
    url_prefix: "https://www.sufe.edu.cn/"
    category: "学工事务"
    publisher: "上海财经大学"
    max_pages: 5
""",
        encoding="utf-8",
    )
    seeds = load_seeds(y)
    assert len(seeds) == 1 and seeds[0].max_pages == 5 and seeds[0].category == "学工事务"


def test_load_seeds_empty(tmp_path):
    y = tmp_path / "seeds.yaml"
    y.write_text("seeds: []\n", encoding="utf-8")
    assert load_seeds(y) == []
