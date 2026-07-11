"""
VibeScholar – Global CSS Styles
================================
Injected once on every page via ui.add_head_html().
"""

GLOBAL_CSS = """
<style>
/* ── Google Font ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Design tokens ── */
:root {
  --bg-base:      #0f1117;
  --bg-card:      #1a1d27;
  --bg-card2:     #212435;
  --bg-sidebar:   #161926;
  --accent:       #6366f1;
  --accent-soft:  #4f52c9;
  --accent-glow:  rgba(99,102,241,.25);
  --success:      #22c55e;
  --warning:      #f59e0b;
  --danger:       #ef4444;
  --text-primary: #f0f2ff;
  --text-muted:   #8b90a0;
  --border:       rgba(255,255,255,.07);
  --radius:       12px;
  --radius-sm:    8px;
  --transition:   all .2s cubic-bezier(.4,0,.2,1);
}

/* ── Base ── */
body, .nicegui-content { background: var(--bg-base) !important; color: var(--text-primary) !important; font-family: 'Inter', sans-serif !important; }

/* ── Scrollbars ── */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,.15); border-radius:99px; }

/* ── Cards ── */
.vs-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  transition: var(--transition);
}
.vs-card:hover { border-color: rgba(99,102,241,.3); }

/* ── Sidebar ── */
.vs-sidebar {
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  min-height: 100vh;
  width: 240px;
  flex-shrink: 0;
}
.vs-sidebar-item {
  display:flex; align-items:center; gap:10px;
  padding: 10px 16px; border-radius: var(--radius-sm);
  cursor:pointer; color: var(--text-muted);
  font-size:14px; font-weight:500;
  transition: var(--transition);
}
.vs-sidebar-item:hover, .vs-sidebar-item.active {
  background: rgba(99,102,241,.15);
  color: var(--text-primary);
}
.vs-sidebar-item.active { color: var(--accent); }

/* ── Header ── */
.vs-header {
  background: rgba(15,17,23,.85);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  height: 56px;
  display:flex; align-items:center; gap:16px;
  padding: 0 24px;
  position: sticky; top:0; z-index:100;
}

/* ── Buttons ── */
.vs-btn {
  background: var(--accent) !important;
  color: #fff !important;
  border-radius: var(--radius-sm) !important;
  font-weight: 600 !important;
  font-size: 14px !important;
  padding: 8px 20px !important;
  border: none !important;
  cursor:pointer;
  transition: var(--transition);
}
.vs-btn:hover { background: var(--accent-soft) !important; box-shadow: 0 0 24px var(--accent-glow) !important; }
.vs-btn-ghost {
  background: transparent !important;
  border: 1px solid var(--border) !important;
  color: var(--text-muted) !important;
  border-radius: var(--radius-sm) !important;
  font-weight: 500 !important;
  font-size: 14px !important;
  padding: 8px 20px !important;
  cursor:pointer;
  transition: var(--transition);
}
.vs-btn-ghost:hover { border-color: var(--accent) !important; color: var(--accent) !important; }
.vs-btn-danger {
  background: var(--danger) !important;
  color: #fff !important;
  border-radius: var(--radius-sm) !important;
  font-weight: 600 !important;
  font-size: 14px !important;
  padding: 8px 20px !important;
  border: none !important;
  cursor:pointer;
}

/* ── Inputs ── */
.q-field__control { background: var(--bg-card2) !important; border-radius: var(--radius-sm) !important; }
.q-field__native, .q-field__input { color: var(--text-primary) !important; }
.q-field--outlined .q-field__control:before { border-color: var(--border) !important; }
.q-field--outlined.q-field--focused .q-field__control:before { border-color: var(--accent) !important; }
.q-field__label { color: var(--text-muted) !important; }
.q-menu,
.q-select__dialog,
.q-virtual-scroll__content {
  background: var(--bg-card2) !important;
  color: var(--text-primary) !important;
}
.q-item,
.q-item__label {
  color: var(--text-primary) !important;
}
.q-item:hover,
.q-item.q-manual-focusable--focused,
.q-item--active {
  background: rgba(99,102,241,.18) !important;
  color: var(--text-primary) !important;
}
.q-field--focused .q-field__native,
.q-field--focused .q-field__input {
  color: var(--text-primary) !important;
}

/* ── Score Badge ── */
.vs-score-ring {
  width: 80px; height: 80px;
  border-radius: 50%;
  display:flex; align-items:center; justify-content:center;
  font-size: 1.4rem; font-weight:700;
  border: 3px solid var(--accent);
  background: rgba(99,102,241,.1);
  color: var(--text-primary);
}

/* ── Sentence status pills ── */
.pill { display:inline-block; padding:2px 10px; border-radius:99px; font-size:11px; font-weight:600; }
.pill-supported  { background:#16a34a22; color:#22c55e; border:1px solid #22c55e55; }
.pill-unverified { background:#78350f22; color:#f59e0b; border:1px solid #f59e0b55; }
.pill-outdated   { background:#7f1d1d22; color:#ef4444; border:1px solid #ef4444aa; }

/* ── Evidence card ── */
.ev-card {
  background: var(--bg-card2);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
  border: 1px solid var(--border);
  margin-bottom: 10px;
  transition: var(--transition);
}
.ev-card:hover { border-color: var(--accent); }

/* ── Quill editor wrapper ── */
#quill-editor-container {
  background: var(--bg-card);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  min-height: 480px;
}
#quill-editor-container .ql-toolbar {
  border-bottom: 1px solid var(--border) !important;
  background: var(--bg-card2) !important;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0 !important;
  border-top: none !important; border-left: none !important; border-right: none !important;
}
#quill-editor-container .ql-container {
  font-family: 'Inter', sans-serif !important;
  font-size: 15px !important;
  color: var(--text-primary) !important;
  border: none !important;
  min-height: 420px;
}
#quill-editor-container .ql-editor { min-height: 420px; padding: 20px 24px; }
.ql-toolbar .ql-stroke { stroke: var(--text-muted) !important; }
.ql-toolbar .ql-fill { fill: var(--text-muted) !important; }
.ql-toolbar button:hover .ql-stroke, .ql-toolbar .ql-active .ql-stroke { stroke: var(--accent) !important; }
.ql-toolbar button:hover .ql-fill, .ql-toolbar .ql-active .ql-fill { fill: var(--accent) !important; }
.ql-picker-label { color: var(--text-muted) !important; }

/* ── Chips / tags ── */
.vs-chip {
  display:inline-flex; align-items:center; gap:4px;
  background: rgba(99,102,241,.15); color: var(--accent);
  padding:3px 10px; border-radius:99px; font-size:12px; font-weight:600;
}

/* ── Table ── */
.q-table { background: var(--bg-card) !important; }
.q-table th { color: var(--text-muted) !important; font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.5px; }
.q-table td { color: var(--text-primary) !important; border-bottom: 1px solid var(--border) !important; }
.q-table tbody tr:hover td { background: rgba(99,102,241,.07) !important; }

/* ── Dialog ── */
.q-dialog__inner > div { background: var(--bg-card) !important; border-radius: var(--radius) !important; border: 1px solid var(--border) !important; }

/* ── Separator ── */
.vs-sep { border: none; border-top: 1px solid var(--border); margin: 16px 0; }

/* ── Misc ── */
.text-accent { color: var(--accent) !important; }
.text-muted  { color: var(--text-muted) !important; }
.text-success { color: var(--success) !important; }
.text-danger  { color: var(--danger) !important; }
.text-warning { color: var(--warning) !important; }
.bg-card  { background: var(--bg-card) !important; }
.bg-card2 { background: var(--bg-card2) !important; }

/* upload */
.vs-upload-dark,
.vs-upload-dark .q-uploader,
.vs-upload-dark .q-uploader__header,
.vs-upload-dark .q-uploader__list {
  background: var(--bg-card2) !important;
  color: var(--text-primary) !important;
}
.vs-upload-dark .q-uploader {
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
  box-shadow: none !important;
}
.vs-upload-dark .q-uploader__header {
  border-bottom: 1px solid var(--border) !important;
}
.vs-upload-dark .q-uploader__title,
.vs-upload-dark .q-uploader__subtitle,
.vs-upload-dark .q-uploader__file,
.vs-upload-dark .q-btn,
.vs-upload-dark .q-icon {
  color: var(--text-primary) !important;
}
.vs-upload-dark .q-uploader__subtitle {
  color: var(--text-muted) !important;
}

/* gradient text */
.grad-text {
  background: linear-gradient(135deg, #818cf8, #6366f1, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* animated pulse dot */
.pulse-dot {
  width:8px; height:8px; border-radius:50%;
  background: var(--success);
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(34,197,94,.4); }
  50%      { box-shadow: 0 0 0 6px rgba(34,197,94,0); }
}

/* fade-in */
.fade-in { animation: fadeIn .35s ease; }
@keyframes fadeIn { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
</style>
"""
