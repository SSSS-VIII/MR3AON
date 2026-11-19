"""仅将原生OCR识别到的任务文字行绑定给后续原生状态识别。"""

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from custom.reco.landlady_qa import box_xywh, iter_ocr_boxes
from utils.logger import logger
from utils.xumi_tasks import task_row_overrides


@AgentServer.custom_action('BindXumiTaskRows')
class BindXumiTaskRows(CustomAction):
    def run(self, context, argv):
        patch = task_row_overrides([(text, box_xywh(box)) for text, box in iter_ocr_boxes(argv.reco_detail)])
        if patch is None:
            logger.warning('须弥幻境未完整识别四项任务文字，拒绝沿用旧行坐标')
            return False
        return context.override_pipeline(patch)
