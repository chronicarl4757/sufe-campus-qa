"""语料库治理：2026-08-31 人工审读结论 + 可重跑的幂等清理。

四类动作，全部走 manifest 追加（可逆，admin dashboard 可恢复）：
  A. 隔离审读确认的垃圾/误导/指针/悬空文档（QUARANTINE 清单）
  B. 无信息量标题改标题（RETITLE 清单）
  C. 空 text_hash 回填（仅 article 且正文可按落盘格式精确复算）
  D. 同 text_hash 重复组隔离多余副本（动态重算；空正文 hash 组排除，防跨主题误并）
  E. dedup 副作用修复：留存副本所在系列无 active 成员时提升最新副本（含附件连带）；
     指针页文章降 historical（内容在附件，系列 active 由附件承担）
  F. 人工确认的被取代旧版标记 superseded（SUPERSEDED 清单）
  G. 附件多父关系修复（RELINK 清单：被隔离副本的父文章改挂留存副本）

用法：.venv/bin/python scripts/corpus_governance.py [--apply]
"""

import collections
import json
import re
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from sufe_qa.schema import append_manifest, load_manifest, sha256_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CORPUS = DATA / "corpus"
MANIFEST = CORPUS / "manifest.jsonl"
ADMIN_LOG = DATA / "admin_actions.jsonl"

ALLOW_MAIN = {"policy", "procedure", "faq", "annual_notice", "form", "manual", "service_guide"}
GENERIC = {
    "联系我们",
    "通知",
    "公告",
    "人才培养",
    "常见问答",
    "招生简章",
    "政策文件",
    "实习招聘",
    "办事指南",
    "首页",
    "简介",
    "就业指导",
    "学生工作",
    "学院动态",
    "新闻中心",
    "下载专区",
    "服务指南",
    "规章制度",
    "办事流程",
    "工作流程",
}

# A. 2026-08-31 逐篇审读后的隔离清单：doc_id -> 理由
QUARANTINE = {
    # 财税投资学院"联系我们"：实为 2013 年就业活动/选聘/转档新闻，标题全错
    "4411db3c1323": "审读:标题《联系我们》实为2013德勤招聘活动新闻,错标题+陈旧",
    "4dc8cf707b4f": "审读:标题《联系我们》实为2013村官选聘通知,错标题+陈旧",
    "b22668ebe1d5": "审读:标题《联系我们》实为2013西部基层计划启事,错标题+陈旧",
    "f3bb8684dab0": "审读:标题《联系我们》实为2013转档通知,错标题+陈旧",
    # 统计学院"人才培养"：实为学院新闻(答辩/讲座/年级大会),kind=procedure 误标
    "448bb4756bea": "审读:标题《人才培养》实为2024结项答辩新闻,误标procedure",
    "647a102e5788": "审读:标题《人才培养》实为2024讲座新闻,误标procedure",
    "a627259c4687": "审读:标题《人才培养》实为2025答辩新闻,误标procedure",
    "a926c37d06a5": "审读:标题《人才培养》实为2025年级大会新闻,误标procedure",
    "b64f5fa6b3c5": "审读:标题《人才培养》实为2025讲座新闻,误标procedure",
    # 保卫处栏目名当标题，2012 年征兵文件，内容已被更新的征兵/兵役文档覆盖
    "5c8241801dd8": "审读:栏目名《保卫处》当标题,2012征兵实施意见,陈旧",
    "7f8293cb80ec": "审读:栏目名《保卫处》当标题,2012征兵通知,陈旧",
    # 学生处指针页：正文仅"通知详见上财门户通知公告"，无实质内容
    "2f80874fece8": "审读:指针页,正文仅指向门户通知公告,无实质内容",
    "4ab5f593f243": "审读:指针页,正文仅指向门户通知公告,无实质内容",
    # jwc 5124 栏目导航页本身入库（其附件已独立成文）
    "b73dbd658c3b": "审读:栏目导航清单页,无正文,导航污染",
    # manifest 有记录但正文文件缺失的悬空条目
    "4b58e478089a": "审读:正文文件缺失的悬空记录",
    "ff90e9bf1db5": "审读:正文文件缺失的悬空记录(2009献血通知)",
    # 双专业 PDF 文本层乱码（标题词堆叠），有效内容已被学籍细则2026版与双学位管理.pdf 覆盖
    "8141859d06df": "审读:PDF文本层乱码,有效内容已被学籍细则2026版等覆盖",
}

