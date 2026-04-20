"""PyQt6 GUI for Pico Oscilloscope."""

import argparse
import collections
import sys
import time
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from serial_reader import (
    ADCBatch,
    PinBatch,
    SerialReader,
    MODE_HAT,
    MODE_OSCILLOSCOPE,
    MSG_ADC_BATCH,
    MSG_ADC_DATA,
    MSG_PIN_BATCH,
    MSG_PIN_DATA,
    MSG_TRIGGER,
)

ADC_CHANNELS = 4
ADC_MAX = 4095
ADC_VREF = 3.3
DIGITAL_DISPLAY_PINS = list(range(0, 23)) + list(range(25, 30))

CHANNEL_COLORS = [
    "#FFD700",
    "#00CFFF",
    "#FF6EC7",
    "#7FFF00",
]

BG_COLOR = "#1A1A1A"
TEXT_COLOR = "#CCCCCC"
DIGITAL_HIGH_COLOR = "#00FF88"

DEFAULT_WAVEFORM_LEN = 2048
REFRESH_RATE_MS = 33
BATCH_APPEND_LIMIT = 256


def format_rate(rate_hz: float) -> str:
    """Format a sample rate for display."""
    if rate_hz >= 1_000_000:
        return f"{rate_hz / 1_000_000:.2f} MS/s"
    if rate_hz >= 1_000:
        return f"{rate_hz / 1_000:.1f} kS/s"
    return f"{rate_hz:.1f} S/s"


class SerialWorker(QThread):
    """Background thread for receiving serial frames."""

    adc_batch_received = pyqtSignal(object)
    pin_batch_received = pyqtSignal(object)
    trigger_received = pyqtSignal()
    connection_lost = pyqtSignal()

    def __init__(self, reader: SerialReader):
        super().__init__()
        self.reader = reader
        self._running = False
        self._legacy_adc_time_ps = 0
        self._legacy_pin_time_ps = 0

    def run(self) -> None:
        self._running = True
        while self._running:
            if not self.reader.connected:
                self.connection_lost.emit()
                break

            result = self.reader.receive_frame(timeout=0.05)
            if result is None:
                continue

            msg_type, payload = result

            if msg_type == MSG_ADC_BATCH:
                batch = SerialReader.decode_adc_batch(payload)
                if batch is not None:
                    self.adc_batch_received.emit(batch)

            elif msg_type == MSG_PIN_BATCH:
                batch = SerialReader.decode_pin_batch(payload)
                if batch is not None:
                    self.pin_batch_received.emit(batch)

            elif msg_type == MSG_ADC_DATA:
                samples = SerialReader.decode_adc_data(payload)
                if samples:
                    batch = ADCBatch(
                        start_time_ps=self._legacy_adc_time_ps,
                        sample_interval_ps=1,
                        sample_count=len(samples),
                        channel_count=ADC_CHANNELS,
                        samples=samples,
                    )
                    self._legacy_adc_time_ps += len(samples)
                    self.adc_batch_received.emit(batch)

            elif msg_type == MSG_PIN_DATA:
                snapshots = SerialReader.decode_pin_data(payload)
                if snapshots:
                    batch = PinBatch(
                        start_time_ps=self._legacy_pin_time_ps,
                        sample_interval_ps=1,
                        sample_count=len(snapshots),
                        pin_mask=0xFFFFFFFF,
                        snapshots=snapshots,
                    )
                    self._legacy_pin_time_ps += len(snapshots)
                    self.pin_batch_received.emit(batch)

            elif msg_type == MSG_TRIGGER:
                self.trigger_received.emit()

    def stop(self) -> None:
        self._running = False
        self.wait(2000)


