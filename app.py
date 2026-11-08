import os
import sys

# Принудительно включаем UTF-8 для консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import re
import shutil
import threading
import uuid
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

DOWNLOADS_DIR = str(Path.home() / "Downloads")

download_tasks = {}

def find_ffmpeg():
    """
    Автоматически находит установленный FFmpeg на компьютере
    """
    p = shutil.which("ffmpeg")
    if p:
        return os.path.dirname(p)
    
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    winget_pkgs = os.path.join(local_app_data, "Microsoft", "WinGet", "Packages")
    if os.path.exists(winget_pkgs):
        for root, dirs, files in os.walk(winget_pkgs):
            if "ffmpeg.exe" in files:
                return root

    for common in [
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        os.path.join(local_app_data, "Programs", "ffmpeg", "bin")
    ]:
        if os.path.exists(os.path.join(common, "ffmpeg.exe")):
            return common
            
    return None

def get_platform_badge(url):
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube"
    elif "tiktok.com" in url_lower:
        return "TikTok"
    elif "instagram.com" in url_lower:
        return "Instagram Reels"
    elif "vk.com" in url_lower or "vkvideo.ru" in url_lower:
        return "VK Видео"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "X / Twitter"
    elif "reddit.com" in url_lower:
        return "Reddit"
    elif "twitch.tv" in url_lower:
        return "Twitch"
    return "Медиа"

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
    ffmpeg_dir = find_ffmpeg()

    # Гарантируем совместимость со всеми плеерами (Windows Media Player, Discord, iOS, Android):
    # Принудительно пережимаем видео в H.264 (avc1) и звук в AAC (mp4a), чтобы открывалось абсолютно везде
    compatibility_merger_args = ['-c:v', 'libx264', '-c:a', 'aac', '-preset', 'veryfast', '-crf', '22']

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
            'windowsfilenames': True,
            'quiet': True,
            'noplaylist': True
        }
    elif format_type == "720p":
        ydl_opts = {
            'format': 'bestvideo[height<=720][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a][acodec^=mp4a]/bestvideo[height<=720][vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best',
            'merge_output_format': 'mp4',
            'outtmpl': outtmpl,
            'progress_hooks': [progress_hook],
            'postprocessor_args': {
                'merger': compatibility_merger_args
            },
            'windowsfilenames': True,
            'quiet': True,
            'noplaylist': True
        }
    else: # 1080p
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a][acodec^=mp4a]/bestvideo[height<=1080][vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
            'merge_output_format': 'mp4',
            'outtmpl': outtmpl,
            'progress_hooks': [progress_hook],
            'postprocessor_args': {
                'merger': compatibility_merger_args
            },
            'windowsfilenames': True,
            'quiet': True,
            'noplaylist': True
        }

    if ffmpeg_dir:
        ydl_opts['ffmpeg_location'] = ffmpeg_dir

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if format_type == "mp3":
                filename = os.path.splitext(filename)[0] + ".mp3"
            elif format_type in ["1080p", "720p"]:
                filename = os.path.splitext(filename)[0] + ".mp4"
                
            task["filename"] = filename
            task["status"] = "finished"
            task["percent"] = 100
    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)[:180]

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

    clean_query = query.rstrip("/")
    if "/id/" in clean_query:
        target = clean_query.split("/id/")[-1]
        xml_url = f"https://steamcommunity.com/id/{target}/?xml=1"
        profile_url = f"https://steamcommunity.com/id/{target}/"
    elif "/profiles/" in clean_query:
        target = clean_query.split("/profiles/")[-1]
        xml_url = f"https://steamcommunity.com/profiles/{target}/?xml=1"
        profile_url = f"https://steamcommunity.com/profiles/{target}/"
    elif clean_query.isdigit() and len(clean_query) == 17:
        xml_url = f"https://steamcommunity.com/profiles/{clean_query}/?xml=1"
        profile_url = f"https://steamcommunity.com/profiles/{clean_query}/"
    else:
        xml_url = f"https://steamcommunity.com/id/{clean_query}/?xml=1"
        profile_url = f"https://steamcommunity.com/id/{clean_query}/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    try:
        resp = requests.get(xml_url, headers=headers, timeout=10)
        if resp.status_code != 200 or not resp.text.strip():
            return jsonify({"error": "Профиль Steam не найден"}), 404

        root = ET.fromstring(resp.content)
        
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
        privacy_state = root.findtext("privacyState", "public")
        
        clean_state_msg = re.sub(r'<[^>]+>', '', state_msg).strip()

        # Parse Level, Badges, and Profile Game Count from public HTML
        level = 0
        badges_cnt = 0
        html_games_cnt = 0
        games = []
        total_hours = 0.0
        est_val_usd = 0

        try:
            r_html = requests.get(profile_url, headers=headers, timeout=8)
            if r_html.status_code == 200:
                html_text = r_html.text
                m_level = re.search(r'<span class="friendPlayerLevelNum">(\d+)</span>', html_text)
                if m_level:
                    level = int(m_level.group(1))
                m_games = re.search(r'href="[^"]*games[^"]*"[^>]*>.*?<span class="profile_count_link_total">\s*(\d+)\s*</span>', html_text, re.DOTALL)
                if m_games:
                    html_games_cnt = int(m_games.group(1))
                m_badges = re.search(r'href="[^"]*/badges/"[^>]*>.*?<span class="profile_count_link_total">\s*(\d+)\s*</span>', html_text, re.DOTALL)
                if m_badges:
                    badges_cnt = int(m_badges.group(1))

                # Also parse any recently played games shown on profile
                for rg in re.findall(r'<div class="recent_game">(.*?)</div>\s*</div>\s*</div>', html_text, re.DOTALL):
                    name_match = re.search(r'<div class="game_name">\s*<a[^>]*>(.*?)</a>', rg)
                    hours_match = re.search(r'([\d\.,]+)\s+(?:hrs|ч)', rg)
                    appid_match = re.search(r'/app/(\d+)', rg)
                    if name_match:
                        g_name = re.sub(r'<[^>]+>', '', name_match.group(1)).strip()
                        g_appid = appid_match.group(1) if appid_match else None
                        g_hrs = float(hours_match.group(1).replace(",", ".")) if hours_match else 0.0
                        total_hours += g_hrs
                        g_logo = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{g_appid}/header.jpg" if g_appid else ""
                        games.append({
                            "name": g_name,
                            "appid": g_appid,
                            "hours": g_hrs,
                            "price": "В библиотеке",
                            "logo": g_logo
                        })
        except Exception:
            pass

        # Attempt 1: Legacy XML (works if target profile allows anonymous game details)
        if not games and steam_id64:
            games_xml_url = f"https://steamcommunity.com/profiles/{steam_id64}/games?xml=1"
            try:
                g_resp = requests.get(games_xml_url, headers=headers, timeout=5)
                if g_resp.status_code == 200 and "<gamesList>" in g_resp.text:
                    g_root = ET.fromstring(g_resp.content)
                    for g in g_root.findall(".//game"):
                        g_name = g.findtext("name", "")
                        g_appid = g.findtext("appID", "")
                        g_hours_str = g.findtext("hoursOnRecord", "0").replace(",", ".")
                        try:
                            g_hours = float(g_hours_str)
                        except ValueError:
                            g_hours = 0.0
                        total_hours += g_hours
                        g_logo = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{g_appid}/header.jpg" if g_appid else g.findtext("logo", "")
                        games.append({
                            "name": g_name,
                            "appid": g_appid,
                            "hours": g_hours,
                            "price": "В библиотеке",
                            "logo": g_logo
                        })
            except Exception:
                pass

        # Attempt 2: Also query SteamID lookup for full catalog, prices, and banners
        if steam_id64:
            try:
                pro_url = f"https://steamid.pro/lookup/{steam_id64}"
                r_pro = requests.get(pro_url, headers=headers, timeout=7)
                if r_pro.status_code == 200:
                    match_table = re.search(r'<table class="table game-table">(.*?)</table>', r_pro.text, re.DOTALL)
                    if match_table:
                        existing_names = {g["name"].lower() for g in games}
                        for row in re.findall(r'<tr>(.*?)</tr>', match_table.group(1), re.DOTALL):
                            gname = re.search(r'<td class="gname">(.*?)</td>', row)
                            gprice = re.search(r'<td class="gprice">(.*?)</td>', row)
                            gtime = re.search(r'<td class="gtime">(.*?)</td>', row)
                            appid_match = re.search(r'/apps/(\d+)/', row)
                            if gname:
                                name = re.sub(r'<[^>]+>', '', gname.group(1)).strip()
                                if name.lower() in existing_names:
                                    continue
                                appid = appid_match.group(1) if appid_match else None
                                price = gprice.group(1).strip() if gprice else "Free"
                                time_str = gtime.group(1).strip() if gtime else "0h"
                                hours = 0.0
                                m_hrs = re.search(r'(\d+)\s*h', time_str)
                                if m_hrs:
                                    hours += float(m_hrs.group(1))
                                m_mins = re.search(r'(\d+)\s*m', time_str)
                                if m_mins:
                                    hours += round(float(m_mins.group(1)) / 60, 1)
                                total_hours += hours
                                logo = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg" if appid else ""
                                games.append({
                                    "name": name,
                                    "appid": appid,
                                    "hours": hours,
                                    "price": price,
                                    "logo": logo
                                })
                                existing_names.add(name.lower())
                    price_match = re.search(r'<span class="number-price">\$?(\d+)</span>', r_pro.text)
                    if price_match:
                        est_val_usd = int(price_match.group(1))
                    cnt_match = re.search(r'Games owned:.*?(\d+)', r_pro.text)
                    if cnt_match:
                        pro_cnt = int(cnt_match.group(1))
                        if pro_cnt > html_games_cnt:
                            html_games_cnt = pro_cnt
            except Exception:
                pass

        # Attempt 3: Check Game Collector badge (badge 13)
        if steam_id64 and html_games_cnt < 2:
            try:
                r_badge = requests.get(f"https://steamcommunity.com/profiles/{steam_id64}/badges/13", headers=headers, timeout=5)
                if r_badge.status_code == 200:
                    m_b = re.search(r'(?:games in library|игр[а-я]* в библиотеке)[:\s]*(\d+)|(\d+)\s+(?:games in library|игр[а-я]* в библиотеке)', r_badge.text, re.IGNORECASE)
                    if m_b:
                        b_cnt = int(m_b.group(1) or m_b.group(2))
                        if b_cnt > html_games_cnt:
                            html_games_cnt = b_cnt
            except Exception:
                pass

        total_games_count = max(len(games), html_games_cnt)
        is_games_private = (len(games) == 0 and total_games_count > 0)
        hours_hidden = (total_hours == 0 and total_games_count > 0)

        # Smart sorting: if hours available, sort by hours descending. If hours hidden, put paid games and popular titles first!
        if not hours_hidden:
            games.sort(key=lambda x: x["hours"], reverse=True)
        else:
            def game_priority(g):
                p = g.get("price", "")
                if "$" in p:
                    try:
                        return float(p.replace("$", "").strip())
                    except ValueError:
                        return 1.0
                elif any(pop in g["name"].lower() for pop in ["counter-strike", "apex", "wallpaper", "among us", "warframe", "destiny"]):
                    return 0.5
                return 0.0
            games.sort(key=game_priority, reverse=True)

        top_games = games[:12] if games else []
        unplayed_count = sum(1 for g in games if g["hours"] == 0)
        unplayed_percent = round((unplayed_count / len(games) * 100)) if games and not hours_hidden else 0

        if est_val_usd > 0:
            estimated_value_rub = est_val_usd * 95
        else:
            estimated_value_rub = total_games_count * 650

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
            "level": level,
            "badges": badges_cnt,
            "totalGames": total_games_count,
            "totalHours": round(total_hours, 1),
            "hoursHidden": hours_hidden,
            "isGamesPrivate": is_games_private,
            "unplayedCount": unplayed_count,
            "unplayedPercent": unplayed_percent,
            "estimatedValue": f"{estimated_value_rub:,}".replace(",", " "),
            "estimatedValueUsd": est_val_usd,
            "topGames": top_games,
            "isPrivate": total_games_count == 0 and privacy_state != "public"
        })
    except Exception as e:
        return jsonify({"error": f"Ошибка анализа профиля: {str(e)}"}), 500

if __name__ == "__main__":
    ffmpeg_detected = find_ffmpeg()
    print("==================================================")
    print("PowerTools server started at http://127.0.0.1:5000")
    print(f"FFmpeg status: {'Found (' + ffmpeg_detected + ')' if ffmpeg_detected else 'NOT FOUND'}")
    print(f"Save folder: {DOWNLOADS_DIR}")
    print("==================================================")
    app.run(host="127.0.0.1", port=5000, debug=False)
