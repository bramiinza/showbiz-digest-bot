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
RUN_MODE = os.getenv("RUN_MODE", "auto")   # manual или auto

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

print(f"=== Запуск ИИ-дайджеста (режим: {RUN_MODE}) ===")

raw_articles = []
for source in SOURCES:
    print(f"→ Собираем {source['name']}...")
    try:
        feed = feedparser.parse(source["url"])
        for entry in feed.entries:
            if not is_recent(entry):
                continue
            url = entry.link
            
            # В ручном режиме НЕ пропускаем уже виденные
            if RUN_MODE == "auto" and url in seen:
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
    # === ИИ-обработка с фильтром по мировым звёздам ===
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY не настроен.")
        digest_html = "<h1>Шоу-биз дайджест</h1><p>ИИ не подключён.</p>"
    else:
        client = Groq(api_key=GROQ_API_KEY)
        
        prompt = f"""Ты — главный редактор русского таблоида о шоу-бизнесе.
Сегодня {datetime.now().strftime('%d %B %Y')}.
Режим запуска: {RUN_MODE}.

Сделай максимально яркий и вкусный дайджест ТОЛЬКО по мировым звёздам, которых хорошо знают в России 
(Taylor Swift, Zendaya, Kardashians, Leonardo DiCaprio, The Rock, Kylie Jenner, Timothée Chalamet, Billie Eilish, Drake, Marvel-актёры и подобные глобальные имена).

Пропускай новости про чисто американских локальных знаменитостей, которых в России почти никто не знает.

Выбери самые интересные 5–6 новостей.
Для каждой:
- Придумай не кликбейтный, но привлекательный русский заголовок.
- Напиши живое summary (3–6 предложений) в таблоидном стиле.

Верни ответ строго в формате HTML (никакого лишнего текста).

Вот сырые статьи:
"""
        for i, art in enumerate(raw_articles, 1):
            prompt += f"\n{i}. [{art['source']}] Заголовок: {art['title']}\nТекст: {art['full_text'][:3500]}\n---\n"

        print("Отправляем в Groq...")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.75,
            max_tokens=7000
        )
        
        digest_html = response.choices[0].message.content
        # Ограничиваем количество статей
MAX_ARTICLES = 20
articles = articles[:MAX_ARTICLES]

# Сокращаем текст каждой статьи
for a in articles:
    a['summary'] = a['summary'][:300]  # оставляем первые 300 символов

    # Отправка письма
    if SMTP_EMAIL and SMTP_PASS and TO_EMAIL:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🎭 Шоу-биз: самое горячее — {datetime.now().strftime('%d.%m.%Y')} ({RUN_MODE})"
        msg["From"] = SMTP_EMAIL
        msg["To"] = TO_EMAIL
        msg.attach(MIMEText(digest_html, "html", "utf-8"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(SMTP_EMAIL, SMTP_PASS)
                server.send_message(msg)
            print("✅ ИИ-дайджест успешно отправлен!")
        except Exception as e:
            print(f"❌ Ошибка отправки: {e}")

# Обновляем историю (в обоих режимах)
for art in raw_articles:
    if art["url"] not in seen:
        seen.append(art["url"])

with open(SEEN_FILE, "w", encoding="utf-8") as f:
    json.dump(seen[-1000:], f, ensure_ascii=False, indent=2)

print("Готово!")
