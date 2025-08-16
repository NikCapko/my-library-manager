import csv
import json
import os
import sqlite3
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

DB_FILE = "library.db"


# --- Работа с БД ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author TEXT,
            description TEXT,
            lang TEXT,
            bnf_path TEXT
        )
        """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
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
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id FROM books WHERE title=? AND author=?", (title, author))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def save_tags(book_id, tags):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        cur.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
        cur.execute("SELECT id FROM tags WHERE name=?", (tag,))
        tag_id = cur.fetchone()[0]
        cur.execute("INSERT OR IGNORE INTO book_tags (book_id, tag_id) VALUES (?, ?)", (book_id, tag_id))
    conn.commit()
    conn.close()


def get_tags_for_book(book_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT name FROM tags
        JOIN book_tags ON tags.id = book_tags.tag_id
        WHERE book_tags.book_id=?
    """, (book_id,))
    tags = [row[0] for row in cur.fetchall()]
    conn.close()
    return tags


def add_or_update_book(title, author, description, lang=None, bnf_path=None, tags=None):
    book_id = find_book_id(title, author)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if book_id:
        cur.execute("""
            UPDATE books SET title=?, author=?, description=?, lang=?, bnf_path=?
            WHERE id=?
        """, (title, author, description, lang, bnf_path, book_id))
    else:
        cur.execute("""
            INSERT INTO books (title, author, description, lang, bnf_path)
            VALUES (?, ?, ?, ?, ?)
        """, (title, author, description, lang, bnf_path))
        book_id = cur.lastrowid
    conn.commit()
    conn.close()
    if tags:
        save_tags(book_id, tags)