# B. 改标题（审读正文后给出真实标题）
RETITLE = {
    "13fd1e1e6fc7": "研究生培养机制改革问答",
    "1512eceb29f5": "研究生招生与培养常见问答",
    "4f160abb07bd": "研究生院证件与学籍事务问答（补办/充磁/休学）",
    "e9d1828c895a": "研究生选课与成绩单常见问答",
    "83b8da8365ee": "上海财经大学国家建设高水平大学公派研究生项目实施办法（2008年修订）",
    "d4bfe4be6af5": "图书馆学习空间与座位预约",
    "08eb01ac6a83": "后勤物业服务信息一览（含宿舍报修电话）",
    "b34e7552a58f": "本科生缓考申请工作流程",
}

# F. 人工确认的被取代旧版：(旧版, canonical, 证据)
SUPERSEDED = [
    ("36481bbba58c", "9bca5424fad0", "学籍细则修订稿被2026年4月修订版取代"),
    ("464375c514e3", "9bca5424fad0", "学籍细则修订稿被2026年4月修订版取代"),
    ("89e97075046b", "9bca5424fad0", "学籍细则2024版被2026年4月修订版取代"),
    ("b4836902351f", "9bca5424fad0", "本科生学籍.pdf(2023)被2026年4月修订版取代"),
    ("a03717bf1391", "28429d197c37", "居民医保结算2022版被2024年11月版取代"),
    ("d40c2cbb1e37", "3f22d69747b0", "2023就业第一步被2025届指南第一步取代"),
    ("c1f8ce2e4219", "afe7f43ac179", "2023就业第二步被2025届指南第二步取代"),
    ("dc06d6db272d", "43f455f9817c", "2023就业第三步网签被2026届指南取代"),
    ("a77e8b0aa307", "43f455f9817c", "2024网签更新版被2026届指南第三步取代"),
    ("b491bb69424e", "43f455f9817c", "2025届第三步网签被2026届取代"),
    ("c37e02020907", "8950886eb316", "2025届第三步纸签被2026届取代"),
    (
        "77ae76931224",
        "28daf8b46612",
        "jwc5124现行页选课锚点指向025b73b4版本,本副本为无标签残留链接且周次冲突",
    ),
    ("c5ae3d61e34e", "7b2761bd63af", "推免办法试行版被2025年7月修订版取代"),
    ("da37c087dee9", "7b2761bd63af", "推免办法试行版被2025年7月修订版取代"),
    # 2026-09-01 手动排查补充（均读正文核实版本证据）
    ("898ea30d9184", "1f5aa08edc4d", "违纪处分规定2017版(2017-09-01施行)被2023年10月修订版取代"),
    ("caef95227715", "1f5aa08edc4d", "同上(附件)"),
    ("bfe180efaa3d", "4381fd4c2139", "重复率检测试行办法被2025年5月修订正式办法取代"),
    ("fb93dacd6384", "4381fd4c2139", "同上(附件)"),
    ("75094c370868", "59f10253846c", "毕业论文工作规定2018年5月修订被2024年5月修订版取代"),
    ("957b9761a1cb", "59f10253846c", "同上(文章)"),
    ("c845c6bbfc32", "b1710c4f86d0", "2018接收外校推免办法被2019版取代"),
    ("b1710c4f86d0", "2e1d67827a30", "2019接收外校推免办法被2020版取代"),
    ("2e1d67827a30", "e2c59b1cc354", "2020接收外校推免办法被2021版取代"),
    ("7f8b708bab07", "2e6feb1af054", "公共经济与管理学院转专业细则2023被2024版取代"),
    (
        "01e7a801900a",
        "06f44255f23e",
        "校内申诉处理实施细则(2017.6修订)被学生申诉处理实施细则(2017-09-01施行)取代",
    ),
    ("5e968e11f5cd", "06f44255f23e", "同上(文章)"),
]

