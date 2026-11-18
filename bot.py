"""Dallanan senaryo (interaktif hikaye) Telegram botu.

Çalıştırma:
    pip install -r requirements.txt
    export BOT_TOKEN="BotFather'dan aldığın token"
    python bot.py
"""
import json
import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("senaryo-bot")

BASE = Path(__file__).parent
SCEN_DIR = BASE / "scenarios"
STATE_FILE = BASE / "state.json"

SCENARIOS: dict[str, dict] = {}
STATE: dict[str, dict] = {}


# ---------- Yükleme / kaydetme ----------
def load_scenarios() -> None:
    SCENARIOS.clear()
    for f in sorted(SCEN_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            validate(f.stem, data)
            SCENARIOS[f.stem] = data
        except Exception as e:  # bozuk dosya botu düşürmesin
            log.error("Senaryo yüklenemedi (%s): %s", f.name, e)
    log.info("%d senaryo yüklendi", len(SCENARIOS))


def validate(name: str, data: dict) -> None:
    nodes = data["nodes"]
    if data["start"] not in nodes:
        raise ValueError("start düğümü yok")
    for nid, node in nodes.items():
        for ch in node.get("choices", []):
            if ch["next"] not in nodes:
                raise ValueError(f"'{nid}' içinde olmayan düğüme gidiyor: {ch['next']}")


def load_state() -> None:
    if STATE_FILE.exists():
        STATE.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))


def save_state() -> None:
    STATE_FILE.write_text(json.dumps(STATE, ensure_ascii=False), encoding="utf-8")


# ---------- Mantık ----------
def is_visible(choice: dict, variables: dict) -> bool:
    """'requires': {"cesaret": 2} -> cesaret >= 2 olmalı."""
    for var, minimum in choice.get("requires", {}).items():
        if variables.get(var, 0) < minimum:
            return False
    return True


def apply_set(choice: dict, variables: dict) -> None:
    """'set': {"cesaret": 1} -> değişkene ekler (negatif de olabilir)."""
    for var, delta in choice.get("set", {}).items():
        variables[var] = variables.get(var, 0) + delta


def build_message(scen_id: str, node_id: str, variables: dict):
    node = SCENARIOS[scen_id]["nodes"][node_id]
    text = node["text"]
    rows = []
    visible = [c for c in node.get("choices", []) if is_visible(c, variables)]
    for idx, ch in enumerate(node.get("choices", [])):
        if is_visible(ch, variables):
            # callback_data: ch:<düğüm>:<seçim index>  (64 bayt sınırı!)
            rows.append([InlineKeyboardButton(ch["text"], callback_data=f"ch:{node_id}:{idx}")])
    if node.get("ending") or not visible:
        text += "\n\n🏁 SON" + (f": {node['ending']}" if isinstance(node.get("ending"), str) else "")
        rows = [[InlineKeyboardButton("🔄 Baştan oyna", callback_data=f"sc:{scen_id}")],
                [InlineKeyboardButton("📚 Senaryolar", callback_data="menu")]]
    return text, InlineKeyboardMarkup(rows)


def scenario_menu():
    rows = [[InlineKeyboardButton(s["title"], callback_data=f"sc:{sid}")]
            for sid, s in SCENARIOS.items()]
    return InlineKeyboardMarkup(rows)


# ---------- Telegram handler'ları ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Merhaba! Bir senaryo seç:", reply_markup=scenario_menu()
    )


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = str(q.from_user.id)
    data = q.data

    if data == "menu":
        await q.message.reply_text("Bir senaryo seç:", reply_markup=scenario_menu())
        return

    if data.startswith("sc:"):  # senaryo başlat
        scen_id = data[3:]
        if scen_id not in SCENARIOS:
            return
        STATE[uid] = {"scenario": scen_id, "node": SCENARIOS[scen_id]["start"], "vars": {}}
        save_state()
        text, kb = build_message(scen_id, STATE[uid]["node"], {})
        await q.message.reply_text(text, reply_markup=kb)
        return

    if data.startswith("ch:"):  # seçim yapıldı
        _, node_id, idx = data.split(":")
        st = STATE.get(uid)
        if not st or st["node"] != node_id:
            await q.message.reply_text("Bu buton eski. /start ile yeniden başlayabilirsin.")
            return
        scen = SCENARIOS[st["scenario"]]
        choice = scen["nodes"][node_id]["choices"][int(idx)]
        if not is_visible(choice, st["vars"]):
            return
        apply_set(choice, st["vars"])
        st["node"] = choice["next"]
        save_state()

        # Eski mesajın butonlarını kaldır, seçimi göster (hikaye geçmişi okunabilir kalsın)
        await q.edit_message_text(f"{q.message.text}\n\n👉 {choice['text']}")
        text, kb = build_message(st["scenario"], st["node"], st["vars"])
        await q.message.reply_text(text, reply_markup=kb)


async def reload_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    admin = os.environ.get("ADMIN_ID")
    if admin and str(update.effective_user.id) != admin:
        return
    load_scenarios()
    await update.message.reply_text(f"{len(SCENARIOS)} senaryo yeniden yüklendi.")


def main():
    load_scenarios()
    load_state()
    app = Application.builder().token(os.environ["BOT_TOKEN"]).build()
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler("reload", reload_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.run_polling()


if __name__ == "__main__":
    main()
