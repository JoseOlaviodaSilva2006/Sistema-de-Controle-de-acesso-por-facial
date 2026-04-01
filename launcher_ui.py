import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import cv2
import threading
import time
import os
from pathlib import Path
from facial_auth_v2 import (
    Storage, FaceEngine, AuthController, DB_PATH, CASCADE_PATH, 
    MODEL_PATH, REQUIRED_SAMPLES, COLOR_PRIMARY, _open_camera
)

ctk.set_appearance_mode("Dark")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AURA ACCESS CONTROL v3")
        self.geometry("1200x800")
        
        # Backend e Configuração
        from facial_auth_v2 import load_env, logger
        self.cfg = load_env()
        self.storage = Storage(DB_PATH)
        
        # Garante admin padrão do .env
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
        
        # State Control
        self.cap = None
        self.is_cam_on = False
        self.is_enrolling = False
        self.logged_admin = None
        self.enroll_data = {"id": None, "name": "", "count": 0, "dir": None}
        self.stop_event = threading.Event()
        
        # Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self._init_sidebar()
        self._init_content_frames()
        self.select_frame("dash")
        
    def _init_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#1a1a1a")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        lbl = ctk.CTkLabel(self.sidebar, text="AURA", font=ctk.CTkFont(size=28, weight="bold"), text_color="#40adff")
        lbl.pack(pady=(40, 40))
        
        self.btn_dash = self._nav_btn("DASHBOARD", "dash")
        self.btn_users = self._nav_btn("USUÁRIOS", "users")
        self.btn_logs = self._nav_btn("HISTÓRICO", "logs")
        
        self.admin_info = ctk.CTkLabel(self.sidebar, text="Status: Guest", font=("Segoe UI", 11), text_color="gray")
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
        self.v_label = ctk.CTkLabel(self.cam_box, text="CÂMERA OFFLINE", width=800, height=500)
        self.v_label.pack(padx=10, pady=10)
        
        ctrls = ctk.CTkFrame(self.f_dash, fg_color="transparent")
        ctrls.grid(row=2, column=0, pady=(0, 40))
        self.btn_cam = ctk.CTkButton(ctrls, text="ATIVAR SISTEMA", width=250, height=55, font=("Segoe UI", 14, "bold"), command=self.toggle_cam)
        self.btn_cam.pack(side="left", padx=10)
        self.btn_new = ctk.CTkButton(ctrls, text="NOVO CADASTRO", width=250, height=55, fg_color="#16a34a", font=("Segoe UI", 14, "bold"), command=self._show_enroll)
        self.btn_new.pack(side="left", padx=10)

        # Users
        self.f_users = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self.f_users, text="Gerenciamento de Identidades", font=ctk.CTkFont(size=22, weight="bold")).pack(padx=40, pady=(40, 20), anchor="w")
        
        u_tools = ctk.CTkFrame(self.f_users, fg_color="transparent")
        u_tools.pack(fill="x", padx=40, pady=10)
        ctk.CTkButton(u_tools, text="Atualizar Lista", width=120, command=self._load_users).pack(side="left", padx=5)
        ctk.CTkButton(u_tools, text="Inativar/Ativar", fg_color="#d97706", command=self._toggle_status).pack(side="right", padx=5)
        ctk.CTkButton(u_tools, text="Deletar Usuário", fg_color="#991b1b", command=self._del_user).pack(side="right", padx=5)
        ctk.CTkButton(u_tools, text="Ver Fotos", fg_color="#40adff", command=self._show_gallery).pack(side="right", padx=5)

        self.tree_frame = ctk.CTkFrame(self.f_users, fg_color="#1a1a1a")
        self.tree_frame.pack(fill="both", expand=True, padx=40, pady=20)
        
        self.tree = ttk.Treeview(self.tree_frame, columns=("ID", "NOME", "STATUS", "DATA"), show="headings")
        for c in ("ID", "NOME", "STATUS", "DATA"):
            self.tree.heading(c, text=c)
            self.tree.column(c, anchor="center", width=150)
        self.tree.pack(fill="both", expand=True)

        # Logs
        self.f_logs = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self.f_logs, text="Registro de Eventos", font=ctk.CTkFont(size=22, weight="bold")).pack(padx=40, pady=(40, 20), anchor="w")
        self.log_list = tk.Listbox(self.f_logs, bg="#111", fg="#bbb", font=("Consolas", 11), border=0)
        self.log_list.pack(fill="both", expand=True, padx=40, pady=20)

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
            # Garante que qualquer thread antiga morreu antes de abrir de novo
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
        
        # O _cam_loop fará o release do cap quando o while terminar para evitar conflito
        self.v_label.configure(image=None, text="CÂMERA OFFLINE")
        self.btn_cam.configure(text="ATIVAR SISTEMA", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])

    def _cam_loop(self):
        fail_count = 0
        while self.is_cam_on and not self.stop_event.is_set():
            ret, frame = self.cap.read()
            if not ret or frame is None:
                fail_count += 1
                if fail_count > 100:  # 5 segundos de tolerância
                    print("Falha ao obter imagem do sensor. Desligando câmera.")
                    break
                time.sleep(0.05)
                continue
            
            fail_count = 0
            frame = cv2.flip(frame, 1)
            
            try:
                if getattr(self, 'is_enrolling', False):
                    rect, face_gray = self.engine.detect_face(frame)
                    if rect is not None and face_gray is not None:
                        fname = self.enroll_data["dir"] / f"{time.time_ns()}.jpg"
                        cv2.imwrite(str(fname), face_gray, [cv2.IMWRITE_JPEG_QUALITY, 88])
                        self.storage.add_sample(self.enroll_data['id'], str(fname))
                        self.enroll_data['count'] += 1
                        
                        if self.enroll_data['count'] >= REQUIRED_SAMPLES:
                            self.is_enrolling = False
                            self.is_training = True
                            
                            def _finish_training():
                                try:
                                    self.engine.train_from_db()
                                    self.after(0, lambda: setattr(self, 'is_training', False))
                                    self.after(0, lambda: self.admin_info.configure(text="Cadastro e Treinamento Concluídos!", text_color="#16a34a"))
                                except Exception as e:
                                    print("Erro no treinamento:", e)
                                
                            threading.Thread(target=_finish_training, daemon=True).start()
                            
                    from facial_auth_v2 import VisualHelper, COLOR_PRIMARY
                    VisualHelper.draw_hud(frame, rect, "CADASTRANDO", f"Capture: {self.enroll_data['count']}/{REQUIRED_SAMPLES}", COLOR_PRIMARY)
                elif getattr(self, 'is_training', False):
                    from facial_auth_v2 import VisualHelper, COLOR_INFO
                    VisualHelper.draw_hud(frame, None, "SISTEMA TREINANDO", "Processando novo modelo de IA...", COLOR_INFO)
                else:
                    frame = self.auth_ctrl.process(frame)
            except Exception as e:
                print(f"Erro no processamento do frame: {e}")
            
            try:
                # Otimização e Segurança de Thread:
                frame_resized = cv2.resize(frame, (800, 500))
                img_pil = Image.fromarray(cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB))
                
                # CRÍTICO: CTkImage DEVE ser instanciado na Thread Principal, senão causa Deadlock no Tkinter!
                def update_ui_safe(image):
                    if self.is_cam_on:
                        ctk_img = ctk.CTkImage(image, size=(800, 500))
                        self.v_label.configure(image=ctk_img, text="")
                
                self.after(0, update_ui_safe, img_pil)
            except Exception as e:
                print(f"Erro na Thread de UI: {e}")
                pass
            
            # Limita a taxa de atualização (cerca de 50fps) para não estrangular o Tkinter
            time.sleep(0.02)
            
        # Quando o loop encerra (por stop_event ou erro), garantimos que solta a câmera
        if self.cap:
            self.cap.release()
            self.cap = None
            
        # Garante que a UI reflete a queda da câmera se foi um erro interno e não um clique de usuário
        if self.is_cam_on and not self.stop_event.is_set():
            self.is_cam_on = False
            self.is_enrolling = False
            self.is_training = False
            self.after(0, lambda: self.v_label.configure(image=None, text="CÂMERA OFFLINE (SINAL PERDIDO)"))
            self.after(0, lambda: self.btn_cam.configure(text="ATIVAR SISTEMA", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"]))

    def _handle_auth_btn(self):
        if self.logged_admin:
            self.logged_admin = None
            self.admin_info.configure(text="Status: Guest", text_color="gray")
            self.btn_login.configure(text="LOGIN ADM", fg_color="#333")
            messagebox.showinfo("Aura", "Logout realizado.")
        else:
            self._show_login()

    def _show_login(self):
        d = ctk.CTkInputDialog(text="Senha de Administrador:", title="Aura Security")
        pwd = d.get_input()
        if pwd and self.storage.verify_admin("admin", pwd):
            self.logged_admin = "admin"
            self.admin_info.configure(text="Status: Admin Autenticado", text_color="#16a34a")
            self.btn_login.configure(text="LOGOUT", fg_color="#991b1b")
        elif pwd: messagebox.showerror("Erro", "Senha incorreta.")

    def _show_enroll(self):
        if not self.logged_admin: return messagebox.showwarning("ADM", "Login ADM necessário.")
        
        if self.is_enrolling:
            messagebox.showwarning("Aviso", "Já existe um cadastro em andamento.")
            return

        # Pede o nome ANTES de iniciar a câmera para evitar que o diálogo bloqueie a Thread Principal 
        # e cause um Deadlock na atualização de frames da câmera.
        name = ctk.CTkInputDialog(text="Nome do Usuário:", title="Cadastro").get_input()
        if not name: return

        if not self.is_cam_on:
            self.toggle_cam()
            if not self.is_cam_on:
                return # Falhou ao ligar a câmera

        def _start_enroll():
            try:
                u = self.storage.create_user(name)
                p = Path(f"data/faces/{u.id}")
                p.mkdir(parents=True, exist_ok=True)
                self.enroll_data = {"id": u.id, "name": name, "count": 0, "dir": p}
                self.is_enrolling = True
            except ValueError as e:
                messagebox.showerror("Erro", str(e))

        self.after(500, _start_enroll)

    def _load_users(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        for u in self.storage.list_users():
            status = "● ATIVO" if u.active else "○ INATIVO"
            self.tree.insert("", "end", values=(u.id, u.name, status, u.created_at))

    def _toggle_status(self):
        if not self.logged_admin: return
        sel = self.tree.selection()
        if sel:
            uid = self.tree.item(sel[0])['values'][0]
            curr = self.tree.item(sel[0])['values'][2]
            self.storage.set_user_active(uid, 0 if "●" in curr else 1)
            self._load_users()

    def _del_user(self):
        if not self.logged_admin: return
        sel = self.tree.selection()
        if sel:
            uid = self.tree.item(sel[0])['values'][0]
            if messagebox.askyesno("Confirmar", "Deletar usuário e biometria?"):
                self.storage.delete_user(uid)
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
        
        ctk.CTkLabel(self, text=f"Banco de Fotos: {name}", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, pady=20)
        
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        self._load_samples()

    def _load_samples(self):
        for widget in self.scroll.winfo_children(): widget.destroy()
        if not self.path.exists(): return
        
        files = list(self.path.glob("*.jpg"))
        for i, f in enumerate(files):
            frame = ctk.CTkFrame(self.scroll)
            frame.pack(fill="x", pady=5, padx=5)
            
            ctk.CTkLabel(frame, text=f.name, font=("Consolas", 10)).pack(side="left", padx=10)
            ctk.CTkButton(frame, text="Ver", width=60, command=lambda p=f: self._view_img(p)).pack(side="right", padx=5)
            ctk.CTkButton(frame, text="Excluir", width=60, fg_color="#991b1b", command=lambda p=f: self._del_img(p)).pack(side="right", padx=5)

    def _view_img(self, path):
        img = cv2.imread(str(path))
        cv2.imshow("Amostra Biometrica", img)
        cv2.waitKey(1)

    def _del_img(self, path):
        if messagebox.askyesno("Confirmar", "Excluir esta foto?"):
            os.remove(path)
            self._load_samples()

if __name__ == "__main__":
    App().mainloop()