class WaveformWidget(pg.PlotWidget):
    """Real-time analog waveform display."""

    def __init__(self):
        super().__init__()

        self.buffer_length = DEFAULT_WAVEFORM_LEN
        self.enabled = [True] * ADC_CHANNELS
        self.time_buffers: list[collections.deque[float]] = []
        self.value_buffers: list[collections.deque[float]] = []
        self.curves = []

        self.setBackground(BG_COLOR)
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("left", "Voltage", units="V")
        self.setLabel("bottom", "Time", units="s")
        self.setYRange(0, ADC_VREF, padding=0.05)
        self.getAxis("left").setTextPen(TEXT_COLOR)
        self.getAxis("bottom").setTextPen(TEXT_COLOR)

        self.addLegend(offset=(10, 10))

        for ch in range(ADC_CHANNELS):
            self.time_buffers.append(collections.deque(maxlen=self.buffer_length))
            self.value_buffers.append(collections.deque(maxlen=self.buffer_length))
            pen = pg.mkPen(color=CHANNEL_COLORS[ch], width=1.5)
            self.curves.append(self.plot(pen=pen, name=f"CH{ch + 1}"))

        self.trigger_line = pg.InfiniteLine(
            pos=ADC_VREF / 2,
            angle=0,
            pen=pg.mkPen("#FF4444", width=1, style=Qt.PenStyle.DashLine),
            movable=True,
            label="Trig",
            labelOpts={"color": "#FF4444", "position": 0.95},
        )
        self.addItem(self.trigger_line)
        self.trigger_line.hide()

    def append_batch(self, batch: ADCBatch) -> None:
        """Append a timestamped ADC batch to the display buffers."""
        if batch.sample_count == 0 or batch.channel_count <= 0:
            return

        samples = np.asarray(batch.samples, dtype=np.float64)
        if samples.size == 0:
            return

        max_points = max(64, min(self.buffer_length, BATCH_APPEND_LIMIT))
        channel_count = min(batch.channel_count, ADC_CHANNELS)

        for channel in range(channel_count):
            channel_samples = samples[channel::batch.channel_count]
            if channel_samples.size == 0:
                continue

            indices = np.arange(
                channel,
                channel + channel_samples.size * batch.channel_count,
                batch.channel_count,
                dtype=np.int64,
            )
            times = (batch.start_time_ps + indices * batch.sample_interval_ps) / 1_000_000_000_000.0
            voltages = (channel_samples / ADC_MAX) * ADC_VREF

            if channel_samples.size > max_points:
                step = max(1, int(np.ceil(channel_samples.size / max_points)))
                times = times[::step]
                voltages = voltages[::step]

            self.time_buffers[channel].extend(times.tolist())
            self.value_buffers[channel].extend(voltages.tolist())

    def refresh(self) -> None:
        """Refresh waveform curves from buffered data."""
        visible_ranges: list[tuple[float, float]] = []

        for channel in range(ADC_CHANNELS):
            if self.enabled[channel] and self.value_buffers[channel]:
                x_data = np.fromiter(self.time_buffers[channel], dtype=np.float64)
                y_data = np.fromiter(self.value_buffers[channel], dtype=np.float64)
                self.curves[channel].setData(x_data, y_data)
                self.curves[channel].setVisible(True)
                visible_ranges.append((x_data[0], x_data[-1]))
            else:
                self.curves[channel].setVisible(False)

        if visible_ranges:
            x_min = min(start for start, _ in visible_ranges)
            x_max = max(end for _, end in visible_ranges)
            if x_max <= x_min:
                x_max = x_min + 1e-6
            self.setXRange(x_min, x_max, padding=0.02)

    def set_channel_enabled(self, channel: int, enabled: bool) -> None:
        self.enabled[channel] = enabled

    def set_buffer_length(self, length: int) -> None:
        self.buffer_length = length
        for channel in range(ADC_CHANNELS):
            old_times = list(self.time_buffers[channel])
            old_values = list(self.value_buffers[channel])
            self.time_buffers[channel] = collections.deque(old_times[-length:], maxlen=length)
            self.value_buffers[channel] = collections.deque(old_values[-length:], maxlen=length)

    def show_trigger_line(self, show: bool) -> None:
        if show:
            self.trigger_line.show()
        else:
            self.trigger_line.hide()

    def clear_all(self) -> None:
        for channel in range(ADC_CHANNELS):
            self.time_buffers[channel].clear()
            self.value_buffers[channel].clear()
        self.refresh()


