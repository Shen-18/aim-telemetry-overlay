"""AIM Telemetry Overlay - 现代化桌面导出工作台 (PySide6)
Linear 风格深色质感界面，支持拖拽 CSV、自动解析、多进程加速与实时看板。
"""
import sys, os, time, json, shutil
from pathlib import Path

# 确保 scripts 目录在 Python 模块搜索路径中
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QProgressBar, QFileDialog, QFrame, QSpinBox,
    QLineEdit, QMessageBox, QGraphicsDropShadowEffect
)
from PySide6.QtGui import QColor, QFont, QIcon, QDragEnterEvent, QDropEvent, QCursor

import telemetry
import dashboard


def format_seconds(sec: float) -> str:
    sec = max(0, int(round(sec)))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class RenderWorker(QThread):
    """后台渲染工作线程，避免阻塞 Qt UI 主事件循环。"""
    progress_signal = Signal(dict)  # {current, total, fps, elapsed, eta, percent}
    status_signal = Signal(str)
    finished_signal = Signal(bool, str, str)  # success, message, final_path

    def __init__(self, csv_path: str, out_dir: str, workers: int, config_override=None):
        super().__init__()
        self.csv_path = csv_path
        self.out_dir = Path(out_dir).resolve()
        self.workers = workers
        self.config_override = config_override or {}
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self.status_signal.emit("正在加载并预处理遥测数据...")
            cfg = telemetry.config()
            cfg.update(self.config_override)
            cfg["render_workers"] = self.workers

            data, ts, report = telemetry.prepare(self.csv_path, cfg)
            if self._is_cancelled:
                self.finished_signal.emit(False, "任务已取消", "")
                return

            self.out_dir.mkdir(parents=True, exist_ok=True)
            final = self.out_dir / ('dashboard_100fps_alpha.mov' if cfg['fps'] == 100 else 'dashboard_alpha.mov')
            if final.exists():
                suffix = time.strftime("_%Y%m%d_%H%M%S")
                final = self.out_dir / (f'dashboard_100fps_alpha{suffix}.mov' if cfg['fps'] == 100 else f'dashboard_alpha{suffix}.mov')

            dashboard.dump(self.out_dir / 'resolved-config.json', cfg)
            dashboard.dump(self.out_dir / 'report.json', report)

            self.status_signal.emit("正在生成首帧与预览图...")
            draw = dashboard.make_renderer(data, ts, cfg, info=report['meta'])
            speed = data['VehSpd']
            import numpy as np
            from PIL import Image
            idx = int(np.nanargmax(speed)) if np.any(np.isfinite(speed)) else 0
            shot = draw(idx)
            shot.save(self.out_dir / 'transparent.png')

            def background(im):
                bg = Image.new('RGBA', im.size, (80, 89, 98, 255))
                bg.alpha_composite(im)
                return bg.convert('RGB')

            background(shot).save(self.out_dir / 'preview.jpg')

            ff = dashboard.ffmpeg_path()
            preview_cfg = dict(cfg, fps=25)
            begin = max(0, idx / cfg['fps'] - 4)
            end = min(len(ts) / cfg['fps'], begin + 8)
            indices_prev = np.minimum((np.arange(begin, end, 1 / 25) * cfg['fps']).astype(int), len(ts) - 1)
            dashboard.encode(ff, (background(draw(int(i))) for i in indices_prev), self.out_dir / 'preview.mp4', preview_cfg, False)

            if self._is_cancelled:
                self.finished_signal.emit(False, "任务已取消", "")
                return

            self.status_signal.emit("正在高速多核渲染透明视频...")
            indices = list(dashboard.render_indices(len(ts), cfg['fps'], cfg['render_fps']))
            temporary = self.out_dir / 'dashboard.partial.mov'

            def on_prog(d):
                self.progress_signal.emit(d)

            from render_mp import render_chunks_parallel
            render_chunks_parallel(
                data, ts, cfg, report['meta'], indices, temporary,
                workers=self.workers,
                progress_callback=on_prog,
                cancel_check=lambda: self._is_cancelled
            )

            self.status_signal.emit("正在进行像素级与编码校验...")
            verified = dashboard.verify(temporary, report)
            temporary.replace(final)
            dashboard.dump(self.out_dir / 'verification.json', verified)
            dashboard.dump(self.out_dir / 'progress.json', {
                'rendered_frames': total_render_frames,
                'render_total': total_render_frames,
                'output_frames': len(ts),
                'elapsed': round(time.time() - started),
                'complete': True
            })

            self.status_signal.emit("渲染完成！")
            self.finished_signal.emit(True, "视频导出与校验全部成功！", str(final))

        except Exception as e:
            self.finished_signal.emit(False, str(e), "")


