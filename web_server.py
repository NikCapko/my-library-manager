from flask import Flask, render_template_string, request, abort
import sqlite3
import os

DB_FILE = "library.db"

app = Flask(__name__)

# --- HTML шаблоны ---
BASE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Библиотека</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; }
        th { background: #f2f2f2; }
        a { text-decoration: none; color: blue; }
        .tag { color: blue; cursor: pointer; }
        .lang-btn { margin-right: 10px; padding: 4px 8px; border: 1px solid #ccc; background: #f8f8f8; display: inline-block; }
    </style>
</head>
<body>
    <h1>Библиотека</h1>
    <form method="get">
        <input type="text" name="q" placeholder="Поиск..." value="{{ query }}">
        <button type="submit">Искать</button>
        {% if query %}
        <a href="/" style="margin-left:10px;">Сброс</a>
        {% endif %}
    </form>
    <br>
    <table>
        <tr>
            <th>ID</th>
            <th>Автор</th>
            <th>Название</th>
            <th>Теги</th>
            <th>Язык</th>
        </tr>
        {% for book in books %}
        <tr>
            <td>{{ book['id'] }}</td>
            <td>{{ book['author'] }}</td>
            <td><a href="/book/{{ book['id'] }}">{{ book['title'] }}</a></td>
            <td>
                {% for tag in book['tags'] %}
                    <a href="/?tag={{ tag }}" class="tag">{{ tag }}</a>{% if not loop.last %}, {% endif %}
                {% endfor %}
            </td>
            <td>{{ book['lang'] }}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

BOOK_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
     <p><a href="/">Назад к списку</a></p>
    <title>{{ book['title'] }}</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        pre { white-space: pre-wrap; word-wrap: break-word; border: 1px solid #ccc; padding: 10px; background: #fafafa; }
        .lang-btn { 
            margin-right: 10px; 
            padding: 4px 8px; 
            border: 1px solid #ccc; 
            background: #f8f8f8; 
            display: inline-block; 
            text-decoration: none; 
            color: black; 
        }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ccc; padding: 5px; vertical-align: top; }
        th { background: #f2f2f2; }
    </style>
</head>
<body>
    <h1>{{ book['title'] }}</h1>
    <p><b>Автор:</b> {{ book['author'] }}</p>
    <p><b>Теги:</b>
        {% for tag in book['tags'] %}
            <a href="/?tag={{ tag }}" style="color:blue">{{ tag }}</a>{% if not loop.last %}, {% endif %}
        {% endfor %}
    </p>
    <p><b>Язык:</b> {{ book['lang'] }}</p>

    {% if book['lang'] == "en-ru" %}
        <div>
            <a href="/book/{{ book['id'] }}?ver=ru" class="lang-btn">RU</a>
            <a href="/book/{{ book['id'] }}?ver=en" class="lang-btn">EN</a>
            <a href="/book/{{ book['id'] }}?ver=en-ru" class="lang-btn">EN-RU</a>
        </div>
    {% endif %}
    <hr>

    {% if parallel %}
        {{ content|safe }}
    {% else %}
        <pre>{{ content }}</pre>
    {% endif %}
</body>
</html>
"""


# --- БД ---
def get_books(query=None, tag=None):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if tag:
        cur.execute("""
            SELECT DISTINCT books.* FROM books
            JOIN book_tags ON books.id = book_tags.book_id
            JOIN tags ON tags.id = book_tags.tag_id
            WHERE tags.name=?
            ORDER BY books.title
        """, (tag,))
    elif query:
        cur.execute("""
            SELECT DISTINCT books.* FROM books
            LEFT JOIN book_tags ON books.id = book_tags.book_id
            LEFT JOIN tags ON tags.id = book_tags.tag_id
            WHERE books.title LIKE ? OR books.author LIKE ? OR tags.name LIKE ?
            ORDER BY books.title
        """, (f"%{query}%", f"%{query}%", f"%{query}%"))
    else:
        cur.execute("SELECT * FROM books ORDER BY title")
    rows = cur.fetchall()
    conn.close()

    # добавляем теги в каждый объект
    books = []
    for row in rows:
        books.append({
            "id": row["id"],
            "title": row["title"],
            "author": row["author"],
            "lang": row["lang"],
            "tags": get_tags_for_book(row["id"])
        })
    return books

def get_book(id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM books WHERE id=?", (id,))
    book = cur.fetchone()
    conn.close()
    if not book:
        return None
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
        "lang": book["lang"],
        "bnf_path": book["bnf_path"],
        "tags": get_tags_for_book(book["id"])
    }

def get_tags_for_book(book_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT name FROM tags
        JOIN book_tags ON tags.id = book_tags.tag_id
        WHERE book_tags.book_id=?
    """, (book_id,))
    tags = [r[0] for r in cur.fetchall()]
    conn.close()
    return tags

# --- Маршруты ---
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip()
    books = get_books(query=q if q else None, tag=tag if tag else None)
    return render_template_string(BASE_HTML, books=books, query=q)

@app.route("/book/<int:book_id>")
def view_book(book_id):
    ver = request.args.get("ver")
    book = get_book(book_id)
    if not book:
        abort(404)

    folder = os.path.dirname(book["bnf_path"])
    base_name = os.path.splitext(os.path.basename(book["bnf_path"]))[0]

    content = ""
    parallel = False

    if book["lang"] in ("ru", "en"):
        file_path = os.path.join(folder, f"{base_name}.md")
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = f"[Файл {file_path} не найден]"

    elif book["lang"] == "en-ru":
        if ver == "ru":
            file_path = os.path.join(folder, f"{base_name}.ru.md")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                content = f"[Файл {file_path} не найден]"
        elif ver == "en":
            file_path = os.path.join(folder, f"{base_name}.en.md")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                content = f"[Файл {file_path} не найден]"
        else:  # ver == "en-ru"
            en_file = os.path.join(folder, f"{base_name}.en.md")
            ru_file = os.path.join(folder, f"{base_name}.ru.md")
            if os.path.exists(en_file) and os.path.exists(ru_file):
                with open(en_file, "r", encoding="utf-8") as f:
                    en_lines = [line.strip() for line in f.readlines()]
                with open(ru_file, "r", encoding="utf-8") as f:
                    ru_lines = [line.strip() for line in f.readlines()]

                max_len = max(len(en_lines), len(ru_lines))
                en_lines += [""] * (max_len - len(en_lines))
                ru_lines += [""] * (max_len - len(ru_lines))

                # Формируем HTML-таблицу параллельно
                table_html = "<table border='1' cellpadding='5' style='border-collapse: collapse; width:100%;'>"
                table_html += "<tr><th style='width:50%;'>EN</th><th style='width:50%;'>RU</th></tr>"
                for en_line, ru_line in zip(en_lines, ru_lines):
                    table_html += f"<tr><td>{en_line}</td><td>{ru_line}</td></tr>"
                table_html += "</table>"
                content = table_html
                parallel = True
            else:
                content = "[Файлы EN и RU не найдены]"

    return render_template_string(BOOK_HTML, book=book, content=content, parallel=parallel)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
    