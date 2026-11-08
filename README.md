# ⚡ PowerTools Suite

> **Universal Media Downloader & Steam Profile Auditor**  
> Разработано Германом Деминым (German Demin) в рамках вайб-кодинга с Antigravity.

---

## 🚀 Возможности проекта

### 1. 📥 OmniLoader (Универсальный медиа-загрузчик)
* Поддержка **YouTube, TikTok (без водяного знака), Instagram Reels, VK Видео, X / Twitter, Reddit**.
* Выбор качества: **1080p Full HD MP4**, **720p MP4** или прямое извлечение **MP3 (192 kbps)**.
* Мгновенный предпросмотр (превью, автор, хронометраж, количество просмотров).
* Сохранение прямо в системную папку **«Загрузки» (Downloads)** с кнопкой быстрого открытия.

### 2. 🎮 Steam Profile & Library Auditor
* Парсинг Steam Community XML по ссылке на профиль или логину.
* Отображение онлайна, статуса в игре, аватара и VAC-статуса (проверка блокировок).
* **Суммарный подсчет наигранных часов** и расчет стоимости библиотеки.
* **«Стена позора»**: процент и количество купленных, но ни разу не запущенных игр.
* **Топ-5 самых любимых игр** по часам.

---

## 🛠 Стек технологий
* **Бэкенд:** Python 3.12, Flask, `yt-dlp`, FFmpeg Engine.
* **Фронтенд:** HTML5, Tailwind CSS (Dark Glassmorphism), JavaScript (Fetch API, WebSockets/Polling).
* **Интеграции:** Steam Community Protocol, YouTube/TikTok Stream Extractor.