QSS_STYLE = """
QMainWindow {
    background-color: #0e1117;
}

QWidget {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #e5e7eb;
}

/* 顶部标题栏区域 */
QLabel#titleLabel {
    font-size: 20px;
    font-weight: 700;
    color: #f9fafb;
    letter-spacing: 0.5px;
}
QLabel#subTitleLabel {
    font-size: 12px;
    color: #9ca3af;
}

/* 拖拽放置卡片 */
QFrame#dropZone {
    background-color: #161b22;
    border: 2px dashed #30363d;
    border-radius: 12px;
}
QFrame#dropZone:hover {
    background-color: #1c2129;
    border-color: #3b82f6;
}
QFrame#dropZone[hasFile="true"] {
    border: 1px solid #238636;
    background-color: #161f1c;
}

/* 元信息卡片 */
QFrame#infoCard {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 12px;
}

/* 指标卡片 */
QFrame#metricCard {
    background-color: #161b22;
    border: 1px solid #262c36;
    border-radius: 8px;
}
QLabel#metricTitle {
    font-size: 11px;
    font-weight: 600;
    color: #8b949e;
    text-transform: uppercase;
}
QLabel#metricValue {
    font-size: 18px;
    font-weight: 700;
    color: #58a6ff;
}

/* 进度条 */
QProgressBar {
    border: 1px solid #30363d;
    border-radius: 6px;
    background-color: #0d1117;
    text-align: center;
    color: #ffffff;
    font-size: 12px;
    font-weight: 600;
    height: 18px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #38bdf8);
    border-radius: 5px;
}

/* 输入控件 */
QLineEdit {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f3f4f6;
    font-size: 12px;
}
QLineEdit:focus {
    border-color: #38bdf8;
}

QSpinBox {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 5px 8px;
    color: #f3f4f6;
    font-size: 13px;
    font-weight: 600;
}

/* 按钮 */
QPushButton {
    background-color: #21262d;
    border: 1px solid #363b42;
    border-radius: 6px;
    padding: 7px 16px;
    color: #c9d1d9;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #161b22;
}
QPushButton:disabled {
    background-color: #161b22;
    border-color: #21262d;
    color: #484f58;
}

/* 主要操作按钮 (高亮绿) */
QPushButton#primaryBtn {
    background-color: #238636;
    border: 1px solid #2ea043;
    color: #ffffff;
    font-size: 13px;
}
QPushButton#primaryBtn:hover {
    background-color: #2ea043;
    border-color: #3fb950;
}
QPushButton#primaryBtn:disabled {
    background-color: #1f3526;
    border-color: #24422e;
    color: #6e7681;
}

/* 终止按钮 (警告红) */
QPushButton#dangerBtn {
    background-color: #21262d;
    border: 1px solid #da3633;
    color: #f85149;
}
QPushButton#dangerBtn:hover {
    background-color: #b62324;
    color: #ffffff;
}
QPushButton#dangerBtn:disabled {
    background-color: #161b22;
    border-color: #30363d;
    color: #484f58;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AIM Telemetry Overlay 导出工作台 (2K 100fps)")
        self.resize(760, 680)
        self.setMinimumSize(700, 620)
        self.setAcceptDrops(True)

        self.current_csv = None
        self.current_meta = None
        self.worker = None

        self._init_ui()
        self.setStyleSheet(QSS_STYLE)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(16)

        # 1. 顶部 Header
        header_layout = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(3)

        title = QLabel("AIM Telemetry Overlay 导出工作台")
        title.setObjectName("titleLabel")
        sub_title = QLabel("2560×1440 (2K) · 100 FPS · QTRLE Alpha 极速透明通道视频生成")
        sub_title.setObjectName("subTitleLabel")

        header_text.addWidget(title)
        header_text.addWidget(sub_title)
        header_layout.addLayout(header_text)
        header_layout.addStretch()

        self.status_badge = QLabel("就绪")
        self.status_badge.setStyleSheet(
            "background-color: #1f2937; color: #9ca3af; border: 1px solid #374151; "
            "border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 600;"
        )
        header_layout.addWidget(self.status_badge, alignment=Qt.AlignVCenter)
        main_layout.addLayout(header_layout)

        # 2. 拖拽放置区域 (Drop Zone)
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setCursor(QCursor(Qt.PointingHandCursor))
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(20, 20, 20, 20)
        drop_layout.setSpacing(8)
        drop_layout.setAlignment(Qt.AlignCenter)

        self.drop_icon = QLabel("📥")
        self.drop_icon.setAlignment(Qt.AlignCenter)
        self.drop_icon.setStyleSheet("font-size: 32px; background: transparent;")

        self.drop_label = QLabel("将 AIM 遥测 CSV 数据文件拖入此处，或点击下方按钮选择")
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setStyleSheet("font-size: 13px; font-weight: 500; color: #d1d5db; background: transparent;")

        self.btn_select = QPushButton("浏览并选择 CSV 文件")
        self.btn_select.setFixedWidth(180)
        self.btn_select.clicked.connect(self._choose_csv_file)

        drop_layout.addWidget(self.drop_icon)
        drop_layout.addWidget(self.drop_label)
        drop_layout.addWidget(self.btn_select, alignment=Qt.AlignCenter)
        main_layout.addWidget(self.drop_zone)

        # 3. 数据信息展示卡片 (解析后显示)
        self.info_card = QFrame()
        self.info_card.setObjectName("infoCard")
        info_layout = QGridLayout(self.info_card)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setHorizontalSpacing(24)
        info_layout.setVerticalSpacing(6)

        def make_meta_item(row, col, title, initial="--"):
            t_lbl = QLabel(title)
            t_lbl.setStyleSheet("font-size: 11px; color: #9ca3af; font-weight: 500;")
            v_lbl = QLabel(initial)
            v_lbl.setStyleSheet("font-size: 13px; color: #f3f4f6; font-weight: 600;")
            info_layout.addWidget(t_lbl, row * 2, col)
            info_layout.addWidget(v_lbl, row * 2 + 1, col)
            return v_lbl

        self.meta_driver = make_meta_item(0, 0, "车手姓名")
        self.meta_vehicle = make_meta_item(0, 1, "车辆型号")
        self.meta_duration = make_meta_item(0, 2, "记录时长")
        self.meta_frames = make_meta_item(1, 0, "总帧数")
        self.meta_res = make_meta_item(1, 1, "输出规格", "2560×1440 @ 100 FPS")
        self.meta_codec = make_meta_item(1, 2, "透明编码", "QTRLE (Alpha MOV)")

        self.info_card.setVisible(False)
        main_layout.addWidget(self.info_card)

        # 4. 参数配置行
        config_box = QHBoxLayout()
        config_box.setSpacing(12)

        lbl_out = QLabel("输出路径:")
        lbl_out.setStyleSheet("font-size: 12px; color: #9ca3af;")
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText("选择或输入导出目录...")
        self.btn_browse_out = QPushButton("更改...")
        self.btn_browse_out.clicked.connect(self._choose_output_dir)

        lbl_cpu = QLabel("多核进程:")
        lbl_cpu.setStyleSheet("font-size: 12px; color: #9ca3af;")
        self.spin_cpu = QSpinBox()
        max_cpu = max(1, os.cpu_count() or 4)
        self.spin_cpu.setRange(1, max_cpu)
        default_workers = 8 if max_cpu >= 8 else max(2, max_cpu)
        self.spin_cpu.setValue(default_workers)
        self.spin_cpu.setToolTip(
            f"检测到系统共 {max_cpu} 个逻辑线程。\n"
            f"• 【推荐 8 进程】对应 8845H 等 8 物理大核，独占物理核心，速度最稳且不易过热降频；\n"
            f"• 【激进 10~12 进程】插电且散热良好时可适度压榨超线程；\n"
            f"• 【不建议 16 进程】过多进程激烈争抢 CPU 缓存与内存带宽，易引发发热降频。"
        )

        config_box.addWidget(lbl_out)
        config_box.addWidget(self.edit_output, 1)
        config_box.addWidget(self.btn_browse_out)
        config_box.addWidget(lbl_cpu)
        config_box.addWidget(self.spin_cpu)
        main_layout.addLayout(config_box)

        # 5. 进度与指标卡片
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("等待开始... 0%")
        main_layout.addWidget(self.progress_bar)

        # 4 格看板
        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(10)

        def create_metric_card(title, initial):
            card = QFrame()
            card.setObjectName("metricCard")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(12, 10, 12, 10)
            lay.setSpacing(2)
            t = QLabel(title)
            t.setObjectName("metricTitle")
            v = QLabel(initial)
            v.setObjectName("metricValue")
            lay.addWidget(t)
            lay.addWidget(v)
            return card, v

        c1, self.v_progress = create_metric_card("渲染进度", "0 / 0 帧 (0.0%)")
        c2, self.v_fps = create_metric_card("实时渲染速度", "-- FPS")
        c3, self.v_elapsed = create_metric_card("已耗时", "00:00")
        c4, self.v_eta = create_metric_card("预计剩余时间", "--:--")

        metrics_grid.addWidget(c1, 0, 0)
        metrics_grid.addWidget(c2, 0, 1)
        metrics_grid.addWidget(c3, 0, 2)
        metrics_grid.addWidget(c4, 0, 3)
        main_layout.addLayout(metrics_grid)

        # 6. 底部操作栏
        action_layout = QHBoxLayout()
        action_layout.setSpacing(12)

        self.btn_open_folder = QPushButton("📁 打开输出目录")
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        self.btn_open_folder.setEnabled(False)

        action_layout.addWidget(self.btn_open_folder)
        action_layout.addStretch()

        self.btn_cancel = QPushButton("终止渲染")
        self.btn_cancel.setObjectName("dangerBtn")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_render)

        self.btn_start = QPushButton("🚀 开始极速渲染导出")
        self.btn_start.setObjectName("primaryBtn")
        self.btn_start.setFixedHeight(38)
        self.btn_start.setMinimumWidth(160)
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start_render)

        action_layout.addWidget(self.btn_cancel)
        action_layout.addWidget(self.btn_start)
        main_layout.addLayout(action_layout)

    # 拖拽事件处理
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(url.toLocalFile().lower().endswith('.csv') for url in urls):
                event.acceptProposedAction()
                self.drop_zone.setStyleSheet("border-color: #38bdf8; background-color: #1e293b;")

    def dragLeaveEvent(self, event):
        self.drop_zone.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        self.drop_zone.setStyleSheet("")
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.csv'):
                self._load_csv(path)
                break

    def _choose_csv_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择遥测 CSV 数据文件", str(PROJECT_ROOT), "AIM CSV Files (*.csv);;All Files (*)"
        )
        if path:
            self._load_csv(path)

    def _choose_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.edit_output.text() or str(PROJECT_ROOT))
        if d:
            self.edit_output.setText(d)

    def _load_csv(self, csv_path: str):
        try:
            self.status_badge.setText("正在分析数据...")
            self.status_badge.setStyleSheet("background-color: #1e3a8a; color: #93c5fd; border: 1px solid #3b82f6; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 600;")
            QApplication.processEvents()

            cfg = telemetry.config()
            _, _, report = telemetry.prepare(csv_path, cfg)

            self.current_csv = csv_path
            self.current_meta = report

            meta = report.get("meta", {})
            self.meta_driver.setText(meta.get("racer") or "未知")
            self.meta_vehicle.setText(meta.get("vehicle") or "未知")
            dur = report.get("duration", 0)
            self.meta_duration.setText(f"{dur:.1f} 秒 ({format_seconds(dur)})")
            self.meta_frames.setText(f"{report.get('frames', 0):,} 帧")

            stem = Path(csv_path).stem
            clean_stem = stem.replace(" ", "_")
            out_path = PROJECT_ROOT / f"output-{clean_stem}"
            self.edit_output.setText(str(out_path))

            self.drop_label.setText(f"已载入: {Path(csv_path).name}")
            self.drop_icon.setText("✅")
            self.drop_zone.setProperty("hasFile", "true")
            self.drop_zone.style().unpolish(self.drop_zone)
            self.drop_zone.style().polish(self.drop_zone)

            self.info_card.setVisible(True)
            self.btn_start.setEnabled(True)

            self.status_badge.setText("就绪")
            self.status_badge.setStyleSheet("background-color: #064e3b; color: #6ee7b7; border: 1px solid #10b981; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 600;")

        except Exception as e:
            QMessageBox.critical(self, "解析失败", f"无法解析该 CSV 文件:\n{str(e)}")
            self.status_badge.setText("解析错误")
            self.status_badge.setStyleSheet("background-color: #7f1d1d; color: #fca5a5; border: 1px solid #ef4444; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 600;")

    def _start_render(self):
        if not self.current_csv:
            return

        out_dir = self.edit_output.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "提示", "请指定有效的输出路径！")
            return

        workers = self.spin_cpu.value()

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_select.setEnabled(False)
        self.drop_zone.setEnabled(False)
        self.edit_output.setEnabled(False)
        self.btn_browse_out.setEnabled(False)
        self.spin_cpu.setEnabled(False)
        self.btn_open_folder.setEnabled(False)

        self.status_badge.setText("正在渲染...")
        self.status_badge.setStyleSheet("background-color: #1e3a8a; color: #93c5fd; border: 1px solid #3b82f6; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 600;")

        self.worker = RenderWorker(self.current_csv, out_dir, workers)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.status_signal.connect(self._on_status)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _cancel_render(self):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(self, "确认终止", "确定要终止正在进行的渲染吗？已生成的临时文件将被清除。", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.worker.cancel()
                self.btn_cancel.setEnabled(False)
                self.status_badge.setText("正在取消...")

    def _on_progress(self, d: dict):
        cur = d["current"]
        tot = d["total"]
        pct = d["percent"]
        fps = d["fps"]
        el = d["elapsed"]
        eta = d["eta"]

        self.progress_bar.setValue(int(pct))
        self.progress_bar.setFormat(f"渲染中 {pct:.1f}% ({cur}/{tot} 帧)")

        self.v_progress.setText(f"{cur:,} / {tot:,} ({pct:.1f}%)")
        self.v_fps.setText(f"{fps:.1f} FPS")
        self.v_elapsed.setText(format_seconds(el))
        self.v_eta.setText(format_seconds(eta))

    def _on_status(self, text: str):
        self.status_badge.setText(text)

    def _on_finished(self, success: bool, msg: str, final_path: str):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_select.setEnabled(True)
        self.drop_zone.setEnabled(True)
        self.edit_output.setEnabled(True)
        self.btn_browse_out.setEnabled(True)
        self.spin_cpu.setEnabled(True)

        if success:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("渲染完成 100%")
            self.v_eta.setText("00:00")
            self.status_badge.setText("渲染完成")
            self.status_badge.setStyleSheet("background-color: #064e3b; color: #6ee7b7; border: 1px solid #10b981; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 600;")
            self.btn_open_folder.setEnabled(True)
            QMessageBox.information(self, "导出成功", f"透明视频已成功导出并校验完成！\n\n文件保存于:\n{final_path}")
        else:
            self.status_badge.setText("未完成")
            self.status_badge.setStyleSheet("background-color: #7f1d1d; color: #fca5a5; border: 1px solid #ef4444; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 600;")
            if "用户终止" not in msg:
                QMessageBox.critical(self, "导出失败", f"渲染过程中出错:\n{msg}")

    def _open_output_folder(self):
        out_dir = self.edit_output.text().strip()
        if out_dir and os.path.exists(out_dir):
            import subprocess
            subprocess.Popen(f'explorer "{os.path.abspath(out_dir)}"')


def main():
    import multiprocessing as mp
    mp.freeze_support()

    # Windows 下启动时自动隐藏命令行黑框，仅保留 GUI 界面
    if sys.platform == "win32" and "--no-hide-console" not in sys.argv:
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass

    app = QApplication(sys.argv)
    window = MainWindow()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        window._load_csv(sys.argv[1])
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
