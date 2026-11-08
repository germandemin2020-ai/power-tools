import os
import sys
import re
import threading
import uuid
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

DOWNLOADS_DIR = str(Path.home() / "Downloads")

# Словарь для отслеживания прогресса загрузок
download_tasks = {}

def get_platform_badge(url):
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube 🔴"
    elif "tiktok.com" in url_lower:
        return "TikTok 🎵"
    elif "instagram.com" in url_lower:
        return "Instagram Reels 📸"
    elif "vk.com" in url_lower or "vkvideo.ru" in url_lower:
        return "VK Видео 🔵"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "X / Twitter 🐦"
    elif "reddit.com" in url_lower:
        return "Reddit 🟠"
    elif "twitch.tv" in url_lower:
        return "Twitch 🟣"
    return "Медиа 🌐"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/info", methods=["POST"])
def get_media_info():
    import yt_dlp
    data = request.json or {}
    url = data.get("url", "").strip()
    
    if not url:
        return jsonify({"error": "Введите ссылку"}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            duration_sec = info.get('duration') or 0
            mins = int(duration_sec // 60)
            secs = int(duration_sec % 60)
            duration_str = f"{mins}:{secs:02d}" if duration_sec > 0 else "Не указано"

            return jsonify({
                "title": info.get('title', 'Без названия'),
                "author": info.get('uploader') or info.get('channel') or "Автор неизвестен",
                "duration": duration_str,
                "thumbnail": info.get('thumbnail') or "",
                "views": f"{info.get('view_count', 0):,}".replace(",", " ") if info.get('view_count') else None,
                "platform": get_platform_badge(url)
            })
    except Exception as e:
        return jsonify({"error": f"Не удалось получить информацию: {str(e)[:150]}"}), 400

def run_download_thread(task_id, url, format_type):
    import yt_dlp
    
    task = download_tasks[task_id]
    task["status"] = "downloading"
    task["percent"] = 0

    def progress_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed') or 0
            eta = d.get('eta') or 0
            
            percent = (downloaded / total * 100) if total > 0 else 0
            speed_mb = speed / (1024 * 1024) if speed else 0
            
            task["percent"] = round(percent, 1)
            task["speed"] = f"{speed_mb:.1f} МБ/с"
            task["eta"] = f"{int(eta)} сек" if eta else "..."
        elif d['status'] == 'finished':
            task["percent"] = 100
            task["status"] = "processing"

    outtmpl = os.path.join(DOWNLOADS_DIR, "%(title)s.%(ext)s")

    if format_type == "mp3":
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': outtmpl,
            'progress_hooks': [progress_hook],
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'noplaylist': True
        }
    elif format_type == "720p":
        ydl_opts = {
            'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best',
            'outtmpl': outtmpl,
            'progress_hooks': [progress_hook],
            'quiet': True,
            'noplaylist': True
        }
    else: # 1080p
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best',
            'outtmpl': outtmpl,
            'progress_hooks': [progress_hook],
            'quiet': True,
            'noplaylist': True
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            task["filename"] = ydl.prepare_filename(info)
            if format_type == "mp3":
                task["filename"] = os.path.splitext(task["filename"])[0] + ".mp3"
            task["status"] = "finished"
            task["percent"] = 100
    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)[:150]

@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json or {}
    url = data.get("url", "").strip()
    format_type = data.get("format", "1080p")

    if not url:
        return jsonify({"error": "Ссылка не указана"}), 400

    task_id = str(uuid.uuid4())
    download_tasks[task_id] = {
        "status": "starting",
        "percent": 0,
        "speed": "0 МБ/с",
        "eta": "...",
        "filename": "",
        "error": None
    }

    thread = threading.Thread(target=run_download_thread, args=(task_id, url, format_type))
    thread.daemon = True
    thread.start()

    return jsonify({"task_id": task_id})

@app.route("/api/progress/<task_id>")
def get_progress(task_id):
    task = download_tasks.get(task_id)
    if not task:
        return jsonify({"error": "Задача не найдена"}), 404
    return jsonify(task)

@app.route("/api/open-downloads", methods=["POST"])
def open_downloads():
    try:
        os.startfile(DOWNLOADS_DIR)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/steam", methods=["POST"])
