"""
gui.py — Pico Oscilloscope Real-Time GUI

PyQt6 + pyqtgraph oscilloscope-style waveform viewer.
Supports both hat mode (digital logic) and oscilloscope mode (analog waveforms).

Usage:
    python gui.py --port COM3
    python gui.py --port COM3 --mode oscilloscope
"""

import argparse
import collections
import struct
import sys
import time
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QComboBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QGroupBox, QStatusBar, QSplitter, QCheckBox, QFrame,
)

from serial_reader import (
    SerialReader, MODE_HAT, MODE_OSCILLOSCOPE,
    MSG_PIN_DATA, MSG_ADC_DATA, MSG_TRIGGER,
)

# -- Constants ----------------------------------------------------------------

ADC_CHANNELS = 4
ADC_MAX = 4095
ADC_VREF = 3.3
GPIO_COUNT = 30
DIGITAL_DISPLAY_PINS = list(range(0, 23)) + list(range(25, 30))  # skip 23,24

CHANNEL_COLORS = [
    "#FFD700",  # CH1 yellow
    "#00CFFF",  # CH2 cyan
    "#FF6EC7",  # CH3 pink
    "#7FFF00",  # CH4 green
]

DIGITAL_HIGH_COLOR = "#00FF88"
DIGITAL_LOW_COLOR = "#333333"
GRID_COLOR = "#2A2A2A"
BG_COLOR = "#1A1A1A"
TEXT_COLOR = "#CCCCCC"

DEFAULT_WAVEFORM_LEN = 2048
DIGITAL_DISPLAY_LEN = 512
REFRESH_RATE_MS = 33  # ~30 fps


# -- Serial Worker Thread -----------------------------------------------------

class SerialWorker(QThread):
    """Background thread for receiving serial data without blocking the GUI."""

    adc_data_received = pyqtSignal(list)       # list of (channel, raw_value)
    pin_data_received = pyqtSignal(list)       # list of uint32 snapshots
    trigger_received = pyqtSignal()
    connection_lost = pyqtSignal()

    def __init__(self, reader: SerialReader):
        super().__init__()
        self.reader = reader
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            if not self.reader.connected:
                self.connection_lost.emit()
                break

            result = self.reader.receive_frame(timeout=0.05)
            if result is None:
                continue

            msg_type, payload = result

            if msg_type == MSG_ADC_DATA:
                samples = SerialReader.decode_adc_data(payload)
                tagged = []
                for i, val in enumerate(samples):
                    tagged.append((i % ADC_CHANNELS, val))
                self.adc_data_received.emit(tagged)

            elif msg_type == MSG_PIN_DATA:
                snapshots = SerialReader.decode_pin_data(payload)
                self.pin_data_received.emit(snapshots)

            elif msg_type == MSG_TRIGGER:
                self.trigger_received.emit()

    def stop(self):
        self._running = False
        self.wait(2000)


# -- Oscilloscope Waveform Widget ---------------------------------------------

