import asyncio
import logging

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.client.bot import DefaultBotProperties
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from config import TOKEN, ADMINS, TELEGRAM_CHANNELS, INSTAGRAM_PROFILES, BONUS_CHANNEL_ID
from database import (
    init_db, add_user, get_user, set_phone, set_step, set_completed,
    set_bonus_link, get_bonus_link, add_referral, get_ref_count,
    get_all_user_ids, get_users_list, get_stats,
    get_ref_limit, set_ref_limit,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher()


# ═══════════════════════════════════════════════════════════
# HOLATLAR
# ═══════════════════════════════════════════════════════════

class UserState(StatesGroup):
    waiting_phone      = State()
    waiting_screenshot = State()


class AdminState(StatesGroup):
    broadcast = State()
    set_limit = State()


# ═══════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════

def progress(current: int, total: int, n: int = 8) -> str:
    filled = int(n * current / total) if total else 0
    return "▓" * filled + "░" * (n - filled)


def steps_text(step: int, ref_count: int, limit: int) -> str:
    def icon(s):
        if step > s:    return "✅"
        elif step == s: return "🔄"
        else:           return "⬜"
    lines = [
        f"{icon(0)} <b>1-bosqich:</b> Telefon raqam",
        f"{icon(1)} <b>2-bosqich:</b> Telegram obuna",
        f"{icon(2)} <b>3-bosqich:</b> Instagram screenshot",
        f"{icon(3)} <b>4-bosqich:</b> Referal — {ref_count}/{limit}  {progress(ref_count, limit)}",
        f"{icon(4)} <b>5-bosqich:</b> Bonus kanal 🎁",
    ]
    return "\n".join(lines)


async def is_subscribed(user_id: int) -> bool:
    for ch, _ in TELEGRAM_CHANNELS:
        try:
            m = await bot.get_chat_member(ch, user_id)
            logging.info(f"[SUB] {user_id} | {ch} | {m.status}")
            if m.status in ("left", "kicked", "banned"):
                return False
        except Exception as e:
            logging.error(f"[SUB ERR] {user_id} | {ch} | {e}")
            return False
    return True


async def give_bonus(user_id: int):
    """Har bir user uchun unikal invite link yaratib yuboradi."""
    # Avval saqlanganini tekshir
    existing = get_bonus_link(user_id)
    if existing:
        await bot.send_message(
            user_id,
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🏆 <b>Sizning bonus linkingiz:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎁 {existing}\n\n"
            "⚠️ Bu link faqat siz uchun!",
        )
        return

    try:
        inv = await bot.create_chat_invite_link(
            chat_id=BONUS_CHANNEL_ID,
            name=f"user_{user_id}",
            member_limit=1,
        )
        link = inv.invite_link
        set_bonus_link(user_id, link)
        set_completed(user_id)
        logging.info(f"[BONUS] user={user_id} link={link}")

        limit = get_ref_limit()
        await bot.send_message(
            user_id,
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🏆 <b>TABRIKLAYMIZ!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Siz {limit} ta do'stingizni muvaffaqiyatli\n"
            "taklif qildingiz!\n\n"
            "Sizning shaxsiy bonus kanal linkingiz:\n\n"
            f"🎁 <b>{link}</b>\n\n"
            "⚠️ Bu link faqat siz uchun —\n"
            "boshqalarga bermang!",
        )
    except Exception as e:
        logging.error(f"[BONUS ERR] user={user_id} err={e}")
        await bot.send_message(
            user_id,
            "🏆 <b>Tabriklaymiz!</b>\n\n"
            "Shartlarni bajardingiz!\n"
            "Bonus kanal linki tez orada yuboriladi.",
        )


async def check_and_reward(referrer_id: int):
    """Referrer uchun hisobni oshiradi va shartlar bajariladimi tekshiradi."""
    add_referral(referrer_id)
    limit     = get_ref_limit()
    ref_count = get_ref_count(referrer_id)
    referrer  = get_user(referrer_id)
    if not referrer:
        return

    remaining = max(0, limit - ref_count)
    try:
        await bot.send_message(
            referrer_id,
            f"🎉 <b>Yangi do'st qo'shildi!</b>\n\n"
            f"📊 Holat: <b>{ref_count}/{limit}</b>  {progress(ref_count, limit)}\n\n" +
            (f"⏳ Yana <b>{remaining}</b> ta kerak." if remaining > 0
             else "✅ Shartlar bajarildi! Bonus link yuborilmoqda..."),
        )
    except Exception:
        pass

    # Shartlar bajariladimi va hali bonus berilmaganmi?
    if ref_count >= limit and not referrer[5] and not referrer[6]:
        await give_bonus(referrer_id)


# ═══════════════════════════════════════════════════════════
# KLAVIATURALAR
# ═══════════════════════════════════════════════════════════

def kb_phone():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def kb_main(user_id):
    rows = [
        [KeyboardButton(text="📊 Natijam"),    KeyboardButton(text="🔗 Referal link")],
        [KeyboardButton(text="📋 Bosqichlar"), KeyboardButton(text="ℹ️ Shartlar")],
    ]
    if user_id in ADMINS:
        rows.append([KeyboardButton(text="🔐 Admin panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def ikb_continue(step: int):
    cb = {1: "cont_tg", 2: "cont_ig", 3: "cont_ref"}.get(step)
    if not cb:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Davom etish", callback_data=cb)]
    ])


def ikb_agree():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Qabul qilaman — Boshlash!", callback_data="agree")]
    ])


