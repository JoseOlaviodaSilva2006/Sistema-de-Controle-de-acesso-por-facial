import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog

import cv2
from facial_auth_v2 import DB_PATH, Storage, User

BASE_DIR = Path(__file__).resolve().parent
APP_SCRIPT = BASE_DIR / "facial_auth_v2.py"
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"


class LauncherUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Facial Access Control")
        self.root.geometry("560x420")
        self.root.configure(bg="#0f172a")
        self.root.resizable(False, False)
        self.storage = Storage(DB_PATH)
        self.storage.ensure_default_admin(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD)

        self.admin_logged = False
        self.admin_username = ""
        self._build()

    def _build(self) -> None:
        title = tk.Label(
            self.root,
            text="Facial Access Control",
            font=("Segoe UI", 20, "bold"),
            fg="#f8fafc",
            bg="#0f172a",
        )
        title.pack(pady=(28, 6))

        subtitle = tk.Label(
            self.root,
            text="Painel operacional",
            font=("Segoe UI", 11),
            fg="#94a3b8",
            bg="#0f172a",
        )
        subtitle.pack(pady=(0, 18))

        panel = tk.Frame(self.root, bg="#1e293b", bd=0, highlightthickness=0)
        panel.pack(fill="both", expand=True, padx=28, pady=14)

        self.status = tk.Label(
            panel,
            text="Status ADM: não autenticado",
            font=("Segoe UI", 10),
            fg="#f59e0b",
            bg="#1e293b",
            anchor="w",
        )
        self.status.pack(fill="x", padx=18, pady=(16, 8))

        btn_style = {
            "font": ("Segoe UI", 11, "bold"),
            "fg": "#ffffff",
            "bd": 0,
            "activeforeground": "#ffffff",
            "cursor": "hand2",
            "padx": 10,
            "pady": 10,
        }

        tk.Button(
            panel,
            text="Login ADM",
            bg="#2563eb",
            activebackground="#1d4ed8",
            command=self.admin_login,
            **btn_style,
        ).pack(fill="x", padx=18, pady=8)

        tk.Button(
            panel,
            text="Cadastrar usuário (enrollment)",
            bg="#16a34a",
            activebackground="#15803d",
            command=self.enroll_user,
            **btn_style,
        ).pack(fill="x", padx=18, pady=8)

        tk.Button(
            panel,
            text="Verificar acesso (live)",
            bg="#0ea5e9",
            activebackground="#0284c7",
            command=self.verify_user,
            **btn_style,
        ).pack(fill="x", padx=18, pady=8)

        tk.Button(
            panel,
            text="Retreinar modelo",
            bg="#9333ea",
            activebackground="#7e22ce",
            command=self.retrain_model,
            **btn_style,
        ).pack(fill="x", padx=18, pady=8)

        tk.Button(
            panel,
            text="Gerenciar usuários (CRUD)",
            bg="#f97316",
            activebackground="#ea580c",
            command=self.manage_users,
            **btn_style,
        ).pack(fill="x", padx=18, pady=8)

        tk.Button(
            panel,
            text="Criar novo ADM",
            bg="#475569",
            activebackground="#334155",
            command=self.create_admin,
            **btn_style,
        ).pack(fill="x", padx=18, pady=8)

        help_text = (
            "Ações administrativas exigem login ADM.\n"
            f"ADM inicial: {DEFAULT_ADMIN_USER} / {DEFAULT_ADMIN_PASSWORD}"
        )
        tk.Label(
            panel,
            text=help_text,
            justify="left",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#1e293b",
        ).pack(fill="x", padx=18, pady=(10, 16))

    def _run_cmd(self, args: list[str], title: str) -> None:
        try:
            subprocess.Popen(args, cwd=str(BASE_DIR))
            messagebox.showinfo(title, "Comando iniciado em uma nova janela.")
        except Exception as exc:
            messagebox.showerror("Erro", f"Falha ao executar comando:\n{exc}")

    def _require_admin(self) -> bool:
        if self.admin_logged:
            return True
        messagebox.showwarning("Acesso restrito", "Faça login ADM para continuar.")
        return False

    def admin_login(self) -> None:
        username = simpledialog.askstring("Login ADM", "Usuário ADM:")
        if not username:
            return
        password = simpledialog.askstring("Login ADM", "Digite a senha ADM:", show="*")
        if not password:
            return
        if self.storage.verify_admin(username.strip(), password):
            self.admin_logged = True
            self.admin_username = username.strip()
            self.status.config(
                text=f"Status ADM: autenticado ({self.admin_username})",
                fg="#22c55e",
            )
            messagebox.showinfo("Sucesso", "Login ADM realizado com sucesso.")
        else:
            messagebox.showerror("Falha", "Senha inválida.")

    def enroll_user(self) -> None:
        if not self._require_admin():
            return
        name = simpledialog.askstring("Cadastro", "Nome do usuário:")
        if not name:
            return
        self._run_cmd(
            [sys.executable, str(APP_SCRIPT), "enroll", "--name", name.strip()],
            "Cadastro",
        )

    def verify_user(self) -> None:
        self._run_cmd([sys.executable, str(APP_SCRIPT), "verify"], "Verificação")

    def retrain_model(self) -> None:
        if not self._require_admin():
            return
        self._run_cmd([sys.executable, str(APP_SCRIPT), "retrain"], "Retreino")

    def create_admin(self) -> None:
        if not self._require_admin():
            return
        username = simpledialog.askstring("Novo ADM", "Usuário do novo ADM:")
        if not username:
            return
        password = simpledialog.askstring("Novo ADM", "Senha do novo ADM:", show="*")
        if not password:
            return
        try:
            self.storage.create_admin(username.strip(), password)
            messagebox.showinfo("Sucesso", "Novo administrador criado.")
        except Exception as exc:
            messagebox.showerror("Erro", f"Não foi possível criar ADM:\n{exc}")

    def manage_users(self) -> None:
        if not self._require_admin():
            return
        UserManagerWindow(self.root, self.storage, self._run_cmd)