class DigitalWidget(pg.PlotWidget):
    """Real-time digital logic display."""

    def __init__(self, pin_list: list[int]):
        super().__init__()

        self.pin_list = pin_list
        self.pin_count = len(pin_list)
        self.buffer_length = DEFAULT_WAVEFORM_LEN
        self.time_buffers: list[collections.deque[float]] = []
        self.value_buffers: list[collections.deque[float]] = []
        self.curves = []

        self.setBackground(BG_COLOR)
        self.showGrid(x=True, y=False, alpha=0.2)
        self.setLabel("bottom", "Time", units="s")
        self.getAxis("bottom").setTextPen(TEXT_COLOR)
        self.setYRange(-0.5, self.pin_count * 1.5 - 0.5, padding=0.02)

        left_axis = self.getAxis("left")
        left_axis.setTextPen(TEXT_COLOR)
        ticks = [(index * 1.5 + 0.5, f"GPIO{pin_list[index]}") for index in range(self.pin_count)]
        left_axis.setTicks([ticks])

        for _ in range(self.pin_count):
            self.time_buffers.append(collections.deque(maxlen=self.buffer_length))
            self.value_buffers.append(collections.deque(maxlen=self.buffer_length))
            self.curves.append(self.plot(pen=pg.mkPen(color=DIGITAL_HIGH_COLOR, width=1.1)))

    def append_batch(self, batch: PinBatch) -> None:
        """Append a timestamped GPIO batch to the display buffers."""
        if batch.sample_count == 0:
            return

        snapshots = np.asarray(batch.snapshots, dtype=np.uint32)
        if snapshots.size == 0:
            return

        max_points = max(64, min(self.buffer_length, BATCH_APPEND_LIMIT))
        indices = np.arange(snapshots.size, dtype=np.int64)
        times = (batch.start_time_ps + indices * batch.sample_interval_ps) / 1_000_000_000_000.0

        if snapshots.size > max_points:
            step = max(1, int(np.ceil(snapshots.size / max_points)))
            snapshots = snapshots[::step]
            times = times[::step]

        time_list = times.tolist()
        for index, pin in enumerate(self.pin_list):
            values = ((snapshots >> pin) & 1).astype(np.float64)
            self.time_buffers[index].extend(time_list)
            self.value_buffers[index].extend(values.tolist())

    def refresh(self) -> None:
        """Refresh digital traces from buffered data."""
        visible_ranges: list[tuple[float, float]] = []

        for index in range(self.pin_count):
            if self.value_buffers[index]:
                x_data = np.fromiter(self.time_buffers[index], dtype=np.float64)
                values = np.fromiter(self.value_buffers[index], dtype=np.float64)
                y_offset = index * 1.5
                self.curves[index].setData(x_data, values * 0.8 + y_offset)
                visible_ranges.append((x_data[0], x_data[-1]))

        if visible_ranges:
            x_min = min(start for start, _ in visible_ranges)
            x_max = max(end for _, end in visible_ranges)
            if x_max <= x_min:
                x_max = x_min + 1e-6
            self.setXRange(x_min, x_max, padding=0.02)

    def set_buffer_length(self, length: int) -> None:
        self.buffer_length = length
        for index in range(self.pin_count):
            old_times = list(self.time_buffers[index])
            old_values = list(self.value_buffers[index])
            self.time_buffers[index] = collections.deque(old_times[-length:], maxlen=length)
            self.value_buffers[index] = collections.deque(old_values[-length:], maxlen=length)

    def clear_all(self) -> None:
        for index in range(self.pin_count):
            self.time_buffers[index].clear()
            self.value_buffers[index].clear()
        self.refresh()


