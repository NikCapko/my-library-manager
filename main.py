import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sqlite3
import os
import json

DB_FILE = "library.db"

# --- Работа с БД ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        authors TEXT,
        year INTEGER,
        isbn TEXT,
        description TEXT
    )
    """)
    conn.commit()
    conn.close()

def add_book(title, authors, year, isbn, description):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO books (title, authors, year, isbn, description)
        VALUES (?, ?, ?, ?, ?)
    """, (title, authors, year, isbn, description))
    conn.commit()
    conn.close()

def get_books(filter_text=""):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if filter_text:
        cur.execute("""
            SELECT * FROM books
            WHERE title LIKE ? OR authors LIKE ? OR isbn LIKE ?
            ORDER BY title
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
        ttk.Button(top_frame, text="Импорт .bnf", command=self.import_bnf).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Сканировать папку", command=self.scan_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Экспорт CSV", command=self.export_csv).pack(side=tk.LEFT, padx=2)

        # Основная область
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Список книг
        self.tree = ttk.Treeview(main_frame, columns=("id", "title", "authors", "year", "isbn"), show="headings")
        for col, text in zip(("id", "title", "authors", "year", "isbn"),
                             ("ID", "Название", "Авторы", "Год", "ISBN")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=100 if col != "title" else 250)
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

    def refresh_books(self):
        self.tree.delete(*self.tree.get_children())
        for book in get_books(self.search_var.get()):
            self.tree.insert("", tk.END, values=book)
        self.status_var.set(f"Найдено книг: {len(get_books(self.search_var.get()))}")

    def show_details(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        book_id = self.tree.item(sel[0])["values"][0]
        book = get_book(book_id)
        if book:
            _, title, authors, year, isbn, desc = book
            self.details_text.delete(1.0, tk.END)
            self.details_text.insert(tk.END, f"Название: {title}\n")
            self.details_text.insert(tk.END, f"Авторы: {authors}\n")
            self.details_text.insert(tk.END, f"Год: {year}\n")
            self.details_text.insert(tk.END, f"ISBN: {isbn}\n\n")
            self.details_text.insert(tk.END, f"{desc}")

    def open_file(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        book_id = self.tree.item(sel[0])["values"][0]
        book = get_book(book_id)

    def import_bnf(self):
        filepath = filedialog.askopenfilename(filetypes=[("Info files", "*.bnf")])
        if filepath:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                add_book(
                    data.get("title", ""),
                    ", ".join(data.get("authors", [])),
                    data.get("year"),
                    data.get("isbn", ""),
                    data.get("description", "")
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
                            add_book(
                                data.get("title", ""),
                                ", ".join(data.get("authors", [])),
                                data.get("year"),
                                data.get("isbn", ""),
                                data.get("description", "")
                            )
                            count += 1
                        except:
                            pass
            self.refresh_books()
            messagebox.showinfo("Сканирование", f"Добавлено {count} книг")

    def export_csv(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".csv")
        if filepath:
            import csv
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["ID", "Название", "Авторы", "Год", "ISBN", "Описание"])
                for book in get_books():
                    writer.writerow(book)
            messagebox.showinfo("Экспорт", f"Экспортировано в {filepath}")

if __name__ == "__main__":
    init_db()
    app = LibraryApp()
    app.mainloop()