class UserManagerWindow:
    def __init__(self, parent: tk.Tk, storage: Storage, run_cmd_cb) -> None:
        self.storage = storage
        self.run_cmd = run_cmd_cb
        self.users: list[User] = []
        self.win = tk.Toplevel(parent)
        self.win.title("Gerenciar usuários")
        self.win.geometry("840x520")
        self.win.configure(bg="#0f172a")

        self.listbox = tk.Listbox(
            self.win,
            font=("Consolas", 11),
            bg="#111827",
            fg="#e5e7eb",
            selectbackground="#2563eb",
            activestyle="none",
        )
        self.listbox.pack(fill="both", expand=True, padx=18, pady=(18, 10))

        row = tk.Frame(self.win, bg="#0f172a")
        row.pack(fill="x", padx=18, pady=(0, 14))

        def button(text: str, cmd, bg: str) -> None:
            tk.Button(
                row,
                text=text,
                command=cmd,
                bg=bg,
                fg="#fff",
                bd=0,
                activebackground=bg,
                activeforeground="#fff",
                font=("Segoe UI", 10, "bold"),
                padx=8,
                pady=8,
                cursor="hand2",
            ).pack(side="left", padx=(0, 8))

        button("Atualizar", self.refresh, "#334155")
        button("Criar usuário", self.create_user, "#16a34a")
        button("Editar usuário", self.edit_user, "#0ea5e9")
        button("Ativar/Inativar", self.toggle_user_active, "#f59e0b")
        button("Ver imagens", self.view_images, "#8b5cf6")
        button("Cadastrar rosto", self.enroll_selected, "#22c55e")

        self.refresh()

    def refresh(self) -> None:
        self.users = self.storage.list_users()
        self.listbox.delete(0, tk.END)
        for u in self.users:
            status = "ATIVO" if u.active == 1 else "INATIVO"
            self.listbox.insert(tk.END, f"[{u.id:03}] {u.name:<25}  {status}")

    def _selected_user(self) -> User | None:
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("Seleção", "Selecione um usuário.")
            return None
        return self.users[sel[0]]

    def create_user(self) -> None:
        name = simpledialog.askstring("Criar usuário", "Nome do usuário:")
        if not name:
            return
        try:
            self.storage.create_user(name.strip(), active=1)
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Erro", f"Falha ao criar usuário:\n{exc}")

    def edit_user(self) -> None:
        user = self._selected_user()
        if not user:
            return
        new_name = simpledialog.askstring("Editar usuário", "Novo nome:", initialvalue=user.name)
        if not new_name:
            return
        try:
            self.storage.update_user(user.id, new_name.strip())
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Erro", f"Falha ao editar usuário:\n{exc}")

    def toggle_user_active(self) -> None:
        user = self._selected_user()
        if not user:
            return
        target = 0 if user.active == 1 else 1
        try:
            self.storage.set_user_active(user.id, target)
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Erro", f"Falha ao atualizar status:\n{exc}")

    def enroll_selected(self) -> None:
        user = self._selected_user()
        if not user:
            return
        self.run_cmd(
            [sys.executable, str(APP_SCRIPT), "enroll", "--name", user.name],
            "Cadastro",
        )

    def view_images(self) -> None:
        user = self._selected_user()
        if not user:
            return
        paths = self.storage.get_user_samples(user.id)
        if not paths:
            messagebox.showinfo("Imagens", "Usuário sem imagens salvas.")
            return

        viewer = tk.Toplevel(self.win)
        viewer.title(f"Imagens de {user.name}")
        viewer.geometry("900x520")
        viewer.configure(bg="#0f172a")

        info = tk.Label(
            viewer,
            text=f"Total de imagens: {len(paths)} | Duplo clique para abrir",
            bg="#0f172a",
            fg="#e5e7eb",
            font=("Segoe UI", 10),
            anchor="w",
        )
        info.pack(fill="x", padx=14, pady=(14, 8))

        lb = tk.Listbox(
            viewer,
            font=("Consolas", 10),
            bg="#111827",
            fg="#e5e7eb",
            selectbackground="#2563eb",
            activestyle="none",
        )
        lb.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        for p in paths:
            lb.insert(tk.END, p)

        def open_selected(_event=None) -> None:
            sel = lb.curselection()
            if not sel:
                return
            path = lb.get(sel[0])
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                messagebox.showerror("Erro", f"Não foi possível abrir a imagem:\n{path}")
                return
            cv2.imshow(f"{user.name} - amostra", img)
            cv2.waitKey(1)

        lb.bind("<Double-Button-1>", open_selected)


def main() -> None:
    if not APP_SCRIPT.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {APP_SCRIPT}")
    root = tk.Tk()
    LauncherUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
