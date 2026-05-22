#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import subprocess
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QHeaderView, QProgressBar,
                             QFileDialog, QLabel, QFrame, QGroupBox,
                             QMenu, QSpinBox, QStackedWidget, QDialog,
                             QDialogButtonBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QColor, QPalette, QDesktopServices
from converter_panel import ConverterPanel
from results_panel import ResultsPanel

# Wayland ve modern masaüstü ortamları için uyumluluk ayarları
if "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", ""):
    os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"

#  Arka plan tarama iş parçacığı

class ScanWorker(QThread):
    row_ready = pyqtSignal(dict)
    progress  = pyqtSignal(int, int)
    finished  = pyqtSignal(int)

    def __init__(self, path, kbps_threshold, max_height, tahammul_esigi, min_mb_limit):
        super().__init__()
        self.path           = path
        self.kbps_threshold = kbps_threshold
        self.max_height     = max_height
        self.tahammul_esigi = tahammul_esigi
        self.min_mb_limit   = min_mb_limit

    def run(self):
        video_exts = ('.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.mpg')
        files = [f for f in os.listdir(self.path) if f.lower().endswith(video_exts)]
        total = len(files)
        rows  = []

        for i, filename in enumerate(files):
            file_path  = os.path.join(self.path, filename)
            size_bytes = os.path.getsize(file_path)
            size_mb    = size_bytes / (1024 * 1024)

            w, h, duration, codec, kbps = self._get_metadata(file_path)

            # Çözünürlüğün kısa kenarına göre referans kbps tayini
            short_edge = min(w, h) if (w > 0 and h > 0) else h
            if short_edge >= 1080:
                ref_kbps = 1000
            elif short_edge >= 720:
                ref_kbps = 600
            elif short_edge >= 480:
                ref_kbps = 400
            else:
                ref_kbps = 250

            # İsraf Oranı Formülü
            if kbps > 0:
                israf_orani = ((kbps - ref_kbps) / ref_kbps) * 100
            else:
                israf_orani = 0.0

            # Bağımsız Sütun Rolleri
            kbps_over = kbps > self.kbps_threshold if kbps > 0 else False
            res_warn = (h > self.max_height) if h > 0 else False
            is_cuce = size_mb < self.min_mb_limit

            rows.append({
                'filename'   : filename,
                'res'        : f"{w}x{h}" if w > 0 else "?",
                'h'          : h,
                'short_edge' : short_edge,
                'duration'   : duration,
                'size_mb'    : size_mb,
                'codec'      : codec,
                'kbps'       : kbps,
                'israf_orani': israf_orani,
                'kbps_over'  : kbps_over,
                'res_warn'   : res_warn,
                'is_cuce'    : is_cuce
            })
            self.progress.emit(i + 1, total)

        # Akıllı Öncelik Sıralaması: Önce cüce olmayanlar üstte, sonra israf oranına göre azalan
        def sort_key(r):
            return (not r['is_cuce'], r['israf_orani'])

        rows.sort(key=sort_key, reverse=True)

        for data in rows:
            self.row_ready.emit(data)
        self.finished.emit(total)

    def _get_metadata(self, file_path):
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries',
                'stream=width,height,codec_name,bit_rate'
                ':format=bit_rate,duration',
                '-of', 'default=noprint_wrappers=1',
                file_path
            ]
            raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT)\
                            .decode(errors='replace')

            # Anahtarları topla — bit_rate için ikisini ayrı tut
            kv          = {}
            bit_rates   = []
            for line in raw.splitlines():
                if '=' in line:
                    k, _, v = line.partition('=')
                    k, v = k.strip(), v.strip()
                    if k == 'bit_rate':
                        bit_rates.append(v)   # stream + format sırayla gelir
                    elif k not in kv:
                        kv[k] = v

            codec    = kv.get('codec_name', '?')
            w        = int(kv['width'])      if 'width'    in kv else 0
            h        = int(kv['height'])     if 'height'   in kv else 0
            duration = float(kv['duration']) if 'duration' in kv else 0.0

            # kbps: geçerli (N/A olmayan, 10'dan büyük) ilk değeri al
            kbps = 0
            for brate in bit_rates:
                if brate and brate != 'N/A':
                    try:
                        val = int(brate) // 1000
                        if val > 10:        # 3 kbps gibi saçma değerleri ele
                            kbps = val
                            break
                    except ValueError:
                        pass

            # Süre sıfırsa ffprobe'a format duration için ayrı sor
            if duration == 0.0:
                try:
                    dur_cmd = [
                        'ffprobe', '-v', 'error',
                        '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1',
                        file_path
                    ]
                    dur_out = subprocess.check_output(
                        dur_cmd, stderr=subprocess.STDOUT)\
                        .decode(errors='replace').strip()
                    duration = float(dur_out) if dur_out else 0.0
                except Exception:
                    pass

            return w, h, duration, codec, kbps

        except Exception:
            pass
        return 0, 0, 0, '?', 0


