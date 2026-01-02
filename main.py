#!/usr/bin/python

import json
import os
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from watchdog.observers import Observer

from library_watcher import LibraryWatcher

DB_FILE = "library.db"


# --- Работа с БД ---
def connect():
    conn = sqlite3.connect(DB_FILE)

    # Универсальная регистронезависимая коллация (Unicode)
    def _cmp(a, b):
        a = "" if a is None else str(a)
        b = "" if b is None else str(b)
        aa = a.casefold()
        bb = b.casefold()
        return (aa > bb) - (aa < bb)  # -1, 0, 1

    conn.create_collation("UNI_NOCASE", _cmp)
    # На всякий случай функция для ручного приведения
    conn.create_function(
        "UNI_LOWER", 1, lambda s: "" if s is None else str(s).casefold()
    )
    return conn


def init_db():
    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author TEXT,
            description TEXT,
            lang TEXT,
            bnf_path TEXT,
            favorite INTEGER DEFAULT 0
        )
        """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_books_author_title ON books (author, title)
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS book_tags (
        book_id INTEGER,
        tag_id INTEGER,
        UNIQUE(book_id, tag_id),
        FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
        FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
    )
    """)
    conn.commit()
    conn.close()


def find_book_id(title, author):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM books WHERE title=? AND author=?", (title, author))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def save_tags(book_id, tags):
    conn = connect()
    cur = conn.cursor()
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        cur.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
        cur.execute("SELECT id FROM tags WHERE name=?", (tag,))
        tag_id = cur.fetchone()[0]
        cur.execute(
            "INSERT OR IGNORE INTO book_tags (book_id, tag_id) VALUES (?, ?)",
            (book_id, tag_id),
        )
    conn.commit()
    conn.close()


def get_tags_for_book(book_id):
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT name FROM tags
        JOIN book_tags ON tags.id = book_tags.tag_id
        WHERE book_tags.book_id=?
    """,
        (book_id,),
    )
    tags = [row[0] for row in cur.fetchall()]
    conn.close()
    return tags


def add_or_update_book(title, author, description, lang=None, bnf_path=None, tags=None):
    book_id = find_book_id(title, author)
    conn = connect()
    cur = conn.cursor()
    if book_id:
        cur.execute(
            """
            UPDATE books SET title=?, author=?, description=?, lang=?, bnf_path=?
            WHERE id=?
        """,
            (title, author, description, lang, bnf_path, book_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO books (title, author, description, lang, bnf_path)
            VALUES (?, ?, ?, ?, ?)
        """,
            (title, author, description, lang, bnf_path),
        )
        book_id = cur.lastrowid
    conn.commit()
    conn.close()
    if tags:
        save_tags(book_id, tags)


def get_books(filter_text=""):
    conn = connect()
    cur = conn.cursor()
    if filter_text:
        f = filter_text.casefold()
        cur.execute(
            """
            SELECT DISTINCT books.*
            FROM books
            LEFT JOIN book_tags ON books.id = book_tags.book_id
            LEFT JOIN tags ON tags.id = book_tags.tag_id
            WHERE UNI_LOWER(books.title)  LIKE UNI_LOWER(?)
               OR UNI_LOWER(books.author) LIKE UNI_LOWER(?)
               OR UNI_LOWER(tags.name)    LIKE UNI_LOWER(?)
            ORDER BY UNI_LOWER(books.title)
        """,
            (f"%{f}%", f"%{f}%", f"%{f}%"),
        )
    else:
        cur.execute("SELECT * FROM books ORDER BY UNI_LOWER(title)")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_book(id):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM books WHERE id=?", (id,))
    book = cur.fetchone()
    conn.close()
    return book


