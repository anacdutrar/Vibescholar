"""
VibeScholar – Login & Register Page
"""
from nicegui import ui
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
    .tab-pill { display:flex; background:rgba(255,255,255,.05); border-radius:99px; padding:3px; margin-bottom:28px; }
    .tab-pill-item {
      flex:1; text-align:center; padding:8px 0;
      border-radius:99px; font-size:14px; font-weight:600;
      cursor:pointer; transition: all .2s; color:#8b90a0;
    }
    .tab-pill-item.active { background:#6366f1; color:#fff; }
    </style>
    """)

    with ui.element("div").classes("login-bg"):
        with ui.element("div").classes("login-card fade-in"):
            # Logo
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

            # Tabs state
            show_register = {"value": False}

            # Tab switcher
            with ui.row().style(
                "background:rgba(255,255,255,.05); border-radius:99px; padding:3px; margin-bottom:28px; gap:0;"
            ):
                btn_login = ui.button("Entrar").style(
                    "flex:1; border-radius:99px; font-weight:600; background:#6366f1; color:#fff; border:none; padding:8px 0;"
                )
                btn_register = ui.button("Cadastrar").style(
                    "flex:1; border-radius:99px; font-weight:600; background:transparent; color:#8b90a0; border:none; padding:8px 0;"
                )

            # ── Login form ──────────────────────────────────
            login_form = ui.column().style("width:100%; gap:14px;")
            with login_form:
                inp_username = ui.input("Usuário").style("width:100%;")
                inp_password = ui.input("Senha", password=True, password_toggle_button=True).style("width:100%;")
                lbl_error = ui.label("").style("color:#ef4444; font-size:13px; min-height:18px;")

                def do_login():
                    lbl_error.set_text("")
                    u = inp_username.value.strip()
                    p = inp_password.value
                    if not u or not p:
                        lbl_error.set_text("Preencha usuário e senha.")
                        return
                    try:
                        user_data, cookies = api.api_login(u, p)
                        state.set_user(user_data)
                        state.set_cookies(cookies)
                        ui.navigate.to("/dashboard")
                    except Exception as e:
                        detail = str(e)
                        lbl_error.set_text("Credenciais inválidas." if "401" in detail else f"Erro: {detail[:80]}")

                ui.button("Entrar na Plataforma", on_click=do_login).classes("vs-btn").style("width:100%; margin-top:4px;")

            # ── Register form ──────────────────────────────
            reg_form = ui.column().style("width:100%; gap:14px;").bind_visibility_from(
                show_register, "value"
            )
            reg_form.set_visibility(False)

            with reg_form:
                inp_reg_user = ui.input("Nome de usuário").style("width:100%;")
                inp_reg_email = ui.input("E-mail (opcional)").style("width:100%;")
                inp_reg_pass = ui.input("Senha", password=True, password_toggle_button=True).style("width:100%;")
                lbl_reg_err = ui.label("").style("color:#ef4444; font-size:13px; min-height:18px;")
                lbl_reg_ok = ui.label("").style("color:#22c55e; font-size:13px; min-height:18px;")

                def do_register():
                    lbl_reg_err.set_text("")
                    lbl_reg_ok.set_text("")
                    u = inp_reg_user.value.strip()
                    em = inp_reg_email.value.strip() or None
                    p = inp_reg_pass.value
                    if not u or not p:
                        lbl_reg_err.set_text("Usuário e senha são obrigatórios.")
                        return
                    try:
                        api.api_register(u, p, em)
                        lbl_reg_ok.set_text("Conta criada! Faça login.")
                        inp_reg_user.value = ""
                        inp_reg_email.value = ""
                        inp_reg_pass.value = ""
                    except Exception as e:
                        detail = str(e)
                        lbl_reg_err.set_text("Usuário já existe." if "400" in detail else f"Erro: {detail[:80]}")

                ui.button("Criar Conta", on_click=do_register).classes("vs-btn").style("width:100%;")

            # Tab switching callbacks
            def switch_to_login():
                login_form.set_visibility(True)
                reg_form.set_visibility(False)
                btn_login.style("background:#6366f1; color:#fff;")
                btn_register.style("background:transparent; color:#8b90a0;")

            def switch_to_register():
                login_form.set_visibility(False)
                reg_form.set_visibility(True)
                btn_register.style("background:#6366f1; color:#fff;")
                btn_login.style("background:transparent; color:#8b90a0;")

            btn_login.on_click(switch_to_login)
            btn_register.on_click(switch_to_register)

            # Footer
            ui.separator().style("margin:24px 0; border-color:rgba(255,255,255,.06);")
            ui.label("© 2025 VibeScholar · Todos os direitos reservados").style(
                "font-size:11px; color:#8b90a0; text-align:center; width:100%; display:block;"
            )