def get_books(filter_text=""):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if filter_text:
        cur.execute("""
            SELECT DISTINCT books.*
            FROM books
            LEFT JOIN book_tags ON books.id = book_tags.book_id
            LEFT JOIN tags ON tags.id = book_tags.tag_id
            WHERE books.title LIKE ? OR books.author LIKE ? OR tags.name LIKE ?
            ORDER BY books.title
        """, (f"%{filter_text}%", f"%{filter_text}%", f"%{filter_text}%"))
    else:
        cur.execute("SELECT * FROM books ORDER BY title")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_book(id):
    conn = sqlite3.connect(DB_FILE)
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

        self.create_widgets()
        self.refresh_books()

    def create_widgets(self):
        # Панель поиска
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=5, pady=5)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(top_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_entry.bind("<Return>", lambda e: self.refresh_books())

        ttk.Button(top_frame, text="🔎", width=3, command=self.refresh_books).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="❌", width=3, command=self.reset_search).pack(side=tk.LEFT, padx=2)
        #ttk.Button(top_frame, text="Импорт .bnf", command=self.import_bnf).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Сканировать папку", command=self.scan_folder).pack(side=tk.LEFT, padx=2)
        #ttk.Button(top_frame, text="Экспорт CSV", command=self.export_csv).pack(side=tk.LEFT, padx=2)

        # Основная область
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Список книг
        column_widths = {
            "id": 1,
            "author": 200,
            "title": 400,
            "description": 800,
        }

        self.tree = ttk.Treeview(main_frame, columns=("id", "author", "title", "description"), show="headings")
        for col, text in zip(("id", "author", "title", "description"),
                             ("ID", "Автор", "Название", "Описание")):
            self.tree.heading(col, text=text)
            self.tree.column(col)
        for col in self.tree["columns"]:
            width = column_widths.get(col, 10)
            self.tree.column(col, width=width)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
        self.tree.bind("<Double-1>", self.open_metadata_dialog)

        # Скроллбар
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        # Панель деталей
        self.details_text = tk.Text(main_frame, wrap=tk.WORD, width=50)
        self.details_text.pack(side=tk.RIGHT, fill=tk.BOTH)

        # Статус-бар
        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(fill=tk.X, side=tk.BOTTOM)

    def reset_search(self):
        self.search_var.set("")
        self.refresh_books()

    def search_by_tag(self, tag):
        self.search_var.set(tag)  # чтобы пользователь видел, по чему фильтруем
        self.tree.delete(*self.tree.get_children())
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            SELECT books.* FROM books
            JOIN book_tags ON books.id = book_tags.book_id
            JOIN tags ON tags.id = book_tags.tag_id
            WHERE tags.name=?
            ORDER BY books.title
        """, (tag,))
        books = cur.fetchall()
        conn.close()

        for book in books:
            book_id, title, author, desc, lang, bnf_path = book
            self.tree.insert("", tk.END, values=(book_id, author, title, desc))

        self.status_var.set(f"Найдено книг с тегом '{tag}': {len(books)}")

    def refresh_books(self):
        self.tree.delete(*self.tree.get_children())
        books = get_books(self.search_var.get())
        for book in books:
            book_id, title, author, desc, lang, bnf_path = book
            self.tree.insert("", tk.END, values=(book_id, author, title, desc))
        self.status_var.set(f"Найдено книг: {len(books)}")

    def show_details(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        book_id = self.tree.item(sel[0])["values"][0]
        book = get_book(book_id)
        if book:
            _, title, author, desc, lang, bnf_path = book
            tags = get_tags_for_book(book_id)
            folder = os.path.dirname(bnf_path)
            base_name = os.path.splitext(os.path.basename(bnf_path))[0]

            self.details_text.config(state="normal")
            self.details_text.delete(1.0, tk.END)

            # Стили
            self.details_text.tag_configure("label", font=("TkDefaultFont", 10, "bold"), spacing3=5)
            self.details_text.tag_configure("value", spacing3=5)
            self.details_text.tag_configure("taglink", foreground="blue", underline=True)

            # Название
            self.details_text.insert(tk.END, "Название: ", "label")
            self.details_text.insert(tk.END, f"{title}\n", "value")

            # Автор
            self.details_text.insert(tk.END, "Автор: ", "label")
            self.details_text.insert(tk.END, f"{author}\n", "value")

            # Описание
            self.details_text.insert(tk.END, "\nОписание:\n", "label")
            self.details_text.insert(tk.END, desc, "value")

            # Теги
            self.details_text.insert(tk.END, "\n\nТеги: ", "label")
            for i, tag in enumerate(tags):
                start_index = self.details_text.index(tk.INSERT)
                self.details_text.insert(tk.END, tag, "taglink")
                # Создаем уникальное имя тега для каждой ссылки
                tag_name = f"taglink_{i}"
                self.details_text.tag_add(tag_name, f"end-{len(tag) + 1}c", "end")
                self.details_text.tag_bind(tag_name, "<Button-1>", lambda e, t=tag: self.search_by_tag(t))

                if i != len(tags) - 1:
                    self.details_text.insert(tk.END, ", ", "value")
            self.details_text.insert(tk.END, "\n", "value")

            # Язык
            self.details_text.insert(tk.END, "\nЯзык: ", "label")
            if lang in ("ru", "en"):
                self.details_text.insert(tk.END, lang, "taglink")
                self.details_text.tag_bind("taglink", "<Button-1>",
                                           lambda e, l=lang: self.open_lang_file(folder, base_name, l, paraline=False))
            elif lang == "en-ru":
                langs = [("ru", False), ("en", False), ("en-ru", True)]
                for i, (l, use_paraline) in enumerate(langs):
                    tag_name = f"langlink_{i}"
                    self.details_text.insert(tk.END, l, tag_name)
                    self.details_text.tag_config(tag_name, foreground="blue", underline=True)
                    self.details_text.tag_bind(tag_name, "<Button-1>",
                                               lambda e, ll=l, pp=use_paraline: self.open_lang_file(folder, base_name,
                                                                                                    ll, paraline=pp))
                    if i != len(langs) - 1:
                        self.details_text.insert(tk.END, ", ", "value")
            self.details_text.insert(tk.END, "\n\n", "value")

            self.details_text.config(state="disabled")

    def open_metadata_dialog(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        book_id = self.tree.item(sel[0])["values"][0]
        book = get_book(book_id)
        if not book:
            return

        _, title, author, desc, lang, bnf_path = book
        tags = get_tags_for_book(book_id)

        dialog = tk.Toplevel(self)
        dialog.title("Метаданные книги")
        dialog.geometry("800x400")  # Увеличиваем высоту для многострочных полей
        dialog.resizable(False, False)

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(expand=True, fill=tk.BOTH)

        # поля
        tk.Label(dialog, text="Название").pack(anchor="w")
        title_var = tk.StringVar(value=title)
        tk.Entry(dialog, textvariable=title_var).pack(fill="x")

        tk.Label(dialog, text="Автор").pack(anchor="w")
        author_var = tk.StringVar(value=author)
        tk.Entry(dialog, textvariable=author_var).pack(fill="x")

        tk.Label(dialog, text="Описание").pack(anchor="w")
        desc_text = tk.Text(dialog, height=5)
        desc_text.insert("1.0", desc)
        desc_text.pack(fill="both", expand=True)

        tk.Label(dialog, text="Язык").pack(anchor="w")
        lang_var = tk.StringVar(value=lang or "")
        tk.Entry(dialog, textvariable=lang_var).pack(fill="x")

        tk.Label(dialog, text="Теги (через запятую)").pack(anchor="w")
        tags_var = tk.StringVar(value=", ".join(tags))
        tk.Entry(dialog, textvariable=tags_var).pack(fill="x")

        def save_changes():
            new_title = title_var.get()
            new_author = author_var.get()
            new_desc = desc_text.get("1.0", "end").strip()
            new_lang = lang_var.get().strip() or None
            new_tags = [t.strip() for t in tags_var.get().split(",") if t.strip()]

            # обновляем в БД
            add_or_update_book(new_title, new_author, new_desc, new_lang, bnf_path, new_tags)

            # обновляем bnf-файл
            if bnf_path and os.path.exists(bnf_path):
                try:
                    with open(bnf_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data.update({
                        "title": new_title,
                        "author": new_author,
                        "description": new_desc,
                        "lang": new_lang,
                        "tags": new_tags
                    })
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
                subprocess.Popen(["/home/nikolay/bin/paraline", file_path])
            else:
                subprocess.Popen(["mousepad", file_path])
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
                    tags=data.get("tags", [])
                )
                self.refresh_books()
                messagebox.showinfo("Импорт", f"Импортировано: {data.get('title')}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    def scan_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            count = 0
            for root, _, files in os.walk(folder):
                for file in files:
                    if file.endswith(".bnf"):
                        try:
                            with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                                data = json.load(f)
                            add_or_update_book(
                                data.get("title", ""),
                                data.get("author", ""),
                                data.get("description", ""),
                                lang=data.get("lang"),
                                bnf_path=os.path.join(root, file),
                                tags=data.get("tags", [])
                            )
                            count += 1
                        except:
                            pass
            self.refresh_books()
            messagebox.showinfo("Сканирование", f"Добавлено или обновлено {count} книг")

    def export_csv(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".csv")
        if filepath:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["ID", "Название", "Автор", "Описание", "Теги"])
                for book in get_books():
                    tags = ", ".join(get_tags_for_book(book[0]))
                    writer.writerow(list(book) + [tags])
            messagebox.showinfo("Экспорт", f"Экспортировано в {filepath}")


if __name__ == "__main__":
    init_db()
    app = LibraryApp()
    app.mainloop()