def ikb_tg_channels():
    rows = [[InlineKeyboardButton(text=f"📢 {ch}", url=url)] for ch, url in TELEGRAM_CHANNELS]
    rows.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_tg")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ikb_instagram():
    rows = [[InlineKeyboardButton(text=f"📸 Instagram {i+1}", url=url)]
            for i, url in enumerate(INSTAGRAM_PROFILES)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Admin inline klaviaturalar
def ikb_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika",        callback_data="adm_stats")],
        [InlineKeyboardButton(text="👥 Foydalanuvchilar",  callback_data="adm_users")],
        [InlineKeyboardButton(text="📢 Xabar yuborish",    callback_data="adm_broadcast")],
        [InlineKeyboardButton(text="⚙️ Sozlamalar",        callback_data="adm_settings")],
    ])


def ikb_back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data="adm_home")]
    ])


def ikb_settings():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔢 Referal limitini o'zgartirish", callback_data="adm_set_limit")],
        [InlineKeyboardButton(text="◀️ Orqaga",                        callback_data="adm_home")],
    ])


def ikb_cancel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm_cancel")]
    ])


# ═══════════════════════════════════════════════════════════
# /START
# ═══════════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    uid    = message.from_user.id
    name   = message.from_user.first_name
    ref_id = None

    if command.args and command.args.isdigit():
        ref_id = int(command.args)
        if ref_id == uid:
            ref_id = None

    add_user(uid, ref_id)
    user = get_user(uid)

    # Admin
    if uid in ADMINS:
        await message.answer(
            "🔐 <b>Admin paneliga xush kelibsiz!</b>",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🔐 Admin panel")]],
                resize_keyboard=True,
            ),
        )
        return

    step = user[3] if user else 0

    if step == 0:
        # Yangi user
        await message.answer(
            f"👋 Salom, <b>{name}</b>!\n\n"
            "Botga xush kelibsiz.\n"
            "Boshlash uchun telefon raqamingizni yuboring:",
            reply_markup=kb_phone(),
        )
        await state.set_state(UserState.waiting_phone)
    else:
        # Qaytib kelgan user
        limit     = get_ref_limit()
        ref_count = get_ref_count(uid)
        await message.answer(
            f"👋 Qaytib keldingiz, <b>{name}</b>!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{steps_text(step, ref_count, limit)}\n"
            "━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=kb_main(uid),
        )
        kb = ikb_continue(step)
        if kb:
            await message.answer("Davom etish uchun 👇", reply_markup=kb)


# ═══════════════════════════════════════════════════════════
# 1-BOSQICH: TELEFON
# ═══════════════════════════════════════════════════════════