class ControlPanel(QWidget):
    """Side panel with oscilloscope controls."""

    mode_changed = pyqtSignal(int)
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    trigger_changed = pyqtSignal(int, int, int)
    buffer_changed = pyqtSignal(int)
    digital_toggled = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color: #FF4444; font-weight: bold; font-size: 13px;")
        layout.addWidget(self.status_label)

        mode_group = QGroupBox("Mode")
        mode_layout = QVBoxLayout(mode_group)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Hat Mode (Digital)", MODE_HAT)
        self.mode_combo.addItem("Oscilloscope (Analog)", MODE_OSCILLOSCOPE)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        layout.addWidget(mode_group)

        button_layout = QHBoxLayout()
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
        button_layout.addWidget(self.btn_start)
        button_layout.addWidget(self.btn_stop)
        layout.addLayout(button_layout)

        self.ch_group = QGroupBox("Analog Channels")
        ch_layout = QVBoxLayout(self.ch_group)
        self.ch_checks = []
        for index in range(ADC_CHANNELS):
            checkbox = QCheckBox(f"CH{index + 1} (ADC{index})")
            checkbox.setChecked(True)
            checkbox.setStyleSheet(f"color: {CHANNEL_COLORS[index]}; font-weight: bold;")
            self.ch_checks.append(checkbox)
            ch_layout.addWidget(checkbox)
        layout.addWidget(self.ch_group)

        self.digital_group = QGroupBox("Digital")
        digital_layout = QVBoxLayout(self.digital_group)
        self.digital_checkbox = QCheckBox("Enable digital capture")
        self.digital_checkbox.setChecked(True)
        self.digital_checkbox.toggled.connect(self.digital_toggled.emit)
        digital_layout.addWidget(self.digital_checkbox)
        layout.addWidget(self.digital_group)

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

        display_group = QGroupBox("Display")
        display_layout = QGridLayout(display_group)
        display_layout.addWidget(QLabel("Buffer size:"), 0, 0)
        self.buf_spin = QSpinBox()
        self.buf_spin.setRange(256, 16384)
        self.buf_spin.setSingleStep(256)
        self.buf_spin.setValue(DEFAULT_WAVEFORM_LEN)
        self.buf_spin.valueChanged.connect(self.buffer_changed.emit)
        display_layout.addWidget(self.buf_spin, 0, 1)
        layout.addWidget(display_group)

        self.btn_clear = QPushButton("Clear Display")
        self.btn_clear.setStyleSheet("padding: 6px;")
        layout.addWidget(self.btn_clear)

        layout.addStretch()

        self.stats_label = QLabel("ADC inactive\nDigital inactive | UI 0 FPS")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self.stats_label)

        self._on_mode_changed()

    def _on_mode_changed(self) -> None:
        mode = self.mode_combo.currentData()
        is_osc = mode == MODE_OSCILLOSCOPE
        self.ch_group.setVisible(is_osc)
        self.digital_group.setVisible(is_osc)
        self.trig_group.setVisible(is_osc)
        self.mode_changed.emit(mode)

    def _on_trigger_apply(self) -> None:
        self.trigger_changed.emit(
            self.trig_channel.value(),
            self.trig_mode.currentData(),
            self.trig_level.value(),
        )

    def digital_enabled(self) -> bool:
        return self.digital_checkbox.isChecked()

    def set_connected(self, connected: bool) -> None:
        if connected:
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: #00E676; font-weight: bold; font-size: 13px;")
        else:
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: #FF4444; font-weight: bold; font-size: 13px;")

    def set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.mode_combo.setEnabled(not running)


