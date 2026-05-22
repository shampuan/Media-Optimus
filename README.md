# Video-Optimus
Video archive optimizer for Linux

Media Optimus is an open-source video archive optimizer for Linux. It helps you reclaim disk space by detecting bloated video files and converting them to modern, efficient formats — with minimal quality loss.

Why Media Optimus?
Hard drives fill up. Video archives grow. And buried inside them are files that take up far more space than they should — high bitrate recordings, old screen captures, or simply videos encoded with outdated codecs that modern alternatives can compress much more efficiently.
Media Optimus was built out of a personal need: to systematically identify these "vampire files" and convert them to HEVC or VP9 using FFmpeg's CRF-based encoding — the same quality, a fraction of the size.
It is not a simple converter. It is a detective and a converter in one:

Scan a folder and instantly see which videos are inefficient
Identify oversized files by bitrate, resolution, and file size — at a glance
Queue files across multiple scans without losing your selection
Convert to H.265 (HEVC), VP9, or AV1 with full CRF control
Compare before/after results on a dedicated results screen


Features

Smart detection — color-coded bitrate bars, resolution warnings, and file size indicators help you spot wasteful files immediately
Persistent queue — scan multiple folders and build your conversion queue across sessions without losing your selections
CRF-based conversion — quality-driven encoding via FFmpeg; no guesswork with bitrate targets
Three modern codecs — H.265 (HEVC), VP9, and AV1
Resolution control — keep original, downscale to 720p/480p, or enter a custom resolution
Safe deletion — sends source files to the system trash, never deletes permanently
Results screen — side-by-side comparison of source and converted files with savings percentage
Conversion queue management — add, remove, or clear files before converting


Screenshots
(screenshots go here)

Requirements

Linux (Debian-based recommended)
Python 3.x
PyQt6
FFmpeg (includes ffprobe)
gio or trash-put (for trash support — usually pre-installed on GNOME/KDE desktops)


Installation
Option 1 — Debian Package (recommended)
Download the latest .deb package from the Releases page.
Via terminal:
bashsudo dpkg -i mediaoptimus_x.x.x_amd64.deb
sudo apt-get install -f   # fix dependencies if needed
Or double-click the .deb file to open it with your system's package installer (GDebi, Ubuntu Software, etc.).
Option 2 — Run from source
Clone the repository and install dependencies manually:
bashgit clone https://github.com/shampuan/mediaoptimus.git
cd mediaoptimus
pip install PyQt6
sudo apt install ffmpeg
python3 mediaoptimus.py

Usage

Launch Media Optimus
Click Klasör Seç to choose a folder
Click Analiz Et to scan
Review the results — pay attention to the Durum bar and file size colors
Check the files you want to convert
Click Seçilileri Kuyruğa Ekle — scan more folders if needed
Click Kuyruğa Git to open the converter
Choose your codec, resolution, and CRF value
Click Dönüştür and wait
Review the results screen — see exactly how much space you saved


Understanding the Interface
Durum bar colors:

🟢 Green — bitrate is within acceptable range
🟠 Orange — noticeable inefficiency
🔴 Red — significant waste, strong candidate for conversion

File size colors:

🟢 Green — under 25 MB
🟡 Yellow — 25–55 MB
🟠 Orange — 55–100 MB
🔴 Red — over 100 MB

Resolution warning (▲): The video's height exceeds your configured maximum. Consider downscaling.
Codec colors:

🟢 Green — already HEVC, likely efficient
🔵 Blue — H.264, good conversion candidate
🟠 Orange — older or uncommon codec


Thresholds
All detection thresholds are configurable from the main screen:
SettingDescriptionDefaultMaks. kbpsBitrate above this is flagged1500 kbpsMaks. yükseklikHeight above this triggers a resolution warning720 pxTahammül EşiğiWaste tolerance percentage for the bar40%Min. BoyutFiles below this size are marked as too small to bother10 MB

License
Media Optimus is released under the GNU General Public License v3.0.
See the LICENSE file for details.
© 2026 — A. Serhat KILIÇOĞLU (shampuan)

Credits
Developed with the active assistance of Claude AI by Anthropic.
Built with:

Python 3
PyQt6
FFmpeg