class WaveformWidget(pg.PlotWidget):
    """Real-time analog waveform display (oscilloscope style)."""

    def __init__(self):
        super().__init__()

        self.setBackground(BG_COLOR)
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("left", "Voltage", units="V")
        self.setLabel("bottom", "Samples")
        self.setYRange(0, ADC_VREF, padding=0.05)
        self.setXRange(0, DEFAULT_WAVEFORM_LEN, padding=0)
        self.getAxis("left").setTextPen(TEXT_COLOR)
        self.getAxis("bottom").setTextPen(TEXT_COLOR)

        self.buffers = []
        self.curves = []
        self.enabled = [True] * ADC_CHANNELS

        for ch in range(ADC_CHANNELS):
            buf = collections.deque(maxlen=DEFAULT_WAVEFORM_LEN)
            self.buffers.append(buf)
            pen = pg.mkPen(color=CHANNEL_COLORS[ch], width=1.5)
            curve = self.plot(pen=pen, name=f"CH{ch + 1}")
            self.curves.append(curve)

        self.addLegend(offset=(10, 10))

        # Trigger marker
        self.trigger_line = pg.InfiniteLine(
            pos=ADC_VREF / 2, angle=0,
            pen=pg.mkPen("#FF4444", width=1, style=Qt.PenStyle.DashLine),
            movable=True, label="Trig",
            labelOpts={"color": "#FF4444", "position": 0.95},
        )
        self.addItem(self.trigger_line)
        self.trigger_line.hide()

    def append_samples(self, tagged_samples: list):
        """Append (channel, raw_value) samples to ring buffers."""
        for ch, raw in tagged_samples:
            if 0 <= ch < ADC_CHANNELS:
                voltage = (raw / ADC_MAX) * ADC_VREF
                self.buffers[ch].append(voltage)

    def refresh(self):
        """Update plot curves from buffers."""
        for ch in range(ADC_CHANNELS):
            if self.enabled[ch] and len(self.buffers[ch]) > 0:
                data = np.array(self.buffers[ch])
                self.curves[ch].setData(data)
                self.curves[ch].setVisible(True)
            else:
                self.curves[ch].setVisible(False)

    def set_channel_enabled(self, ch: int, enabled: bool):
        self.enabled[ch] = enabled

    def set_buffer_length(self, length: int):
        for ch in range(ADC_CHANNELS):
            old = list(self.buffers[ch])
            self.buffers[ch] = collections.deque(old[-length:], maxlen=length)
        self.setXRange(0, length, padding=0)

    def show_trigger_line(self, show: bool):
        if show:
            self.trigger_line.show()
        else:
            self.trigger_line.hide()

    def get_trigger_level_raw(self) -> int:
        voltage = self.trigger_line.value()
        return int((voltage / ADC_VREF) * ADC_MAX)

    def clear_all(self):
        for buf in self.buffers:
            buf.clear()
        self.refresh()


# -- Digital Logic Analyzer Widget --------------------------------------------

class DigitalWidget(pg.PlotWidget):
    """Real-time digital logic analyzer display."""

    def __init__(self, pin_list: list):
        super().__init__()

        self.pin_list = pin_list
        self.pin_count = len(pin_list)

        self.setBackground(BG_COLOR)
        self.showGrid(x=True, y=False, alpha=0.2)
        self.setLabel("bottom", "Samples")
        self.getAxis("bottom").setTextPen(TEXT_COLOR)

        # Y axis: one row per pin, with spacing
        self.setYRange(-0.5, self.pin_count * 1.5 - 0.5, padding=0.02)
        self.setXRange(0, DIGITAL_DISPLAY_LEN, padding=0)

        # Hide default y-axis, use custom labels
        left_axis = self.getAxis("left")
        left_axis.setTextPen(TEXT_COLOR)
        ticks = [(i * 1.5 + 0.5, f"GPIO{pin_list[i]}") for i in range(self.pin_count)]
        left_axis.setTicks([ticks])

        self.buffers = []
        self.curves = []
        for i in range(self.pin_count):
            buf = collections.deque(maxlen=DIGITAL_DISPLAY_LEN)
            self.buffers.append(buf)
            pen = pg.mkPen(color=DIGITAL_HIGH_COLOR, width=1.2)
            curve = self.plot(pen=pen)
            self.curves.append(curve)

    def append_snapshots(self, snapshots: list):
        """Append GPIO snapshots (list of uint32)."""
        for snap in snapshots:
            for i, pin in enumerate(self.pin_list):
                val = (snap >> pin) & 1
                self.buffers[i].append(val)

    def refresh(self):
        """Update all digital channel plots."""
        for i in range(self.pin_count):
            if len(self.buffers[i]) > 0:
                data = np.array(self.buffers[i], dtype=np.float32)
                # Scale and offset: each channel occupies its own row
                y_offset = i * 1.5
                self.curves[i].setData(data * 0.8 + y_offset)

    def set_buffer_length(self, length: int):
        for i in range(self.pin_count):
            old = list(self.buffers[i])
            self.buffers[i] = collections.deque(old[-length:], maxlen=length)
        self.setXRange(0, length, padding=0)

    def clear_all(self):
        for buf in self.buffers:
            buf.clear()
        self.refresh()


