"""
VibeScholar - Login & Register Page
"""
import httpx
from nicegui import ui

from app.core.logging import logger
from app.ui.styles import GLOBAL_CSS
from app.ui import state
from app.ui import api_client as api


def login_page() -> None:
    ui.add_head_html(GLOBAL_CSS)
    ui.add_head_html("""
    <style>
    .login-bg {
      min-height:100vh;
      background: radial-gradient(ellipse at 20% 50%, rgba(99,102,241,.15) 0%, transparent 60%),
                  radial-gradient(ellipse at 80% 20%, rgba(167,139,250,.1) 0%, transparent 50%),
                  #0f1117;
      display:flex; align-items:center; justify-content:center;
    }
    .login-card {
      background: rgba(26,29,39,.9);
      backdrop-filter: blur(24px);
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 20px;
      padding: 48px 40px;
      width: 420px;
      box-shadow: 0 24px 64px rgba(0,0,0,.5);
    }
    .logo-icon {
      width:52px; height:52px; border-radius:14px;
      background: linear-gradient(135deg,#818cf8,#6366f1);
      display:flex; align-items:center; justify-content:center;
      font-size:24px; margin:0 auto 16px;
    }
    .login-tabs {
      background:rgba(255,255,255,.05);
      border-radius:99px;
      padding:3px;
      margin-bottom:28px;
      color:#8b90a0;
    }
    .login-tabs .q-tab {
      border-radius:99px;
      min-height:36px;
      font-size:14px;
      font-weight:600;
      text-transform:none;
      color:#8b90a0;
    }
    .login-tabs .q-tab--active {
      background:#6366f1;
      color:#fff;
    }
    .login-tabs .q-tab__indicator { display:none; }
    .login-panels .q-panel { overflow:visible; }
    </style>
    """)

    with ui.element("div").classes("login-bg"):
        with ui.element("div").classes("login-card fade-in"):
            with ui.element("div").style("text-align:center; margin-bottom:8px"):
                ui.element("div").classes("logo-icon").style("margin:0 auto 12px").add_slot(
                    "default", "<span>📚</span>"
                )
                ui.label("VibeScholar").style(
                    "font-size:26px; font-weight:800; background:linear-gradient(135deg,#818cf8,#6366f1);"
                    "-webkit-background-clip:text; -webkit-text-fill-color:transparent;"
                    "background-clip:text; display:block;"
                )
                ui.label("Plataforma de Fundamentação Científica").style(
                    "font-size:13px; color:#8b90a0; margin-top:4px; display:block;"
                )

            ui.separator().style("margin:24px 0; border-color:rgba(255,255,255,.06);")

            with ui.tabs().classes("login-tabs").style("width:100%;") as tabs:
                tab_login = ui.tab("Login")
                tab_register = ui.tab("Cadastrar")

            with ui.tab_panels(tabs, value=tab_login).classes("login-panels").style(
                "width:100%; background:transparent; color:#f0f2ff;"
            ):
                with ui.tab_panel(tab_login).style("padding:0;"):
                    with ui.column().style("width:100%; gap:14px;"):
                        inp_username = ui.input("Usuário").style("width:100%;")
                        inp_password = ui.input("Senha", password=True, password_toggle_button=True).style("width:100%;")
                        lbl_error = ui.label("").style("color:#ef4444; font-size:13px; min-height:18px;")

                        async def do_login():
                            lbl_error.set_text("")
                            username = (inp_username.value or "").strip()
                            password = inp_password.value or ""
                            if not username or not password:
                                lbl_error.set_text("Preencha usuário e senha.")
                                return
                            try:
                                user_data, cookies = await api.api_login(username, password)
                                state.set_user(user_data)
                                state.set_cookies(cookies)
                                ui.notify("Login realizado com sucesso.", type="positive")
                                ui.navigate.to("/dashboard")
                            except httpx.HTTPStatusError as exc:
                                logger.exception("Login failed with HTTP status error")
                                if exc.response.status_code == 401:
                                    lbl_error.set_text("Credenciais inválidas.")
                                else:
                                    lbl_error.set_text(f"Erro no login: {exc.response.status_code}")
                            except Exception:
                                logger.exception("Unexpected login failure")
                                lbl_error.set_text("Não foi possível entrar. Tente novamente.")

                        ui.button("Entrar na plataforma", on_click=do_login).classes("vs-btn").style(
                            "width:100%; margin-top:4px;"
                        )

                with ui.tab_panel(tab_register).style("padding:0;"):
                    with ui.column().style("width:100%; gap:14px;"):
                        inp_reg_user = ui.input("Nome de usuário").style("width:100%;")
                        inp_reg_email = ui.input("E-mail (opcional)").style("width:100%;")
                        inp_reg_pass = ui.input("Senha", password=True, password_toggle_button=True).style("width:100%;")
                        lbl_reg_err = ui.label("").style("color:#ef4444; font-size:13px; min-height:18px;")
                        lbl_reg_ok = ui.label("").style("color:#22c55e; font-size:13px; min-height:18px;")

                        async def do_register():
                            lbl_reg_err.set_text("")
                            lbl_reg_ok.set_text("")
                            username = (inp_reg_user.value or "").strip()
                            email = (inp_reg_email.value or "").strip() or None
                            password = inp_reg_pass.value or ""
                            if not username or not password:
                                lbl_reg_err.set_text("Usuário e senha são obrigatórios.")
                                return
                            try:
                                await api.api_register(username, password, email)
                                lbl_reg_ok.set_text("Conta criada. Faça login.")
                                ui.notify("Conta criada com sucesso.", type="positive")
                                inp_reg_user.value = ""
                                inp_reg_email.value = ""
                                inp_reg_pass.value = ""
                                tabs.value = tab_login
                            except httpx.HTTPStatusError as exc:
                                logger.exception("Registration failed with HTTP status error")
                                if exc.response.status_code == 400:
                                    lbl_reg_err.set_text("Usuário já existe ou dados inválidos.")
                                else:
                                    lbl_reg_err.set_text(f"Erro no cadastro: {exc.response.status_code}")
                            except Exception:
                                logger.exception("Unexpected registration failure")
                                lbl_reg_err.set_text("Não foi possível criar a conta. Tente novamente.")

                        ui.button("Criar conta", on_click=do_register).classes("vs-btn").style("width:100%;")
                        ui.button("Voltar ao login", on_click=lambda: setattr(tabs, "value", tab_login)).classes(
                            "vs-btn-ghost"
                        ).style("width:100%;")

            ui.separator().style("margin:24px 0; border-color:rgba(255,255,255,.06);")
            ui.label("© 2025 VibeScholar · Todos os direitos reservados").style(
                "font-size:11px; color:#8b90a0; text-align:center; width:100%; display:block;"
            )
