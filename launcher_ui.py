import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
import cv2
import threading
import time
import os
from pathlib import Path
import csv
import zipfile
import shutil
import re
from validate_docbr import CPF
import phonenumbers

from facial_auth_v2 import (
    Storage, FaceEngine, AuthController, DB_PATH, CASCADE_PATH, 
    MODEL_PATH, REQUIRED_SAMPLES, COLOR_PRIMARY, _open_camera
)
from secure_storage import secure_io

ctk.set_appearance_mode("Dark")

# Utilitários de Validação e Formatação
cpf_validator = CPF()

def format_cpf(cpf_str):
    cpf_str = re.sub(r'\D', '', cpf_str)
    if len(cpf_str) == 11:
        return f"{cpf_str[:3]}.{cpf_str[3:6]}.{cpf_str[6:9]}-{cpf_str[9:]}"
    return cpf_str

def format_phone(phone_str):
    phone_str = re.sub(r'\D', '', phone_str)
    if len(phone_str) == 11:
        return f"({phone_str[:2]}) {phone_str[2:7]}-{phone_str[7:]}"
    elif len(phone_str) == 10:
        return f"({phone_str[:2]}) {phone_str[2:6]}-{phone_str[6:]}"
    return phone_str

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AURA ACCESS CONTROL v3 - SECURE EDITION")
        self.geometry("1200x800")
        
        from facial_auth_v2 import load_env, logger
        self.cfg = load_env()
        self.storage = Storage(DB_PATH)
        
        def_user = self.cfg.get("DEFAULT_ADMIN_USER", "admin")
        def_pwd = self.cfg.get("DEFAULT_ADMIN_PASSWORD", "admin123")
        self.storage.ensure_default_admin(def_user, def_pwd)
        
        try:
            self.engine = FaceEngine(CASCADE_PATH, MODEL_PATH, self.storage)
            self.auth_ctrl = AuthController(self.engine, self.storage)
        except Exception as e:
            logger.critical(f"Falha ao carregar motor biométrico: {e}")
            messagebox.showerror("Erro Crítico", f"Falha ao carregar motor biométrico:\n{e}")
            self.destroy()
            return
        
        self.cap = None
        self.is_cam_on = False
        self.is_enrolling = False
        self.is_enrolling_dep = False
        self.logged_admin = None
        self.enroll_data = {"id": None, "name": "", "count": 0, "dir": None}
        self.enroll_dep_data = {}
        self.stop_event = threading.Event()
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self._init_sidebar()
        self._init_content_frames()
        self.select_frame("dash")
        
        self._start_camera_service()
        
    def _init_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#1a1a1a")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        lbl = ctk.CTkLabel(self.sidebar, text="AURA", font=ctk.CTkFont(size=28, weight="bold"), text_color="#40adff")
        lbl.pack(pady=(40, 40))
        
        self.btn_dash = self._nav_btn("DASHBOARD", "dash")
        self.btn_users = self._nav_btn("USUÁRIOS", "users")
        self.btn_logs = self._nav_btn("HISTÓRICO", "logs")
        
        # Oculta botões sensíveis até logar
        self.btn_users.pack_forget()
        self.btn_logs.pack_forget()
        
        self.admin_info = ctk.CTkLabel(self.sidebar, text="", font=("Segoe UI", 12, "bold"), text_color="#16a34a")
        self.admin_info.pack(side="bottom", pady=(0, 10))
        
        self.btn_login = ctk.CTkButton(self.sidebar, text="LOGIN ADM", height=40, fg_color="#333", command=self._handle_auth_btn)
        self.btn_login.pack(side="bottom", pady=20, padx=20)

    def _nav_btn(self, text, tag):
        btn = ctk.CTkButton(self.sidebar, text=text, height=50, corner_radius=0, fg_color="transparent", 
                            anchor="w", font=ctk.CTkFont(size=13, weight="bold"), border_spacing=20,
                            command=lambda: self.select_frame(tag))
        btn.pack(fill="x")
        return btn

    def _init_content_frames(self):
        # Dashboard
        self.f_dash = ctk.CTkFrame(self, fg_color="transparent")
        self.f_dash.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.f_dash, text="Monitoramento em Tempo Real", font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, padx=40, pady=(40, 0), sticky="w")
        
        self.cam_box = ctk.CTkFrame(self.f_dash, corner_radius=15, fg_color="#000", border_width=2, border_color="#333")
        self.cam_box.grid(row=1, column=0, padx=40, pady=30, sticky="nsew")
        self.v_label = ctk.CTkLabel(self.cam_box, text="INICIANDO SENSOR...", width=800, height=500)
        self.v_label.pack(padx=10, pady=10)
        
        ctrls = ctk.CTkFrame(self.f_dash, fg_color="transparent")
        ctrls.grid(row=2, column=0, pady=(0, 40))
        self.btn_new = ctk.CTkButton(ctrls, text="NOVO CADASTRO", width=250, height=55, fg_color="#16a34a", font=("Segoe UI", 14, "bold"), command=self._show_enroll)
        self.btn_new.pack(side="left", padx=10)

        # Users
        self.f_users = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self.f_users, text="Gerenciamento de Identidades", font=ctk.CTkFont(size=22, weight="bold")).pack(padx=40, pady=(40, 10), anchor="w")
        
        # Filtros de Busca de Usuario
        search_f = ctk.CTkFrame(self.f_users, fg_color="transparent")
        search_f.pack(fill="x", padx=40, pady=5)
        self.user_search_entry = ctk.CTkEntry(search_f, placeholder_text="Buscar por ID, Nome ou CPF...", width=400)
        self.user_search_entry.pack(side="left")
        ctk.CTkButton(search_f, text="Filtrar", width=100, command=self._load_users).pack(side="left", padx=10)
        
        u_tools = ctk.CTkFrame(self.f_users, fg_color="transparent")
        u_tools.pack(fill="x", padx=40, pady=10)
        ctk.CTkButton(u_tools, text="Atualizar Lista", width=100, command=self._load_users).pack(side="left", padx=5)
        ctk.CTkButton(u_tools, text="Exportar Zip", fg_color="#2563eb", width=100, command=self._export_users).pack(side="left", padx=5)
        ctk.CTkButton(u_tools, text="Importar Zip", fg_color="#059669", width=100, command=self._import_users).pack(side="left", padx=5)
        
        ctk.CTkButton(u_tools, text="Inativar/Ativar", fg_color="#d97706", width=100, command=self._toggle_status).pack(side="right", padx=5)
        ctk.CTkButton(u_tools, text="Deletar Usuário", fg_color="#991b1b", width=100, command=self._del_user).pack(side="right", padx=5)
        ctk.CTkButton(u_tools, text="Ver Fotos", fg_color="#40adff", width=100, command=self._show_gallery).pack(side="right", padx=5)
        ctk.CTkButton(u_tools, text="Editar Dados", fg_color="#8b5cf6", width=100, command=self._edit_user).pack(side="right", padx=5)

        self.tree_frame = ctk.CTkFrame(self.f_users, fg_color="#1a1a1a")
        self.tree_frame.pack(fill="both", expand=True, padx=40, pady=20)
        
        self.tree = ttk.Treeview(self.tree_frame, columns=("ID", "NOME", "CPF", "STATUS", "DATA"), show="headings")
        for c in ("ID", "NOME", "CPF", "STATUS", "DATA"):
            self.tree.heading(c, text=c)
            self.tree.column(c, anchor="center", width=120)
        self.tree.pack(fill="both", expand=True)

        # Logs
        self.f_logs = ctk.CTkFrame(self, fg_color="transparent")
        l_top = ctk.CTkFrame(self.f_logs, fg_color="transparent")
        l_top.pack(fill="x", padx=40, pady=(40, 10))
        ctk.CTkLabel(l_top, text="Registro de Eventos Criptografados", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkButton(l_top, text="Exportar CSV", fg_color="#16a34a", command=self._export_logs).pack(side="right")
        
        log_filter_f = ctk.CTkFrame(self.f_logs, fg_color="transparent")
        log_filter_f.pack(fill="x", padx=40, pady=5)
        
        self.log_type_filter = ctk.CTkComboBox(log_filter_f, values=["TODOS", "verify_granted", "verify_denied", "verify_unknown", "user_edited", "admin_login", "user_imported"], width=200)
        self.log_type_filter.set("TODOS")
        self.log_type_filter.pack(side="left", padx=5)
        
        self.log_date_filter = ctk.CTkEntry(log_filter_f, placeholder_text="Filtrar Data (Ex: YYYY-MM-DD)", width=200)
        self.log_date_filter.pack(side="left", padx=5)
        
        ctk.CTkButton(log_filter_f, text="Buscar Logs", width=100, command=self._load_logs).pack(side="left", padx=10)

        self.log_tree_frame = ctk.CTkFrame(self.f_logs, fg_color="#1a1a1a")
        self.log_tree_frame.pack(fill="both", expand=True, padx=40, pady=20)
        
        self.log_tree = ttk.Treeview(self.log_tree_frame, columns=("ID", "DATA", "EVENTO", "USUARIO", "CONFIANCA", "IMG_PATH", "USER_ID"), show="headings")
        for c in ("ID", "DATA", "EVENTO", "USUARIO", "CONFIANCA"):
            self.log_tree.heading(c, text=c)
        self.log_tree.heading("IMG_PATH", text="IMG_PATH")
        self.log_tree.heading("USER_ID", text="USER_ID")
        
        self.log_tree.column("ID", width=50, anchor="center")
        self.log_tree.column("DATA", width=150, anchor="center")
        self.log_tree.column("EVENTO", width=200, anchor="w")
        self.log_tree.column("USUARIO", width=200, anchor="w")
        self.log_tree.column("CONFIANCA", width=80, anchor="center")
        self.log_tree.column("IMG_PATH", width=0, stretch=False)
        self.log_tree.column("USER_ID", width=0, stretch=False)
        
        self.log_tree.pack(fill="both", expand=True)
        self.log_tree.bind("<Double-1>", self._on_log_double_click)

    def select_frame(self, tag):
        for b in (self.btn_dash, self.btn_users, self.btn_logs): b.configure(fg_color="transparent")
        self.f_dash.grid_forget(); self.f_users.grid_forget(); self.f_logs.grid_forget()
        if tag == "dash":
            self.f_dash.grid(row=0, column=1, sticky="nsew")
            self.btn_dash.configure(fg_color="#333")
        elif tag == "users":
            self.f_users.grid(row=0, column=1, sticky="nsew")
            self.btn_users.configure(fg_color="#333")
            self._load_users()
        elif tag == "logs":
            self.f_logs.grid(row=0, column=1, sticky="nsew")
            self.btn_logs.configure(fg_color="#333")
            self._load_logs()

    def toggle_cam(self):
        if not self.is_cam_on:
            if getattr(self, 'cam_thread', None) and self.cam_thread.is_alive():
                self.stop_event.set()
                self.cam_thread.join(timeout=1.0)
                
            self.stop_event.clear()
            self.cap = _open_camera(0)
            if not self.cap or not self.cap.isOpened():
                messagebox.showerror("Erro", "Câmera não encontrada ou ocupada.")
                return
            self.is_cam_on = True
            self.is_enrolling = False
            self.is_training = False
            self.btn_cam.configure(text="DESATIVAR SISTEMA", fg_color="#991b1b")
            self.cam_thread = threading.Thread(target=self._cam_loop, daemon=True)
            self.cam_thread.start()
        else:
            self._force_stop_cam()

    def _force_stop_cam(self):
        self.is_cam_on = False
        self.is_enrolling = False
        self.is_training = False
        self.stop_event.set()
        self.v_label.configure(image=None, text="CÂMERA OFFLINE")
        self.btn_cam.configure(text="ATIVAR SISTEMA", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])

    def _cam_loop(self):
        fail_count = 0
        while self.is_cam_on and not self.stop_event.is_set():
            ret, frame = self.cap.read()
            if not ret or frame is None:
                fail_count += 1
                if fail_count > 100:
                    break
                time.sleep(0.05)
                continue
            
            fail_count = 0
            frame = cv2.flip(frame, 1)
            
            try:
                if getattr(self, 'is_enrolling', False):
                    rect, face_gray = self.engine.detect_face(frame)
                    if rect is not None and face_gray is not None:
                        fname = self.enroll_data["dir"] / f"{time.time_ns()}.enc"
                        secure_io.save_encrypted_image(face_gray, str(fname), quality=88)
                        self.storage.add_sample(self.enroll_data['id'], str(fname))
                        self.enroll_data['count'] += 1
                        
                        if self.enroll_data['count'] >= REQUIRED_SAMPLES:
                            self.is_enrolling = False
                            self.is_training = True
                            
                            def _finish_training():
                                try:
                                    self.engine.train_from_db()
                                    self.after(0, lambda: setattr(self, 'is_training', False))
                                    self.after(0, lambda: messagebox.showinfo("Aura Access", "Cadastro Biométrico Seguro Concluído!"))
                                except Exception as e:
                                    print("Erro no treinamento:", e)
                                
                            threading.Thread(target=_finish_training, daemon=True).start()
                            
                    from facial_auth_v2 import VisualHelper, COLOR_PRIMARY
                    VisualHelper.draw_hud(frame, rect, "CADASTRANDO", f"Capture: {self.enroll_data['count']}/{REQUIRED_SAMPLES}", COLOR_PRIMARY)
                elif getattr(self, 'is_training', False):
                    from facial_auth_v2 import VisualHelper, COLOR_INFO
                    VisualHelper.draw_hud(frame, None, "SISTEMA TREINANDO", "Processando IA Segura...", COLOR_INFO)
                else:
                    frame = self.auth_ctrl.process(frame)
            except Exception as e:
                print(f"Erro no processamento do frame: {e}")
            
            try:
                frame_resized = cv2.resize(frame, (800, 500))
                img_pil = Image.fromarray(cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB))
                
                def update_ui_safe(image):
                    if self.is_cam_on:
                        ctk_img = ctk.CTkImage(image, size=(800, 500))
                        self.v_label.configure(image=ctk_img, text="")
                
                self.after(0, update_ui_safe, img_pil)
            except Exception:
                pass
            
            time.sleep(0.02)
            
        if self.cap:
            self.cap.release()
            self.cap = None
            
        if self.is_cam_on and not self.stop_event.is_set():
            self.is_cam_on = False
            self.is_enrolling = False
            self.is_training = False
            self.after(0, lambda: self.v_label.configure(image=None, text="CÂMERA OFFLINE (SINAL PERDIDO)"))
            self.after(0, lambda: self.btn_cam.configure(text="ATIVAR SISTEMA", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"]))

    def _handle_auth_btn(self):
        if self.logged_admin:
            self.logged_admin = None
            self.admin_info.configure(text="")
            self.btn_login.configure(text="LOGIN ADM", fg_color="#333")
            self.btn_users.pack_forget()
            self.btn_logs.pack_forget()
            self.select_frame("dash")
            self.storage.log_event("admin_logout", details="Logout Efetuado")
            messagebox.showinfo("Aura", "Logout realizado.")
        else:
            self._show_login()

    def _show_login(self):
        # Usando Janela Customizada para Login e Senha simultâneos e seguros
        dialog = ctk.CTkToplevel(self)
        dialog.title("Autenticação Admin")
        dialog.geometry("400x300")
        dialog.attributes("-topmost", True)
        
        ctk.CTkLabel(dialog, text="Acesso Restrito", font=("Segoe UI", 20, "bold")).pack(pady=20)
        
        u_entry = ctk.CTkEntry(dialog, width=300, placeholder_text="Login")
        u_entry.pack(pady=10)
        
        p_entry = ctk.CTkEntry(dialog, width=300, placeholder_text="Senha", show="*")
        p_entry.pack(pady=10)
        
        def _try_login():
            u = u_entry.get().strip()
            p = p_entry.get()
            if u and p and self.storage.verify_admin(u, p):
                self.logged_admin = u
                self.admin_info.configure(text=f"ADMIN: {u.upper()}")
                self.btn_login.configure(text="LOGOUT", fg_color="#991b1b")
                self.btn_users.pack(fill="x", after=self.btn_dash)
                self.btn_logs.pack(fill="x", after=self.btn_users)
                self.storage.log_event("admin_login", details=f"Admin {u} logou")
                dialog.destroy()
            else:
                messagebox.showerror("Erro", "Credenciais incorretas.")
                self.storage.log_event("admin_login_failed", details=f"Tentativa com user: {u}")
                
        ctk.CTkButton(dialog, text="ENTRAR", command=_try_login).pack(pady=20)

    def _export_users(self):
        if not self.logged_admin: return messagebox.showwarning("ADM", "Login ADM necessário.")
        save_path = filedialog.asksaveasfilename(defaultextension=".zip", filetypes=[("ZIP files", "*.zip")], title="Exportar Usuários Criptografados")
        if not save_path: return
        
        try:
            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                users = self.storage.list_users()
                csv_path = "temp_users_export.csv"
                with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(["ID", "Nome", "CPF", "Email", "Telefone", "Dependentes", "Status", "Criado_Em"])
                    for u in users:
                        writer.writerow([u.id, u.name, u.cpf, u.email, u.phone, u.dependents, u.active, u.created_at])
                
                zipf.write(csv_path, arcname="usuarios_db.csv")
                os.remove(csv_path)
                
                faces_dir = Path("data/faces")
                if faces_dir.exists():
                    for root, _, files in os.walk(faces_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, start="data")
                            zipf.write(file_path, arcname=arcname)
            
            self.storage.log_event("admin_export", details="Base de Usuários e Biometrias Exportada")
            messagebox.showinfo("Exportar", f"Banco exportado com segurança.")
        except Exception as e:
            messagebox.showerror("Erro na Exportação", str(e))

    def _export_logs(self):
        if not self.logged_admin: return messagebox.showwarning("ADM", "Login ADM necessário.")
        save_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")], title="Exportar Histórico")
        if not save_path: return
        
        try:
            logs = self.storage.get_logs(limit=10000)
            with open(save_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Data/Hora", "Evento", "Usuário", "Confiança"])
                for log in logs:
                    writer.writerow([log['time'], log['type'].upper(), log['user'], f"{log['conf']:.2f}"])
            self.storage.log_event("admin_export", details="Log de Eventos Exportado")
            messagebox.showinfo("Exportar", f"Histórico salvo com sucesso.")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _show_enroll(self):
        if not self.logged_admin: return messagebox.showwarning("ADM", "Login ADM necessário.")
        if self.is_enrolling: return messagebox.showwarning("Aviso", "Já existe um cadastro em andamento.")
        EnrollForm(self)

    def _edit_user(self):
        if not self.logged_admin: return messagebox.showwarning("ADM", "Login ADM necessário.")
        sel = self.tree.selection()
        if not sel: return messagebox.showwarning("Seleção", "Selecione um usuário para editar.")
        
        uid = self.tree.item(sel[0])['values'][0]
        users = self.storage.list_users()
        target = next((u for u in users if u.id == uid), None)
        
        if target:
            user_data = {
                "id": target.id, "name": target.name, "cpf": target.cpf, 
                "email": target.email, "phone": target.phone, "dependents": target.dependents
            }
            EnrollForm(self, user_data=user_data)

    def _import_users(self):
        if not self.logged_admin: return messagebox.showwarning("ADM", "Login ADM necessário.")
        
        d = ctk.CTkInputDialog(text="Confirme sua senha de ADMIN para autorizar a importação:", title="Segurança")
        pwd = d.get_input()
        if not pwd or not self.storage.verify_admin(self.logged_admin, pwd):
            return messagebox.showerror("Erro", "Senha incorreta ou cancelado.")
            
        zip_path = filedialog.askopenfilename(filetypes=[("ZIP files", "*.zip")], title="Importar Usuários")
        if not zip_path: return
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                for member in zipf.namelist():
                    if member.startswith("faces/") or member.startswith("faces\\"):
                        dest = os.path.join("data", member)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with open(dest, "wb") as f:
                            f.write(zipf.read(member))
                            
                if "usuarios_db.csv" in zipf.namelist():
                    with zipf.open("usuarios_db.csv") as csvfile:
                        reader = csv.DictReader(csvfile.read().decode('utf-8').splitlines())
                        for row in reader:
                            try:
                                self.storage.create_user(
                                    name=row.get('Nome', ''), cpf=row.get('CPF', ''),
                                    email=row.get('Email', ''), phone=row.get('Telefone', ''),
                                    dependents=row.get('Dependentes', '')
                                )
                                self.storage.log_event("user_imported", details=f"Usuario {row.get('Nome')}")
                            except Exception: pass
                                
            self.engine.train_from_db()
            self._load_users()
            self.storage.log_event("admin_import", details="Massa de usuários e biometrias importada")
            messagebox.showinfo("Sucesso", "Usuários importados com sucesso! Motor biométrico atualizado.")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao importar: {e}")

    def start_enroll_process(self, form_data):
        if form_data.get('id'): # MODO EDIÇÃO
            try:
                updates = {
                    "name": form_data['name'], "cpf": form_data['cpf'],
                    "email": form_data['email'], "phone": form_data['phone'],
                    "dependents": form_data['dependents']
                }
                self.storage.update_user(form_data['id'], updates)
                self.storage.log_event("admin_edited_user", details=f"Editado user ID {form_data['id']}")
                self._load_users()
                messagebox.showinfo("Sucesso", "Dados do usuário atualizados.")
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao editar: {e}")
            return
            
        if not self.is_cam_on:
            self.toggle_cam()
            if not self.is_cam_on:
                messagebox.showerror("Erro", "Falha ao iniciar câmera.")
                return

        def _start_enroll():
            try:
                u = self.storage.create_user(
                    name=form_data['name'], cpf=form_data['cpf'], 
                    email=form_data['email'], phone=form_data['phone'], 
                    dependents=form_data['dependents']
                )
                
                if form_data.get('is_admin'):
                    self.storage.create_admin(form_data['admin_login'], form_data['admin_pwd'])
                    self.storage.log_event("admin_created_admin", details=f"Novo admin: {form_data['admin_login']}")

                p = Path(f"data/faces/{u.id}")
                p.mkdir(parents=True, exist_ok=True)
                self.enroll_data = {"id": u.id, "name": form_data['name'], "count": 0, "dir": p}
                self.is_enrolling = True
                self.storage.log_event("admin_created_user", details=f"Novo usuario: {form_data['name']}")
            except Exception as e:
                messagebox.showerror("Erro", str(e))

        self.after(500, _start_enroll)

    def _load_users(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        for u in self.storage.list_users():
            status = "● ATIVO" if u.active else "○ INATIVO"
            self.tree.insert("", "end", values=(u.id, u.name, format_cpf(u.cpf), status, u.created_at))

    def _toggle_status(self):
        if not self.logged_admin: return
        sel = self.tree.selection()
        if sel:
            uid = self.tree.item(sel[0])['values'][0]
            curr = self.tree.item(sel[0])['values'][3]
            self.storage.set_user_active(uid, 0 if "●" in curr else 1)
            self.storage.log_event("admin_toggled_status", details=f"User ID: {uid}")
            self._load_users()

    def _del_user(self):
        if not self.logged_admin: return
        sel = self.tree.selection()
        if sel:
            uid = self.tree.item(sel[0])['values'][0]
            if messagebox.askyesno("Confirmar", "Deletar usuário e biometria definitivamente?"):
                self.storage.delete_user(uid)
                self.storage.log_event("admin_deleted_user", details=f"User ID: {uid} deletado")
                self._load_users()

    def _show_gallery(self):
        sel = self.tree.selection()
        if not sel: return messagebox.showwarning("Seleção", "Selecione um usuário.")
        uid = self.tree.item(sel[0])['values'][0]
        name = self.tree.item(sel[0])['values'][1]
        GalleryWindow(self, uid, name)

    def _load_logs(self):
        self.log_list.delete(0, "end")
        for l in self.storage.get_logs():
            self.log_list.insert("end", f"[{l['time']}] {l['type'].upper()} - {l['user']} (Conf: {l['conf']:.1f})")

class GalleryWindow(ctk.CTkToplevel):
    def __init__(self, parent, uid, name):
        super().__init__(parent)
        self.title(f"Amostras: {name}")
        self.geometry("800x600")
        self.uid = uid
        self.path = Path(f"data/faces/{uid}")
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(self, text=f"Banco de Fotos (Seguras): {name}", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, pady=20)
        
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        self._load_samples()

    def _load_samples(self):
        for widget in self.scroll.winfo_children(): widget.destroy()
        if not self.path.exists(): return
        
        files = list(self.path.glob("*.enc"))
        for i, f in enumerate(files):
            frame = ctk.CTkFrame(self.scroll)
            frame.pack(fill="x", pady=5, padx=5)
            
            ctk.CTkLabel(frame, text=f.name, font=("Consolas", 10)).pack(side="left", padx=10)
            ctk.CTkButton(frame, text="Ver", width=60, command=lambda p=f: self._view_img(p)).pack(side="right", padx=5)
            ctk.CTkButton(frame, text="Excluir", width=60, fg_color="#991b1b", command=lambda p=f: self._del_img(p)).pack(side="right", padx=5)

    def _view_img(self, path):
        img = secure_io.load_decrypted_image(str(path))
        if img is not None:
            cv2.imshow("Amostra Biometrica Segura", img)
            cv2.waitKey(1)
        else:
            messagebox.showerror("Erro", "Falha ao decriptar a imagem. A chave pode estar incorreta.")

    def _del_img(self, path):
        if messagebox.askyesno("Confirmar", "Excluir esta foto?"):
            os.remove(path)
            self._load_samples()

class EnrollForm(ctk.CTkToplevel):
    def __init__(self, parent, user_data=None):
        super().__init__(parent)
        self.parent = parent
        self.user_data = user_data
        self.is_edit = bool(user_data)
        
        self.title("Editar Usuário" if self.is_edit else "Novo Cadastro")
        self.geometry("600x850")
        self.attributes("-topmost", True)
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        ctk.CTkLabel(self.scroll_frame, text="Dados do Usuário", font=("Segoe UI", 20, "bold")).pack(pady=20)
        
        # Form Fields
        self.entries = {}
        fields = [
            ("name", "Nome Completo *"),
            ("cpf", "CPF * (Apenas números)"),
            ("email", "Email *"),
            ("phone", "Telefone Celular * (Ex: 11999999999)")
        ]
        
        for key, label in fields:
            ctk.CTkLabel(self.scroll_frame, text=label).pack(anchor="w", padx=40)
            e = ctk.CTkEntry(self.scroll_frame, width=450)
            e.pack(padx=40, pady=(0, 15))
            if self.is_edit and key in user_data:
                val = str(user_data[key])
                if key == 'cpf': val = format_cpf(val)
                elif key == 'phone': val = format_phone(val)
                e.insert(0, val)
            
            if key == 'cpf': e.bind('<KeyRelease>', lambda ev, entry=e: self._mask_cpf(ev, entry))
            if key == 'phone': e.bind('<KeyRelease>', lambda ev, entry=e: self._mask_phone(ev, entry))
            self.entries[key] = e
            
        # Dependentes
        self.has_dependents = ctk.BooleanVar(value=False)
        self.chk_deps = ctk.CTkCheckBox(self.scroll_frame, text="Adicionar Dependentes / Autorizados Extras", variable=self.has_dependents, command=self._toggle_deps)
        self.chk_deps.pack(anchor="w", padx=40, pady=10)
        
        self.deps_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        ctk.CTkLabel(self.deps_frame, text="Nomes e Parentesco (Um por linha):").pack(anchor="w")
        self.dep_text = ctk.CTkTextbox(self.deps_frame, width=450, height=100)
        self.dep_text.pack(pady=5)
        
        if self.is_edit and user_data.get('dependents'):
            self.has_dependents.set(True)
            self.dep_text.insert("0.0", user_data['dependents'])
            self._toggle_deps()
            
        # Admin Section
        self.is_admin_var = ctk.BooleanVar(value=False)
        self.admin_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        
        if self.is_edit:
            ctk.CTkLabel(self.admin_frame, text="Validação de Segurança (Admin Atual):", text_color="#d97706").pack(anchor="w", pady=(10,0))
            self.auth_pwd = ctk.CTkEntry(self.admin_frame, width=450, placeholder_text="Senha do admin logado", show="*")
            self.auth_pwd.pack(pady=5)
            self.admin_frame.pack(padx=40, fill="x", pady=20)
        else:
            self.chk_admin = ctk.CTkCheckBox(self.scroll_frame, text="Conceder Acesso ao Painel Admin", variable=self.is_admin_var, command=self._toggle_admin)
            self.chk_admin.pack(anchor="w", padx=40, pady=(20, 10))
            
            ctk.CTkLabel(self.admin_frame, text="Autorização (Senha do Admin Logado):").pack(anchor="w")
            self.auth_pwd = ctk.CTkEntry(self.admin_frame, width=450, placeholder_text="Sua senha", show="*")
            self.auth_pwd.pack(pady=5)
            
            ctk.CTkLabel(self.admin_frame, text="Credenciais do Novo Painel:").pack(anchor="w", pady=(15,0))
            self.new_admin_login = ctk.CTkEntry(self.admin_frame, width=450, placeholder_text="Novo Login de Acesso")
            self.new_admin_login.pack(pady=5)
            self.new_admin_pwd = ctk.CTkEntry(self.admin_frame, width=450, placeholder_text="Nova Senha", show="*")
            self.new_admin_pwd.pack(pady=5)
        
        btn_text = "SALVAR E ATUALIZAR" if self.is_edit else "VALIDAR E INICIAR CAPTURA FACIAL"
        self.btn_save = ctk.CTkButton(self.scroll_frame, text=btn_text, height=50, command=self._submit)
        self.btn_save.pack(pady=40)
        

    def _mask_cpf(self, event, entry):
        if event.keysym in ('BackSpace', 'Delete'): return
        val = re.sub(r'\D', '', entry.get())
        if len(val) > 11: val = val[:11]
        entry.delete(0, 'end')
        entry.insert(0, format_cpf(val))

    def _mask_phone(self, event, entry):
        if event.keysym in ('BackSpace', 'Delete'): return
        val = re.sub(r'\D', '', entry.get())
        if len(val) > 11: val = val[:11]
        entry.delete(0, 'end')
        entry.insert(0, format_phone(val))

    def _toggle_deps(self):
        if self.has_dependents.get():
            self.deps_frame.pack(padx=40, fill="x")
        else:
            self.deps_frame.pack_forget()

    def _toggle_admin(self):
        if self.is_admin_var.get():
            self.admin_frame.pack(padx=40, fill="x")
        else:
            self.admin_frame.pack_forget()

    def _validate_inputs(self, data):
        # CPF
        clean_cpf = re.sub(r'\D', '', data['cpf'])
        if not cpf_validator.validate(clean_cpf): return "CPF Inválido."
        data['cpf'] = clean_cpf
            
        # Email
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, data['email']): return "Email em formato inválido."
            
        # Telefone BR (mais flexível)
        clean_phone = re.sub(r'\D', '', data['phone'])
        if len(clean_phone) not in (10, 11): 
            return "Telefone celular inválido (deve ter 10 ou 11 dígitos)."
        data['phone'] = clean_phone
            
        return None

    def _submit(self):
        data = {k: v.get().strip() for k, v in self.entries.items()}
        
        if not data['name'] or not data['cpf'] or not data['email'] or not data['phone']:
            messagebox.showerror("Erro", "Preencha todos os campos obrigatórios (*).")
            return
            
        err = self._validate_inputs(data)
        if err:
            messagebox.showerror("Validação Recusada", err)
            return
            
        data['dependents'] = self.dep_text.get("0.0", "end").strip() if self.has_dependents.get() else ""
            
        # Validação de Segurança Admin Local apenas quando exigido
        if self.is_edit or self.is_admin_var.get():
            a_pwd = self.auth_pwd.get()
            if not a_pwd:
                messagebox.showerror("Segurança", "É necessária a sua senha de Admin para confirmar a operação.")
                return
                
            if not self.parent.storage.verify_admin(self.parent.logged_admin, a_pwd):
                messagebox.showerror("Segurança", "Senha do administrador atual incorreta. Ação bloqueada.")
                return

        if self.is_edit:
            data['id'] = self.user_data['id']
        else:
            data['is_admin'] = self.is_admin_var.get()
            if data['is_admin']:
                n_log = self.new_admin_login.get().strip()
                n_pwd = self.new_admin_pwd.get()
                if not n_log or not n_pwd:
                    messagebox.showerror("Erro", "Credenciais do novo admin são obrigatórias.")
                    return
                data['admin_login'] = n_log
                data['admin_pwd'] = n_pwd
            
        self.destroy()
        self.parent.start_enroll_process(data)

if __name__ == "__main__":
    App().mainloop()