# G. 附件多父关系修复：被隔离副本的父文章改挂同 binary 留存副本
RELINK = [
    ("d0ad79e7348c", "cc4a93d90c3e", "dedup:同 binary 附件顶替已隔离副本 52a785d3df9c"),
]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _body_from_file(path: Path, title: str) -> str | None:
    """pipeline 落盘格式为 '# {title}\\n\\n{body}\\n'，精确还原 body。"""
    text = path.read_text(encoding="utf-8")
    prefix = f"# {title}\n\n"
    if not text.startswith(prefix):
        return None
    body = text[len(prefix) :]
    if body.endswith("\n"):
        body = body[:-1]
    return body


def main() -> None:
    apply = "--apply" in sys.argv
    latest = load_manifest(MANIFEST)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    actions: list[tuple[str, str, str]] = []
    records = []

    def quarantine(meta, reason):
        records.append(
            replace(
                meta,
                content_hash="",
                file_path="",
                quality_status="quarantined",
                document_kind="incomplete",
                retention_status="archived",
                retention_reason=f"admin_quarantine:{reason}",
                index_collection="none",
                fetched_at=now,
            )
        )
        actions.append((meta.doc_id, "quarantine", reason))

    # ---- A. 审读隔离 ----
    for doc_id, reason in QUARANTINE.items():
        meta = latest.get(doc_id)
        if meta is None or meta.quality_status == "quarantined":
            continue
        quarantine(meta, reason)

    # ---- B. 改标题 ----
    for doc_id, new_title in RETITLE.items():
        meta = latest.get(doc_id)
        if meta is None or doc_id in QUARANTINE or meta.title == new_title:
            continue
        records.append(replace(meta, title=new_title, fetched_at=now))
        actions.append((doc_id, "retitle", f"{meta.title} -> {new_title}"))

    # ---- C. 空 text_hash 回填（仅 article、文件在、格式可还原）----
    backfill_ok = backfill_skip = 0
    for doc_id, meta in latest.items():
        if meta.quality_status != "accepted" or meta.text_hash or doc_id in QUARANTINE:
            continue
        if meta.document_type != "article" or not meta.file_path:
            backfill_skip += 1
            continue
        path = CORPUS / meta.file_path
        if not path.is_file():
            backfill_skip += 1
            continue
        body = _body_from_file(path, meta.title)
        if body is None:
            backfill_skip += 1
            continue
        records.append(replace(meta, text_hash=sha256_text(_squash(body)), fetched_at=now))
        actions.append((doc_id, "backfill_text_hash", ""))
        backfill_ok += 1

    # 用新记录更新 latest 视图
    for rec in records:
        latest[rec.doc_id] = rec

    # ---- D. 重复组隔离多余副本 ----
    EMPTY_HASH = sha256_text("")  # 标题-only 指针页共享空正文 hash，绝不能跨主题误并
    groups: dict[tuple[str, str], list] = collections.defaultdict(list)
    for doc_id, meta in latest.items():
        if meta.quality_status != "accepted" or not meta.text_hash or meta.text_hash == EMPTY_HASH:
            continue
        if meta.document_kind not in ALLOW_MAIN and meta.document_kind != "public_list":
            continue
        groups[(meta.text_hash, meta.document_type)].append(meta)

    def _has_file(m) -> bool:
        return bool(m.file_path) and (CORPUS / m.file_path).is_file()

    def _keeper_key(m):
        title = m.title.strip()
        marketing = ("｜" in title) or title.startswith("【")
        wechat = "mp.weixin.qq.com" in (m.source_url or "")
        return (
            not _has_file(m),  # 有正文文件者优先当 keeper
            title in GENERIC or len(title) <= 4,  # 有信息量标题优先
            wechat,  # 官网原件优先于公众号镜像
            marketing,  # 无营销前缀的干净标题优先
            -len(m.title.strip()),  # 其余相当时标题更具体者优先
            m.fetched_at,
        )

    deduped = 0
    for docs in groups.values():
        docs = [d for d in docs if d.doc_id not in QUARANTINE]
        if len(docs) < 2:
            continue
        docs.sort(key=_keeper_key)
        keeper = docs[0]
        for m in docs[1:]:
            if not _has_file(m):
                quarantine(m, "审读:正文文件缺失的悬空记录")
            else:
                quarantine(m, f"dedup:与《{keeper.title[:30]}》({keeper.doc_id})内容重复")
            deduped += 1
    for rec in records:
        latest[rec.doc_id] = rec

    # ---- E. dedup 副作用修复 ----
    # E1. 本次被 dedup 隔离的文档若隔离前为 active 且留存副本非 active，提升留存副本（含附件连带）
    history: dict[str, list[dict]] = collections.defaultdict(list)
    for line in MANIFEST.open():
        d = json.loads(line)
        history[d["doc_id"]].append(d)
    rels = [json.loads(row) for row in (CORPUS / "relations.jsonl").open()]
    children = collections.defaultdict(list)
    for r in rels:
        if r["relation"] == "attachment_of":
            children[r["parent_doc_id"]].append(r["child_doc_id"])

    series_groups = collections.defaultdict(list)
    for doc_id, meta in latest.items():
        if meta.quality_status != "accepted":
            continue
        key = meta.series_key or (f"hash:{meta.text_hash}" if meta.text_hash else None)
        if key:
            series_groups[key].append(meta)

    promoted = 0
    dedup_quarantined = [
        (doc_id, reason)
        for doc_id, action, reason in actions
        if action == "quarantine" and reason.startswith("dedup:")
    ]
    for doc_id, reason in dedup_quarantined:
        rows = history.get(doc_id, [])
        before = rows[-1] if rows else None
        if not before or before.get("retention_status") != "active":
            continue
        m = re.search(r"\(([0-9a-f]{12})\)", reason)
        if not m:
            continue
        kept = latest.get(m.group(1))
        if not kept or kept.quality_status != "accepted" or kept.retention_status == "active":
            continue
        key = kept.series_key or f"hash:{kept.text_hash}"
        members = series_groups.get(key, [])
        if any(mm.retention_status == "active" for mm in members):
            continue
        records.append(
            replace(
                kept,
                retention_status="active",
                retention_reason="dedup_repair:系列无 active 成员，提升留存副本",
                fetched_at=now,
            )
        )
        actions.append((kept.doc_id, "retention_promote", "dedup_repair"))
        latest[kept.doc_id] = records[-1]
        promoted += 1
        for cid in children.get(kept.doc_id, []):
            cm = latest.get(cid)
            if cm and cm.quality_status == "accepted" and cm.retention_status != "active":
                records.append(
                    replace(
                        cm,
                        retention_status="active",
                        retention_reason="dedup_repair:随主文档提升",
                        fetched_at=now,
                    )
                )
                actions.append((cid, "retention_promote", "dedup_repair:随主文档"))
                latest[cid] = records[-1]
                promoted += 1

    # E2. 已知指针页文章（正文为空壳、内容在附件）降 historical，保持系列唯一 active
    POINTER_ARTICLES = {
        "0d50734f5379": "困难认定通知(指针页,正文在附件77d10806304e)",
        "6c329033183e": "人民奖学金2023-2024(指针页,正文在附件1067b1ad3777)",
        "8e67932f3528": "社会奖学金2023-2024(指针页,正文在附件3cd9009d3563)",
        "98e4a621dcd5": "港澳及华侨奖学金2024(指针页,正文在附件b880d66272a2)",
    }
    demoted = 0
    for doc_id, note in POINTER_ARTICLES.items():
        meta = latest.get(doc_id)
        if not meta or meta.quality_status != "accepted" or meta.retention_status != "active":
            continue
        siblings = [
            m
            for m in series_groups.get(meta.series_key, [])
            if m.doc_id != doc_id and m.retention_status == "active"
        ]
        if not siblings:
            continue
        records.append(
            replace(
                meta,
                retention_status="historical",
                retention_reason=f"dedup_repair:指针页文章({note}),系列active由附件承担",
                fetched_at=now,
            )
        )
        actions.append((doc_id, "retention_demote", note))
        latest[doc_id] = records[-1]
        demoted += 1

    # E3. 系列唯一 active 收敛：同一 series_key 内按“家族”聚簇（同规范化标题 或 父子链接），
    # 簇内多个 active 成员时只留一个（最新年且有实质内容者），其余降 historical。
    #   - 指针页文章+内容附件（父子链接）→ 留附件
    #   - 不同年份的同通知 → 留最新年；最新年是无内容指针而旧年有内容 → 留旧年内容
    #   - 规范化标题不同的独立文章（如“1-6周调课”vs“7-10周调课”）不并簇，不动
    converged = 0

    def _norm_title(t: str) -> str:
        t = re.sub(r"\s+", "", t or "").replace("上海财经大学", "")
        return re.sub(r"20\d{2}年(?:度)?", "", t)

    parent_of = {}
    for r0 in rels:
        if r0["relation"] == "attachment_of":
            parent_of[r0["child_doc_id"]] = r0["parent_doc_id"]

    for key, members in series_groups.items():
        # 只收敛 annual_notice 系列（门禁口径）；public_list 等年度名单本就需要多年共存
        active = [
            m
            for m in members
            if m.retention_status == "active"
            and _has_file(m)
            and m.document_kind == "annual_notice"
        ]
        if len(active) <= 1:
            continue
        # 聚簇：附件按父子链接入父簇；父文章无条件并入其附件簇（父子关系是确定性的）；
        # 无父子关系的独立文章按规范化标题（去年份/校名）归簇
        by_norm: dict[str, list] = collections.defaultdict(list)
        standalone = []
        for m in active:
            if m.document_type == "attachment" and parent_of.get(m.doc_id):
                by_norm[f"parent:{parent_of[m.doc_id]}"].append(m)
            else:
                standalone.append(m)
        for m in standalone:
            kids_key = f"parent:{m.doc_id}"
            if kids_key in by_norm and m not in by_norm[kids_key]:
                by_norm[kids_key].append(m)
            elif not any(m in c for c in by_norm.values()):
                by_norm[f"title:{_norm_title(m.title)}"].append(m)

        def _body_len(m):
            b = _body_from_file(CORPUS / m.file_path, m.title)
            return len(b) if b is not None else 0

        def _year(m):
            # 附件标题常是无年份文件名（硕士生招生.pdf），年份回退到发布日期
            for src in (m.title, m.publish_date or ""):
                mm = re.search(r"20\d{2}", src or "")
                if mm:
                    return int(mm.group(0))
            return 0

        for cluster in by_norm.values():
            cluster = list({m.doc_id: m for m in cluster}.values())
            if len(cluster) <= 1:
                continue
            newest_year = max(_year(m) for m in cluster)
            rich_newest = [m for m in cluster if _year(m) == newest_year and _body_len(m) >= 300]
            if rich_newest:
                # 最新年有实质内容者
                keeper = max(rich_newest, key=_body_len)
            else:
                rich_any = [m for m in cluster if _body_len(m) >= 300]
                if rich_any:
                    # 最新年是无内容指针而旧年有内容 → 留内容最实者
                    keeper = max(rich_any, key=_body_len)
                else:
                    # 全是薄内容：最新年优先
                    keeper = max(cluster, key=lambda m: (_year(m), _body_len(m)))
            for m in cluster:
                if m.doc_id == keeper.doc_id:
                    continue
                reason = (
                    f"series_canonical:系列「{key[-24:]}」active 唯一化，"
                    f"保留《{keeper.title[:24]}》({keeper.doc_id})"
                )
                records.append(
                    replace(
                        m, retention_status="historical", retention_reason=reason, fetched_at=now
                    )
                )
                actions.append((m.doc_id, "series_canonical", reason))
                latest[m.doc_id] = records[-1]
                converged += 1

    # E4. 门禁口径兜底：annual_notice 系列在 E3 簇收敛后仍有多个 active，
    # 且规范化标题（去年份/校名/扩展名）完全一致时，系列级只留最优者
    # （标题不同的同系列独立通知——如“1-6周调课”vs“7-10周调课”——不动）
    e4 = 0

    def _norm4(t: str) -> str:
        t = re.sub(r"\s+", "", t or "").replace("上海财经大学", "")
        t = re.sub(r"20\d{2}", "", t)  # 学年区间（2024-2025学年）整体抹掉
        return re.sub(r"\.(pdf|docx?|xlsx?)$", "", t, flags=re.I)

    for key, members in series_groups.items():
        active = []
        for m0 in members:
            m = latest.get(m0.doc_id)
            if (
                m
                and m.quality_status == "accepted"
                and m.retention_status == "active"
                and m.document_kind == "annual_notice"
                and _has_file(m)
            ):
                active.append(m)
        if len(active) <= 1:
            continue
        if len({_norm4(m.title) for m in active}) > 1:
            continue

        def _body_len4(m):
            b = _body_from_file(CORPUS / m.file_path, m.title)
            return len(b) if b is not None else 0

        def _year4(m):
            for src in (m.title, m.publish_date or ""):
                mm = re.search(r"20\d{2}", src or "")
                if mm:
                    return int(mm.group(0))
            return 0

        newest_year = max(_year4(m) for m in active)
        rich_newest = [m for m in active if _year4(m) == newest_year and _body_len4(m) >= 300]
        if rich_newest:
            keeper = max(rich_newest, key=_body_len4)
        else:
            rich_any = [m for m in active if _body_len4(m) >= 300]
            # 有内容者优先（同有内容取最新年），全是指针才取最新年
            keeper = (
                max(rich_any, key=lambda m: (_year4(m), _body_len4(m)))
                if rich_any
                else max(active, key=lambda m: (_year4(m), _body_len4(m)))
            )
        for m in active:
            if m.doc_id == keeper.doc_id:
                continue
            reason = (
                f"series_canonical:年度系列「{key[-24:]}」唯一 active 兜底，"
                f"保留《{keeper.title[:24]}》({keeper.doc_id})"
            )
            records.append(
                replace(m, retention_status="historical", retention_reason=reason, fetched_at=now)
            )
            actions.append((m.doc_id, "series_canonical", reason))
            latest[m.doc_id] = records[-1]
            e4 += 1

    # ---- F. 被取代旧版 ----
    superseded_n = 0
    for old_id, new_id, evidence in SUPERSEDED:
        old = latest.get(old_id)
        new = latest.get(new_id)
        if old is None or new is None or old.quality_status != "accepted":
            continue
        if old.validity_status == "superseded":
            continue
        records.append(
            replace(
                old,
                validity_status="superseded",
                superseded_by=(new_id,),
                validity_evidence=evidence,
                fetched_at=now,
            )
        )
        actions.append((old_id, "mark_superseded", evidence))
        superseded_n += 1

    # ---- H. 标准答复依赖失效传播 ----
    # curated 标准答复（topic_key=curated.answer.*）经 derived_from 依赖官方资料；
    # 任一依据被取代/隔离/下架后，答复降为 unknown_validity 待人工复核（管理端重新确认恢复）
    stale_n = 0
    derived_children = collections.defaultdict(list)
    derived_hash: dict[tuple[str, str], str] = {}
    for r in rels:
        if r["relation"] == "derived_from":
            derived_children[r["child_doc_id"]].append(r["parent_doc_id"])
            m = re.search(r"source_content_hash:(\S+)", r.get("evidence", ""))
            if m:
                derived_hash[(r["child_doc_id"], r["parent_doc_id"])] = m.group(1)
    for meta in list(latest.values()):
        if not meta.topic_key.startswith("curated.answer."):
            continue
        if meta.quality_status != "accepted" or meta.validity_status != "current":
            continue
        parents = [latest.get(pid) for pid in derived_children.get(meta.doc_id, [])]
        bad = [
            p
            for p in parents
            if p is None
            or p.quality_status != "accepted"
            or p.retention_status != "active"
            or p.validity_status in {"superseded", "historical"}
            # 同 URL 正文换版也算失效：核验时记录的快照 hash 与当前不一致
            or (
                derived_hash.get((meta.doc_id, p.doc_id)) is not None
                and derived_hash[(meta.doc_id, p.doc_id)] != p.content_hash
            )
        ]
        if not bad:
            continue
        records.append(
            replace(
                meta,
                validity_status="unknown_validity",
                validity_confidence=0.0,
                validity_evidence="依赖资料失效，待人工复核",
                retention_reason=f"dependency_stale:{','.join(p.doc_id[:8] for p in bad if p)}",
                fetched_at=now,
            )
        )
        actions.append((meta.doc_id, "dependency_stale", meta.title[:40]))
        stale_n += 1

    # ---- 汇总 ----
    print(
        f"A 隔离审读垃圾: {sum(1 for a in actions if a[1] == 'quarantine' and not a[2].startswith('dedup'))}"
    )
    print(f"B 改标题: {sum(1 for a in actions if a[1] == 'retitle')}")
    print(f"C 回填 text_hash: {backfill_ok}（跳过 {backfill_skip}）")
    print(f"D 去重隔离: {deduped}")
    print(
        f"E1 提升 active: {promoted} | E2 指针页降级: {demoted} | E3 系列收敛: {converged} | E4 兜底: {e4}"
    )
    print(f"F 标记旧版: {superseded_n} | H 依赖失效: {stale_n}")
    print(f"manifest 追加记录总数: {len(records)}")
    if not apply:
        print("DRY-RUN，加 --apply 生效")
        return

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(MANIFEST, CORPUS / f"manifest.jsonl.bak-{ts}")
    append_manifest(MANIFEST, records)
    # G. 多父关系修复（幂等：已存在则跳过）
    existing = {(r["parent_doc_id"], r["child_doc_id"]) for r in rels}
    with (CORPUS / "relations.jsonl").open("a", encoding="utf-8") as fh:
        for parent, child, evidence in RELINK:
            if (parent, child) in existing:
                continue
            fh.write(
                json.dumps(
                    {
                        "parent_doc_id": parent,
                        "child_doc_id": child,
                        "relation": "attachment_of",
                        "evidence": evidence,
                        "confidence": 1.0,
                        "created_at": now,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    with ADMIN_LOG.open("a", encoding="utf-8") as fh:
        titles = {r.doc_id: r.title for r in records}
        for doc_id, action, reason in actions:
            fh.write(
                json.dumps(
                    {
                        "ts": now,
                        "doc_id": doc_id,
                        "title": titles.get(doc_id, ""),
                        "action": action,
                        "reason": reason,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"已应用。备份: manifest.jsonl.bak-{ts}")


if __name__ == "__main__":
    main()