@dp.message(UserState.waiting_phone, F.contact)
async def got_phone(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    set_phone(uid, message.contact.phone_number)
    set_step(uid, 1)
    await state.clear()

    # Referrer bormi — hisob oshir
    user = get_user(uid)
    if user and user[2]:
        await check_and_reward(user[2])

    limit = get_ref_limit()
    await message.answer("✅ <b>Telefon raqam saqlandi!</b>", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>Shartlar</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣  2 ta Telegram kanalga obuna bo'lish\n"
        "2️⃣  2 ta Instagram profilga obuna bo'lib,\n"
        "      screenshot yuborish\n"
        f"3️⃣  {limit} ta do'stingizni taklif qilish\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Hamma bajarsangiz 🎁 <b>bonus kanal</b> ochiladi!",
        reply_markup=ikb_agree(),
    )


@dp.message(UserState.waiting_phone)
async def wrong_phone(message: types.Message):
    await message.answer(
        "❗ Tugma orqali telefon raqamingizni yuboring:",
        reply_markup=kb_phone(),
    )


# ═══════════════════════════════════════════════════════════
# SHARTLAR QABUL → 2-BOSQICH
# ═══════════════════════════════════════════════════════════

@dp.callback_query(F.data == "agree")
async def cb_agree(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    user = get_user(uid)
    if not user or user[3] < 1:
        await callback.answer("Avval telefon raqamingizni yuboring.", show_alert=True)
        return
    await callback.message.edit_text("✅ <b>Shartlar qabul qilindi!</b>")
    await _show_tg_step(callback.message)
    await callback.answer()


# ═══════════════════════════════════════════════════════════
# 2-BOSQICH: TELEGRAM OBUNA
# ═══════════════════════════════════════════════════════════

async def _show_tg_step(msg):
    await msg.answer(
        "2️⃣ <b>Telegram kanallariga obuna bo'ling:</b>\n\n"
        "Ikkala kanalga obuna bo'lgach,\n"
        "<b>«✅ Obunani tekshirish»</b> tugmasini bosing.",
        reply_markup=ikb_tg_channels(),
    )


@dp.callback_query(F.data == "cont_tg")
async def cb_cont_tg(callback: types.CallbackQuery):
    await callback.message.edit_text("2️⃣ <b>Telegram bosqichi</b>")
    await _show_tg_step(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "check_tg")
async def cb_check_tg(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    user = get_user(uid)

    if not user or user[3] < 1:
        await callback.answer("Avval /start bosing.", show_alert=True)
        return
    if user[3] >= 2:
        await callback.answer("Bu bosqichni allaqachon o'tdingiz ✅", show_alert=True)
        return

    if not await is_subscribed(uid):
        await callback.answer(
            "❌ Ikkala kanalga ham obuna bo'ling!\nKeyin qayta tekshiring.",
            show_alert=True,
        )
        return

    set_step(uid, 2)
    await callback.message.edit_text("✅ <b>Telegram obuna tasdiqlandi!</b>")
    await _show_ig_step(callback.message)
    await callback.answer()


# ═══════════════════════════════════════════════════════════
# 3-BOSQICH: INSTAGRAM SCREENSHOT
# ═══════════════════════════════════════════════════════════

async def _show_ig_step(msg):
    await msg.answer(
        "3️⃣ <b>Instagram bosqichi:</b>\n\n"
        "Quyidagi 2 ta profilga obuna bo'ling va\n"
        "<b>ikkita alohida screenshot</b> yuboring:\n\n" +
        "\n".join(f"• {p}" for p in INSTAGRAM_PROFILES),
        reply_markup=ikb_instagram(),
    )


@dp.callback_query(F.data == "cont_ig")
async def cb_cont_ig(callback: types.CallbackQuery):
    await callback.message.edit_text("3️⃣ <b>Instagram bosqichi</b>")
    await _show_ig_step(callback.message)
    await callback.answer()


@dp.message(F.photo)
async def got_screenshot(message: types.Message, state: FSMContext):
    uid  = message.from_user.id
    user = get_user(uid)
    if not user or user[3] != 2:
        return

    data  = await state.get_data()
    count = data.get("ig", 0) + 1
    await state.update_data(ig=count)

    if count < 2:
        await message.answer(f"✅ <b>{count}/2</b> screenshot qabul qilindi.\n📸 Yana 1 ta yuboring:")
        return

    await state.clear()
    set_step(uid, 3)

    limit     = get_ref_limit()
    ref_count = get_ref_count(uid)
    me        = await bot.get_me()
    ref_link  = f"https://t.me/{me.username}?start={uid}"

    await message.answer("✅ <b>Instagram bosqichi bajarildi!</b>")
    await message.answer(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "4️⃣ <b>So'nggi bosqich — Referal!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Quyidagi linkni <b>{limit} ta do'stingizga</b> yuboring:\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"👆 Ustiga bosib nusxalang!\n\n"
        f"📊 Holat: <b>{ref_count}/{limit}</b>  {progress(ref_count, limit)}",
        reply_markup=kb_main(uid),
    )


# ═══════════════════════════════════════════════════════════
# 4-BOSQICH: REFERAL (davom etish tugmasi)
# ═══════════════════════════════════════════════════════════

@dp.callback_query(F.data == "cont_ref")
async def cb_cont_ref(callback: types.CallbackQuery):
    uid       = callback.from_user.id
    limit     = get_ref_limit()
    ref_count = get_ref_count(uid)
    me        = await bot.get_me()
    ref_link  = f"https://t.me/{me.username}?start={uid}"
    remaining = max(0, limit - ref_count)

    await callback.message.edit_text(
        "4️⃣ <b>Referal bosqichi:</b>\n\n"
        f"Ushbu linkni do'stlaringizga yuboring:\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"📊 Holat: <b>{ref_count}/{limit}</b>  {progress(ref_count, limit)}\n\n" +
        (f"⏳ Yana <b>{remaining}</b> ta kerak." if remaining > 0 else "✅ Shartlar bajarildi!")
    )
    await callback.answer()


# ═══════════════════════════════════════════════════════════
# USER MENYU
# ═══════════════════════════════════════════════════════════

@dp.message(F.text == "📊 Natijam")
async def my_result(message: types.Message):
    uid   = message.from_user.id
    user  = get_user(uid)
    if not user:
        await message.answer("Avval /start bosing.")
        return

    limit     = get_ref_limit()
    ref_count = get_ref_count(uid)
    step      = user[3]
    saved     = get_bonus_link(uid)

    text = (
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Sizning natijangiz</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{steps_text(step, ref_count, limit)}"
    )

    if step >= 3:
        remaining = max(0, limit - ref_count)
        if remaining > 0:
            text += f"\n\n⏳ Yana <b>{remaining}</b> ta do'st kerak."
        elif saved:
            text += f"\n\n🎉 <b>Bajarildi!</b>\n🎁 Linkingiz: {saved}"
        else:
            text += "\n\n🎉 <b>Bajarildi!</b> Bonus link yuborilmoqda..."
            await give_bonus(uid)

    await message.answer(text)


@dp.message(F.text == "🔗 Referal link")
async def referal_link(message: types.Message):
    uid  = message.from_user.id
    user = get_user(uid)
    if not user or user[3] < 3:
        await message.answer(
            "❗ Bu bo'lim <b>4-bosqichdan</b> keyin ochiladi.\n"
            "Avval barcha bosqichlarni bajaring."
        )
        return

    limit     = get_ref_limit()
    ref_count = get_ref_count(uid)
    me        = await bot.get_me()
    link      = f"https://t.me/{me.username}?start={uid}"
    remaining = max(0, limit - ref_count)

    await message.answer(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 <b>Sizning referal linkingiz</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<code>{link}</code>\n\n"
        f"👆 Ustiga bosib nusxalang!\n\n"
        f"📊 Taklif qilinganlar: <b>{ref_count}/{limit}</b>\n"
        f"{progress(ref_count, limit, 10)}\n\n" +
        (f"⏳ Yana <b>{remaining}</b> ta kerak." if remaining > 0
         else "✅ Shartlar bajarildi!")
    )


@dp.message(F.text == "📋 Bosqichlar")
async def my_steps(message: types.Message):
    uid  = message.from_user.id
    user = get_user(uid)
    if not user:
        await message.answer("Avval /start bosing.")
        return

    limit     = get_ref_limit()
    ref_count = get_ref_count(uid)
    step      = user[3]

    await message.answer(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>Bosqichlaringiz</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{steps_text(step, ref_count, limit)}\n\n"
        "✅ bajarildi  🔄 hozirgi  ⬜ kutilmoqda",
        reply_markup=ikb_continue(step),
    )


@dp.message(F.text == "ℹ️ Shartlar")
async def show_conditions(message: types.Message):
    limit = get_ref_limit()
    await message.answer(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "ℹ️ <b>Shartlar</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣  Telefon raqam yuborish\n"
        "2️⃣  2 ta Telegram kanalga obuna bo'lish\n"
        "3️⃣  2 ta Instagram profilga obuna bo'lib,\n"
        "      2 ta screenshot yuborish\n"
        f"4️⃣  {limit} ta do'stni botga taklif qilish\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 Hamma bajarsangiz — bonus kanal ochiladi!"
    )


# ═══════════════════════════════════════════════════════════
# ADMIN PANEL
# ═══════════════════════════════════════════════════════════

def is_admin(uid): return uid in ADMINS


@dp.message(F.text == "🔐 Admin panel")
async def open_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    await message.answer(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔐 <b>Admin Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=ikb_admin(),
    )


@dp.callback_query(F.data == "adm_home")
async def adm_home(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.clear()
    await callback.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔐 <b>Admin Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=ikb_admin(),
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_stats")
async def adm_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    total, completed, w_phone = get_stats()
    limit = get_ref_limit()
    await callback.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Statistika</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Jami foydalanuvchilar:  <b>{total}</b>\n"
        f"📱 Telefon yuborgan:       <b>{w_phone}</b>\n"
        f"🏆 Shartlarni bajardi:     <b>{completed}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ Referal limiti: <b>{limit}</b>\n"
        f"🎁 Bonus kanal ID: <code>{BONUS_CHANNEL_ID}</code>",
        reply_markup=ikb_back(),
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_users")
async def adm_users(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    users = get_users_list()
    if not users:
        await callback.message.edit_text("👥 Hali foydalanuvchi yo'q.", reply_markup=ikb_back())
        await callback.answer()
        return

    step_labels = ["Yangi", "📱 Tel", "📢 TG", "📸 IG", "🔗 Ref", "🏆 Tayyor"]
    text = "━━━━━━━━━━━━━━━━━━━━━\n👥 <b>Foydalanuvchilar</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, (uid, phone, step, done) in enumerate(users[:30], 1):
        status = "🏆 Bajarildi" if done else step_labels[min(step, 5)]
        ph     = phone or "—"
        text  += f"{i}. <code>{uid}</code>  {ph}  {status}\n"

    await callback.message.edit_text(text, reply_markup=ikb_back())
    await callback.answer()


@dp.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminState.broadcast)
    await callback.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📢 <b>Xabar yuborish</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Barcha foydalanuvchilarga yuboriladigan\n"
        "xabarni yozing (matn, rasm, video — hammasi bo'ladi).",
        reply_markup=ikb_cancel(),
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_cancel")
async def adm_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.clear()
    await callback.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔐 <b>Admin Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=ikb_admin(),
    )
    await callback.answer("❌ Bekor qilindi")


@dp.message(AdminState.broadcast)
async def do_broadcast(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    users  = get_all_user_ids()
    sent   = failed = 0
    status = await message.answer(f"⏳ Yuborilmoqda... 0/{len(users)}")

    for i, uid in enumerate(users, 1):
        try:
            await message.copy_to(uid)
            sent += 1
        except Exception:
            failed += 1
        if i % 20 == 0:
            try:
                await status.edit_text(f"⏳ Yuborilmoqda... {i}/{len(users)}")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await status.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📢 <b>Xabar yuborildi!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ Muvaffaqiyatli: <b>{sent}</b>\n"
        f"❌ Xato (bloklagan): <b>{failed}</b>",
        reply_markup=ikb_back(),
    )


@dp.callback_query(F.data == "adm_settings")
async def adm_settings(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    limit = get_ref_limit()
    await callback.message.edit_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ <b>Sozlamalar</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔢 Referal limiti: <b>{limit}</b>\n"
        f"🎁 Bonus kanal ID: <code>{BONUS_CHANNEL_ID}</code>\n\n"
        "Bonus kanal ID ni o'zgartirish uchun\n"
        "<code>config.py</code> faylini tahrirlang.",
        reply_markup=ikb_settings(),
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_set_limit")
async def adm_set_limit_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    limit = get_ref_limit()
    await state.set_state(AdminState.set_limit)
    await callback.message.edit_text(
        f"🔢 Hozirgi limit: <b>{limit}</b>\n\nYangi limitni kiriting (raqam):",
        reply_markup=ikb_cancel(),
    )
    await callback.answer()


@dp.message(AdminState.set_limit)
async def adm_set_limit_done(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if not message.text or not message.text.strip().isdigit():
        await message.answer("❗ Faqat raqam kiriting:", reply_markup=ikb_cancel())
        return
    new_limit = int(message.text.strip())
    set_ref_limit(new_limit)
    await state.clear()
    await message.answer(
        f"✅ Referal limiti o'zgartirildi: <b>{new_limit}</b>",
        reply_markup=ikb_back(),
    )


# ═══════════════════════════════════════════════════════════
# DEBUG BUYRUQLAR (test uchun, keyin o'chirsa bo'ladi)
# ═══════════════════════════════════════════════════════════

@dp.message(Command("checksub"))
async def cmd_checksub(message: types.Message):
    uid = message.from_user.id
    await message.answer(f"🔍 User ID: <code>{uid}</code>")
    for ch, _ in TELEGRAM_CHANNELS:
        try:
            m    = await bot.get_chat_member(ch, uid)
            icon = "✅" if m.status not in ("left", "kicked", "banned") else "❌"
            await message.answer(f"{icon} {ch}\nStatus: <b>{m.status}</b>")
        except Exception as e:
            await message.answer(f"⚠️ {ch}\n<code>{type(e).__name__}: {e}</code>")


@dp.message(Command("testbonus"))
async def cmd_testbonus(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer(f"🔍 Bonus kanal ID: <code>{BONUS_CHANNEL_ID}</code>\nSinab ko'rilmoqda...")
    try:
        inv = await bot.create_chat_invite_link(
            chat_id=BONUS_CHANNEL_ID,
            name=f"test_{message.from_user.id}",
            member_limit=1,
        )
        await message.answer(f"✅ Link yaratildi:\n{inv.invite_link}")
    except Exception as e:
        await message.answer(
            f"❌ <b>{type(e).__name__}</b>\n<code>{e}</code>\n\n"
            "Tekshiring:\n"
            "1. BONUS_CHANNEL_ID to'g'rimi? (-100... bilan boshlanishi kerak)\n"
            "2. Bot kanalga admin qilinganmi?\n"
            "3. 'Invite Users' huquqi berilganmi?"
        )


@dp.message(Command("mybonus"))
async def cmd_mybonus(message: types.Message):
    uid   = message.from_user.id
    saved = get_bonus_link(uid)
    if saved:
        await message.answer(f"🎁 Sizning linkingiz:\n{saved}")
    else:
        user      = get_user(uid)
        step      = user[3] if user else 0
        ref_count = get_ref_count(uid)
        limit     = get_ref_limit()
        await message.answer(
            f"Hali link yo'q.\n"
            f"Bosqich: <b>{step}</b> | Ref: <b>{ref_count}/{limit}</b> | "
            f"Completed: <b>{user[5] if user else 0}</b>"
        )


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

async def main():
    init_db()
    logging.info("Bot ishga tushdi!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
