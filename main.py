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

        ttk.Button(top_frame, text="Поиск", command=self.refresh_books).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Сбросить", command=self.reset_search).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Импорт .bnf", command=self.import_bnf).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Сканировать папку", command=self.scan_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Экспорт CSV", command=self.export_csv).pack(side=tk.LEFT, padx=2)

        # Основная область
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Список книг
        column_widths = {
            "id": 50,
            "author": 200,
            "title": 1000,
        }

        self.tree = ttk.Treeview(main_frame, columns=("id", "author", "title"), show="headings")
        for col, text in zip(("id", "author", "title"),
                             ("ID", "Автор", "Название",)):
            self.tree.heading(col, text=text)
            self.tree.column(col)
        for col in self.tree["columns"]:
            width = column_widths.get(col, 10)
            self.tree.column(col, width=width, minwidth=20)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
        self.tree.bind("<Double-1>", self.open_file)

        # Скроллбар
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        # Панель деталей
        self.details_text = tk.Text(main_frame, wrap=tk.WORD, width=40)
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
            self.tree.insert("", tk.END, values=(book_id, author, title))

        self.status_var.set(f"Найдено книг с тегом '{tag}': {len(books)}")

    def refresh_books(self):
        self.tree.delete(*self.tree.get_children())
        books = get_books(self.search_var.get())
        for book in books:
            book_id, title, author, desc, lang, bnf_path = book
            self.tree.insert("", tk.END, values=(book_id, author, title))
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

            self.details_text.config(state="normal")
            self.details_text.delete(1.0, tk.END)

            self.details_text.insert(tk.END, f"Название: {title}\n")
            self.details_text.insert(tk.END, f"Автор: {author}\n")
            self.details_text.insert(tk.END, "Теги: ")

            # Выводим теги как кликабельные
            for i, tag in enumerate(tags):
                tag_start = self.details_text.index(tk.INSERT)
                self.details_text.insert(tk.END, tag)
                tag_end = self.details_text.index(tk.INSERT)
                self.details_text.tag_add(f"tag_{i}", tag_start, tag_end)
                self.details_text.tag_config(f"tag_{i}", foreground="blue", underline=True)
                self.details_text.tag_bind(f"tag_{i}", "<Button-1>", lambda e, t=tag: self.search_by_tag(t))
                if i != len(tags) - 1:
                    self.details_text.insert(tk.END, ", ")

            self.details_text.insert(tk.END, "\n\n" + desc)

            self.details_text.config(state="disabled")

    def open_file(self, event):
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
            if lang == "en-ru":
                target_file = os.path.join(folder, f"{base_name}.en.md")
                if not os.path.exists(target_file):
                    messagebox.showerror("Ошибка", f"Файл {target_file} не найден")
                    return
                subprocess.Popen(["/home/nikolay/bin/paraline", target_file])
            else:
                target_file = os.path.join(folder, f"{base_name}.md")
                if not os.path.exists(target_file):
                    messagebox.showerror("Ошибка", f"Файл {target_file} не найден")
                    return
                subprocess.Popen(["xdg-open", target_file])  # или открыть чем-то ещё
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
