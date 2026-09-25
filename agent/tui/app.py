"""btop 风格 Agent TUI：左任务列表 / 中当前任务节点 / 底栏小人。"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Static

from .snapshot import build_view_model
from .status import TaskRow

# 小帧像素风搬砖（不含地面，地面按舞台宽度单独画）
_WORKER_FRAMES_RIGHT = (
    "  .-.  \n"
    " (o o) \n"
    " /|\\▓▓ \n"
    " / \\   ",
    "  .-.  \n"
    " (o o) \n"
    " /|\\▓▓ \n"
    "  >\\   ",
    "  .-.  \n"
    " (o o) \n"
    " /|\\▓▓ \n"
    " / \\   ",
    "  .-.  \n"
    " (o o) \n"
    " /|\\▓▓ \n"
    " /<    ",
)

_WORKER_FRAMES_LEFT = (
    "  .-.  \n"
    " (o o) \n"
    " ▓▓/|\\ \n"
    "   / \\ ",
    "  .-.  \n"
    " (o o) \n"
    " ▓▓/|\\ \n"
    "   /<  ",
    "  .-.  \n"
    " (o o) \n"
    " ▓▓/|\\ \n"
    "   / \\ ",
    "  .-.  \n"
    " (o o) \n"
    " ▓▓/|\\ \n"
    "   >/  ",
)

_WAITING_DOTS = ("●○○", "○●○", "○○●")

_PHASE_MARK = {
    "running": ">",
    "pending": ".",
    "deferred": "~",
    "done": "*",
    "disabled": "x",
}

_SPRITE_WIDTH = 7


def _format_task_list(rows: list[TaskRow]) -> str:
    if not rows:
        return "[dim]等待任务计划…[/]"
    lines: list[str] = []
    for row in rows:
        mark = _PHASE_MARK.get(row.phase, ".")
        detail = f" [dim]{row.detail}[/]" if row.detail else ""
        if row.phase == "running":
            lines.append(f"[bold #9ece6a]{mark} {row.name}[/]{detail}")
        elif row.phase == "done":
            lines.append(f"[dim]{mark} {row.name}[/]{detail}")
        elif row.phase == "deferred":
            lines.append(f"[#e0af68]{mark} {row.name}[/]{detail}")
        else:
            lines.append(f"{mark} {row.name}{detail}")
    return "\n".join(lines)


class TaskListPanel(Static):
    rows: reactive[list[TaskRow]] = reactive(list, always_update=True)

    def render(self) -> str:
        return _format_task_list(self.rows)


class CurrentPanel(Static):
    task_name: reactive[str] = reactive("—")
    node_name: reactive[str] = reactive("—")
    agent_phase: reactive[str] = reactive("idle")
    waiting_hint: reactive[str] = reactive("")
    wait_frame: reactive[int] = reactive(0)

    def on_mount(self) -> None:
        self.set_interval(0.35, self._tick_wait)

    def _tick_wait(self) -> None:
        if self.agent_phase == "waiting":
            self.wait_frame = (self.wait_frame + 1) % len(_WAITING_DOTS)

    def render(self) -> str:
        phase = self.agent_phase
        if phase == "waiting":
            dots = f"[#e0af68]{_WAITING_DOTS[self.wait_frame]}[/]"
            phase_line = f"[dim]agent[/] waiting {dots}"
            if self.waiting_hint:
                phase_line += f"\n[#e0af68]{self.waiting_hint}[/]"
        else:
            phase_line = f"[dim]agent[/] {phase}"
        return (
            f"[dim]task[/]\n"
            f"[bold #7aa2f7]{self.task_name}[/]\n"
            f"\n"
            f"[dim]node[/]\n"
            f"[#c0caf5]{self.node_name}[/]\n"
            f"\n"
            f"{phase_line}"
        )


class WorkerStage(Static):
    """底栏：小人走到舞台尽头再回头。"""

    frame_i: reactive[int] = reactive(0)
    going_right: reactive[bool] = reactive(True)
    offset: reactive[int] = reactive(0)

    def on_mount(self) -> None:
        self.set_interval(0.18, self._tick)

    def _max_offset(self) -> int:
        # 内容区宽度；留 1 列边距
        width = max(int(self.size.width) - 2, _SPRITE_WIDTH + 2)
        return max(0, width - _SPRITE_WIDTH)

    def _tick(self) -> None:
        self.frame_i = (self.frame_i + 1) % 4
        max_off = self._max_offset()
        if self.going_right:
            if self.offset >= max_off:
                self.going_right = False
                self.offset = max_off
            else:
                self.offset = min(max_off, self.offset + 1)
        else:
            if self.offset <= 0:
                self.going_right = True
                self.offset = 0
            else:
                self.offset = max(0, self.offset - 1)

    def render(self) -> str:
        max_off = self._max_offset()
        if self.offset > max_off:
            self.offset = max_off
        frames = _WORKER_FRAMES_RIGHT if self.going_right else _WORKER_FRAMES_LEFT
        sprite_lines = frames[self.frame_i].splitlines()
        pad = " " * self.offset
        body = "\n".join(pad + line for line in sprite_lines)
        ground_w = max(int(self.size.width) - 2, _SPRITE_WIDTH + 2)
        ground = "~" * ground_w
        return f"[dim]worker[/]\n[#ff9e64]{body}[/]\n[#565f89]{ground}[/]"


class AgentTuiApp(App[None]):
    """竖屏半窗优先：左列表 / 中当前 / 底动画。"""

    CSS = """
    Screen {
        background: #1a1b26;
        color: #a9b1d6;
        layout: vertical;
    }

    #topbar {
        dock: top;
        height: 1;
        background: #16161e;
        color: #565f89;
        padding: 0 1;
    }

    #body {
        height: 1fr;
        min-height: 12;
    }

    #body > * {
        height: 1fr;
    }

    #task-pane {
        width: 32%;
        min-width: 18;
        max-width: 36;
        border: tall #3b4261;
        background: #16161e;
        padding: 0 1;
    }

    #task-title {
        color: #565f89;
        text-style: bold;
        height: 1;
    }

    #task-list {
        height: 1fr;
        overflow-y: auto;
        scrollbar-size: 1 1;
    }

    #current-pane {
        width: 1fr;
        border: tall #3b4261;
        background: #16161e;
        padding: 1 2;
    }

    #stage {
        dock: bottom;
        height: 9;
        min-height: 7;
        border: tall #3b4261;
        background: #0f0f14;
        padding: 0 1;
    }

    Footer {
        background: #16161e;
        color: #565f89;
    }
    """

    BINDINGS = [
        ("q", "quit", "quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("mr3a  ·  agent", id="topbar")
        with Horizontal(id="body"):
            with Vertical(id="task-pane"):
                yield Static("tasks", id="task-title")
                yield TaskListPanel(id="task-list")
            yield CurrentPanel(id="current-pane")
        yield WorkerStage(id="stage")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.5, self.refresh_status)
        self.refresh_status()

    def refresh_status(self) -> None:
        model = build_view_model()
        status = model["status"]
        tasks: list[TaskRow] = model["tasks"]
        self.query_one("#task-list", TaskListPanel).rows = tasks
        current = self.query_one("#current-pane", CurrentPanel)
        current.task_name = status["task_name"]
        current.node_name = status["node"]
        current.agent_phase = status["phase"]
        current.waiting_hint = status.get("waiting_hint", "")
        phase = status["phase"]
        self.query_one("#topbar", Static).update(f"mr3a  ·  {phase}")