def analyze_steam():
    data = request.json or {}
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"error": "Введите ссылку на Steam или Steam ID"}), 400

    # Извлечение ID или vanity имени
    # Примеры: https://steamcommunity.com/id/username/ или https://steamcommunity.com/profiles/76561198.../ или просто username
    clean_query = query.rstrip("/")
    if "/id/" in clean_query:
        target = clean_query.split("/id/")[-1]
        xml_url = f"https://steamcommunity.com/id/{target}/?xml=1"
        games_xml_url = f"https://steamcommunity.com/id/{target}/games?xml=1"
    elif "/profiles/" in clean_query:
        target = clean_query.split("/profiles/")[-1]
        xml_url = f"https://steamcommunity.com/profiles/{target}/?xml=1"
        games_xml_url = f"https://steamcommunity.com/profiles/{target}/games?xml=1"
    elif clean_query.isdigit() and len(clean_query) == 17:
        xml_url = f"https://steamcommunity.com/profiles/{clean_query}/?xml=1"
        games_xml_url = f"https://steamcommunity.com/profiles/{clean_query}/games?xml=1"
    else:
        xml_url = f"https://steamcommunity.com/id/{clean_query}/?xml=1"
        games_xml_url = f"https://steamcommunity.com/id/{clean_query}/games?xml=1"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        resp = requests.get(xml_url, headers=headers, timeout=10)
        if resp.status_code != 200 or not resp.text.strip():
            return jsonify({"error": "Профиль Steam не найден"}), 404

        root = ET.fromstring(resp.content)
        
        # Проверка на ошибку в XML
        error_node = root.find("error")
        if error_node is not None:
            return jsonify({"error": error_node.text or "Профиль не найден"}), 404

        steam_id = root.findtext("steamID", "Неизвестный")
        steam_id64 = root.findtext("steamID64", "")
        avatar = root.findtext("avatarFull", "")
        online_state = root.findtext("onlineState", "offline")
        state_msg = root.findtext("stateMessage", "Офлайн")
        vac_banned = root.findtext("vacBanned", "0") == "1"
        trade_ban = root.findtext("tradeBanState", "None")
        member_since = root.findtext("memberSince", "Скрыто")
        custom_url = root.findtext("customURL", "")
        privacy_state = root.findtext("privacyState", "public")
        
        # Очистка stateMessage от HTML тегов
        clean_state_msg = re.sub(r'<[^>]+>', '', state_msg).strip()

        # Попытка вытянуть список игр
        games = []
        total_hours = 0.0
        try:
            g_resp = requests.get(games_xml_url, headers=headers, timeout=8)
            if g_resp.status_code == 200 and "<gamesList>" in g_resp.text:
                g_root = ET.fromstring(g_resp.content)
                for g in g_root.findall(".//game"):
                    g_name = g.findtext("name", "")
                    g_hours_str = g.findtext("hoursOnRecord", "0").replace(",", ".")
                    try:
                        g_hours = float(g_hours_str)
                    except ValueError:
                        g_hours = 0.0
                    
                    total_hours += g_hours
                    g_logo = g.findtext("logo", "")
                    games.append({
                        "name": g_name,
                        "hours": g_hours,
                        "logo": g_logo
                    })
        except Exception:
            pass

        # Сортируем топ-5 игр по наигранным часам
        games.sort(key=lambda x: x["hours"], reverse=True)
        top_games = games[:5]

        # Расчетные показатели
        unplayed_count = sum(1 for g in games if g["hours"] == 0)
        unplayed_percent = round((unplayed_count / len(games) * 100)) if games else 0

        # Ориентировочная стоимость библиотеки (в среднем 850 руб за купленную игру)
        estimated_value = len(games) * 850

        return jsonify({
            "steamID": steam_id,
            "steamID64": steam_id64,
            "avatar": avatar,
            "onlineState": online_state,
            "stateMessage": clean_state_msg,
            "vacBanned": vac_banned,
            "tradeBan": trade_ban,
            "memberSince": member_since,
            "privacyState": privacy_state,
            "totalGames": len(games),
            "totalHours": round(total_hours, 1),
            "unplayedCount": unplayed_count,
            "unplayedPercent": unplayed_percent,
            "estimatedValue": f"{estimated_value:,}".replace(",", " "),
            "topGames": top_games,
            "isPrivate": len(games) == 0 and privacy_state != "public"
        })
    except Exception as e:
        return jsonify({"error": f"Ошибка анализа профиля: {str(e)}"}), 500

if __name__ == "__main__":
    print(f"🚀 PowerTools сервер запущен на http://127.0.0.1:5000")
    print(f"📁 Папка сохранения: {DOWNLOADS_DIR}")
    app.run(host="127.0.0.1", port=5000, debug=False)