# -- Control Panel -------------------------------------------------------------

class ControlPanel(QWidget):
    """Side panel with oscilloscope controls."""

    mode_changed = pyqtSignal(int)
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    trigger_changed = pyqtSignal(int, int, int)  # channel, mode, level
    buffer_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # -- Connection status
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color: #FF4444; font-weight: bold; font-size: 13px;")
        layout.addWidget(self.status_label)

        # -- Mode selection
        mode_group = QGroupBox("Mode")
        mode_layout = QVBoxLayout(mode_group)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Hat Mode (Digital)", MODE_HAT)
        self.mode_combo.addItem("Oscilloscope (Analog)", MODE_OSCILLOSCOPE)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        layout.addWidget(mode_group)

        # -- Start / Stop
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_start.setStyleSheet(
            "QPushButton { background: #2E7D32; color: white; padding: 8px; font-weight: bold; }"
            "QPushButton:hover { background: #388E3C; }"
        )
        self.btn_start.clicked.connect(self.start_requested.emit)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setStyleSheet(
            "QPushButton { background: #C62828; color: white; padding: 8px; font-weight: bold; }"
            "QPushButton:hover { background: #D32F2F; }"
        )
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        self.btn_stop.setEnabled(False)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        # -- Channel toggles (oscilloscope mode)
        self.ch_group = QGroupBox("Channels")
        ch_layout = QVBoxLayout(self.ch_group)
        self.ch_checks = []
        for i in range(ADC_CHANNELS):
            cb = QCheckBox(f"CH{i + 1} (ADC{i})")
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {CHANNEL_COLORS[i]}; font-weight: bold;")
            self.ch_checks.append(cb)
            ch_layout.addWidget(cb)
        layout.addWidget(self.ch_group)

        # -- Trigger settings
        self.trig_group = QGroupBox("Trigger")
        trig_layout = QGridLayout(self.trig_group)

        trig_layout.addWidget(QLabel("Mode:"), 0, 0)
        self.trig_mode = QComboBox()
        self.trig_mode.addItem("None", 0)
        self.trig_mode.addItem("Rising", 1)
        self.trig_mode.addItem("Falling", 2)
        self.trig_mode.addItem("Both", 3)
        trig_layout.addWidget(self.trig_mode, 0, 1)

        trig_layout.addWidget(QLabel("Channel:"), 1, 0)
        self.trig_channel = QSpinBox()
        self.trig_channel.setRange(0, 3)
        trig_layout.addWidget(self.trig_channel, 1, 1)

        trig_layout.addWidget(QLabel("Level:"), 2, 0)
        self.trig_level = QSpinBox()
        self.trig_level.setRange(0, ADC_MAX)
        self.trig_level.setValue(ADC_MAX // 2)
        trig_layout.addWidget(self.trig_level, 2, 1)

        self.btn_apply_trig = QPushButton("Apply Trigger")
        self.btn_apply_trig.clicked.connect(self._on_trigger_apply)
        trig_layout.addWidget(self.btn_apply_trig, 3, 0, 1, 2)
        layout.addWidget(self.trig_group)

        # -- Buffer length
        buf_group = QGroupBox("Display")
        buf_layout = QGridLayout(buf_group)
        buf_layout.addWidget(QLabel("Buffer size:"), 0, 0)
        self.buf_spin = QSpinBox()
        self.buf_spin.setRange(256, 16384)
        self.buf_spin.setSingleStep(256)
        self.buf_spin.setValue(DEFAULT_WAVEFORM_LEN)
        self.buf_spin.valueChanged.connect(self.buffer_changed.emit)
        buf_layout.addWidget(self.buf_spin, 0, 1)
        layout.addWidget(buf_group)

        # -- Clear
        self.btn_clear = QPushButton("Clear Display")
        self.btn_clear.setStyleSheet("padding: 6px;")
        layout.addWidget(self.btn_clear)

        layout.addStretch()

        # -- Stats
        self.stats_label = QLabel("Samples: 0 | FPS: 0")
        self.stats_label.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self.stats_label)

    def _on_mode_changed(self):
        mode = self.mode_combo.currentData()
        is_osc = mode == MODE_OSCILLOSCOPE
        self.ch_group.setVisible(is_osc)
        self.trig_group.setVisible(is_osc)
        self.mode_changed.emit(mode)

    def _on_trigger_apply(self):
        self.trigger_changed.emit(
            self.trig_channel.value(),
            self.trig_mode.currentData(),
            self.trig_level.value(),
        )

    def set_connected(self, connected: bool):
        if connected:
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: #00E676; font-weight: bold; font-size: 13px;")
        else:
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: #FF4444; font-weight: bold; font-size: 13px;")

    def set_running(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.mode_combo.setEnabled(not running)


# -- Main Window ---------------------------------------------------------------

class OscilloscopeWindow(QMainWindow):
    """Main oscilloscope GUI window."""

    def __init__(self, port: str, mode: int = MODE_HAT):
        super().__init__()

        self.port = port
        self.current_mode = mode
        self.reader: Optional[SerialReader] = None
        self.worker: Optional[SerialWorker] = None
        self.sample_count = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.last_fps_value = 0

        self.setWindowTitle("Pico Oscilloscope")
        self.resize(1200, 700)
        self.setStyleSheet(f"background-color: {BG_COLOR}; color: {TEXT_COLOR};")

        self._build_ui()
        self._connect_signals()
        self._apply_mode(self.current_mode)

        # Refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_display)
        self.refresh_timer.start(REFRESH_RATE_MS)

        # FPS counter timer
        self.fps_timer = QTimer()
        self.fps_timer.timeout.connect(self._update_fps)
        self.fps_timer.start(1000)

        # Auto-connect
        self._connect_device()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Plot area (splitter for analog + digital)
        self.splitter = QSplitter(Qt.Orientation.Vertical)

        self.waveform = WaveformWidget()
        self.digital = DigitalWidget(DIGITAL_DISPLAY_PINS)

        self.splitter.addWidget(self.waveform)
        self.splitter.addWidget(self.digital)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)

        main_layout.addWidget(self.splitter, stretch=1)

        # Control panel
        self.panel = ControlPanel()
        main_layout.addWidget(self.panel)

        # Status bar
        self.statusBar().showMessage("Ready")
        self.statusBar().setStyleSheet("color: #888888;")

    def _connect_signals(self):
        self.panel.mode_changed.connect(self._on_mode_changed)
        self.panel.start_requested.connect(self._on_start)
        self.panel.stop_requested.connect(self._on_stop)
        self.panel.trigger_changed.connect(self._on_trigger_changed)
        self.panel.buffer_changed.connect(self._on_buffer_changed)
        self.panel.btn_clear.clicked.connect(self._on_clear)

        for i, cb in enumerate(self.panel.ch_checks):
            cb.toggled.connect(lambda checked, ch=i: self.waveform.set_channel_enabled(ch, checked))

    def _connect_device(self):
        self.reader = SerialReader(self.port, timeout=0.1)
        if self.reader.connect():
            self.panel.set_connected(True)
            self.statusBar().showMessage(f"Connected to {self.port}")
        else:
            self.panel.set_connected(False)
            self.statusBar().showMessage(f"Failed to connect to {self.port}")

    def _apply_mode(self, mode: int):
        self.current_mode = mode
        if mode == MODE_HAT:
            # Hat mode: show digital only
            self.waveform.hide()
            self.digital.show()
            self.splitter.setSizes([0, 1])
        else:
            # Oscilloscope mode: show both
            self.waveform.show()
            self.digital.show()
            self.splitter.setSizes([400, 200])
            self.waveform.show_trigger_line(True)

    def _on_mode_changed(self, mode: int):
        was_running = self.worker is not None
        if was_running:
            self._on_stop()

        self._apply_mode(mode)

        if self.reader and self.reader.connected:
            self.reader.set_mode(mode)

    def _on_start(self):
        if not self.reader or not self.reader.connected:
            self.statusBar().showMessage("Not connected")
            return

        self.reader.set_mode(self.current_mode)

        if not self.reader.start_sampling():
            self.statusBar().showMessage("Failed to start sampling")
            return

        self.worker = SerialWorker(self.reader)
        self.worker.adc_data_received.connect(self._on_adc_data)
        self.worker.pin_data_received.connect(self._on_pin_data)
        self.worker.trigger_received.connect(self._on_trigger_event)
        self.worker.connection_lost.connect(self._on_connection_lost)
        self.worker.start()

        self.panel.set_running(True)
        self.sample_count = 0
        self.statusBar().showMessage("Sampling...")

    def _on_stop(self):
        if self.worker:
            self.worker.stop()
            self.worker = None

        if self.reader and self.reader.connected:
            self.reader.stop_sampling()

        self.panel.set_running(False)
        self.statusBar().showMessage("Stopped")

    def _on_adc_data(self, tagged_samples: list):
        self.waveform.append_samples(tagged_samples)
        self.sample_count += len(tagged_samples)

    def _on_pin_data(self, snapshots: list):
        self.digital.append_snapshots(snapshots)
        self.sample_count += len(snapshots)

    def _on_trigger_event(self):
        self.statusBar().showMessage("Trigger!", 1000)

    def _on_connection_lost(self):
        self.panel.set_connected(False)
        self.panel.set_running(False)
        self.worker = None
        self.statusBar().showMessage("Connection lost")

    def _on_trigger_changed(self, channel: int, mode: int, level: int):
        if self.reader and self.reader.connected:
            self.reader.configure_trigger(channel, mode, level)
            self.waveform.trigger_line.setValue((level / ADC_MAX) * ADC_VREF)
            show = mode != 0
            self.waveform.show_trigger_line(show)
            self.statusBar().showMessage(f"Trigger: CH{channel} mode={mode} level={level}")

    def _on_buffer_changed(self, length: int):
        self.waveform.set_buffer_length(length)
        self.digital.set_buffer_length(length)

    def _on_clear(self):
        self.waveform.clear_all()
        self.digital.clear_all()
        self.sample_count = 0

    def _refresh_display(self):
        self.frame_count += 1
        if self.current_mode == MODE_OSCILLOSCOPE:
            self.waveform.refresh()
        self.digital.refresh()

    def _update_fps(self):
        now = time.time()
        dt = now - self.last_fps_time
        if dt > 0:
            self.last_fps_value = self.frame_count / dt
        self.frame_count = 0
        self.last_fps_time = now
        self.panel.stats_label.setText(
            f"Samples: {self.sample_count:,} | FPS: {self.last_fps_value:.0f}"
        )

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
        if self.reader:
            if self.reader.connected:
                try:
                    self.reader.stop_sampling()
                except Exception:
                    pass
            self.reader.disconnect()
        event.accept()


# -- Entry point ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="pico_oscilloscope_gui",
        description="Pico Oscilloscope — Real-time waveform viewer",
    )
    parser.add_argument("--port", "-p", required=True,
                        help="Serial port (e.g., COM3, /dev/ttyACM0)")
    parser.add_argument("--mode", "-m", choices=["hat", "oscilloscope"], default="hat",
                        help="Initial operating mode")
    args = parser.parse_args()

    mode = MODE_HAT if args.mode == "hat" else MODE_OSCILLOSCOPE

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(BG_COLOR))
    palette.setColor(palette.ColorRole.WindowText, QColor(TEXT_COLOR))
    palette.setColor(palette.ColorRole.Base, QColor("#222222"))
    palette.setColor(palette.ColorRole.AlternateBase, QColor("#2A2A2A"))
    palette.setColor(palette.ColorRole.Text, QColor(TEXT_COLOR))
    palette.setColor(palette.ColorRole.Button, QColor("#333333"))
    palette.setColor(palette.ColorRole.ButtonText, QColor(TEXT_COLOR))
    palette.setColor(palette.ColorRole.Highlight, QColor("#1565C0"))
    palette.setColor(palette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)

    window = OscilloscopeWindow(args.port, mode)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
