"""Traditional Chinese desktop UI; importing this module never creates a window."""

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from queue import Empty, Queue
import re
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from collections.abc import Callable

from PIL import Image, ImageTk

from .deploy import DeploymentError, deploy, make_qr
from .models import Episode, NewsRequest
from .project import default_project_name, validate_project_name
from .pipeline import build_and_deploy, synthesize_episode
from .script_gen import ScriptGenerationError, generate_script
from .tts import SynthesisError

LOGGER = logging.getLogger("prank_news.gui")
VOICES = {
    "女聲 曉臻": "zh-TW-HsiaoChenNeural",
    "女聲 曉雨": "zh-TW-HsiaoYuNeural",
    "男聲 雲哲": "zh-TW-YunJheNeural",
}
TOPIC_HINT = "例如：他最近在學衝浪、很愛吃臭豆腐（可留空）"
PHONE_HINT = (
    "用 iPhone 相機掃描 → Safari 開啟 → 分享 → 加入主畫面；"
    "打開 App 等到顯示『已可離線收聽』"
)


def parse_names(text: str) -> list[str]:
    """Split ASCII/Chinese commas and ideographic commas, ignoring empty parts."""
    return [name.strip() for name in re.split(r"[,，、]", text) if name.strip()]


def script_character_count(script: str) -> int:
    """Count visible characters (including punctuation), excluding whitespace."""
    return sum(not char.isspace() for char in script)


def estimate_minutes(script: str) -> float:
    return script_character_count(script) / 250


def output_directory(base_dir: str | Path, when: datetime) -> Path:
    """Return a timestamped child path without creating or changing files."""
    return Path(base_dir) / when.strftime("%Y%m%d-%H%M%S-%f")


def configure_logging() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    log_path = base / "PrankNews" / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    return log_path


