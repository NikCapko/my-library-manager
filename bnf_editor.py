#!/usr/bin/python
import json
import os
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class BnfEditor:
    def __init__(self, root, filepath=None):
        self.root = root
        self.root.title("Редактор BNF метаданных")
        self.root.geometry("800x400")
        self.root.resizable(False, False)

        self.filepath = filepath
        self.metadata_path = None

        root.bind("<Control-s>", lambda event: self.save_metadata())

        self.build_ui()
        if filepath:
            if filepath.endswith(".bnf"):
                self.load_metadata(filepath)
            else:
                self.load_from_filename(filepath)

    def build_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(expand=True, fill=tk.BOTH)

        # Переменные для полей
        self.title_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.lang_var = tk.StringVar(value="ru")
        self.tags_var = tk.StringVar()

        row = 0
        ttk.Label(main_frame, text="Название:", font=("Arial", 10, "bold")).grid(
            row=row, column=0, sticky="w", pady=5
        )
        ttk.Entry(main_frame, textvariable=self.title_var, width=50).grid(
            row=row, column=1, sticky="ew", padx=5, pady=5
        )
        row += 1

        ttk.Label(main_frame, text="Автор:", font=("Arial", 10, "bold")).grid(
            row=row, column=0, sticky="w", pady=5
        )
        ttk.Entry(main_frame, textvariable=self.author_var, width=50).grid(
            row=row, column=1, sticky="ew", padx=5, pady=5
        )
        row += 1

        ttk.Label(main_frame, text="Язык:", font=("Arial", 10, "bold")).grid(
            row=row, column=0, sticky="w", pady=5
        )
        ttk.Combobox(
            main_frame,
            textvariable=self.lang_var,
            values=("ru", "en-ru"),
            state="readonly",
            width=50,
        ).grid(row=row, column=1, sticky="ew", padx=5, pady=5)
        row += 1

        ttk.Label(
            main_frame, text="Теги (через запятую):", font=("Arial", 10, "bold")
        ).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(main_frame, textvariable=self.tags_var, width=50).grid(
            row=row, column=1, sticky="ew", padx=5, pady=5
        )
        row += 1

        # Описание
        ttk.Label(main_frame, text="Описание:", font=("Arial", 10, "bold")).grid(
            row=row, column=0, sticky="nw", pady=5
        )
        desc_frame = ttk.Frame(main_frame)
        desc_frame.grid(row=row, column=1, sticky="nsew", padx=5, pady=5)

        self.desc_text = tk.Text(desc_frame, height=5, wrap=tk.WORD, undo=True)
        self.desc_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        desc_scroll = ttk.Scrollbar(desc_frame, command=self.desc_text.yview)
        desc_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.desc_text.configure(yscrollcommand=desc_scroll.set)
        row += 1

        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(4, weight=1)

        # Кнопки
        buttons_frame = ttk.Frame(self.root)
        buttons_frame.pack(side=tk.BOTTOM, pady=10)

        ttk.Button(buttons_frame, text="Сохранить", command=self.save_metadata).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(buttons_frame, text="Выход", command=self.root.quit).pack(
            side=tk.LEFT, padx=5
        )

    def load_from_filename(self, filepath):
        """Парсинг названия и автора из имени файла .md"""
        base_dir = os.path.dirname(filepath)
        base_name = os.path.splitext(os.path.basename(filepath))[0]  # без .md
        self.metadata_path = os.path.join(base_dir, f"{base_name}.bnf")

        # Проверяем формат "Название [Автор]"
        match = re.match(r"^(.*?)(?:\[(.*?)\])?$", base_name)
        if match:
            title = match.group(1).strip()
            author = match.group(2).strip() if match.group(2) else ""
            self.title_var.set(title)
            self.author_var.set(author)

        # Если рядом уже есть bnf → загрузим его
        if os.path.exists(self.metadata_path):
            self.load_metadata(self.metadata_path)

    def load_metadata(self, filepath):
        """Загрузка данных из .bnf"""
        self.metadata_path = filepath
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.title_var.set(data.get("title", ""))
                self.author_var.set(data.get("author", ""))
                self.lang_var.set(data.get("lang", ""))
                self.tags_var.set(", ".join(data.get("tags", [])))
                self.desc_text.insert("1.0", data.get("description", ""))
        except Exception:
            pass

    def save_metadata(self):
        data = {
            "title": self.title_var.get(),
            "author": self.author_var.get(),
            "lang": self.lang_var.get(),
            "tags": [
                tag.strip() for tag in self.tags_var.get().split(",") if tag.strip()
            ],
            "description": self.desc_text.get("1.0", tk.END).strip(),
        }

        save_path = self.metadata_path
        if not save_path:
            save_path = filedialog.asksaveasfilename(
                defaultextension=".bnf",
                filetypes=[("BNF файлы", "*.bnf"), ("Все файлы", "*.*")],
            )
            if not save_path:
                return

        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            messagebox.showinfo("Успех", f"Метаданные сохранены в {save_path}")
            self.metadata_path = save_path
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}")


if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    app = BnfEditor(root, filepath)
    root.mainloop()
