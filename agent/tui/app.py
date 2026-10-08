"""btop 风格 Agent TUI：左任务列表 / 中当前任务节点 / 底栏小人。"""

from __future__ import annotations

from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from .kitty_image import get_term_image_class, term_image_unavailable_reason
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


class RewardGallery(Vertical):
    """当前任务面板下方：d 打开目录选择 + Kitty TGP 单图；不支持则只提示。"""

    dir_filter: reactive[Optional[str]] = reactive(None)
    index: reactive[int] = reactive(0)
    dirs_open: reactive[bool] = reactive(False)
    _use_kitty: bool = False
    _dirs_fingerprint: str = ""
    _syncing_highlight: bool = False

    def compose(self) -> ComposeResult:
        yield Static(id="reward-meta")
        with Horizontal(id="reward-body"):
            yield OptionList(id="reward-dirs", classes="-textual-compact")
            term_cls = get_term_image_class()
            self._use_kitty = term_cls is not None
            if self._use_kitty:
                yield term_cls(id="reward-main", classes="reward-main")

    def on_mount(self) -> None:
        ol = self.query_one("#reward-dirs", OptionList)
        ol.display = False
        self.refresh_dir_options(force=True)
        self.apply_shots()

    def open_dirs(self) -> None:
        ol = self.query_one("#reward-dirs", OptionList)
        self.refresh_dir_options(force=True)
        ol.display = True
        self.dirs_open = True
        ol.focus()
        self.apply_shots()

    def close_dirs(self) -> None:
        if not self.dirs_open:
            return
        ol = self.query_one("#reward-dirs", OptionList)
        ol.display = False
        self.dirs_open = False
        self.app.set_focus(None)
        self.apply_shots()

    def toggle_dirs(self) -> None:
        if self.dirs_open:
            self.close_dirs()
        else:
            self.open_dirs()

    def refresh_dir_options(self, *, force: bool = False) -> None:
        from custom.reward_shots import listed_dirs

        dirs = listed_dirs()
        fp = f"{self.dir_filter or ''}||{'|'.join(dirs)}"
        ol = self.query_one("#reward-dirs", OptionList)
        if not force and fp == self._dirs_fingerprint and ol.option_count:
            return
        self._dirs_fingerprint = fp
        target = "__all__" if self.dir_filter is None else self.dir_filter
        self._syncing_highlight = True
        try:
            ol.clear_options()
            items: list[tuple[str, str]] = [("全部", "__all__")]
            items.extend((name, name) for name in dirs)
            for label, oid in items:
                if oid == target:
                    # 选中项：主题蓝字，与 task 名一致
                    ol.add_option(Option(f"[#7aa2f7]{label}[/]", id=oid))
                else:
                    ol.add_option(Option(f"[#565f89]{label}[/]", id=oid))
            for i in range(ol.option_count):
                if ol.get_option_at_index(i).id == target:
                    ol.highlighted = i
                    break
        finally:
            self._syncing_highlight = False

    def _apply_dir_option(self, oid: Optional[str]) -> None:
        new_filter = None if oid in (None, "__all__") else str(oid)
        if new_filter == self.dir_filter:
            return
        self.dir_filter = new_filter
        self.index = 0
        self.refresh_dir_options(force=True)
        self.apply_shots()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option_list.id != "reward-dirs":
            return
        self._apply_dir_option(event.option.id)
        self.close_dirs()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if (
            self._syncing_highlight
            or not self.dirs_open
            or event.option_list.id != "reward-dirs"
            or event.option is None
        ):
            return
        self._apply_dir_option(event.option.id)

    def step(self, delta: int) -> None:
        from custom.reward_shots import list_shots

        paths = list_shots(self.dir_filter)
        if not paths:
            self.index = 0
        else:
            self.index = max(0, min(len(paths) - 1, self.index + delta))
        self.apply_shots()

    def apply_shots(self) -> None:
        from custom.reward_shots import gallery_snapshot

        state = gallery_snapshot(self.dir_filter, self.index)
        filt = state.dir_filter or "全部"
        meta = self.query_one("#reward-meta", Static)
        hint = (
            "[dim]↑↓ 选 · enter 定 · d/esc 关[/]"
            if self.dirs_open
            else "[dim]d 目录 · ←/→ 翻图[/]"
        )

        if not self._use_kitty:
            reason = term_image_unavailable_reason() or "未知原因"
            meta.update(
                f"[dim]rewards[/]  {hint}\n"
                f"[#e0af68]不支持显示高清图[/]  [dim]{reason}[/]"
            )
            return

        main = self.query_one("#reward-main")
        if not state.paths:
            meta.update(
                f"[dim]rewards[/]  [#7aa2f7]{filt}[/]  {hint}\n"
                f"[dim]今日尚无奖励截图[/]"
            )
            main.image = None  # type: ignore[attr-defined]
            return

        i = state.index
        path = state.paths[i]
        left_mark = "◀" if i > 0 else " "
        right_mark = "▶" if i + 1 < len(state.paths) else " "
        meta.update(
            f"[dim]rewards[/]  [#7aa2f7]{filt}[/]  {hint}\n"
            f"[dim]{left_mark} {i + 1}/{len(state.paths)} {right_mark}[/]  "
            f"[#c0caf5]{path.parent.name}/{path.name}[/]"
        )
        main.image = path  # type: ignore[attr-defined]


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
        layout: vertical;
    }

    #current-info {
        height: 1fr;
        padding: 1 2;
    }

    /* 游戏截图 1280x720 ≈ 16:9；终端字格约 1:2，横条高度约宽的 28% */
    #reward-gallery {
        dock: bottom;
        height: 14;
        min-height: 12;
        max-height: 16;
        border-top: tall #3b4261;
        background: #0f0f14;
        padding: 0 1;
        layout: vertical;
    }

    #reward-meta {
        height: 2;
        color: #a9b1d6;
    }

    #reward-body {
        height: 10;
        layout: horizontal;
    }

    #reward-dirs {
        width: 14;
        min-width: 10;
        max-width: 18;
        height: 10;
        background: #0f0f14;
        color: #565f89;
        border: none;
        padding: 0 1 0 0;
        scrollbar-size: 1 1;
    }

    #reward-dirs:focus {
        background: #0f0f14;
        background-tint: 0%;
        border: none;
    }

    #reward-dirs > .option-list--option {
        color: #565f89;
        background: #0f0f14;
        padding: 0;
    }

    #reward-dirs > .option-list--option-highlighted {
        color: #7aa2f7;
        background: #0f0f14;
        text-style: none;
    }

    #reward-dirs > .option-list--option-hover {
        color: #c0caf5;
        background: #0f0f14;
    }

    #reward-body .reward-main {
        /* 10 行高 → 约 36 列宽贴合 16:9 */
        width: 36;
        max-width: 1fr;
        height: 10;
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
        ("d", "reward_dirs", "dirs"),
        ("escape", "reward_dirs_close", "close dirs"),
        ("left", "reward_prev", "prev shot"),
        ("right", "reward_next", "next shot"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("mr3a  ·  agent", id="topbar")
        with Horizontal(id="body"):
            with Vertical(id="task-pane"):
                yield Static("tasks", id="task-title")
                yield TaskListPanel(id="task-list")
            with Vertical(id="current-pane"):
                yield CurrentPanel(id="current-info")
                yield RewardGallery(id="reward-gallery")
        yield WorkerStage(id="stage")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.5, self.refresh_status)
        self.refresh_status()

    def action_reward_dirs(self) -> None:
        self.query_one("#reward-gallery", RewardGallery).toggle_dirs()

    def action_reward_dirs_close(self) -> None:
        self.query_one("#reward-gallery", RewardGallery).close_dirs()

    def action_reward_prev(self) -> None:
        self.query_one("#reward-gallery", RewardGallery).step(-1)

    def action_reward_next(self) -> None:
        self.query_one("#reward-gallery", RewardGallery).step(1)

    def refresh_status(self) -> None:
        from .status import runtime_status

        if runtime_status.should_exit():
            self.exit()
            return
        model = build_view_model()
        status = model["status"]
        tasks: list[TaskRow] = model["tasks"]
        self.query_one("#task-list", TaskListPanel).rows = tasks
        current = self.query_one("#current-info", CurrentPanel)
        current.task_name = status["task_name"]
        current.node_name = status["node"]
        current.agent_phase = status["phase"]
        current.waiting_hint = status.get("waiting_hint", "")
        phase = status["phase"]
        self.query_one("#topbar", Static).update(f"mr3a  ·  {phase}")