# --- GUI ---
class LibraryApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Book Library Manager")
        self.geometry("900x600")

        self.library_path = "/home/nikolay/Books/"
        os.makedirs(self.library_path, exist_ok=True)

        self.create_widgets()
        self.check_db_files_exist()
        self.refresh_books()

        self.start_watcher()

    def create_widgets(self):
        # Панель поиска
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=5, pady=5)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(top_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_entry.bind("<Return>", lambda e: self.refresh_books())

        ttk.Button(top_frame, text="🔎", width=3, command=self.refresh_books).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(top_frame, text="❌", width=3, command=self.reset_search).pack(
            side=tk.LEFT, padx=2
        )
        # ttk.Button(top_frame, text="Импорт .bnf", command=self.import_bnf).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            top_frame, text="Сканировать папку", command=self.scan_folder_dialog
        ).pack(side=tk.LEFT, padx=2)

        # Основная область
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Список книг
        column_widths = {
            "id": 50,
            "author": 200,
            "title": 350,
            "lang": 50,
            "description": 650,
            "tags": 300,
        }

        self.tree = ttk.Treeview(
            main_frame,
            columns=("id", "author", "title", "lang", "description", "tags"),
            show="headings",
        )
        self.sort_orders = {"author": True, "title": True}

        self.tree.heading("id", text="ID")
        self.tree.heading(
            "author", text="Автор", command=lambda: self.sort_column("author")
        )
        self.tree.heading(
            "title", text="Название", command=lambda: self.sort_column("title")
        )
        self.tree.heading("lang", text="Язык")
        self.tree.heading("description", text="Описание")
        self.tree.heading("tags", text="Теги")
        for col in self.tree["columns"]:
            width = column_widths.get(col, 10)
            self.tree.column(col, width=width)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
        self.tree.bind("<Double-1>", self.open_file_from_list)

        # Скроллбар
        scrollbar = ttk.Scrollbar(
            main_frame, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        # Панель деталей
        self.details_text = tk.Text(main_frame, wrap=tk.WORD, width=50)
        self.details_text.pack(side=tk.RIGHT, fill=tk.BOTH)

        # Статус-бар
        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(
            fill=tk.X, side=tk.BOTTOM
        )

    def start_watcher(self):
        """Запуск watchdog в отдельном потоке"""
        event_handler = LibraryWatcher()
        self.observer = Observer()
        self.observer.schedule(event_handler, self.library_path, recursive=True)
        self.observer_thread = threading.Thread(target=self.observer.start, daemon=True)
        self.observer_thread.start()

    def sort_column(self, col):
        # получаем все элементы
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        # сортируем
        data.sort(reverse=not self.sort_orders[col])
        for index, (val, k) in enumerate(data):
            self.tree.move(k, "", index)
        # меняем направление сортировки на противоположное
        self.sort_orders[col] = not self.sort_orders[col]

    def reset_search(self):
        self.search_var.set("")
        self.refresh_books()

    def search_by_author(self, author):
        self.search_var.set(author)
        self.tree.delete(*self.tree.get_children())
        conn = connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM books
            WHERE UNI_LOWER(author) = UNI_LOWER(?)
            ORDER BY UNI_LOWER(title)
        """,
            (author,),
        )
        books = cur.fetchall()
        conn.close()

        for book in books:
            book_id, title, author, desc, lang, bnf_path, favorite = book
            tags = ", ".join(get_tags_for_book(book_id))
            self.tree.insert(
                "", tk.END, values=(book_id, author, title, lang, desc, tags)
            )

        self.status_var.set(f"Найдено книг автора '{author}': {len(books)}")

    def search_by_tag(self, tag):
        self.search_var.set(tag)
        self.tree.delete(*self.tree.get_children())
        conn = connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT books.* FROM books
            JOIN book_tags ON books.id = book_tags.book_id
            JOIN tags ON tags.id = book_tags.tag_id
            WHERE UNI_LOWER(tags.name) = UNI_LOWER(?)
            ORDER BY UNI_LOWER(books.title)
        """,
            (tag,),
        )
        books = cur.fetchall()
        conn.close()

        for book in books:
            book_id, title, author, desc, lang, bnf_path, favorite = book
            tags = ", ".join(get_tags_for_book(book_id))
            self.tree.insert(
                "", tk.END, values=(book_id, author, title, lang, desc, tags)
            )

        self.status_var.set(f"Найдено книг с тегом '{tag}': {len(books)}")

    def find_book_id(title, author):
        conn = connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM books
            WHERE UNI_LOWER(title)  = UNI_LOWER(?)
              AND UNI_LOWER(author) = UNI_LOWER(?)
        """,
            (title, author),
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None

    def sort_column(self, col):
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]

        def key_fn(item):
            val = item[0]
            if val is None:
                return ""
            return str(val).casefold()

        data.sort(key=key_fn, reverse=not self.sort_orders[col])
        for index, (_, k) in enumerate(data):
            self.tree.move(k, "", index)
        self.sort_orders[col] = not self.sort_orders[col]

    def check_db_files_exist(self):
        """Удаляем из БД записи, у которых нет .bnf файла"""
        conn = connect()
        cur = conn.cursor()
        cur.execute("SELECT id, bnf_path FROM books")
        rows = cur.fetchall()

        deleted = 0
        for book_id, path in rows:
            if not os.path.exists(path):
                cur.execute("DELETE FROM books WHERE id=?", (book_id,))
                deleted += 1

        if deleted:
            conn.commit()
            print(f"Удалено {deleted} записей без файлов.")

    def refresh_books(self):
        self.tree.delete(*self.tree.get_children())
        books = get_books(self.search_var.get())
        for book in books:
            book_id, title, author, desc, lang, bnf_path, favorite = book
            tags = ", ".join(get_tags_for_book(book_id))
            self.tree.insert(
                "", tk.END, values=(book_id, author, title, lang, desc, tags)
            )
        self.status_var.set(f"Найдено книг: {len(books)}")

    def show_details(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        book_id = self.tree.item(sel[0])["values"][0]
        book = get_book(book_id)
        if book:
            _, title, author, desc, lang, bnf_path, favorite = book
            tags = get_tags_for_book(book_id)
            folder = os.path.dirname(bnf_path) if bnf_path else None
            base_name = (
                os.path.splitext(os.path.basename(bnf_path))[0] if bnf_path else None
            )

            self.details_text.config(state="normal")
            self.details_text.delete(1.0, tk.END)

            # Стили
            self.details_text.tag_configure(
                "label", font=("TkDefaultFont", 10, "bold"), spacing3=5
            )
            self.details_text.tag_configure("value", spacing3=5)
            self.details_text.tag_configure(
                "taglink", foreground="blue", underline=True
            )

            # Название
            self.details_text.insert(tk.END, "Название: ", "label")
            self.details_text.insert(tk.END, f"{title}\n", "value")

            # Автор (ссылка)
            self.details_text.insert(tk.END, "Автор: ", "label")
            start_index = self.details_text.index(tk.INSERT)
            self.details_text.insert(tk.END, f"{author}\n", "taglink")
            tag_name = f"authorlink_{book_id}"
            self.details_text.tag_add(
                tag_name, start_index, f"{start_index}+{len(author)}c"
            )
            self.details_text.tag_config(tag_name, foreground="blue", underline=True)
            self.details_text.tag_bind(
                tag_name, "<Button-1>", lambda e, a=author: self.search_by_author(a)
            )

            # Описание
            self.details_text.insert(tk.END, "\nОписание:\n", "label")
            self.details_text.insert(tk.END, desc, "value")

            # Теги
            self.details_text.insert(tk.END, "\n\nТеги: ", "label")
            for i, tag in enumerate(tags):
                start_index = self.details_text.index(tk.INSERT)
                tag_name = f"taglink_{book_id}_{i}"
                self.details_text.insert(tk.END, tag, tag_name)
                self.details_text.tag_add(tag_name, f"end-{len(tag)}c", "end")
                self.details_text.tag_config(
                    tag_name, foreground="blue", underline=True
                )
                self.details_text.tag_bind(
                    tag_name, "<Button-1>", lambda e, t=tag: self.search_by_tag(t)
                )
                if i != len(tags) - 1:
                    self.details_text.insert(tk.END, ", ", "value")
            self.details_text.insert(tk.END, "\n", "value")

            # Язык
            self.details_text.insert(tk.END, "\nЯзык: ", "label")
            if lang in ("ru", "en"):
                langlink_name = f"langlink_{lang}"
                self.details_text.insert(tk.END, lang, langlink_name)
                self.details_text.tag_add(
                    langlink_name, f"end-{len(langlink_name)}c", "end"
                )
                self.details_text.tag_config(
                    langlink_name, foreground="blue", underline=True
                )
                self.details_text.tag_bind(
                    langlink_name,
                    "<Button-1>",
                    lambda e, l=lang: self.open_file(folder, base_name),
                )
            elif lang == "en-ru":
                langs = [("ru", False), ("en", False), ("en-ru", True)]
                for i, (l, use_paraline) in enumerate(langs):
                    langlink_name = f"lang_link_{i}"
                    self.details_text.insert(tk.END, l, langlink_name)
                    self.details_text.tag_config(
                        langlink_name, foreground="blue", underline=True
                    )
                    self.details_text.tag_bind(
                        langlink_name,
                        "<Button-1>",
                        lambda e, ll=l, pp=use_paraline: self.open_lang_file(
                            folder, base_name, ll, pp
                        ),
                    )
                    if i != len(langs) - 1:
                        self.details_text.insert(tk.END, ", ", "value")
            self.details_text.insert(tk.END, "\n\n", "value")

            # --- Новое: кнопка "Открыть папку" ---
            if bnf_path and os.path.exists(bnf_path):
                folder_name = f"open_folder_{book_id}"
                self.details_text.insert(tk.END, "Открыть папку\n", folder_name)
                self.details_text.tag_add(
                    folder_name, f"end-{len(folder_name)}c", "end"
                )
                self.details_text.tag_config(
                    folder_name, foreground="blue", underline=True
                )
                self.details_text.tag_bind(
                    folder_name, "<Button-1>", lambda e, f=bnf_path: self.open_folder(f)
                )
            # Редактировать bnf файл
            open_bnf = f"open_bnf_{book_id}"
            self.details_text.insert(tk.END, "\nОткрыть bnf-файл\n", open_bnf)
            self.details_text.tag_add(open_bnf, f"end-{len(open_bnf)}c", "end")
            self.details_text.tag_config(open_bnf, foreground="blue", underline=True)
            self.details_text.tag_bind(
                open_bnf,
                "<Button-1>",
                lambda e, f=book_id: self.open_metadata_dialog(f),
            )

            self.details_text.config(state="disabled")

    def open_folder(self, file_path):
        folder = os.path.dirname(file_path)
        try:
            if os.name == "nt":  # Windows
                subprocess.Popen(["explorer", "/select,", file_path])
            elif sys.platform == "darwin":  # macOS
                subprocess.Popen(["open", "-R", file_path])
            else:  # Linux
                # пытаемся разные менеджеры
                for fm in ["nautilus", "dolphin", "thunar", "pcmanfm"]:
                    if (
                        subprocess.call(
                            ["which", fm],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        == 0
                    ):
                        if fm in ("nautilus", "dolphin"):
                            subprocess.Popen([fm, "--select", file_path])
                        else:
                            subprocess.Popen([fm, file_path])
                        return
                # fallback — просто открыть папку
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть папку: {e}")

    def open_file_from_list(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        book_id = self.tree.item(sel[0])["values"][0]
        book = get_book(book_id)
        if not book:
            return

        _, title, author, desc, lang, bnf_path, favorite = book
        folder = os.path.dirname(bnf_path) if bnf_path else None
        base_name = (
            os.path.splitext(os.path.basename(bnf_path))[0] if bnf_path else None
        )
        if lang in ("ru", "en"):
            self.open_file(folder, base_name)
        elif lang == "en-ru":
            self.open_lang_file(folder, base_name, "en-ru", True)

    def open_metadata_dialog(self, book_id):
        sel = self.tree.selection()
        if not sel:
            return
        # book_id = self.tree.item(sel[0])["values"][0]
        book = get_book(book_id)
        if not book:
            return

        _, title, author, desc, lang, bnf_path, favorite = book
        tags = get_tags_for_book(book_id)

        dialog = tk.Toplevel(self)
        dialog.title("Метаданные книги")
        dialog.geometry("800x400")  # Увеличиваем высоту для многострочных полей
        dialog.resizable(False, False)

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(expand=True, fill=tk.BOTH)

        # поля
        ttk.Label(dialog, text="Название").pack(anchor="w")
        title_var = tk.StringVar(value=title)
        ttk.Entry(dialog, textvariable=title_var).pack(fill="x")

        ttk.Label(dialog, text="Автор").pack(anchor="w")
        author_var = tk.StringVar(value=author)
        ttk.Entry(dialog, textvariable=author_var).pack(fill="x")

        ttk.Label(dialog, text="Язык").pack(anchor="w")
        lang_var = tk.StringVar(value=lang or "ru")
        ttk.Combobox(
            dialog,
            textvariable=lang_var,
            values=("ru", "en-ru"),
            state="readonly",
        ).pack(fill="x")

        ttk.Label(dialog, text="Теги (через запятую)").pack(anchor="w")
        tags_var = tk.StringVar(value=", ".join(tags))
        ttk.Entry(dialog, textvariable=tags_var).pack(fill="x")

        ttk.Label(dialog, text="Описание").pack(anchor="w")
        desc_text = tk.Text(dialog, height=5)
        desc_text.insert("1.0", desc)
        desc_text.pack(fill="both", expand=True)

        def save_changes():
            new_title = title_var.get()
            new_author = author_var.get()
            new_desc = desc_text.get("1.0", "end").strip()
            new_lang = lang_var.get().strip() or None
            new_tags = [t.strip() for t in tags_var.get().split(",") if t.strip()]

            # обновляем в БД
            add_or_update_book(
                new_title, new_author, new_desc, new_lang, bnf_path, new_tags
            )

            # обновляем bnf-файл
            if bnf_path and os.path.exists(bnf_path):
                try:
                    with open(bnf_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data.update(
                        {
                            "title": new_title,
                            "author": new_author,
                            "description": new_desc,
                            "lang": new_lang,
                            "tags": new_tags,
                        }
                    )
                    with open(bnf_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    messagebox.showerror("Ошибка", f"Не удалось обновить .bnf: {e}")

            self.refresh_books()
            dialog.destroy()

        # Кнопки
        buttons_frame = ttk.Frame(dialog)
        buttons_frame.pack(side=tk.BOTTOM, pady=10)

        save_button = ttk.Button(buttons_frame, text="Сохранить", command=save_changes)
        save_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(buttons_frame, text="Отмена", command=dialog.destroy)
        cancel_button.pack(side=tk.LEFT, padx=5)

    def open_lang_file(self, folder, base_name, lang_code, paraline=False):
        if lang_code in ("ru", "en"):
            file_name = f"{base_name}.{lang_code}.md"
        elif lang_code == "en-ru":
            file_name = f"{base_name}.en.md"
        else:
            file_name = f"{base_name}.md"

        file_path = os.path.join(folder, file_name)
        if not os.path.exists(file_path):
            messagebox.showerror("Ошибка", f"Файл {file_path} не найден")
            return

        try:
            if paraline:
                subprocess.Popen(
                    ["/home/nikolay/bin/paraline", file_path],
                    cwd="/home/nikolay/Projects/parallel_editor",
                )
            else:
                subprocess.Popen(["ghostwriter", file_path])
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def open_file(self, folder, base_name):
        file_name = f"{base_name}.md"
        file_path = os.path.join(folder, file_name)

        if not os.path.exists(file_path):
            messagebox.showerror("Ошибка", f"Файл {file_path} не найден")
            return

        try:
            subprocess.Popen(["ghostwriter", file_path])
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def open_bnf_file(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        book_id = self.tree.item(sel[0])["values"][0]
        book = get_book(book_id)
        if not book:
            return
        _, title, author, desc, lang, bnf_path = book
        if not bnf_path or not os.path.exists(bnf_path):
            messagebox.showerror("Ошибка", "Файл .bnf не найден")
            return

        folder = os.path.dirname(bnf_path)
        base_name = os.path.splitext(os.path.basename(bnf_path))[0]

        try:
            target_file = os.path.join(folder, f"{base_name}.bnf")
            if not os.path.exists(target_file):
                messagebox.showerror("Ошибка", f"Файл {target_file} не найден")
                return
            subprocess.Popen(["mousepad", target_file])
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def import_bnf(self):
        filepath = filedialog.askopenfilename(filetypes=[("Info files", "*.bnf")])
        if filepath:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                add_or_update_book(
                    data.get("title", ""),
                    data.get("author", ""),
                    data.get("description", ""),
                    lang=data.get("lang"),
                    bnf_path=filepath,
                    tags=data.get("tags", []),
                )
                self.refresh_books()
                messagebox.showinfo("Импорт", f"Импортировано: {data.get('title')}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    def scan_folder_dialog(self):
        folder = filedialog.askdirectory()
        self.library_path = folder
        self.start_watcher()
        self.scan_folder(folder)

    def scan_folder(self, folder):
        if folder:
            count = 0
            for root, _, files in os.walk(folder):
                for file in files:
                    if file.endswith(".bnf"):
                        try:
                            with open(
                                os.path.join(root, file), "r", encoding="utf-8"
                            ) as f:
                                data = json.load(f)
                            add_or_update_book(
                                data.get("title", ""),
                                data.get("author", ""),
                                data.get("description", ""),
                                lang=data.get("lang"),
                                bnf_path=os.path.join(root, file),
                                tags=data.get("tags", []),
                            )
                            count += 1
                        except:
                            pass
            self.check_db_files_exist()
            self.refresh_books()
            messagebox.showinfo("Сканирование", f"Добавлено или обновлено {count} книг")


if __name__ == "__main__":
    init_db()
    app = LibraryApp()
    app.mainloop()
    style = ttk.Style()
    style.theme_use("clam")
