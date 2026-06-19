# -*- coding: utf-8 -*-
"""老板娘问答：答错学题入库 + 上报金山文档（CustomAction）。"""

from __future__ import annotations

import json

import requests
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from custom.pipeline_params import parse_pipeline_json_param
from custom.reco.landlady_qa import (
    DEFAULT_DB,
    LEARN_OFFSET,
    NODE_QUESTION,
    QUESTION_ROI,
    match_box,
    ocr_answer_from_icon,
    ocr_roi,
    pop_pending_round,
)
from utils.logger import logger
from utils.text_match import append_qa_entry, extract_question_body, strip_option_prefix

# ==== 金山文档上传配置 ====
_KDOCS_FILE_ID = "crcMio8nY0BC"
_KDOCS_QA_SCRIPT_ID = "V2-4VRu2Hw09Jsfc8WLad2vbL"
_KDOCS_TOKEN = "1NKkJQNwt4yNsLNVTTmnVH"
_KDOCS_QA_SHEET = "老板娘问答"
# ==========================


def _upload_qa_to_kdocs(question: str, answer: str) -> None:
    """上传问答到金山文档（仅开发者参考用，失败不影响主流程）。"""
    if not _KDOCS_FILE_ID or not _KDOCS_QA_SCRIPT_ID or not _KDOCS_TOKEN:
        return

    url = (
        f"https://www.kdocs.cn/api/v3/ide/file/"
        f"{_KDOCS_FILE_ID}/script/{_KDOCS_QA_SCRIPT_ID}/sync_task"
    )
    headers = {
        "Content-Type": "application/json",
        "AirScript-Token": _KDOCS_TOKEN,
    }
    payload = {
        "Context": {
            "argv": {
                "sheetName": _KDOCS_QA_SHEET,
                "rowData": [question, answer],
            }
        }
    }

    try:
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        if resp.status_code != 200:
            logger.warning(f"LandladyQa: 上传金山文档失败 HTTP {resp.status_code}")
        else:
            logger.debug(f"LandladyQa: 已上报金山文档 Q={question!r}")
    except requests.RequestException:
        logger.warning("LandladyQa: 上传金山文档网络异常")


@AgentServer.custom_action("LandladyQaLearnAnswer")
class LandladyQaLearnAnswer(CustomAction):
    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        param = parse_pipeline_json_param(argv.custom_action_param)
        db_path = str(param.get("db_path", DEFAULT_DB)).strip() or DEFAULT_DB
        offset = param.get("target_offset", LEARN_OFFSET)
        if not isinstance(offset, list) or len(offset) != 4:
            return CustomAction.RunResult(success=False)

        rd = argv.reco_detail
        image = context.tasker.controller.cached_image
        if not rd or not rd.hit or rd.box is None or image is None:
            logger.error("LandladyQa learn: 未匹配到选项区「回答正确」图标")
            return CustomAction.RunResult(success=False)

        answer = strip_option_prefix(ocr_answer_from_icon(rd, context, image, offset))
        logger.debug(f"LandladyQa learn: OCR 答案={answer!r} offset={offset}")
        if not answer:
            logger.error(
                f"LandladyQa learn: OCR 答案为空 (icon={match_box(rd)} offset={offset})"
            )
            return CustomAction.RunResult(success=False)

        pending = pop_pending_round()
        if pending and (pending.body or pending.raw):
            question = pending.body or extract_question_body(pending.raw)
            logger.debug(f"LandladyQa learn: 题干来自缓存 {question!r}")
        else:
            question = extract_question_body(
                ocr_roi(context, image, QUESTION_ROI, NODE_QUESTION)
            )
            logger.debug(f"LandladyQa learn: 题干重新 OCR {question!r}")
        if not question:
            logger.error("LandladyQa learn: 无法取得题干")
            return CustomAction.RunResult(success=False)

        on_dup = str(param.get("on_duplicate", "update"))
        try:
            append_qa_entry(db_path, question, answer, on_duplicate=on_dup)
        except (OSError, ValueError) as e:
            logger.error(f"LandladyQa learn: 写入失败 {e}")
            return CustomAction.RunResult(success=False)

        # 上报金山文档（不影响本地写入结果）
        _upload_qa_to_kdocs(question, answer)

        logger.debug(
            f"LandladyQa learn: 已写入 {db_path} Q={question!r} A={answer!r} dup={on_dup}"
        )
        return CustomAction.RunResult(success=True)
