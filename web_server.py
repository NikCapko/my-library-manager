import os
import re
import sqlite3

import markdown
from flask import Flask, render_template_string, request, abort, redirect, url_for, make_response
from markdown import Extension
from markdown.blockprocessors import HashHeaderProcessor
from markdown.extensions.toc import TocExtension

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
        {% if query or tag or author or favorite %}
        <a href="/" style="margin-left:10px;">Сброс</a>
        {% endif %}
        <a href="/?favorite=1" style="margin-left:10px;">Только избранные</a>
    </form>
    <br>
    <table>
        <tr>
            <th>ID</th>
            <th>★</th>
            <th><a href="/?sort=author{% if query %}&q={{ query }}{% endif %}{% if tag %}&tag={{ tag }}{% endif %}{% if author %}&author={{ author }}{% endif %}">Автор</a></th>
            <th><a href="/?sort=title{% if query %}&q={{ query }}{% endif %}{% if tag %}&tag={{ tag }}{% endif %}{% if author %}&author={{ author }}{% endif %}">Название</a></th>
            <th>Описание</th>
            <th>Теги</th>
        </tr>
        {% for book in books %}
        <tr>
            <td>{{ book['id'] }}</td>
            <td>
              {% if book['favorite'] %}
                <a href="/toggle_fav/{{ book['id'] }}">⭐</a>
              {% else %}
                <a href="/toggle_fav/{{ book['id'] }}">☆</a>
              {% endif %}
            </td>
            <td><a href="/?author={{ book['author'] }}" style="color:blue">{{ book['author'] }}</a></td>
            <td><a href="/book/{{ book['id'] }}">{{ book['title'] }}</a></td>
            <td>{{ book['description'] }}</td>
            <td>
                {% for tag in book['tags'] %}
                    <a href="/?tag={{ tag }}" class="tag">{{ tag }}</a>{% if not loop.last %}, {% endif %}
                {% endfor %}
            </td>
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
    <meta name="viewport" content="width=device-width, initial-scale=1">
        <p><a href="/">Назад к списку</a></p>
        <p><a href="/edit/{{ book['id'] }}">Редактировать</a></p>
    <title>{{ book['title'] }}</title>
    <style>
        body { font-family: sans-serif; margin: 20px; font-size: 16px; }
        .markdown-body h1, .markdown-body h2, .markdown-body h3 { margin-top: 20px; }
        .markdown-body p { margin: 10px 0; }
        .markdown-body code { background: #f4f4f4; padding: 2px 4px; border-radius: 4px; }
        .markdown-body pre { background: #f4f4f4; padding: 10px; border-radius: 4px; overflow-x: auto; }
        .markdown-body table { border-collapse: collapse; width: 100%; }
        .markdown-body th, .markdown-body td { border: 1px solid #ccc; padding: 5px; }

        pre { white-space: pre-wrap; word-wrap: break-word; border: 1px solid #ccc; padding: 10px; background: #fafafa; font-size: 16px; }
        .lang-btn { 
            margin-right: 10px; 
            padding: 6px 10px; 
            border: 1px solid #ccc; 
            background: #f8f8f8; 
            display: inline-block; 
            text-decoration: none; 
            color: black; 
            font-size: 16px;
        }
        table { border-collapse: collapse; width: 100%; font-size: 16px; }
        th, td { border: 1px solid #ccc; padding: 5px; vertical-align: top; }
        th { background: #f2f2f2; }
    </style>
</head>
<body>
    <h1>{{ book['title'] }}</h1>
    <p><b>Автор:</b> <a href="/?author={{ book['author'] }}" style="color:blue">{{ book['author'] }}</a></p>
    <p><b>Теги:</b>
        {% for tag in book['tags'] %}
            <a href="/?tag={{ tag }}" style="color:blue">{{ tag }}</a>{% if not loop.last %}, {% endif %}
        {% endfor %}
    </p>
    <p><b>Язык:</b> {{ book['lang'] }}</p>
    
    <p><b>Избранное:</b>
        {% if book['favorite'] %}
            <a href="/toggle_fav/{{ book['id'] }}?from=book" style="font-size:22px; text-decoration:none;">⭐</a>
        {% else %}
            <a href="/toggle_fav/{{ book['id'] }}?from=book" style="font-size:22px; text-decoration:none;">☆</a>
        {% endif %}
    </p>


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
        <div class="markdown-body">{{ content|safe }}</div>
    {% endif %}
</body>
</html>
"""

EDIT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Редактировать {{ book['title'] }}</title>
    <style>
        body { font-family: sans-serif; margin: 20px; font-size: 18px; }
        label { display: block; margin-top: 10px; font-weight: bold; }
        input, textarea, select { width: 100%; padding: 8px; margin-top: 5px; font-size: 16px; }
        button { margin-top: 15px; padding: 8px 12px; font-size: 16px; }
    </style>
</head>
<body>
    <h1>Редактировать книгу</h1>
    <form method="post">
        <label>Название:</label>
        <input type="text" name="title" value="{{ book['title'] }}">

        <label>Автор:</label>
        <input type="text" name="author" value="{{ book['author'] }}">

        <label>Описание:</label>
        <textarea name="description" rows="6">{{ book['description'] }}</textarea>

        <label>Язык:</label>
        <select name="lang">
            <option value="ru" {% if book['lang']=="ru" %}selected{% endif %}>ru</option>
            <option value="en" {% if book['lang']=="en" %}selected{% endif %}>en</option>
            <option value="en-ru" {% if book['lang']=="en-ru" %}selected{% endif %}>en-ru</option>
        </select>

        <label>Теги (через запятую):</label>
        <input type="text" name="tags" value="{{ tags }}">

        <button type="submit">Сохранить</button>
    </form>
    <p><a href="/book/{{ book['id'] }}">Назад</a></p>
</body>
</html>
"""


# --- БД ---
def get_books(query=None, tag=None, author=None, sort="title", favorite=False):
    if sort not in ("title", "author"):
        sort = "title"

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = "SELECT DISTINCT books.* FROM books "
    joins = []
    where = []
    params = []

    if tag:
        joins.append("JOIN book_tags ON books.id = book_tags.book_id JOIN tags ON tags.id = book_tags.tag_id")
        where.append("tags.name=?")
        params.append(tag)
    if author:
        where.append("books.author=?")
        params.append(author)
    if query:
        joins.append("LEFT JOIN book_tags ON books.id = book_tags.book_id LEFT JOIN tags ON tags.id = book_tags.tag_id")
        where.append("(books.title LIKE ? OR books.author LIKE ? OR tags.name LIKE ?)")
        params += [f"%{query}%", f"%{query}%", f"%{query}%"]
    if favorite:
        where.append("books.favorite=1")

    if joins:
        sql += " " + " ".join(joins)
    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += f" ORDER BY books.{sort}"

    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    conn.close()

    books = []
    for row in rows:
        books.append({
            "id": row["id"],
            "title": row["title"],
            "author": row["author"],
            "lang": row["lang"],
            "tags": get_tags_for_book(row["id"]),
            "favorite": row["favorite"]
        })
    return books


def get_book(id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM books WHERE id=?", (id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "author": row["author"],
        "description": row["description"],
        "lang": row["lang"],
        "bnf_path": row["bnf_path"],
        "favorite": row["favorite"],
        "tags": get_tags_for_book(row["id"])
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
    author = request.args.get("author", "").strip()
    sort = request.args.get("sort", "title")
    favorite = request.args.get("favorite", "")

    books = get_books(
        query=q if q else None,
        tag=tag if tag else None,
        author=author if author else None,
        sort=sort,
        favorite=(favorite == "1")
    )

    resp = make_response(render_template_string(
        BASE_HTML,
        books=books,
        query=q,
        tag=tag,
        author=author,
        sort=sort,
        favorite=(favorite == "1")
    ))
    # 🔥 отключаем кэш для списка
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

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
                    if file_path.endswith(".md"):
                        with open(file_path, "r", encoding="utf-8") as f:
                            md_text = f.read()
                        md = markdown.Markdown(extensions=[StrictHeadersExtension(), TocExtension(), 'nl2br'])
                        html_content = md.convert(md_text)
                        toc_html = md.toc
                        content = f"""
                        <div class="toc">{toc_html}</div>
                        {html_content}
                        """
                    else:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f"<pre>{f.read()}</pre>"
            else:
                content = f"[Файл {file_path} не найден]"
        elif ver == "en":
            file_path = os.path.join(folder, f"{base_name}.en.md")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    if file_path.endswith(".md"):
                        with open(file_path, "r", encoding="utf-8") as f:
                            md_text = f.read()
                        md = markdown.Markdown(extensions=[StrictHeadersExtension(), TocExtension(), 'nl2br'])
                        html_content = md.convert(md_text)
                        toc_html = md.toc
                        content = f"""
                                          <div class="toc">{toc_html}</div>
                                          {html_content}
                                          """
                    else:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f"<pre>{f.read()}</pre>"
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


@app.route("/edit/<int:book_id>", methods=["GET", "POST"])
def edit_book(book_id):
    book = get_book(book_id)
    if not book:
        abort(404)

    if request.method == "POST":
        title = request.form["title"].strip()
        author = request.form["author"].strip()
        description = request.form["description"].strip()
        lang = request.form["lang"].strip()
        tags = [t.strip() for t in request.form["tags"].split(",") if t.strip()]

        # --- обновляем в БД ---
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            UPDATE books SET title=?, author=?, description=?, lang=?
            WHERE id=?
        """, (title, author, description, lang, book_id))
        cur.execute("DELETE FROM book_tags WHERE book_id=?", (book_id,))
        conn.commit()
        conn.close()

        for tag in tags:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
            cur.execute("SELECT id FROM tags WHERE name=?", (tag,))
            tag_id = cur.fetchone()[0]
            cur.execute("INSERT INTO book_tags (book_id, tag_id) VALUES (?, ?)", (book_id, tag_id))
            conn.commit()
            conn.close()

        # --- обновляем .bnf файл ---
        bnf_path = book["bnf_path"]
        try:
            import json
            if os.path.exists(bnf_path):
                with open(bnf_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
            data["title"] = title
            data["author"] = author
            data["description"] = description
            data["lang"] = lang
            data["tags"] = tags
            with open(bnf_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            return f"<p>Ошибка при обновлении BNF: {e}</p>"

        return f"<meta http-equiv='refresh' content='0; url=/book/{book_id}'>"

    tags = ", ".join(book["tags"])
    return render_template_string(EDIT_HTML, book=book, tags=tags)


@app.route("/toggle_fav/<int:book_id>")
def toggle_fav(book_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT favorite FROM books WHERE id=?", (book_id,))
    row = cur.fetchone()
    if row:
        new_val = 0 if row[0] else 1
        cur.execute("UPDATE books SET favorite=? WHERE id=?", (new_val, book_id))
        conn.commit()
    conn.close()

    # куда вернуться
    back = request.args.get("from", "list")
    if back == "book":
        return redirect(url_for("view_book", book_id=book_id))
    else:
        q = request.args.get("q", "")
        tag = request.args.get("tag", "")
        author = request.args.get("author", "")
        favorite = request.args.get("favorite", "")
        return redirect(url_for("index", q=q, tag=tag, author=author, favorite=favorite))


class StrictHeaderProcessor(HashHeaderProcessor):
    """Обрабатывает только заголовки с пробелом после #"""
    RE = re.compile(r'(?:^|\n)(?P<level>#{1,6})\s+(?P<header>.*?)\s*#*(\n|$)')


class StrictHeadersExtension(Extension):
    """Расширение для строгих заголовков"""

    def extendMarkdown(self, md):
        md.parser.blockprocessors.register(
            StrictHeaderProcessor(md.parser),
            'strict_hashheader',
            70
        )
        # Удаляем стандартный процессор заголовков
        md.parser.blockprocessors.deregister('hashheader')


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