class OscilloscopeWindow(QMainWindow):
    """Main oscilloscope GUI window."""

    def __init__(self, port: str, mode: int = MODE_HAT):
        super().__init__()

        self.port = port
        self.current_mode = mode
        self.reader: Optional[SerialReader] = None
        self.worker: Optional[SerialWorker] = None

        self.frame_count = 0
        self.last_fps_time = time.time()
        self.last_fps_value = 0.0

        self.adc_total_samples = 0
        self.pin_total_samples = 0
        self.adc_samples_since_update = 0
        self.pin_samples_since_update = 0
        self.last_adc_interval_ps = 0
        self.last_pin_interval_ps = 0
        self.last_adc_channel_count = ADC_CHANNELS

        self.setWindowTitle("Pico Oscilloscope")
        self.resize(1280, 760)
        self.setStyleSheet(f"background-color: {BG_COLOR}; color: {TEXT_COLOR};")

        self._build_ui()
        self._connect_signals()
        self._apply_mode(self.current_mode)

        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_display)
        self.refresh_timer.start(REFRESH_RATE_MS)

        self.fps_timer = QTimer()
        self.fps_timer.timeout.connect(self._update_stats)
        self.fps_timer.start(1000)

        self._connect_device()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.waveform = WaveformWidget()
        self.digital = DigitalWidget(DIGITAL_DISPLAY_PINS)
        self.splitter.addWidget(self.waveform)
        self.splitter.addWidget(self.digital)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)

        main_layout.addWidget(self.splitter, stretch=1)

        self.panel = ControlPanel()
        main_layout.addWidget(self.panel)

        self.statusBar().showMessage("Ready")
        self.statusBar().setStyleSheet("color: #888888;")

    def _connect_signals(self) -> None:
        self.panel.mode_changed.connect(self._on_mode_changed)
        self.panel.start_requested.connect(self._on_start)
        self.panel.stop_requested.connect(self._on_stop)
        self.panel.trigger_changed.connect(self._on_trigger_changed)
        self.panel.buffer_changed.connect(self._on_buffer_changed)
        self.panel.digital_toggled.connect(self._on_digital_toggled)
        self.panel.btn_clear.clicked.connect(self._on_clear)

        for index, checkbox in enumerate(self.panel.ch_checks):
            checkbox.toggled.connect(
                lambda checked, channel=index: self.waveform.set_channel_enabled(channel, checked)
            )

    def _connect_device(self) -> None:
        self.reader = SerialReader(self.port, timeout=0.1)
        if self.reader.connect():
            self.panel.set_connected(True)
            self.statusBar().showMessage(f"Connected to {self.port}")
        else:
            self.panel.set_connected(False)
            self.statusBar().showMessage(f"Failed to connect to {self.port}")

    def _apply_mode(self, mode: int) -> None:
        self.current_mode = mode
        self.waveform.show_trigger_line(mode == MODE_OSCILLOSCOPE)
        self._update_digital_visibility()

    def _update_digital_visibility(self) -> None:
        if self.current_mode == MODE_HAT:
            self.waveform.hide()
            self.digital.show()
            self.splitter.setSizes([0, 1])
            return

        self.waveform.show()
        if self.panel.digital_enabled():
            self.digital.show()
            self.splitter.setSizes([420, 220])
        else:
            self.digital.hide()
            self.splitter.setSizes([1, 0])

    def _on_mode_changed(self, mode: int) -> None:
        if self.worker is not None:
            self._on_stop()

        self._apply_mode(mode)

        if self.reader and self.reader.connected:
            self.reader.set_mode(mode)
            if mode == MODE_OSCILLOSCOPE:
                self.reader.configure_digital_enabled(self.panel.digital_enabled())

    def _on_start(self) -> None:
        if not self.reader or not self.reader.connected:
            self.statusBar().showMessage("Not connected")
            return

        if not self.reader.set_mode(self.current_mode):
            self.statusBar().showMessage("Failed to set mode")
            return

        if self.current_mode == MODE_OSCILLOSCOPE:
            if not self.reader.configure_digital_enabled(self.panel.digital_enabled()):
                self.statusBar().showMessage("Failed to configure digital capture")
                return

            if not self.reader.configure_trigger(
                self.panel.trig_channel.value(),
                self.panel.trig_mode.currentData(),
                self.panel.trig_level.value(),
            ):
                self.statusBar().showMessage("Failed to configure trigger")
                return

        if not self.reader.start_sampling():
            self.statusBar().showMessage("Failed to start sampling")
            return

        self.worker = SerialWorker(self.reader)
        self.worker.adc_batch_received.connect(self._on_adc_batch)
        self.worker.pin_batch_received.connect(self._on_pin_batch)
        self.worker.trigger_received.connect(self._on_trigger_event)
        self.worker.connection_lost.connect(self._on_connection_lost)
        self.worker.start()

        self.panel.set_running(True)
        self._reset_stream_counters()
        self.statusBar().showMessage("Sampling...")

    def _on_stop(self) -> None:
        if self.worker:
            self.worker.stop()
            self.worker = None

        if self.reader and self.reader.connected:
            self.reader.stop_sampling()

        self.panel.set_running(False)
        self.statusBar().showMessage("Stopped")

    def _reset_stream_counters(self) -> None:
        self.adc_total_samples = 0
        self.pin_total_samples = 0
        self.adc_samples_since_update = 0
        self.pin_samples_since_update = 0
        self.last_adc_interval_ps = 0
        self.last_pin_interval_ps = 0

    def _on_adc_batch(self, batch: ADCBatch) -> None:
        self.waveform.append_batch(batch)
        self.adc_total_samples += batch.sample_count
        self.adc_samples_since_update += batch.sample_count
        self.last_adc_interval_ps = batch.sample_interval_ps
        self.last_adc_channel_count = max(batch.channel_count, 1)

    def _on_pin_batch(self, batch: PinBatch) -> None:
        if self.current_mode == MODE_HAT or self.panel.digital_enabled():
            self.digital.append_batch(batch)
        self.pin_total_samples += batch.sample_count
        self.pin_samples_since_update += batch.sample_count
        self.last_pin_interval_ps = batch.sample_interval_ps

    def _on_trigger_event(self) -> None:
        self.statusBar().showMessage("Trigger detected", 1000)

    def _on_connection_lost(self) -> None:
        self.panel.set_connected(False)
        self.panel.set_running(False)
        self.worker = None
        self.statusBar().showMessage("Connection lost")

    def _on_trigger_changed(self, channel: int, mode: int, level: int) -> None:
        self.waveform.trigger_line.setValue((level / ADC_MAX) * ADC_VREF)
        self.waveform.show_trigger_line(mode != 0 and self.current_mode == MODE_OSCILLOSCOPE)

        if self.reader and self.reader.connected:
            if self.reader.configure_trigger(channel, mode, level):
                self.statusBar().showMessage(
                    f"Trigger: CH{channel + 1} mode={mode} level={level}"
                )
            else:
                self.statusBar().showMessage("Failed to configure trigger")

    def _on_buffer_changed(self, length: int) -> None:
        self.waveform.set_buffer_length(length)
        self.digital.set_buffer_length(length)

    def _on_digital_toggled(self, enabled: bool) -> None:
        self._update_digital_visibility()

        if not enabled:
            self.digital.clear_all()

        if self.current_mode != MODE_OSCILLOSCOPE:
            return

        if self.reader and self.reader.connected:
            if self.reader.configure_digital_enabled(enabled):
                state = "enabled" if enabled else "disabled"
                self.statusBar().showMessage(f"Digital capture {state}")
            else:
                self.statusBar().showMessage("Failed to update digital capture state")

    def _on_clear(self) -> None:
        self.waveform.clear_all()
        self.digital.clear_all()
        self._reset_stream_counters()

    def _refresh_display(self) -> None:
        self.frame_count += 1
        if self.current_mode == MODE_OSCILLOSCOPE:
            self.waveform.refresh()
        if self.current_mode == MODE_HAT or self.panel.digital_enabled():
            self.digital.refresh()

    def _update_stats(self) -> None:
        now = time.time()
        dt = now - self.last_fps_time
        if dt <= 0:
            return

        self.last_fps_value = self.frame_count / dt
        self.frame_count = 0
        self.last_fps_time = now

        adc_recv_rate = self.adc_samples_since_update / dt
        pin_recv_rate = self.pin_samples_since_update / dt
        self.adc_samples_since_update = 0
        self.pin_samples_since_update = 0

        if self.current_mode == MODE_OSCILLOSCOPE and self.last_adc_interval_ps > 0:
            cfg_adc_rate = SerialReader.sample_rate_from_interval_ps(self.last_adc_interval_ps)
            cfg_channel_rate = cfg_adc_rate / max(self.last_adc_channel_count, 1)
            adc_text = (
                f"ADC recv {format_rate(adc_recv_rate)} | cfg {format_rate(cfg_adc_rate)} agg "
                f"/ {format_rate(cfg_channel_rate)} ch"
            )
        else:
            adc_text = "ADC inactive"

        digital_active = self.current_mode == MODE_HAT or self.panel.digital_enabled()
        if digital_active and self.last_pin_interval_ps > 0:
            cfg_pin_rate = SerialReader.sample_rate_from_interval_ps(self.last_pin_interval_ps)
            pin_text = (
                f"Digital recv {format_rate(pin_recv_rate)} | cfg {format_rate(cfg_pin_rate)}"
            )
        else:
            pin_text = "Digital inactive"

        self.panel.stats_label.setText(
            f"{adc_text}\n{pin_text} | UI {self.last_fps_value:.0f} FPS"
        )

    def closeEvent(self, event) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pico_oscilloscope_gui",
        description="Pico Oscilloscope — real-time waveform viewer",
    )
    parser.add_argument("--port", "-p", required=True, help="Serial port (for example COM3)")
    parser.add_argument(
        "--mode",
        "-m",
        choices=["hat", "oscilloscope"],
        default="hat",
        help="Initial operating mode",
    )
    args = parser.parse_args()

    mode = MODE_HAT if args.mode == "hat" else MODE_OSCILLOSCOPE

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

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