class PrankNewsWindow:
    def __init__(self, root: tk.Tk, log_path: Path):
        self.root = root
        self.log_path = log_path
        self.events: Queue = Queue()
        self.busy = False
        self.closed = False
        self.episode: Episode | None = None
        self.out_dir: Path | None = None
        self.qr_image: ImageTk.PhotoImage | None = None
        self.locked_widgets: list[tuple[tk.Widget, str]] = []
        root.title("PrankNews 整人新聞製作")
        root.geometry("760x720")
        root.minsize(660, 640)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.names = tk.StringVar()
        self.minutes = tk.StringVar(value="3")
        self.voice = tk.StringVar(value=next(iter(VOICES)))
        self.project = tk.StringVar(value=default_project_name())
        self.show = tk.StringVar()
        self.anchor = tk.StringVar()
        profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        self.base_dir = tk.StringVar(value=str(profile / "Documents" / "PrankNews"))
        self.url = tk.StringVar()
        self.status = tk.StringVar(value="請輸入素材，再按「產生新聞稿」。")
        self.count = tk.StringVar(value="0 字｜預估 0.0 分鐘（250 字／分鐘，不計空白）")
        self._create_widgets()
        for variable in (self.show, self.anchor, self.voice):
            variable.trace_add("write", self._content_changed)
        self.project.trace_add("write", self._project_changed)
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.report_callback_exception = self._callback_error
        self._refresh_buttons()
        self.poll_id = root.after(80, self._poll_events)

    def _lockable(self, widget: tk.Widget, idle_state: str = "normal") -> tk.Widget:
        self.locked_widgets.append((widget, idle_state))
        return widget

    def _create_widgets(self) -> None:
        panel = ttk.Frame(self.root, padding=12)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        inputs = ttk.LabelFrame(panel, text="輸入素材", padding=8)
        inputs.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        inputs.columnconfigure(1, weight=1)
        inputs.columnconfigure(3, weight=1)
        ttk.Label(inputs, text="乘客名字").grid(row=0, column=0, sticky="w")
        self._lockable(ttk.Entry(inputs, textvariable=self.names)).grid(
            row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0))
        ttk.Label(inputs, text="多人請用逗號或頓號分隔，例如：王小明、陳美麗").grid(
            row=1, column=1, columnspan=3, sticky="w")
        ttk.Label(inputs, text="長度（分鐘）").grid(row=2, column=0, sticky="w", pady=4)
        self._lockable(ttk.Spinbox(inputs, from_=0.5, to=15, increment=0.5,
                                 textvariable=self.minutes, width=8)).grid(
            row=2, column=1, sticky="w", padx=8)
        ttk.Label(inputs, text="主播聲音").grid(row=2, column=2, sticky="w")
        self._lockable(ttk.Combobox(inputs, textvariable=self.voice, values=list(VOICES),
                                  state="readonly", width=15), "readonly").grid(
            row=2, column=3, sticky="ew", padx=(8, 0))
        ttk.Label(inputs, text="內容／梗").grid(row=3, column=0, sticky="nw")
        topic_frame = ttk.Frame(inputs)
        topic_frame.grid(row=3, column=1, columnspan=3, sticky="ew", padx=(8, 0))
        self.topic = tk.Text(topic_frame, height=2, wrap="word", undo=True)
        self.topic.pack(fill="x")
        self._lockable(self.topic)
        # A visual placeholder never enters the submitted topic text.
        self.topic_hint = ttk.Label(topic_frame, text=TOPIC_HINT, foreground="#777777")
        self.topic_hint.place(x=5, y=3)
        self.topic_hint.bind("<Button-1>", lambda event: self.topic.focus_set())
        self.topic.bind("<FocusIn>", self._update_topic_hint)
        self.topic.bind("<FocusOut>", self._update_topic_hint)
        self.topic.bind("<<Modified>>", self._topic_modified)
        ttk.Label(inputs, text="Vercel 專案").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self._lockable(ttk.Entry(inputs, textvariable=self.project)).grid(
            row=4, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(6, 0))

        editor = ttk.LabelFrame(panel, text="新聞稿（可編輯，也可直接貼上稿子）", padding=8)
        editor.grid(row=1, column=0, sticky="nsew")
        editor.columnconfigure(1, weight=1)
        editor.columnconfigure(3, weight=1)
        editor.rowconfigure(1, weight=1)
        ttk.Label(editor, text="節目名").grid(row=0, column=0, sticky="w")
        self._lockable(ttk.Entry(editor, textvariable=self.show)).grid(
            row=0, column=1, sticky="ew", padx=8)
        ttk.Label(editor, text="主播名").grid(row=0, column=2, sticky="w")
        self._lockable(ttk.Entry(editor, textvariable=self.anchor)).grid(
            row=0, column=3, sticky="ew", padx=(8, 0))
        self.script = tk.Text(editor, height=6, wrap="word", undo=True)
        self.script.grid(row=1, column=0, columnspan=4, sticky="nsew", pady=(6, 4))
        self._lockable(self.script)
        scrollbar = ttk.Scrollbar(editor, command=self.script.yview)
        scrollbar.grid(row=1, column=4, sticky="ns", pady=(6, 4))
        self.script.configure(yscrollcommand=scrollbar.set)
        self.script.bind("<<Modified>>", self._script_modified)
        ttk.Label(editor, textvariable=self.count).grid(row=2, column=0, columnspan=4, sticky="w")

        actions = ttk.Frame(panel)
        actions.grid(row=2, column=0, sticky="ew", pady=8)
        for column in range(3):
            actions.columnconfigure(column, weight=1)
        self.generate_button = ttk.Button(actions, text="一、產生新聞稿", command=self._generate)
        self.generate_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.build_button = ttk.Button(actions, text="二、產生語音並建立 App", command=self._build)
        self.build_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.deploy_button = ttk.Button(actions, text="三、部署到手機", command=self._deploy)
        self.deploy_button.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        folder = ttk.Frame(panel)
        folder.grid(row=3, column=0, sticky="ew")
        folder.columnconfigure(1, weight=1)
        ttk.Label(folder, text="輸出位置").grid(row=0, column=0)
        self._lockable(ttk.Entry(folder, textvariable=self.base_dir, state="readonly"), "readonly").grid(
            row=0, column=1, sticky="ew", padx=8)
        self._lockable(ttk.Button(folder, text="選資料夾", command=self._choose_folder)).grid(row=0, column=2)
        self.listen_button = ttk.Button(folder, text="試聽", command=lambda: self._open_path(self.episode.audio_path))
        self.listen_button.grid(row=0, column=3, padx=(8, 4))
        self.folder_button = ttk.Button(folder, text="開啟資料夾", command=lambda: self._open_path(self.out_dir))
        self.folder_button.grid(row=0, column=4)

        result = ttk.LabelFrame(panel, text="手機 App", padding=8)
        result.grid(row=4, column=0, sticky="ew", pady=8)
        result.columnconfigure(0, weight=1)
        ttk.Entry(result, textvariable=self.url, state="readonly").grid(row=0, column=0, sticky="ew")
        self.copy_button = ttk.Button(result, text="複製網址", command=self._copy_url)
        self.copy_button.grid(row=0, column=1, padx=8)
        self.qr_label = ttk.Label(result, text="部署完成後顯示 QR code", anchor="center", width=24)
        self.qr_label.grid(row=0, column=2, rowspan=2, padx=(4, 0))
        ttk.Label(result, text=PHONE_HINT, wraplength=450, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.progressbar = ttk.Progressbar(panel, mode="indeterminate", length=200)
        self.progressbar.grid(row=5, column=0, sticky="ew")
        ttk.Label(panel, textvariable=self.status, anchor="w", wraplength=710).grid(
            row=6, column=0, sticky="ew", pady=(4, 0))

    def _update_topic_hint(self, event=None) -> None:
        try:
            focused = self.root.focus_get()
        except KeyError:  # ttk's native Combobox popdown is not a Python widget.
            focused = None
        if not self.topic.get("1.0", "end-1c") and focused != self.topic:
            self.topic_hint.place(x=5, y=3)
        else:
            self.topic_hint.place_forget()

    def _topic_modified(self, event=None) -> None:
        if self.topic.edit_modified():
            self.topic.edit_modified(False)
            self._update_topic_hint()

    def _script_modified(self, event=None) -> None:
        if self.script.edit_modified():
            self.script.edit_modified(False)
            self._content_changed()

    def _clear_deployment(self) -> None:
        self.url.set("")
        self.qr_label.configure(image="", text="部署完成後顯示 QR code")
        self.qr_image = None

    def _project_changed(self, *args) -> None:
        self._clear_deployment()
        self._refresh_buttons()

    def _content_changed(self, *args) -> None:
        self.episode = None
        self.out_dir = None
        self._clear_deployment()
        script = self.script.get("1.0", "end-1c")
        self.count.set(f"{script_character_count(script)} 字｜預估 {estimate_minutes(script):.1f} 分鐘（250 字／分鐘，不計空白）")
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        has_script = bool(self.script.get("1.0", "end-1c").strip() and self.show.get().strip() and self.anchor.get().strip())
        for button, enabled in (
            (self.generate_button, True), (self.build_button, has_script),
            (self.deploy_button, self.out_dir is not None),
            (self.listen_button, self.episode is not None),
            (self.folder_button, self.out_dir is not None), (self.copy_button, bool(self.url.get())),
        ):
            button.configure(state="normal" if enabled and not self.busy else "disabled")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget, idle_state in self.locked_widgets:
            widget.configure(state="disabled" if busy else idle_state)
        if busy:
            self.progressbar.start(12)
        else:
            self.progressbar.stop()
        self._refresh_buttons()

    def _progress(self, stage: str, message: str) -> None:
        # Workers only enqueue Python data; the root.after poll owns all Tk calls.
        self.events.put(("progress", (stage, message)))

    def _start(self, job: Callable, on_success: Callable, message: str) -> None:
        if self.busy:
            return
        self.status.set(message)
        self._set_busy(True)

        def worker() -> None:
            try:
                result = job()
            except Exception as exc:
                LOGGER.exception("背景工作失敗")
                self.events.put(("error", self._error_message(exc)))
            else:
                self.events.put(("success", (on_success, result)))

        threading.Thread(target=worker, name="prank-news-worker", daemon=True).start()

    def _poll_events(self) -> None:
        if self.closed:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    stage, message = payload
                    self.status.set(f"[{stage}] {message}")
                elif kind == "error":
                    self._set_busy(False)
                    self.status.set("工作失敗，可修正後重試。")
                    messagebox.showerror("無法完成", payload, parent=self.root)
                else:
                    self._set_busy(False)
                    callback, result = payload
                    try:
                        callback(result)
                    except Exception as exc:
                        LOGGER.exception("顯示工作結果失敗")
                        messagebox.showerror("無法顯示結果", self._error_message(exc), parent=self.root)
                    self._refresh_buttons()
        except Empty:
            pass
        finally:
            if not self.closed:
                self.poll_id = self.root.after(80, self._poll_events)

    def _error_message(self, exc: Exception) -> str:
        if isinstance(exc, (ScriptGenerationError, DeploymentError, SynthesisError, ValueError)):
            return str(exc)
        if isinstance(exc, OSError):
            # Preserve the core's Chinese file errors; native/network errors get a Chinese explanation.
            if re.search(r"[\u4e00-\u9fff]", str(exc)):
                return str(exc)
            return f"無法存取檔案或連線，請確認輸出位置、權限與網路。\n完整錯誤：{self.log_path}"
        return f"工作發生錯誤，請稍後重試。\n完整錯誤：{self.log_path}"

    def _generate(self) -> None:
        try:
            try:
                minutes = float(self.minutes.get())
            except ValueError:
                raise ValueError("新聞長度必須介於 0.5–15 分鐘。") from None
            request = NewsRequest(parse_names(self.names.get()), minutes,
                                  self.topic.get("1.0", "end-1c"), voice=VOICES[self.voice.get()])
        except (ValueError, KeyError) as exc:
            self._validation_error(exc)
            return

        def job():
            self._progress("script", "正在產生新聞播報稿…")
            result = generate_script(request)
            self._progress("done", "新聞稿已完成，請檢查並編輯。")
            return result

        def completed(result):
            show, anchor, script = result
            self.show.set(show)
            self.anchor.set(anchor)
            self.script.delete("1.0", "end")
            self.script.insert("1.0", script)
            self.script.edit_modified(False)
            self._content_changed()
            self.status.set("新聞稿已完成，可編輯後產生語音。")

        self._start(job, completed, "正在產生新聞稿…")

    def _build(self) -> None:
        if self.busy:
            return
        # Each build is a new episode. The entry remains editable before deploy.
        self.project.set(default_project_name())
        passenger_names = parse_names(self.names.get())
        show, anchor = self.show.get().strip(), self.anchor.get().strip()
        script = self.script.get("1.0", "end-1c")
        voice = VOICES[self.voice.get()]
        output = output_directory(self.base_dir.get(), datetime.now())

        def job():
            output.parent.mkdir(parents=True, exist_ok=True)
            # Never place temporary synthesis work inside the directory the builder replaces.
            with tempfile.TemporaryDirectory(prefix="prank-news-", dir=output.parent) as temp:
                episode = synthesize_episode(show, anchor, script, voice, temp, self._progress,
                                             passenger_names=passenger_names)
                result = build_and_deploy(episode, output, deploy=False, progress=self._progress)
            return episode, result["out_dir"]

        def completed(result):
            self.episode, self.out_dir = result
            self._clear_deployment()
            self.status.set(f"App 已建立：{self.out_dir}；可試聽或部署。")

        self._start(job, completed, "正在產生語音並建立 App…")

    def _deploy(self) -> None:
        try:
            project = validate_project_name(self.project.get())
        except ValueError as exc:
            self._validation_error(exc)
            return
        output = self.out_dir
        if output is None:
            return
        self._clear_deployment()

        def job():
            self._progress("deploy", "正在部署至 Vercel…")
            url = deploy(output, project)
            self._progress("qr", "正在產生 QR code…")
            qr_path = make_qr(url, output / "qr.png")
            self._progress("done", "部署已完成。")
            return url, qr_path

        def completed(result):
            url, qr_path = result
            self.url.set(url)
            with Image.open(qr_path) as source:
                qr = source.convert("RGB").resize((150, 150), Image.Resampling.NEAREST)
            self.qr_image = ImageTk.PhotoImage(qr, master=self.root)
            self.qr_label.configure(image=self.qr_image, text="", width=0)
            self.status.set("部署已完成，請用 iPhone 掃描 QR code。")

        self._start(job, completed, "正在部署到手機…")

    def _validation_error(self, exc: Exception) -> None:
        LOGGER.error("輸入驗證失敗", exc_info=(type(exc), exc, exc.__traceback__))
        messagebox.showerror("請檢查輸入", self._error_message(exc), parent=self.root)

    def _choose_folder(self) -> None:
        directory = filedialog.askdirectory(parent=self.root, title="選擇輸出位置（會建立時間戳子資料夾）")
        if directory:
            self.base_dir.set(directory)

    def _open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))
        except Exception as exc:
            LOGGER.exception("開啟檔案或資料夾失敗")
            messagebox.showerror("無法開啟", self._error_message(exc), parent=self.root)

    def _copy_url(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url.get())
        self.status.set("網址已複製。")

    def _callback_error(self, exc_type, exc, traceback) -> None:
        LOGGER.error("介面操作失敗", exc_info=(exc_type, exc, traceback))
        messagebox.showerror("介面操作失敗", self._error_message(exc), parent=self.root)

    def _close(self) -> None:
        # Keep active subprocesses and temporary work alive until they finish.
        if self.busy:
            messagebox.showinfo("工作進行中", "請等目前工作完成後再關閉視窗。", parent=self.root)
            return
        self.closed = True
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        log_path = configure_logging()
        PrankNewsWindow(root, log_path)
    except Exception as exc:
        LOGGER.exception("程式啟動失敗")
        messagebox.showerror("無法啟動", f"無法初始化程式或錯誤紀錄，請確認資料夾權限。\n{exc}", parent=root)
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
