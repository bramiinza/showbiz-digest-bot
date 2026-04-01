import feedparser
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
import json
import os
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import time
import difflib
import re

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

SEEN_FILE = "seen_articles.json"

# Загрузка/создание истории
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        seen = json.load(f)
else:
    seen = []

def is_recent(pub_date_str):
    try:
        pub_date = datetime(*feedparser._parse_date(pub_date_str)[:6])
        return pub_date > datetime.now() - timedelta(days=1)
    except:
        return True  # если дата не распарсилась — берём

def get_full_text(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "lxml")
        # Убираем скрипты и стили
        for tag in soup(["script", "style", "header", "footer", "nav"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines[:1500])  # ограничиваем длину
    except:
        return ""

def translate_text(text):
    if not text:
        return ""
    try:
        translator = GoogleTranslator(source='en', target='ru')
        return translator.translate(text[:5000])  # лимит на один запрос
    except:
        return text  # если перевод упал — оставляем оригинал

def normalize_text(text):
    return re.sub(r'\s+', ' ', text.lower().strip())

def articles_similar(a, b, threshold=0.75):
    text_a = normalize_text(a.get("title", "") + " " + a.get("summary", ""))
    text_b = normalize_text(b.get("title", "") + " " + b.get("summary", ""))
    similarity = difflib.SequenceMatcher(None, text_a, text_b).ratio()
    return similarity > threshold

# Собираем новые статьи
new_articles = []
for source in SOURCES:
    print(f"Собираем {source['name']}...")
    feed = feedparser.parse(source["url"])
    for entry in feed.entries:
        if not is_recent(entry.get("published", entry.get("updated", ""))):
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
            "source": source["name"],
            "date": datetime.now().isoformat()
        }
        new_articles.append(article)
        time.sleep(2)  # пауза, чтобы не банили

# Дедупликация и объединение похожих
unique_articles = []
for article in new_articles:
    merged = False
    for unique in unique_articles:
        if articles_similar(article, unique):
            # Объединяем
            unique["full_text"] = unique["full_text"] + "\n\n" + article["full_text"][:800]
            unique["sources"] = unique.get("sources", [unique["source"]]) + [article["source"]]
            merged = True
            break
    if not merged:
        article["sources"] = [article["source"]]
        unique_articles.append(article)

# Перевод и формирование дайджеста
digest_html = f"<h1>Шоу-биз дайджест — {datetime.now().strftime('%d %B %Y')}</h1><hr>"

for i, art in enumerate(unique_articles[:15], 1):  # максимум 15 статей
    ru_title = translate_text(art["title"])
    ru_text = translate_text(art["full_text"])
    
    sources_str = ", ".join(set(art["sources"]))
    
    digest_html += f"""
    <h2>{i}. {ru_title}</h2>
    <p><strong>Источники:</strong> {sources_str}</p>
    <p><a href="{art['url']}">Читать оригинал</a></p>
    <div style="margin: 20px 0; line-height: 1.6;">
        {ru_text.replace('\n', '<br>')}
    </div>
    <hr>
    """

# Отправка письма
if unique_articles and SMTP_EMAIL and SMTP_PASS and TO_EMAIL:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Шоу-бизнес дайджест — {datetime.now().strftime('%d.%m.%Y')}"
    msg["From"] = SMTP_EMAIL
    msg["To"] = TO_EMAIL
    
    msg.attach(MIMEText(digest_html, "html", "utf-8"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_EMAIL, SMTP_PASS)
            server.send_message(msg)
        print("Дайджест успешно отправлен!")
    except Exception as e:
        print(f"Ошибка отправки: {e}")
else:
    print("Нет новых статей или не настроены секреты.")

# Обновляем историю
for art in unique_articles:
    if art["url"] not in seen:
        seen.append(art["url"])

with open(SEEN_FILE, "w", encoding="utf-8") as f:
    json.dump(seen[-500:], f, ensure_ascii=False, indent=2)  # храним последние 500

print(f"Обработано {len(unique_articles)} уникальных статей.")
