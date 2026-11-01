# -*- coding: utf-8 -*-
"""文本规范化与题库模糊匹配（老板娘问答等）。"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# 中英文标点、括号、空白等（匹配前剥离，避免 OCR 与题库标点差异）
_PUNCT_AND_SPACE_RE = re.compile(
    r"[\s\u3000"
    r"\.,，。！？!?:;；、·…—\-－_"
    r"\(\)（）\[\]【】「」『』〈〉《》"
    r"\"'""''`~@#$%^&*+=|\\/<>]+"
)

# 保留中文、字母、数字（游戏内英文如 freestyle、3v3）
_CORE_CHARS_RE = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]+")

_MIN_SUBSTRING_LEN = 8

# 答题回合题头，如「第1/10问:」；答错后的解析区不含此字样
_QUESTION_ROUND_RE = re.compile(r"第\s*\d+\s*/\s*\d+\s*问")
_QUESTION_HEADER_STRIP_RE = re.compile(
    r"第\s*\d+\s*/\s*\d+\s*问\s*[:：]?\s*"
)

# 选项前缀：A. / B. / A、 等（学题 OCR 常见）
_OPTION_LABEL_PREFIX_RE = re.compile(
    r"^[A-Da-d]\s*[\.．、:：\)]\s*"
)


@dataclass(frozen=True)
class QaEntry:
    question: str
    answer: str
    core_question: str
    core_answer: str


@dataclass(frozen=True)
class QuestionMatch:
    entry: QaEntry
    score: float
    method: str  # exact | substring | fuzzy


@dataclass(frozen=True)
class AnswerBoxMatch:
    box: Any
    text: str
    score: float
    method: str  # exact | substring | fuzzy | contains


def normalize_text(text: str) -> str:
    """NFKC + 去标点空白 + 小写（仅影响英文）。"""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = _PUNCT_AND_SPACE_RE.sub("", s)
    return s.casefold()


def core_text(text: str) -> str:
    """仅保留中文、字母、数字（用于鲁棒比对）。"""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = _CORE_CHARS_RE.sub("", s)
    return s.casefold()


def is_active_question_round(ocr_text: str) -> bool:
    """
    是否为正常出题界面（含「第 x/10 问」题头）。

    答错后题目区会短暂显示解析文案，不含题头，此时应跳过搜库与点击。
    """
    if not ocr_text or not ocr_text.strip():
        return False
    s = unicodedata.normalize("NFKC", ocr_text)
    return _QUESTION_ROUND_RE.search(s) is not None


def strip_option_prefix(text: str) -> str:
    """去掉答案 OCR 开头的选项标号，如 A.忍刀 → 忍刀、B.300 → 300。"""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).strip()
    return _OPTION_LABEL_PREFIX_RE.sub("", s, count=1).strip()


def extract_question_body(ocr_text: str) -> str:
    """
    从 OCR 原文去掉「第1/10问:」类题头，得到可与题库比对的题干。

    若未匹配到题头，返回规范化后的全文（调用方应先判断 is_active_question_round）。
    """
    if not ocr_text:
        return ""
    s = unicodedata.normalize("NFKC", ocr_text).strip()
    m = _QUESTION_HEADER_STRIP_RE.search(s)
    if m:
        return s[m.end() :].strip()
    return s


def _resolve_db_path(db_path: str) -> Path:
    rel = Path(db_path.strip())
    import os
    if os.environ.get("MR3A_WORK_ROOT") and not rel.is_absolute() and rel.parts[:2] == ("resource", "data"):
        from utils.runtime_paths import get_runtime_paths
        return get_runtime_paths().data_dir.joinpath(*rel.parts[2:])
    if rel.is_file():
        return rel.resolve()

    agent_dir = Path(__file__).resolve().parent.parent
    project_root = agent_dir.parent
    candidates = [
        Path.cwd() / rel,
        Path.cwd() / "assets" / rel,
        project_root / "assets" / rel,
        project_root / rel,
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    raise FileNotFoundError(
        f"问答题库不存在: {db_path!r}（已尝试 cwd、assets、项目根）"
    )


@lru_cache(maxsize=4)
def load_qa_db_cached(resolved_path_str: str) -> Tuple[QaEntry, ...]:
    path = Path(resolved_path_str)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"问答题库须为 JSON 数组: {path}")

    entries: List[QaEntry] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"问答题库[{i}] 须为对象")
        q = item.get("问题")
        a = item.get("答案")
        if not isinstance(q, str) or not isinstance(a, str):
            raise ValueError(f"问答题库[{i}] 缺少非空字符串字段 问题/答案")
        q, a = q.strip(), a.strip()
        if not q or not a:
            raise ValueError(f"问答题库[{i}] 问题或答案为空")
        entries.append(
            QaEntry(
                question=q,
                answer=a,
                core_question=core_text(q),
                core_answer=core_text(a),
            )
        )
    if not entries:
        raise ValueError(f"问答题库为空: {path}")
    return tuple(entries)


def load_qa_db(db_path: str = "resource/data/老板娘问答.json") -> Tuple[QaEntry, ...]:
    resolved = _resolve_db_path(db_path)
    return load_qa_db_cached(str(resolved))


def _substring_match(core_ocr: str, entry: QaEntry) -> bool:
    if len(core_ocr) < _MIN_SUBSTRING_LEN and len(entry.core_question) < _MIN_SUBSTRING_LEN:
        return core_ocr == entry.core_question
    if not core_ocr or not entry.core_question:
        return False
    return core_ocr in entry.core_question or entry.core_question in core_ocr


def find_best_question(
    ocr_text: str,
    db: Sequence[QaEntry],
    *,
    min_ratio: float = 0.85,
) -> Optional[QuestionMatch]:
    """
    在题库中匹配题干。

    优先级：core 完全相等 > 子串包含（长度门槛）> SequenceMatcher 模糊（>= min_ratio）。
    """
    core_ocr = core_text(ocr_text)
    if not core_ocr:
        return None

    norm_ocr = normalize_text(ocr_text)

    # 1) core 完全相等
    for entry in db:
        if core_ocr == entry.core_question:
            return QuestionMatch(entry=entry, score=1.0, method="exact")

    # 2) normalize 完全相等（兜底 core 与 normalize 边界情况）
    if norm_ocr:
        for entry in db:
            if norm_ocr == normalize_text(entry.question):
                return QuestionMatch(entry=entry, score=1.0, method="exact")

    # 3) 子串
    substring_hits: List[QuestionMatch] = []
    for entry in db:
        if _substring_match(core_ocr, entry):
            # 越长越可信（完整题干优先）
            overlap = min(len(core_ocr), len(entry.core_question))
            score = overlap / max(len(entry.core_question), 1)
            substring_hits.append(
                QuestionMatch(entry=entry, score=score, method="substring")
            )
    if substring_hits:
        return max(substring_hits, key=lambda m: (m.score, len(m.entry.core_question)))

    # 4) 模糊
    best: Optional[QuestionMatch] = None
    for entry in db:
        ratio = SequenceMatcher(None, core_ocr, entry.core_question).ratio()
        if ratio >= min_ratio and (best is None or ratio > best.score):
            best = QuestionMatch(entry=entry, score=ratio, method="fuzzy")
    return best


def _score_answer_text(
    option_text: str,
    target_answer: str,
    *,
    min_ratio: float,
) -> Optional[Tuple[float, str]]:
    """返回 (score, method) 或 None。"""
    core_opt = core_text(option_text)
    core_ans = core_text(target_answer)
    if not core_opt or not core_ans:
        return None

    if core_opt == core_ans:
        return 1.0, "exact"
    if core_ans in core_opt or core_opt in core_ans:
        overlap = min(len(core_opt), len(core_ans)) / max(len(core_ans), 1)
        return max(overlap, 0.9), "substring"

    ratio = SequenceMatcher(None, core_opt, core_ans).ratio()
    if ratio >= min_ratio:
        return ratio, "fuzzy"
    return None


def find_best_answer_box(
    ocr_items: Sequence[Tuple[str, Any]],
    target_answer: str,
    *,
    min_ratio: float = 0.78,
) -> Optional[AnswerBoxMatch]:
    """
    在 (text, box) 列表中找与目标答案最匹配的项。

    ocr_items: OCR 各行/各框文本与包围盒。
    """
    if not ocr_items or not target_answer.strip():
        return None

    best: Optional[AnswerBoxMatch] = None
    for text, box in ocr_items:
        if box is None:
            continue
        scored = _score_answer_text(text, target_answer, min_ratio=min_ratio)
        if scored is None:
            continue
        score, method = scored
        if best is None or score > best.score:
            best = AnswerBoxMatch(box=box, text=text, score=score, method=method)
    return best


def join_ocr_lines(
    items: Sequence[Tuple[str, Any]],
    *,
    line_y_tolerance: int = 12,
) -> str:
    """按阅读顺序拼接多框 OCR 文本（用于题干）。"""
    if not items:
        return ""

    def sort_key(item: Tuple[str, Any]) -> Tuple[int, int]:
        text, box = item
        _ = text
        y, x = _box_top_left(box)
        return y, x

    sorted_items = sorted(items, key=sort_key)
    lines: List[str] = []
    current_line: List[str] = []
    current_y: Optional[int] = None

    for text, box in sorted_items:
        t = (text or "").strip()
        if not t:
            continue
        y, _ = _box_top_left(box)
        if current_y is None or abs(y - current_y) <= line_y_tolerance:
            current_line.append(t)
            if current_y is None:
                current_y = y
        else:
            lines.append("".join(current_line))
            current_line = [t]
            current_y = y
    if current_line:
        lines.append("".join(current_line))
    return "".join(lines)


def _box_top_left(box: Any) -> Tuple[int, int]:
    if box is None:
        return 0, 0
    if isinstance(box, (list, tuple)) and len(box) >= 2:
        return int(box[1]), int(box[0])
    if isinstance(box, dict):
        return int(box.get("y", 0)), int(box.get("x", 0))
    y = int(getattr(box, "y", 0))
    x = int(getattr(box, "x", 0))
    return y, x


def clear_qa_db_cache() -> None:
    """测试或热重载时清空题库缓存。"""
    load_qa_db_cached.cache_clear()


def append_qa_entry(
    db_path: str,
    question: str,
    answer: str,
    *,
    on_duplicate: str = "update",
) -> tuple[bool, int]:
    """
    向题库 JSON 追加或更新一条问答。

    Returns:
        (is_new, total_count) — is_new 为 True 表示新增，False 表示更新已有题干。
    """
    q = question.strip()
    a = answer.strip()
    if not q or not a:
        raise ValueError("问题或答案为空")

    resolved = _resolve_db_path(db_path)
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"问答题库须为 JSON 数组: {resolved}")

    core_q = core_text(q)
    is_new = True
    for item in raw:
        if not isinstance(item, dict):
            continue
        existing_q = item.get("问题", "")
        if isinstance(existing_q, str) and core_text(existing_q) == core_q:
            is_new = False
            if on_duplicate == "update":
                item["问题"] = q
                item["答案"] = a
            break
    else:
        raw.append({"问题": q, "答案": a})

    if not is_new and on_duplicate == "skip":
        clear_qa_db_cache()
        return False, len(raw)

    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.write_text(
        json.dumps(raw, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    tmp.replace(resolved)
    clear_qa_db_cache()
    return is_new, len(raw)