#  Ana Pencere

class BigFileDetector(QMainWindow):

    COL_CHK   = 0
    COL_NAME  = 1
    COL_RES   = 2
    COL_DUR   = 3
    COL_SIZE  = 4
    COL_CODEC = 5
    COL_KBPS  = 6
    COL_BAR   = 7

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Optimus")
        
        # Dinamik ikon yolu tanımı ve pencere ikonunun ayarlanması
        self.app_dir = os.path.dirname(os.path.abspath(__file__))
        self.icon_path = os.path.join(self.app_dir, "Media Optimus.png")
        if os.path.exists(self.icon_path):
            from PyQt6.QtGui import QIcon
            self.setWindowIcon(QIcon(self.icon_path))
            
        self.setMinimumSize(860, 520)
        self.resize(950, 650)
        self.worker = None
        self.results_panel = None
        self.queue = []   # kalıcı dönüştürme kuyruğu
        self._blink_timer = None

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.central_widget = QWidget()
        self.stack.addWidget(self.central_widget)
        central = self.central_widget
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        root.addWidget(self._build_header())
        root.addWidget(self._build_controls())
        root.addWidget(self._build_table())

        self.status = QLabel("Başlamak için bir klasör seçin.")
        root.addWidget(self.status)

        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.setFixedHeight(8)
        root.addWidget(self.scan_progress)
        btn_frame = QFrame()
        btn_lay   = QHBoxLayout(btn_frame)
        btn_lay.setContentsMargins(0, 4, 0, 0)

        self.about_btn = QPushButton("About")
        self.about_btn.setFixedHeight(32)
        self.about_btn.setFixedWidth(80)
        self.about_btn.clicked.connect(self._show_about)
        btn_lay.addWidget(self.about_btn)

        btn_lay.addStretch()

        self.queue_btn = QPushButton("Seçilileri Kuyruğa Ekle")
        self.queue_btn.setFixedHeight(32)
        self.queue_btn.setMinimumWidth(200)
        self.queue_btn.setEnabled(False)
        self.queue_btn.clicked.connect(self._add_to_queue)
        btn_lay.addWidget(self.queue_btn)

        self.goto_queue_btn = QPushButton("Kuyruğa Git (0) →")
        self.goto_queue_btn.setFixedHeight(32)
        self.goto_queue_btn.setMinimumWidth(160)
        self.goto_queue_btn.setEnabled(False)
        self.goto_queue_btn.clicked.connect(self._open_converter)
        btn_lay.addWidget(self.goto_queue_btn)

        root.addWidget(btn_frame)

    def _build_header(self):
        frame = QFrame()
        lay   = QHBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)

        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("Klasör yolu...")

        self.browse_btn = QPushButton("Klasör Seç")
        self.browse_btn.setFixedWidth(110)
        self.browse_btn.clicked.connect(self.select_folder)

        self.scan_btn = QPushButton("▶  Analiz Et")
        self.scan_btn.setFixedWidth(110)
        self.scan_btn.clicked.connect(self.start_analysis)

        self.results_btn = QPushButton("Son Sonuçlar")
        self.results_btn.setFixedWidth(110)
        self.results_btn.setEnabled(False)
        self.results_btn.clicked.connect(self._show_results)

        lay.addWidget(self.address_bar)
        lay.addWidget(self.browse_btn)
        lay.addWidget(self.scan_btn)
        lay.addWidget(self.results_btn)
        return frame

    def _build_controls(self):
        group = QGroupBox("Eşikler")
        lay   = QHBoxLayout(group)
        lay.setSpacing(12)

        lay.addWidget(QLabel("Maks. kbps:"))
        self.spin_kbps = QSpinBox()
        self.spin_kbps.setRange(100, 50000)
        self.spin_kbps.setSingleStep(100)
        self.spin_kbps.setValue(1500)
        self.spin_kbps.setSuffix(" kbps")
        self.spin_kbps.setFixedWidth(110)
        lay.addWidget(self.spin_kbps)

        lay.addWidget(QLabel("    Maks. yükseklik:"))
        self.spin_maxh = QSpinBox()
        self.spin_maxh.setRange(144, 4320)
        self.spin_maxh.setSingleStep(10)
        self.spin_maxh.setValue(720)
        self.spin_maxh.setSuffix(" px")
        self.spin_maxh.setFixedWidth(90)
        lay.addWidget(self.spin_maxh)

        lay.addWidget(QLabel("    Tahammül Eşiği:"))
        self.spin_tahammul = QSpinBox()
        self.spin_tahammul.setRange(0, 500)
        self.spin_tahammul.setSingleStep(5)
        self.spin_tahammul.setValue(40)
        self.spin_tahammul.setSuffix(" %")
        self.spin_tahammul.setFixedWidth(80)
        lay.addWidget(self.spin_tahammul)

        lay.addWidget(QLabel("    Min. Boyut:"))
        self.spin_min_mb = QSpinBox()
        self.spin_min_mb.setRange(0, 1000)
        self.spin_min_mb.setSingleStep(5)
        self.spin_min_mb.setValue(10)
        self.spin_min_mb.setSuffix(" MB")
        self.spin_min_mb.setFixedWidth(85)
        lay.addWidget(self.spin_min_mb)

        lay.addStretch()
        return group

    def _show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("About Media Optimus")
        dlg.setMinimumWidth(420)

        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)

        # Hakkında paneline ikon eklenmesi
        if os.path.exists(self.icon_path):
            from PyQt6.QtGui import QPixmap
            logo_label = QLabel()
            pixmap = QPixmap(self.icon_path)
            # İkonu Hakkında paneli için 64x64 boyutuna ölçeklendiriyoruz
            scaled_pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(scaled_pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(logo_label)

        title = QLabel("<b style='font-size:32px;'>Media Optimus</b>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        info = QLabel(
            "<table cellspacing='6'>"
            "<tr><td><b>Version:</b></td><td>1.0.0 </td></tr>"
            "<tr><td><b>License:</b></td><td>GNU GPLv1</td></tr>"
            "<tr><td><b>GUI/UX:</b></td><td>Qt-6</td></tr>"
            "<tr><td><b>Developer:</b></td><td>A. Serhat KILIÇOĞLU (shampuan)</td></tr>"
            "<tr><td><b>GitHub:</b></td><td>"
            "<a href='https://www.github.com/shampuan'>github.com/shampuan</a>"
            "</td></tr>"
            "</table>"
        )
        info.setOpenExternalLinks(True)
        lay.addWidget(info)

        #lay.addWidget(QLabel(""))  # boşluk

        desc = QLabel(
            "Media Optimus is a video archive optimizer that helps you reclaim disk space "
            "by detecting bloated video files and converting them to efficient "
            "HEVC or VP9 formats with minimal quality loss."
            "<br><br>"
            "This program was developed with the active assistance of Claude AI."
            "<br><br>"
            "This program comes with absolutely no warranty."
            "<br><br>"
            "© 2026 — A. Serhat KILIÇOĞLU"
        )
        desc.setWordWrap(True)
        lay.addWidget(desc)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dlg.accept)
        lay.addWidget(buttons)

        dlg.exec()

    def _start_blink(self):
        if self._blink_timer is not None:
            return
        self._blink_state = False
        self._blink_timer = QTimer()
        self._blink_timer.timeout.connect(self._do_blink)
        self._blink_timer.start(600)

    def _stop_blink(self):
        if self._blink_timer is not None:
            self._blink_timer.stop()
            self._blink_timer = None
        self.queue_btn.setEnabled(False)
        self.queue_btn.setStyleSheet("")
        self.queue_btn.setText("Seçilileri Kuyruğa Ekle →")

    def _do_blink(self):
        self._blink_state = not self._blink_state
        if self._blink_state:
            self.queue_btn.setStyleSheet("background-color: #f1c40f; color: black;")
        else:
            self.queue_btn.setStyleSheet("")

    def _build_table(self):
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "", "Video Adı", "Çözünürlük", "Süre", "Boyut", "Codec", "kbps", "Durum"
        ])

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setMinimumSectionSize(20)
        hdr.setStretchLastSection(False)

        self.table.setColumnWidth(self.COL_CHK,   28)
        self.table.setColumnWidth(self.COL_NAME,  250)
        self.table.setColumnWidth(self.COL_RES,   110)
        self.table.setColumnWidth(self.COL_DUR,   65)
        self.table.setColumnWidth(self.COL_SIZE,  80)
        self.table.setColumnWidth(self.COL_CODEC, 55)
        self.table.setColumnWidth(self.COL_KBPS,  60)
        self.table.setColumnWidth(self.COL_BAR,   180)

        hdr.sectionDoubleClicked.connect(
            lambda col: self.table.resizeColumnToContents(col))
        self.table.verticalHeader().setVisible(False)

        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemDoubleClicked.connect(self.play_video)
        self.table.itemChanged.connect(self._on_checkbox_changed)
        from PyQt6.QtGui import QShortcut, QKeySequence
        self._del_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table)
        self._del_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._del_shortcut.activated.connect(self._trash_selected)
        
        return self.table

    # ── Analiz ──

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Klasör Seç")
        if folder:
            self.address_bar.setText(folder)
            self.status.setText("Klasör seçildi.")

    def start_analysis(self):
        path = self.address_bar.text()
        if not os.path.isdir(path):
            self.status.setText("Hata: Geçersiz klasör!")
            return
        if self.worker and self.worker.isRunning():
            return

        self.table.setRowCount(0)
        self.scan_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.status.setText("Taranıyor...")
        self.scan_progress.setValue(0)

        self.worker = ScanWorker(
            path,
            self.spin_kbps.value(),
            self.spin_maxh.value(),
            self.spin_tahammul.value(),
            self.spin_min_mb.value()
        )
        self.worker.row_ready.connect(self._append_row)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    # ── Satır ekleme 

    def _append_row(self, d):
        i = self.table.rowCount()
        self.table.insertRow(i)
        chk_item = QTableWidgetItem()
        # ItemIsSelectable bayrağını kaldırarak hücrenin kendi kendine seçilmesini ve odaklanmasını engelliyoruz
        chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        chk_item.setCheckState(Qt.CheckState.Unchecked)
        chk_item.setBackground(QColor("#1a3a5c"))
        self.table.setItem(i, self.COL_CHK, chk_item)
        
        # Hücreye tıklandığında tablonun o küçük alanı odaklamasını tamamen kapatmak için:
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        mins, secs = divmod(int(d['duration']), 60)

        # Video adı
        name_item = QTableWidgetItem(d['filename'])
        self.table.setItem(i, self.COL_NAME, name_item)

        # Çözünürlük - Sadece arayüzdeki Maks. yükseklik spinner'ına göre uyarır
        res_text = d['res'] + (" ▲" if d['res_warn'] else "")
        res_item  = QTableWidgetItem(res_text)
        if d['res_warn']:
            res_item.setForeground(QColor("#f1c40f"))
        self.table.setItem(i, self.COL_RES, res_item)

        self.table.setItem(i, self.COL_DUR,
            QTableWidgetItem(f"{mins:02d}:{secs:02d}"))
        
        # Boyut Sütunu
        size_item = QTableWidgetItem(f"{d['size_mb']:.1f} MB")
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if d['is_cuce']:
            size_item.setForeground(QColor("#5499c7"))   # mavi: cüce
        elif d['size_mb'] <= 25:
            size_item.setForeground(QColor("#2ecc71"))   # yeşil
        elif d['size_mb'] <= 55:
            size_item.setForeground(QColor("#f1c40f"))   # sarı
        elif d['size_mb'] <= 100:
            size_item.setForeground(QColor("#e67e22"))   # turuncu
        else:
            size_item.setForeground(QColor("#e74c3c"))   # kırmızı
        self.table.setItem(i, self.COL_SIZE, size_item)

        # Codec
        codec_item = QTableWidgetItem(d['codec'].upper())
        cl = d['codec'].lower()
        if cl in ('hevc', 'h265'):
            codec_item.setForeground(QColor("#2ecc71"))
        elif cl in ('h264', 'avc'):
            codec_item.setForeground(QColor("#3498db"))
        else:
            codec_item.setForeground(QColor("#e67e22"))
        self.table.setItem(i, self.COL_CODEC, codec_item)

        # kbps — eşik aşıldıysa kırmızı
        kbps_item = QTableWidgetItem(str(d['kbps']))
        kbps_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if d['kbps_over']:
            kbps_item.setForeground(QColor("#e74c3c"))
        self.table.setItem(i, self.COL_KBPS, kbps_item)

        # Progress bar — Yeni İsraf Oranı formülüne ve seçilen tahammül eşiğine göre dinamik renklenir
        self.table.setCellWidget(i, self.COL_BAR,
            self._make_bar(d['israf_orani'], self.spin_tahammul.value()))

    def _make_bar(self, israf_orani: float, tahammul_esigi: int) -> QProgressBar:
        bar = QProgressBar()
        
        # İsraf eksi değerde çıkabilir (ref_kbps altı), barın taşmaması için 0 ile sınırlıyoruz
        bar_degeri = max(0, int(israf_orani))
        
        # Eğer israf oranı çok yüksekse barın görsel doluluğunu %100'e cap'liyoruz
        bar.setRange(0, 100)
        bar.setValue(min(bar_degeri, 100))
        bar.setTextVisible(True)
        bar.setFormat(f"%{israf_orani:.1f} İsraf")

        # Renk Yönetimi: İsraf oranı belirlenen tahammül eşiğinin altındaysa Yeşil, üstündeyse Kırmızı/Turuncu
        if israf_orani <= tahammul_esigi:
            color = "#27ae60"   # Yeşil Bar: Tahammül Edilebilir Hafif Fazlalık
        elif israf_orani <= tahammul_esigi * 2:
            color = "#e67e22"   # Turuncu Bar: Belirgin İsraf / Sınırı Aşmaya Başlamış
        else:
            color = "#c0392b"   # Kırmızı Bar: Azılı Vampir Dosya

        pal = bar.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor(color))
        bar.setPalette(pal)
        return bar

    def _make_size_item(self, size_mb: float) -> QTableWidgetItem:
        item = QTableWidgetItem(f"{size_mb:.1f} MB")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if size_mb <= 25:
            item.setForeground(QColor("#2ecc71"))   # yeşil
        elif size_mb <= 55:
            item.setForeground(QColor("#f1c40f"))   # sarı
        elif size_mb <= 100:
            item.setForeground(QColor("#e67e22"))   # turuncu
        else:
            item.setForeground(QColor("#e74c3c"))   # kırmızı
        return item

    def _on_progress(self, done, total):
        self.status.setText(f"Taranan: {done} / {total}")
        if total > 0:
            self.scan_progress.setValue(int(done / total * 100))

    def _on_finished(self, total):
        kbps_count = sum(
            1 for row in range(self.table.rowCount())
            if self.table.item(row, self.COL_KBPS) and
               self.table.item(row, self.COL_KBPS).foreground().color() == QColor("#e74c3c")
        )
        res_count = sum(
            1 for row in range(self.table.rowCount())
            if self.table.item(row, self.COL_RES) and
               "▲" in self.table.item(row, self.COL_RES).text()
        )
        self.status.setText(
            f"Tamamlandı — {total} dosya.  "
            f"kbps aşımı: {kbps_count}  |  "
            f"Çözünürlük aşımı: {res_count}  |  "
            f"Tablo öncelik sırasına göre dizilmiştir."
        )
        self.scan_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_table_columns()
    
    def showEvent(self, event):
        super().showEvent(event)
        self._fit_table_columns()

    def _fit_table_columns(self):
        total_w   = self.table.viewport().width()
        other_w   = sum(self.table.columnWidth(c)
                        for c in range(self.table.columnCount())
                        if c != self.COL_NAME)
        name_w = max(80, total_w - other_w)
        self.table.setColumnWidth(self.COL_NAME, name_w)

    def _on_checkbox_changed(self, item):
        if item.column() != self.COL_CHK:
            return
        checked_count = sum(
            1 for row in range(self.table.rowCount())
            if self.table.item(row, self.COL_CHK) and
               self.table.item(row, self.COL_CHK).checkState() == Qt.CheckState.Checked
        )
        if checked_count > 0:
            self.queue_btn.setEnabled(True)
            self.queue_btn.setText(f"Seçilileri Kuyruğa Ekle ({checked_count}) →")
            self._start_blink()
        else:
            self._stop_blink()

    def _add_to_queue(self):
        added = 0
        skipped = 0
        existing_paths = {q['full_path'] for q in self.queue}

        for row in range(self.table.rowCount()):
            chk = self.table.item(row, self.COL_CHK)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                filename  = self.table.item(row, self.COL_NAME).text()
                full_path = os.path.join(self.address_bar.text(), filename)
                if full_path in existing_paths:
                    skipped += 1
                    continue
                self.queue.append({
                    'full_path': full_path,
                    'filename' : filename,
                    'res'      : self.table.item(row, self.COL_RES).text().replace(" ▲", ""),
                    'duration' : self._get_duration_from_row(row),
                    'size_mb'  : float(self.table.item(row, self.COL_SIZE).text().replace(" MB", "")),
                    'codec'    : self.table.item(row, self.COL_CODEC).text(),
                    'kbps'     : int(self.table.item(row, self.COL_KBPS).text()),
                })
                added += 1

        self._update_goto_btn()

        msg = f"{added} dosya kuyruğa eklendi."
        if skipped > 0:
            msg += f" {skipped} dosya zaten kuyruktaydı, atlandı."
        self.status.setText(msg)

    def _update_goto_btn(self):
        count = len(self.queue)
        self.goto_queue_btn.setText(f"Kuyruğa Git ({count}) →")
        self.goto_queue_btn.setEnabled(count > 0)

    def _open_converter(self):
        self.converter = ConverterPanel(self.queue, self.address_bar.text())
        self.converter.back_requested.connect(self._show_main)
        self.converter.conversion_done.connect(self._on_conversion_done)
        self.stack.addWidget(self.converter)
        self.stack.setCurrentWidget(self.converter)

    def _get_duration_from_row(self, row):
        dur_item = self.table.item(row, self.COL_DUR)
        if not dur_item:
            return 0
        try:
            parts = dur_item.text().split(':')
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except Exception:
            pass
        return 0

    def _show_main(self):
        self.stack.setCurrentWidget(self.central_widget)
        if hasattr(self, 'converter') and self.converter is not None:
            self.stack.removeWidget(self.converter)
            self.converter.deleteLater()
            self.converter = None

    def _on_conversion_done(self, results):
        # Kuyruğu temizle
        self.queue.clear()
        self._update_goto_btn()

        if self.results_panel is not None:
            self.stack.removeWidget(self.results_panel)
            self.results_panel.deleteLater()
        self.results_panel = ResultsPanel(results)
        self.results_panel.back_requested.connect(self._show_main)
        self.stack.addWidget(self.results_panel)
        self.stack.setCurrentWidget(self.results_panel)
        self.results_btn.setEnabled(True)

    def _show_results(self):
        if self.results_panel is not None:
            self.stack.setCurrentWidget(self.results_panel)

    def play_video(self, item):
        row  = item.row()
        name = self.table.item(row, self.COL_NAME)
        if name:
            fp = os.path.join(self.address_bar.text(), name.text())
            if os.path.exists(fp):
                subprocess.Popen(['xdg-open', fp],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        name_item = self.table.item(row, self.COL_NAME)
        if not name_item:
            return
        filename = name_item.text()
        folder   = self.address_bar.text()

        menu        = QMenu(self)
        act_open    = menu.addAction("Dosya Konumunu Aç")
        act_copy    = menu.addAction("İsmi Kopyala")
        menu.addSeparator()
        act_trash   = menu.addAction("🗑  Çöpe Gönder")
        

        selected = menu.exec(self.table.viewport().mapToGlobal(pos))

        if selected == act_open:
            subprocess.Popen(['xdg-open', folder],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        elif selected == act_copy:
            QApplication.clipboard().setText(filename)
        elif selected == act_trash:
            self._trash_file(row, os.path.join(folder, filename))

    def _trash_file(self, row, full_path):
        if not os.path.exists(full_path):
            return
        try:
            subprocess.run(['gio', 'trash', full_path],
                           check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except Exception:
            try:
                subprocess.run(['trash-put', full_path],
                               check=True,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            except Exception:
                return
        self.table.removeRow(row)

    def _trash_selected(self):
        rows = sorted(set(
            idx.row() for idx in self.table.selectedIndexes()
        ), reverse=True)
        folder = self.address_bar.text()
        for row in rows:
            name_item = self.table.item(row, self.COL_NAME)
            if name_item:
                full_path = os.path.join(folder, name_item.text())
                self._trash_file(row, full_path)

    

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = BigFileDetector()
    win.show()
    sys.exit(app.exec())
