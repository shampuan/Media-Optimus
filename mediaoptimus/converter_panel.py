import os
import subprocess
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
                             QHeaderView, QGroupBox, QComboBox, QSlider, QSpinBox,
                             QCheckBox, QFileDialog, QRadioButton, QButtonGroup,
                             QFrame, QProgressBar, QSizePolicy)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from results_panel import ResultsPanel


# ─────────────────────────────────────────────────────────────────────────────
#  FFmpeg dönüştürme iş parçacığı
# ─────────────────────────────────────────────────────────────────────────────
class ConvertWorker(QThread):
    file_started  = pyqtSignal(int, str)       # sıra no, dosya adı
    file_progress = pyqtSignal(int, int)       # sıra no, yüzde (0-100)
    file_done     = pyqtSignal(int, bool, str) # sıra no, başarılı mı, hata mesajı
    all_done      = pyqtSignal()

    def __init__(self, jobs):
        super().__init__()
        # jobs: list of dict {src, dst, codec, resolution, crf, trash_src}
        self.jobs    = jobs
        self._cancel = False

    def cancel(self):
        self._cancel = True
        if hasattr(self, '_proc') and self._proc:
            self._proc.terminate()

    def run(self):
        for i, job in enumerate(self.jobs):
            if self._cancel:
                break

            self.file_started.emit(i, os.path.basename(job['src']))

            cmd = self._build_cmd(job)
            try:
                duration = self._get_duration(job['src'])
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    universal_newlines=True
                )
                proc = self._proc
                for line in proc.stdout:
                    line = line.strip()
                    if line.startswith('out_time_ms='):
                        try:
                            ms = int(line.split('=')[1])
                            if duration > 0 and ms > 0:
                                pct = min(int(ms / 1000000 / duration * 100), 99)
                                self.file_progress.emit(i, pct)
                        except ValueError:
                            pass
                proc.wait()
                if proc.returncode != 0:
                    raise subprocess.CalledProcessError(proc.returncode, cmd)
                self.file_progress.emit(i, 100)
                if job.get('trash_src'):
                    self._trash(job['src'])
                self.file_done.emit(i, True, "")
            except subprocess.CalledProcessError as e:
                self.file_done.emit(i, False, str(e))

        self.all_done.emit()

    def _build_cmd(self, job):
        cmd = ['ffmpeg', '-y', '-i', job['src']]

        # Codec
        if job['codec'] == 'H.265':
            cmd += ['-c:v', 'libx265', '-crf', str(job['crf']),
                    '-preset', 'fast', '-tag:v', 'hvc1']
        elif job['codec'] == 'AV1':
            cmd += ['-c:v', 'libsvtav1', '-crf', str(job['crf']),
                    '-preset', '6']
        else:  # VP9
            cmd += ['-c:v', 'libvpx-vp9', '-crf', str(job['crf']),
                    '-b:v', '0']

        # Çözünürlük
        if job['resolution'] == '720p':
            cmd += ['-vf', 'scale=-2:720']
        elif job['resolution'] == '480p':
            cmd += ['-vf', 'scale=-2:480']
        elif 'x' in str(job['resolution']):
            w, h = job['resolution'].split('x')
            cmd += ['-vf', f'scale={w}:{h}']

        # Ses — AVI için yeniden kodla, diğerleri kopyala
        ext_in = os.path.splitext(job['src'])[1].lower()
        if ext_in == '.avi':
            cmd += ['-c:a', 'aac', '-b:a', '128k']
        else:
            cmd += ['-c:a', 'copy']
        cmd += ['-progress', 'pipe:1', '-nostats']
        cmd.append(job['dst'])
        return cmd

    def _trash(self, path):
        try:
            # gio trash — freedesktop uyumlu
            subprocess.run(['gio', 'trash', path],
                           check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except Exception:
            try:
                subprocess.run(['trash-put', path],
                               check=True,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            except Exception:
                pass   # çöp kutusu araçları yoksa sessizce geç

    def _get_duration(self, path):
        try:
            cmd = ['ffprobe', '-v', 'error',
                   '-show_entries', 'format=duration',
                   '-of', 'default=noprint_wrappers=1:nokey=1',
                   path]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)\
                            .decode().strip()
            return float(out)
        except Exception:
            return 0.0

# ─────────────────────────────────────────────────────────────────────────────
#  Converter Panel Widget
# ─────────────────────────────────────────────────────────────────────────────
class ConverterPanel(QWidget):
    """
    Ana pencere bu widget'ı merkez widget olarak set eder.
    Dönüştürme bitince 'done' sinyali yayılır; ana pencere
    results_panel'i açar ya da ana ekrana döner.
    """
    back_requested = pyqtSignal()                      # geri dön
    conversion_done = pyqtSignal(list)                 # sonuçlar listesi

    def __init__(self, items: list, source_folder: str, parent=None):
        """
        items: [{'filename', 'res', 'duration', 'size_mb', 'codec', 'kbps'}, ...]
        source_folder: tarama yapılan klasör
        """
        super().__init__(parent)
        self.items         = items
        self.source_folder = source_folder
        self.worker        = None
        self._conv_blink_timer  = None
        self._conv_blink_state  = False
        self._next_blink_timer  = None
        self._next_blink_state  = False
        self.results       = []   # dönüştürme sonuçları

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        root.addWidget(self._build_left(), stretch=2)
        root.addWidget(self._build_right(), stretch=2)

    # ── Sol panel: video listesi ──────────────────────────────────────────

    def _build_left(self):
        frame = QFrame()
        lay   = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        title = QLabel("Dönüştürülecek Videolar")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        lay.addWidget(title)

        self.queue_table = QTableWidget()
        self.queue_table.setColumnCount(6)
        self.queue_table.setHorizontalHeaderLabels(
            ["Video Adı", "Çözünürlük", "Süre", "Boyut", "Codec", "kbps"])
        self.queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.queue_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.queue_table.setAlternatingRowColors(True)

        hdr = self.queue_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in {1: 100, 2: 60, 3: 75, 4: 65, 5: 60}.items():
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.queue_table.setColumnWidth(col, w)

        for d in self.items:
            r = self.queue_table.rowCount()
            self.queue_table.insertRow(r)
            mins, secs = divmod(int(d.get('duration', 0)), 60)
            self.queue_table.setItem(r, 0, QTableWidgetItem(d['filename']))
            self.queue_table.setItem(r, 1, QTableWidgetItem(d.get('res', '?')))
            self.queue_table.setItem(r, 2, QTableWidgetItem(f"{mins:02d}:{secs:02d}"))
            self.queue_table.setItem(r, 3, QTableWidgetItem(f"{d.get('size_mb', 0):.1f} MB"))
            self.queue_table.setItem(r, 4, QTableWidgetItem(d.get('codec', '?').upper()))
            self.queue_table.setItem(r, 5, QTableWidgetItem(str(d.get('kbps', 0))))

        lay.addWidget(self.queue_table)

        # Kuyruk yönetim butonları
        queue_btn_row = QHBoxLayout()
        self.remove_selected_btn = QPushButton("Seçilileri Kaldır")
        self.remove_selected_btn.setFixedHeight(28)
        self.remove_selected_btn.clicked.connect(self._remove_selected)
        self.clear_queue_btn = QPushButton("Listeyi Temizle")
        self.clear_queue_btn.setFixedHeight(28)
        self.clear_queue_btn.clicked.connect(self._clear_queue)
        queue_btn_row.addWidget(self.remove_selected_btn)
        queue_btn_row.addWidget(self.clear_queue_btn)
        queue_btn_row.addStretch()
        lay.addLayout(queue_btn_row)

        # Alt: ilerleme
        self.current_label = QLabel("")
        lay.addWidget(self.current_label)

        self.conv_progress = QProgressBar()
        self.conv_progress.setRange(0, len(self.items))
        self.conv_progress.setValue(0)
        self.conv_progress.setTextVisible(True)
        self.conv_progress.setFormat(f"0 / {len(self.items)}")
        lay.addWidget(self.conv_progress)

        return frame

    # ── Sağ panel: seçenekler ─────────────────────────────────────────────

    def _build_right(self):
        frame = QFrame()
        lay   = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("Dönüştürme Seçenekleri")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        lay.addWidget(title)

        # Codec
        codec_group = QGroupBox("Codec")
        codec_lay   = QVBoxLayout(codec_group)
        self.radio_h265 = QRadioButton("H.265 (HEVC)")
        self.radio_vp9  = QRadioButton("VP9")
        self.radio_av1  = QRadioButton("AV1")
        self.radio_h265.setChecked(True)
        codec_lay.addWidget(self.radio_h265)
        codec_lay.addWidget(self.radio_vp9)
        codec_lay.addWidget(self.radio_av1)
        lay.addWidget(codec_group)

        # Çözünürlük
        res_group = QGroupBox("Çözünürlük")
        res_lay   = QVBoxLayout(res_group)
        self.radio_orig   = QRadioButton("Orijinal kalsın")
        self.radio_720    = QRadioButton("720p'ye küçült")
        self.radio_480    = QRadioButton("480p'ye küçült")
        self.radio_custom = QRadioButton("Elle gir:")
        self.radio_orig.setChecked(True)

        custom_row = QHBoxLayout()
        self.custom_w = QSpinBox()
        self.custom_w.setRange(144, 7680)
        self.custom_w.setValue(1280)
        self.custom_w.setFixedWidth(70)
        self.custom_w.setEnabled(False)
        lbl_x = QLabel("x")
        self.custom_h = QSpinBox()
        self.custom_h.setRange(144, 4320)
        self.custom_h.setValue(720)
        self.custom_h.setFixedWidth(70)
        self.custom_h.setEnabled(False)
        custom_row.addWidget(self.radio_custom)
        custom_row.addWidget(self.custom_w)
        custom_row.addWidget(lbl_x)
        custom_row.addWidget(self.custom_h)
        custom_row.addStretch()

        self.radio_custom.toggled.connect(
            lambda checked: (self.custom_w.setEnabled(checked),
                             self.custom_h.setEnabled(checked)))

        res_lay.addWidget(self.radio_orig)
        res_lay.addWidget(self.radio_720)
        res_lay.addWidget(self.radio_480)
        res_lay.addLayout(custom_row)
        lay.addWidget(res_group)

        # CRF
        crf_group = QGroupBox("CRF Değeri  (düşük = yüksek kalite)")
        crf_lay   = QHBoxLayout(crf_group)
        self.crf_slider = QSlider(Qt.Orientation.Horizontal)
        self.crf_slider.setRange(18, 35)
        self.crf_slider.setValue(28)
        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(18, 35)
        self.crf_spin.setValue(28)
        self.crf_spin.setFixedWidth(55)
        self.crf_slider.valueChanged.connect(self.crf_spin.setValue)
        self.crf_spin.valueChanged.connect(self.crf_slider.setValue)
        crf_lay.addWidget(QLabel("18"))
        crf_lay.addWidget(self.crf_slider)
        crf_lay.addWidget(QLabel("35"))
        crf_lay.addWidget(self.crf_spin)
        lay.addWidget(crf_group)

        # Çıktı klasörü
        out_group = QGroupBox("Çıktı")
        out_lay   = QVBoxLayout(out_group)

        self.radio_same  = QRadioButton("Aynı klasöre kaydet")
        self.radio_other = QRadioButton("Başka klasöre kaydet")
        self.radio_same.setChecked(True)
        out_lay.addWidget(self.radio_same)

        self.chk_trash = QCheckBox("Kaynağı çöp kutusuna taşı")
        self.chk_trash.setContentsMargins(16, 0, 0, 0)
        out_lay.addWidget(self.chk_trash)

        out_lay.addWidget(self.radio_other)

        dest_row = QHBoxLayout()
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Hedef klasör seçin...")
        self.dest_edit.setReadOnly(True)
        self.dest_edit.setEnabled(False)
        self.dest_btn  = QPushButton("Seç")
        self.dest_btn.setFixedWidth(60)
        self.dest_btn.setEnabled(False)
        self.dest_btn.clicked.connect(self._pick_dest)
        dest_row.addWidget(self.dest_edit, stretch=1)
        dest_row.addWidget(self.dest_btn)
        out_lay.addLayout(dest_row)

        self.radio_same.toggled.connect(self._on_output_toggle)
        lay.addWidget(out_group)

        lay.addStretch()

        # Butonlar
        btn_row = QHBoxLayout()
        self.back_btn    = QPushButton("← Geri")
        self.back_btn.setFixedHeight(34)
        self.convert_btn = QPushButton("▶  Dönüştür")
        self.convert_btn.setFixedHeight(34)
        self.convert_btn.setMinimumWidth(140)
        self.stop_btn    = QPushButton("■  Durdur")
        self.stop_btn.setFixedHeight(34)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("color: #e74c3c;")
        self.next_btn    = QPushButton("Sonuçları Gör →")
        self.next_btn.setFixedHeight(34)
        self.next_btn.setEnabled(False)
        self.next_btn.setStyleSheet("color: gray;")
        self.back_btn.clicked.connect(self._on_back)
        self.convert_btn.clicked.connect(self._on_convert)
        self.stop_btn.clicked.connect(self._on_stop)
        self.next_btn.clicked.connect(self._on_next)
        btn_row.addWidget(self.back_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.convert_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.next_btn)
        lay.addLayout(btn_row)

        return frame

    # ── Yardımcı ─────────────────────────────────────────────────────────

    def _on_output_toggle(self, same_checked):
        self.chk_trash.setVisible(same_checked)
        self.dest_btn.setEnabled(not same_checked)
        self.dest_edit.setEnabled(not same_checked)
        if same_checked:
            self.dest_edit.clear()

    def _pick_dest(self):
        folder = QFileDialog.getExistingDirectory(self, "Hedef Klasör Seç")
        if folder:
            self.dest_edit.setText(folder)

    def _on_back(self):
        self.back_requested.emit()
        
    def _remove_selected(self):
        rows = sorted(set(
            idx.row() for idx in self.queue_table.selectedIndexes()
        ), reverse=True)
        for row in rows:
            self.queue_table.removeRow(row)
            if row < len(self.items):
                self.items.pop(row)

    def _clear_queue(self):
        self.queue_table.setRowCount(0)
        self.items.clear()

    def _get_resolution_str(self):
        if self.radio_720.isChecked():
            return '720p'
        if self.radio_480.isChecked():
            return '480p'
        if self.radio_custom.isChecked():
            return f"{self.custom_w.value()}x{self.custom_h.value()}"
        return 'original'

    def _get_output_ext(self):
        if self.radio_h265.isChecked():
            return '.mp4'
        elif self.radio_av1.isChecked():
            return '.mkv'
        else:
            return '.webm'

    # ── Dönüştürme başlat ─────────────────────────────────────────────────

    def _on_convert(self):
        # Hedef klasör belirle
        if self.radio_same.isChecked():
            dest_folder = self.source_folder
        else:
            dest_folder = self.dest_edit.text()
            if dest_folder == "—" or not os.path.isdir(dest_folder):
                self.current_label.setText("Hata: Geçerli bir hedef klasör seçin.")
                return

        if self.radio_h265.isChecked():
            codec = 'H.265'
        elif self.radio_av1.isChecked():
            codec = 'AV1'
        else:
            codec = 'VP9'
        resolution = self._get_resolution_str()
        crf        = self.crf_spin.value()
        ext        = self._get_output_ext()
        trash_src  = self.chk_trash.isChecked() and self.radio_same.isChecked()

        jobs = []
        for d in self.items:
            src      = os.path.join(self.source_folder, d['filename'])
            base     = os.path.splitext(d['filename'])[0]
            dst_name = base + '_conv' + ext
            dst      = os.path.join(dest_folder, dst_name)
            counter  = 1
            while os.path.exists(dst):
                dst_name = f"{base}_conv_{counter}{ext}"
                dst      = os.path.join(dest_folder, dst_name)
                counter += 1
            jobs.append({
                'src'        : src,
                'dst'        : dst,
                'codec'      : codec,
                'resolution' : resolution,
                'crf'        : crf,
                'trash_src'  : trash_src,
                'filename'   : d['filename'],
                'src_mb'     : d.get('size_mb', 0),
                'src_codec'  : d.get('codec', '?'),
                'src_kbps'   : d.get('kbps', 0),
                'src_res'    : d.get('res', '?'),
            })

        self.results = []
        self.convert_btn.setEnabled(False)
        self.back_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.remove_selected_btn.setEnabled(False)
        self.clear_queue_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("color: #e74c3c;")
        self.next_btn.setEnabled(False)
        self.next_btn.setStyleSheet("color: gray;")
        self.conv_progress.setEnabled(True)
        self._start_conv_blink()
        self.conv_progress.setValue(0)
        self.conv_progress.setFormat(f"0 / {len(jobs)}")

        self.worker = ConvertWorker(jobs)
        self.worker.file_started.connect(self._on_file_started)
        self.worker.file_progress.connect(self._on_file_progress)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.all_done.connect(self._on_all_done)
        self.worker.start()

    def _on_file_started(self, idx, name):
        self.current_label.setText(f"İşleniyor: {name}")
        self.conv_progress.setValue(0)
        self.queue_table.selectRow(idx)

    def _on_file_progress(self, idx, pct):
        total = len(self.items)
        self.conv_progress.setRange(0, 100)
        self.conv_progress.setValue(pct)
        self.conv_progress.setFormat(f"{idx + 1} / {total}  —  %{pct}")

    def _on_file_done(self, idx, success, error_msg):
        done = idx + 1
        self.conv_progress.setValue(done)
        self.conv_progress.setFormat(f"{done} / {len(self.items)}")

        job = self.worker.jobs[idx]

        dst_mb = 0
        if success and os.path.exists(job['dst']):
            dst_mb = os.path.getsize(job['dst']) / (1024 * 1024)

        self.results.append({
            'filename'  : job['filename'],
            'src'       : job['src'],
            'dst'       : job['dst'],
            'src_mb'    : job['src_mb'],
            'src_codec' : job['src_codec'],
            'src_kbps'  : job['src_kbps'],
            'src_res'   : job['src_res'],
            'dst_mb'    : dst_mb,
            'success'   : success,
            'error'     : error_msg,
            'trashed'   : job['trash_src'] and success,
        })

        color = QColor("#2ecc71") if success else QColor("#e74c3c")
        for col in range(self.queue_table.columnCount()):
            item = self.queue_table.item(idx, col)
            if item:
                item.setForeground(color)

    def _on_next(self):
        self._stop_next_blink()
        self.conversion_done.emit(self.results)
    
    def _start_conv_blink(self):
        if self._conv_blink_timer is not None:
            return
        self.convert_btn.setText("⟳  Dönüştürülüyor")
        self._conv_blink_timer = QTimer()
        self._conv_blink_timer.timeout.connect(self._do_conv_blink)
        self._conv_blink_timer.start(600)

    def _stop_conv_blink(self):
        if self._conv_blink_timer is not None:
            self._conv_blink_timer.stop()
            self._conv_blink_timer = None
        self.convert_btn.setStyleSheet("")
        self.convert_btn.setText("▶  Dönüştür")

    def _do_conv_blink(self):
        self._conv_blink_state = not self._conv_blink_state
        if self._conv_blink_state:
            self.convert_btn.setStyleSheet(
                "background-color: #f1c40f; color: black;")
        else:
            self.convert_btn.setStyleSheet("")

    def _start_next_blink(self):
        if self._next_blink_timer is not None:
            return
        self._next_blink_timer = QTimer()
        self._next_blink_timer.timeout.connect(self._do_next_blink)
        self._next_blink_timer.start(600)

    def _stop_next_blink(self):
        if self._next_blink_timer is not None:
            self._next_blink_timer.stop()
            self._next_blink_timer = None
        self.next_btn.setStyleSheet("")

    def _do_next_blink(self):
        self._next_blink_state = not self._next_blink_state
        if self._next_blink_state:
            self.next_btn.setStyleSheet(
                "background-color: #2ecc71; color: black;")
        else:
            self.next_btn.setStyleSheet("")
    
    def _on_stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.stop_btn.setEnabled(False)
            self.current_label.setText("Durduruluyor...")

    def _on_all_done(self):
        self.current_label.setText("Tamamlandı.")
        self.conv_progress.setValue(0)
        self.conv_progress.setRange(0, 100)
        self.conv_progress.setFormat("")
        self.conv_progress.setEnabled(False)
        self.convert_btn.setEnabled(True)
        self.convert_btn.setStyleSheet("")
        self.back_btn.setEnabled(True)
        self.remove_selected_btn.setEnabled(True)
        self.clear_queue_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("color: gray;")
        self.next_btn.setEnabled(True)
        self._stop_conv_blink()
        self._start_next_blink()
