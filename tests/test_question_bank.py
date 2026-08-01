from __future__ import annotations

from collections import Counter
from pathlib import Path

from sufe_qa.coverage.question_bank import load_question_bank


QUESTION_BANK = Path("data/eval/sufe_question_bank.jsonl")


def test_question_bank_has_fixed_scene_quota_and_required_fields():
    items = load_question_bank(QUESTION_BANK)
    assert len(items) == 150
    assert Counter(x.scene for x in items) == Counter(
        {
            "本科教务": 20,
            "研究生培养与学位": 20,
            "奖助学金": 15,
            "推免与招生": 15,
            "就业手续": 15,
            "宿舍后勤": 10,
            "信息化与校园卡": 15,
            "图书馆": 10,
            "医疗医保": 10,
            "国际交流": 10,
            "新生与安全": 10,
        }
    )
    assert all(item.status == "unverified" for item in items)
    assert all(item.required_answer_points for item in items)
    assert all(item.expected_domains for item in items)


def test_question_bank_ids_are_unique_and_hash_is_stable():
    first = load_question_bank(QUESTION_BANK)
    second = load_question_bank(QUESTION_BANK)
    assert len({item.id for item in first}) == 150
    assert [item.id for item in first] == [item.id for item in second]
    assert first.version == "sufe-question-bank.v1"
    assert first.content_hash == second.content_hash
