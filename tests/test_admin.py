"""管理员闭环：鉴权、真实问答诊断、标准答复增量索引与可回退版本。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from sufe_qa.app.server import create_app
from sufe_qa.config import Settings, load_settings
from sufe_qa.generate.client import FakeLLM
from sufe_qa.indexing.indexer import FakeEmbedder, update_index
from sufe_qa.ingest.inbox import ingest_inbox
from sufe_qa.retrieve.retriever import HybridRetriever
from sufe_qa.schema import doc_id_from, load_manifest

SOURCE_URL = "https://jwc.sufe.edu.cn/official/scholarship-policy.htm"
DOC = (
    "# 奖学金申请办法\n\n第一条 奖学金申请人应当遵守校纪校规，完成规定课程，"
    "并在规定期限内向学院提交申请表和成绩证明。评审结果由学院公示。\n"
) * 4
QUESTION = "奖学金申请人应满足什么条件并提交哪些材料？"


@dataclass
class AdminEnv:
    client: TestClient
    settings: Settings
    source_doc_id: str
    headers: dict[str, str]


@pytest.fixture
def admin_env(tmp_path, monkeypatch) -> AdminEnv:
    monkeypatch.setenv("SUFE_QA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SUFE_QA_ADMIN_TOKEN", "admin-secret")
    settings = load_settings()
    source = settings.inbox_dir / "scholarship.md"
    source.write_text(DOC, encoding="utf-8")
    ingest_inbox(
        settings.inbox_dir,
        settings.corpus_dir,
        settings.manifest_path,
        "奖助学金",
        "上海财经大学教务处",
        {source.name: SOURCE_URL},
    )
    embedder = FakeEmbedder()
    update_index(settings, embedder)
    app = create_app(
        settings,
        retriever=HybridRetriever(settings, embedder),
        llm=FakeLLM(1),
    )
    return AdminEnv(
        client=TestClient(app),
        settings=settings,
        source_doc_id=doc_id_from(SOURCE_URL),
        headers={"Authorization": "Bearer admin-secret"},
    )


def test_admin_requires_token_and_serves_no_build_dashboard(admin_env: AdminEnv):
    assert admin_env.client.get("/admin").status_code == 200
    assert admin_env.client.get("/api/admin/overview").status_code == 401
    assert (
        admin_env.client.get(
            "/api/admin/overview", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    overview = admin_env.client.get("/api/admin/overview", headers=admin_env.headers).json()
    assert overview["counts"]["documents"] == 1
    assert overview["freshness"]["index_matches_manifest"] is True

    script = admin_env.client.get("/static/admin.js").text
    page = admin_env.client.get("/admin").text
    assert "/api/admin/debug" in script
    assert "/api/admin/answers" in script
    assert "/api/admin/wechat/import" in script
    assert "innerHTML" not in script
    assert "问答诊室" in page and "保存并增量索引" in page


def test_curated_answer_is_incremental_traceable_and_versioned(admin_env: AdminEnv):
    debug = admin_env.client.post(
        "/api/admin/debug",
        headers=admin_env.headers,
        json={"question": QUESTION},
    )
    assert debug.status_code == 200
    assert debug.json()["refused"] is False
    assert debug.json()["citation_check"]["ok"] is True
    assert admin_env.source_doc_id in {hit["doc_id"] for hit in debug.json()["hits"]}

    base = {
        "question": QUESTION,
        "category": "奖助学金",
        "editor": "测试维护员",
        "source_doc_ids": [admin_env.source_doc_id],
    }
    first = admin_env.client.post(
        "/api/admin/answers",
        headers=admin_env.headers,
        json={**base, "answer": "申请人须遵守校纪校规并完成规定课程，按期提交申请表和成绩证明。"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["index"]["added_docs"] == 1
    answer_doc_id = first.json()["document"]["doc_id"]
    first_hash = first.json()["document"]["content_hash"]

    second = admin_env.client.post(
        "/api/admin/answers",
        headers=admin_env.headers,
        json={
            **base,
            "answer": "申请人须遵守校纪校规、完成规定课程，并在规定期限内提交申请表与成绩证明；结果由学院公示。",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["index"]["updated_docs"] == 1
    assert second.json()["document"]["source_url"] == SOURCE_URL

    detail = admin_env.client.get(
        f"/api/admin/documents/{answer_doc_id}", headers=admin_env.headers
    ).json()
    assert len(detail["history"]) == 2
    old = next(version for version in detail["history"] if version["content_hash"] == first_hash)
    assert old["version_available"] is True
    version = admin_env.client.get(
        f"/api/admin/documents/{answer_doc_id}/versions/{first_hash}",
        headers=admin_env.headers,
    )
    assert version.status_code == 200
    assert "申请表和成绩证明" in version.json()["content"]

    rollback = admin_env.client.post(
        f"/api/admin/documents/{answer_doc_id}/action",
        headers=admin_env.headers,
        json={"action": "rollback", "reason": "复核后恢复上一版", "version_hash": first_hash},
    )
    assert rollback.status_code == 200, rollback.text
    assert load_manifest(admin_env.settings.manifest_path)[answer_doc_id].content_hash == first_hash


def test_wechat_reject_detail_is_actionable():
    from sufe_qa.app.admin import _wechat_reject_detail

    class _Report:
        def __init__(self, decisions, status="ok"):
            self.decisions = decisions
            self.discovery_status = status

    detail = _wechat_reject_detail(
        _Report([{"decision": "reject", "reason": "not_whitelisted", "account": "上财就业CEPC"}])
    )
    assert "上财就业CEPC" in detail and "白名单" in detail and "仍要导入" in detail
    assert "not_whitelisted" not in detail

    detail = _wechat_reject_detail(_Report([{"decision": "reject", "reason": "too_old"}]))
    assert "2024-01-01" in detail

    detail = _wechat_reject_detail(_Report([], status="auth_required"))
    assert "auth_required" in detail  # 未知状态码兜底透出，便于排查


def test_import_boundaries_and_pending_changes_block_hotfix(admin_env: AdminEnv):
    invalid_wechat = admin_env.client.post(
        "/api/admin/wechat/import",
        headers=admin_env.headers,
        json={"url": "https://example.com/not-wechat/article"},
    )
    assert invalid_wechat.status_code == 422

    imported = admin_env.client.post(
        "/api/admin/import",
        params={
            "filename": "new-rule.md",
            "category": "学工事务",
            "publisher": "上海财经大学学生工作部",
            "source_url": "https://student.sufe.edu.cn/new-rule.htm",
        },
        content="# 新办事规则\n\n学生应在线提交申请材料，等待学院审核。",
        headers={**admin_env.headers, "Content-Type": "application/octet-stream"},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["document"]["is_searchable"] is True

    blocked = admin_env.client.post(
        "/api/admin/answers",
        headers=admin_env.headers,
        json={
            "question": QUESTION,
            "answer": "这是一条不会被夹带发布的人工答案正文。",
            "category": "奖助学金",
            "editor": "测试维护员",
            "source_doc_ids": [admin_env.source_doc_id],
        },
    )
    assert blocked.status_code == 409
    assert "未发布变更" in blocked.json()["detail"]
