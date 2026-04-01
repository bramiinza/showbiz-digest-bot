import feedparser
import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import time
import difflib
import re
from groq import Groq

# Настройки
SOURCES = [
    {"name": "TMZ", "url": "https://tmz.com/rss.xml"},
    {"name": "Page Six", "url": "https://pagesix.com/feed/"},
    {"name": "Us Weekly", "url": "https://www.usmagazine.com/category/celebrity-news/feed/"},
    {"name": "Deadline", "url": "https://deadline.com/feed/"},
    {"name": "Variety", "url": "https://variety.com/feed/"},
]

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASS = os.getenv("SMTP_PASS")
TO_EMAIL = os.getenv("TO_EMAIL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

SEEN_FILE = "seen_articles.json"

# Загрузка истории
seen = []
if os.path.exists(SEEN_FILE):
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen = json.load(f)
    except:
        seen = []

def is_recent(entry):
    for date_field in ["published", "updated", "pubDate"]:
        if date_field in entry:
            try:
                pub_date = feedparser.parse(entry[date_field]).feed.get("published_parsed")
                if pub_date:
                    pub_dt = datetime(*pub_date[:6])
                    return pub_dt > datetime.now() - timedelta(days=1)
            except:
                continue
    return True

def get_full_text(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "header", "footer", "nav", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)[:5000]
    except:
        return ""

print("=== Запуск ИИ-дайджеста шоу-бизнеса ===")

raw_articles = []
for source in SOURCES:
    print(f"→ Собираем {source['name']}...")
    try:
        feed = feedparser.parse(source["url"])
        for entry in feed.entries:
            if not is_recent(entry):
                continue
            url = entry.link
            if url in seen:
                continue
            full_text = get_full_text(url)
            article = {
                "url": url,
                "title": entry.title,
                "summary": entry.get("summary", ""),
                "full_text": full_text or entry.get("summary", ""),
                "source": source["name"]
            }
            raw_articles.append(article)
            time.sleep(1.5)
    except Exception as e:
        print(f"Ошибка {source['name']}: {e}")

print(f"Собрано сырых статей: {len(raw_articles)}")

if not raw_articles:
    print("Нет новых статей.")
else:
    # === ИИ-обработка ===
    client = Groq(api_key=GROQ_API_KEY)
    
    prompt = f"""Ты — главный редактор русского таблоида. 
Сегодня {datetime.now().strftime('%d %B %Y')}.
У меня {len(raw_articles)} свежих новостей из TMZ, Page Six, Us Weekly и др. за последние 24 часа.

Сделай максимально яркий и вкусный дайджест:
- Выбери самые интересные и яркие 8–12 новостей (или все, если их мало).
- Для каждой придумай кликбейтный, но честный русский заголовок.
- Напиши короткое (3–6 предложений), живое summary на русском.
- Стиль: лёгкий, эмоциональный, с лёгким сплетничаньем, как в TMZ.

Верни ответ строго в формате HTML:

<h1>🎭 Шоу-биз: самое горячее за день</h1>
<h2>1. Заголовок</h2>
<p>Текст summary...</p>
<p><a href="URL">Оригинал</a> • Источник: XYZ</p>
<hr>
... и так далее.

Вот сырые статьи:
"""
    for i, art in enumerate(raw_articles, 1):
        prompt += f"\n{i}. Источник: {art['source']}\nЗаголовок: {art['title']}\nТекст: {art['full_text'][:3000]}\n---\n"

    print("Отправляем в Groq для обработки...")
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=8000
    )
    
    digest_html = response.choices[0].message.content

    # Отправка письма
    if SMTP_EMAIL and SMTP_PASS and TO_EMAIL:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🎭 Шоу-биз: самое горячее — {datetime.now().strftime('%d.%m.%Y')}"
        msg["From"] = SMTP_EMAIL
        msg["To"] = TO_EMAIL
        msg.attach(MIMEText(digest_html, "html", "utf-8"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(SMTP_EMAIL, SMTP_PASS)
                server.send_message(msg)
            print("✅ Красивый ИИ-дайджест успешно отправлен!")
        except Exception as e:
            print(f"❌ Ошибка отправки: {e}")

# Обновление истории
for art in raw_articles:
    if art["url"] not in seen:
        seen.append(art["url"])

with open(SEEN_FILE, "w", encoding="utf-8") as f:
    json.dump(seen[-1000:], f, ensure_ascii=False, indent=2)

print("Готово!")
