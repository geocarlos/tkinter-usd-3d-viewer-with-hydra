import os
import tkinter as tk
from tkinter import filedialog

from pxr import Usd

from viewport import USDGLViewport


class USDViewerTk(tk.Tk):
    def __init__(self, width=800, height=600):
        super().__init__()
        self.title("Tkinter USD 3D Viewer")
        self.geometry(f"{width}x{height}")

        self.open_bar = tk.Frame(self)
        self.open_bar.pack(side=tk.TOP, pady=5)

        self.lbl_filename = tk.Label(self.open_bar, text="")
        self.lbl_filename.pack(side=tk.LEFT, padx=(0, 8))

        self.toolbar = tk.Frame(self)
        self.toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(0, 5))

        self.btn_open = tk.Button(self.toolbar, text="Open USD File", command=self.load_file)
        self.btn_open.pack(side=tk.RIGHT)

        tk.Label(self.toolbar, text="Shading:").pack(side=tk.LEFT)
        self.shading_var = tk.StringVar(value="Shaded")
        self.shading_menu = tk.OptionMenu(self.toolbar, self.shading_var,
                                           "Shaded", "Solid", "Wireframe", "Normals",
                                           command=self.on_shading_changed)
        self.shading_menu.pack(side=tk.LEFT, padx=(2, 10))

        self.btn_reset_view = tk.Button(self.toolbar, text="Reset View", command=self.reset_view)
        self.btn_reset_view.pack(side=tk.LEFT, padx=(0, 10))

        self.show_bbox_var = tk.BooleanVar(value=False)
        self.chk_bbox = tk.Checkbutton(self.toolbar, text="Bounding Box",
                                        variable=self.show_bbox_var, command=self.on_bbox_toggled)
        self.chk_bbox.pack(side=tk.LEFT, padx=(0, 10))

        self.show_grid_var = tk.BooleanVar(value=True)
        self.chk_grid = tk.Checkbutton(self.toolbar, text="Grid",
                                        variable=self.show_grid_var, command=self.on_grid_toggled)
        self.chk_grid.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(self.toolbar, text="Background:").pack(side=tk.LEFT)
        self.background_var = tk.StringVar(value="Black")
        self.background_menu = tk.OptionMenu(self.toolbar, self.background_var,
                                              "Black", "Gray", "Sky", "Foggy",
                                              command=self.on_background_changed)
        self.background_menu.pack(side=tk.LEFT, padx=(2, 0))

        self.viewport = USDGLViewport(self, width=width, height=height)
        self.viewport.pack(fill=tk.BOTH, expand=True)

        self.playback = tk.Frame(self)
        self.playback.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)

        self.btn_play = tk.Button(self.playback, text="Play", width=6,
                                   command=self.toggle_play, state=tk.DISABLED)
        self.btn_play.pack(side=tk.LEFT)

        self.time_var = tk.DoubleVar(value=0.0)
        self.time_slider = tk.Scale(self.playback, orient=tk.HORIZONTAL,
                                     from_=0.0, to=0.0, showvalue=False,
                                     variable=self.time_var, command=self.on_scrub,
                                     state=tk.DISABLED)
        self.time_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.status = tk.Label(self, text="No file loaded", anchor=tk.W)
        self.status.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)

        self.stage = None
        self.stage_path = None
        self.stage_mtime = None
        self.playing = False
        self.fps = 24.0
        self._play_job = None

        self.after(1000, self._check_hot_reload)

    def _check_hot_reload(self):
        if self.stage_path:
            try:
                mtime = os.path.getmtime(self.stage_path)
            except OSError:
                mtime = self.stage_mtime
            if mtime != self.stage_mtime:
                self._reload_current_file(mtime)
        self.after(1000, self._check_hot_reload)

    def _reload_current_file(self, mtime):
        # Usd.Stage.Open() on a path that's already loaded returns the cached
        # in-memory layer, not a fresh read from disk -- Reload() is the actual
        # API for picking up on-disk changes to a layer that's already open.
        #
        # Advance stage_mtime unconditionally (success or failure) so a save
        # that fails to load is not retried every second until a *different*
        # save changes the mtime again -- and so a subsequent good save (a
        # new mtime) is always re-checked regardless of what happened here.
        self.stage_mtime = mtime
        try:
            self.stage.Reload()
        except Exception as exc:
            print(f"Hot-reload skipped for {self.stage_path}: {exc}")
            return  # syntax error mid-save; keep showing the last good version and retry on the next save

        if self._safe_set_time(Usd.TimeCode(self.time_var.get())):
            self.status.config(text=f"Hot-reloaded: {os.path.basename(self.stage_path)}")

    def _safe_set_time(self, time_code):
        """viewport.set_time() can raise if the stage's current content is
        broken -- e.g. Reload() succeeded but a value USD couldn't parse
        cleanly came back as an UnregisteredValue placeholder. Never let that
        escape into a recurring after() callback, or the callback chain dies
        silently; on failure the last successfully rendered geometry just
        stays on screen."""
        try:
            self.viewport.set_time(self.stage, time_code)
            return True
        except Exception as exc:
            print(f"Failed to refresh viewport for {self.stage_path}: {exc}")
            return False

    def on_shading_changed(self, mode):
        self.viewport.shading_mode = mode
        self.viewport.tkExpose(None)

    def on_bbox_toggled(self):
        self.viewport.show_bbox = self.show_bbox_var.get()
        self.viewport.tkExpose(None)

    def on_grid_toggled(self):
        self.viewport.show_grid = self.show_grid_var.get()
        self.viewport.tkExpose(None)

    def on_background_changed(self, mode):
        self.viewport.background_mode = mode
        self.viewport.tkExpose(None)

    def reset_view(self):
        self.viewport.frame_camera_on_geometry()
        self.viewport.tkExpose(None)

    def load_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("USD Files", "*.usd *.usda *.usdc *.usdz")]
        )
        if not file_path:
            return

        self.stop_playback()
        new_stage = Usd.Stage.Open(file_path)
        if new_stage is None:
            self.status.config(text=f"Failed to open: {file_path}")
            return

        self.stage = new_stage
        self.stage_path = file_path
        self.stage_mtime = os.path.getmtime(file_path)

        filename = os.path.basename(file_path)
        self.title(f"Tkinter USD 3D Viewer | {filename}")
        self.lbl_filename.config(text=filename)
        self.btn_open.config(text="Open Another USD File")

        self.viewport.load_stage(self.stage)
        self._setup_playback_range()

        if self.viewport.bbox_min is None:
            self.status.config(text="Opened, but found no geometry to render")
        else:
            self.status.config(text=f"Rendered {filename}")

    def _setup_playback_range(self):
        has_range = self.stage.HasAuthoredTimeCodeRange()
        start = self.stage.GetStartTimeCode()
        end = self.stage.GetEndTimeCode()
        self.fps = self.stage.GetFramesPerSecond() or 24.0

        self.time_slider.config(from_=start, to=end,
                                 state=tk.NORMAL if has_range else tk.DISABLED)
        self.time_var.set(start)
        self.btn_play.config(state=tk.NORMAL if has_range else tk.DISABLED)

    def on_scrub(self, value):
        if self.stage is None:
            return
        self._safe_set_time(Usd.TimeCode(float(value)))

    def toggle_play(self):
        if self.playing:
            self.stop_playback()
        else:
            self.playing = True
            self.btn_play.config(text="Pause")
            self._tick()

    def stop_playback(self):
        self.playing = False
        self.btn_play.config(text="Play")
        if self._play_job is not None:
            self.after_cancel(self._play_job)
            self._play_job = None

    def _tick(self):
        if not self.playing or self.stage is None:
            return

        start = self.time_slider.cget("from")
        end = self.time_slider.cget("to")
        next_time = self.time_var.get() + 1.0
        if next_time > end:
            next_time = start

        self.time_var.set(next_time)
        self._safe_set_time(Usd.TimeCode(next_time))
        self._play_job = self.after(max(1, int(1000 / self.fps)), self._tick)
