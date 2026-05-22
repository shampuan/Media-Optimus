import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
                             QFrame)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor


class ResultsPanel(QWidget):
    """
    Dönüştürme tamamlandıktan sonra açılan karşılaştırma ekranı.
    results: _on_file_done tarafından doldurulan liste.
    """
    back_requested = pyqtSignal()

    # Sütun indeksleri
    COL_SRC_NAME  = 0
    COL_SRC_RES   = 1
    COL_SRC_SIZE  = 2
    COL_SRC_CODEC = 3
    COL_SRC_KBPS  = 4
    COL_DST_NAME  = 5
    COL_DST_SIZE  = 6
    COL_DST_CODEC = 7
    COL_SAVING    = 8
    COL_NOTE      = 9

    def __init__(self, results: list, parent=None):
        super().__init__(parent)
        self.results = results

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Dönüştürme Sonuçları")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        root.addWidget(title)

        root.addWidget(self._build_table())
        root.addWidget(self._build_summary())
        root.addLayout(self._build_buttons())

    # ── Tablo ────────────────────────────────────────────────────────────

    def _build_table(self):
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Kaynak Adı", "Çözünürlük", "Boyut", "Codec", "kbps",
            "Hedef Adı", "Yeni Boyut", "Yeni Codec", "Kazanım", "Not"
        ])

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_SRC_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_DST_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_NOTE, QHeaderView.ResizeMode.Stretch)
        fixed = {
            1: 100, 2: 80, 3: 70, 4: 60,
            6: 80,  7: 80, 8: 80, 9: 200
        }
        for col, w in fixed.items():
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, w)

        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)

        self._populate()
        return self.table

    def _populate(self):
        for r in self.results:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # ── Kaynak sütunları ──────────────────────────────────────
            self.table.setItem(row, self.COL_SRC_NAME,
                QTableWidgetItem(r['filename']))
            self.table.setItem(row, self.COL_SRC_RES,
                QTableWidgetItem(r.get('src_res', '?')))
            self.table.setItem(row, self.COL_SRC_SIZE,
                QTableWidgetItem(f"{r['src_mb']:.1f} MB"))
            self.table.setItem(row, self.COL_SRC_CODEC,
                QTableWidgetItem(r.get('src_codec', '?').upper()))
            self.table.setItem(row, self.COL_SRC_KBPS,
                QTableWidgetItem(str(r.get('src_kbps', 0))))

            # ── Hedef sütunları ───────────────────────────────────────
            dst_name = os.path.basename(r['dst'])
            self.table.setItem(row, self.COL_DST_NAME,
                QTableWidgetItem(dst_name))

            if r['success']:
                dst_mb   = r['dst_mb']
                src_mb   = r['src_mb']
                saving   = ((src_mb - dst_mb) / src_mb * 100) if src_mb > 0 else 0

                size_item = QTableWidgetItem(f"{dst_mb:.1f} MB")
                self.table.setItem(row, self.COL_DST_SIZE, size_item)

                # Yeni codec — dst uzantısından tahmin
                ext = os.path.splitext(r['dst'])[1].lower()
                new_codec = "HEVC" if ext == '.mp4' else "VP9"
                codec_item = QTableWidgetItem(new_codec)
                codec_item.setForeground(QColor("#2ecc71"))
                self.table.setItem(row, self.COL_DST_CODEC, codec_item)

                # Kazanım
                saving_item = QTableWidgetItem(f"%{saving:.1f}")
                saving_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if saving >= 20:
                    saving_item.setForeground(QColor("#2ecc71"))
                elif saving >= 0:
                    saving_item.setForeground(QColor("#f1c40f"))
                else:
                    saving_item.setForeground(QColor("#e74c3c"))
                self.table.setItem(row, self.COL_SAVING, saving_item)

                # Not — çöpe taşındı mı?
                note = "Kaynak çöpe taşındı" if r.get('trashed') else ""
                note_item = QTableWidgetItem(note)
                note_item.setForeground(QColor("#95a5a6"))
                self.table.setItem(row, self.COL_NOTE, note_item)

            else:
                # Başarısız satır
                fail_item = QTableWidgetItem("Başarısız")
                fail_item.setForeground(QColor("#e74c3c"))
                self.table.setItem(row, self.COL_DST_SIZE, fail_item)

                err_item = QTableWidgetItem(r.get('error', ''))
                err_item.setForeground(QColor("#e74c3c"))
                self.table.setItem(row, self.COL_NOTE, err_item)

                # Başarısız satırın arka planını hafif kırmızı yap
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(QColor(80, 20, 20))

    # ── Özet satırı ──────────────────────────────────────────────────────

    def _build_summary(self):
        frame = QFrame()
        lay   = QHBoxLayout(frame)
        lay.setContentsMargins(0, 4, 0, 4)

        total     = len(self.results)
        success   = sum(1 for r in self.results if r['success'])
        total_src = sum(r['src_mb'] for r in self.results)
        total_dst = sum(r['dst_mb'] for r in self.results if r['success'])
        saved_mb  = total_src - total_dst
        saved_pct = (saved_mb / total_src * 100) if total_src > 0 else 0

        summary = (
            f"Toplam: {total} dosya  |  "
            f"Başarılı: {success}  |  "
            f"Başarısız: {total - success}  |  "
            f"Kazanılan alan: {saved_mb:.1f} MB  (%{saved_pct:.1f})"
        )
        lbl = QLabel(summary)
        lbl.setStyleSheet("font-weight: bold;")
        lay.addWidget(lbl)
        lay.addStretch()
        return frame

    # ── Butonlar ─────────────────────────────────────────────────────────

    def _build_buttons(self):
        lay = QHBoxLayout()

        self.back_btn = QPushButton("← Ana Ekrana Dön")
        self.back_btn.clicked.connect(self.back_requested.emit)

        self.open_btn = QPushButton("Klasörü Aç")
        self.open_btn.clicked.connect(self._open_folder)

        lay.addWidget(self.back_btn)
        lay.addStretch()
        lay.addWidget(self.open_btn)
        return lay

    def _open_folder(self):
        import subprocess
        if self.results:
            folder = os.path.dirname(self.results[0]['dst'])
            if os.path.isdir(folder):
                subprocess.Popen(['xdg-open', folder],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
