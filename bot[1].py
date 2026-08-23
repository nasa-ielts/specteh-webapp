
import asyncio, logging, os, json, html, re, secrets, pathlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv()
from cryptography.fernet import Fernet, InvalidToken
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from database import *
from webserver import setup_web
from keyboards import *
from texts import t, schema, format_specs, label_for

logging.basicConfig(level=logging.INFO)
BOT_TOKEN=os.getenv("BOT_TOKEN","")
raw_admins=os.getenv("ADMIN_IDS","")
ADMIN_IDS={int(x.strip()) for x in raw_admins.split(",") if x.strip().isdigit()}
ADMIN_USERNAMES={x.strip().lstrip("@").lower() for x in raw_admins.split(",") if x.strip() and not x.strip().isdigit()}
ADMIN_USERNAMES |= {x.strip().lstrip("@").lower() for x in os.getenv("ADMIN_USERNAMES","").split(",") if x.strip()}
if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN is not set. Put it in the .env file.")
bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp=Dispatcher(); states={}; timer_tasks={}; timer_messages={}
COMMISSION_RATE=0.05
PAYMENT_CARD_NUMBER=os.getenv("PAYMENT_CARD_NUMBER","")
PAYMENT_RECIPIENT_NAME=os.getenv("PAYMENT_RECIPIENT_NAME","")
COMMISSION_CARD_NUMBER=os.getenv("COMMISSION_CARD_NUMBER","")
COMMISSION_RECIPIENT_NAME=os.getenv("COMMISSION_RECIPIENT_NAME",PAYMENT_RECIPIENT_NAME)
SUPPORT_USERNAME=os.getenv("SUPPORT_USERNAME","")
CARD_ENCRYPTION_KEY=os.getenv("CARD_ENCRYPTION_KEY","")
if not CARD_ENCRYPTION_KEY:
    CARD_ENCRYPTION_KEY=Fernet.generate_key().decode()
    try:
        env_path=pathlib.Path(__file__).parent/".env"
        with env_path.open("a",encoding="utf-8") as f:f.write("\nCARD_ENCRYPTION_KEY="+CARD_ENCRYPTION_KEY+"\n")
    except Exception:pass
CARD_CIPHER=Fernet(CARD_ENCRYPTION_KEY.encode())

def encrypt_card(value):
    return CARD_CIPHER.encrypt(value.encode()).decode()
def decrypt_card(value):
    if not value:return None
    try:return CARD_CIPHER.decrypt(value.encode()).decode()
    except (InvalidToken,ValueError):return value

def esc(v): return html.escape(str(v))
def is_admin_user(u): return u.id in ADMIN_IDS or (u.username and u.username.lower() in ADMIN_USERNAMES)
async def lang(uid):
    u=await get_user(uid); return u["language"] if u and u["language"] else "ru"
def clear(uid): states.pop(uid,None)
def num(v):
    m=re.search(r"\d+(?:[.,]\d+)?",str(v).replace(" ",""))
    return float(m.group().replace(",",".")) if m else None

def parse_specs(row):
    try:return json.loads(row["specs"] or "{}").get("values",{})
    except:return {}

def matches(req, row):
    have=parse_specs(row)
    for k,v in req.items():
        hv=num(have.get(k))
        if hv is None or hv < float(v): return False
    return True

async def owner_is_busy(uid, date_value=None):
    if date_value is None:
        date_value=datetime.now().date().isoformat()
    return await owner_has_order_on_date(uid,date_value)

def elapsed_seconds(started_at):
    if not started_at: return 0
    try:
        dt=datetime.fromisoformat(started_at)
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return max(0,int((datetime.now(timezone.utc)-dt).total_seconds()))
    except Exception: return 0

def format_elapsed(seconds):
    seconds=max(0,int(seconds)); h=seconds//3600; m=(seconds%3600)//60; sec=seconds%60
    return f"{h:02d}:{m:02d}:{sec:02d}"

def calc_amount(price_per_hour, seconds):
    return round(float(price_per_hour or 0)*seconds/3600,2)


async def notify_admins(text,markup=None):
    ids=set(ADMIN_IDS)|set(await get_admin_ids())
    for aid in ids:
        try: await bot.send_message(aid,text,reply_markup=markup)
        except: pass

async def notify_matches(order_id):
    o=await get_order(order_id)
    if not o:return 0
    req=json.loads(o["request_specs"] or "{}")
    eq=[e for e in await get_available_equipment(o["category"]) if matches(req,e)]
    if o["payment_method"]=="card":
        eq=[e for e in eq if await get_owner_card(e["owner_id"])]
    sent=set()
    for e in eq:
        if e["owner_id"] in sent or await owner_is_busy(e["owner_id"], str(o["date_time"])[:10]): continue
        sent.add(e["owner_id"]); l=await lang(e["owner_id"])
        try:
            await bot.send_message(
                e["owner_id"],
                t("new_order",l).format(
                    id=o["id"],
                    category=esc(o["category"]),
                    specs=format_specs(o["category"],req,l),
                    date_time=esc(o["date_time"]),
                    price=e["price_per_hour"],
                    payment=t("payment_card",l) if o["payment_method"]=="card" else t("payment_cash",l),
                    customer_phone=(await get_user(o["customer_id"]))["phone_number"]
                ),
                reply_markup=owner_order_keyboard(o["id"],l)
            )
            # Send the customer's exact GPS location as a Telegram location message.
            # The coordinates are stored in the order and must be forwarded to the
            # owner/driver, not replaced by the placeholder string "GPS".
            if o["latitude"] is not None and o["longitude"] is not None:
                await bot.send_location(
                    chat_id=e["owner_id"],
                    latitude=float(o["latitude"]),
                    longitude=float(o["longitude"])
                )
        except: pass
    return len(sent)

async def wake_waiting_orders(category):
    for o in await get_searching_orders(category):
        req=json.loads(o["request_specs"] or "{}")
        eq=[e for e in await get_available_equipment(category) if matches(req,e)]
        if eq:
            n=await notify_matches(o["id"])
            if n:
                cl=await lang(o["customer_id"])
                try: await bot.send_message(o["customer_id"],t("match_found",cl).format(id=o["id"]))
                except: pass

@dp.message(CommandStart())
async def start(m):
    await create_user(m.from_user.id,m.from_user.full_name)
    if is_admin_user(m.from_user): await set_role(m.from_user.id,"admin")
    u=await get_user(m.from_user.id)
    if not u["language"]:
        await m.answer("SpecTech\n\nВыберите язык / Tilni tanlang:",reply_markup=language_keyboard()); return
    if not u["phone_number"]:
        await m.answer(t("need_phone",u["language"]),reply_markup=phone_keyboard(u["language"])); return
    clear(m.from_user.id)
    await m.answer(t("welcome",u["language"]),reply_markup=main_menu(u["language"],is_admin_user(m.from_user)))

@dp.callback_query(F.data.startswith("lang:"))
async def choose_lang(c):
    l=c.data.split(":")[1];uid=c.from_user.id
    await create_user(uid,c.from_user.full_name);await set_language(uid,l)
    if is_admin_user(c.from_user): await set_role(uid,"admin")
    clear(uid);await c.message.edit_text(t("language_saved",l))
    u=await get_user(uid)
    if not u["phone_number"]:
        await c.message.answer(t("need_phone",l),reply_markup=phone_keyboard(l))
    else:
        await c.message.answer(t("welcome",l),reply_markup=main_menu(l,is_admin_user(c.from_user)))
    await c.answer()

@dp.message(F.contact)
async def receive_phone(m):
    uid=m.from_user.id
    if m.contact.user_id and m.contact.user_id != uid:
        return
    await set_phone(uid,m.contact.phone_number)
    l=await lang(uid)
    if is_admin_user(m.from_user): await set_role(uid,"admin")
    clear(uid)
    await m.answer("📱 " + ("Номер сохранён." if l=="ru" else "Telefon raqami saqlandi."))
    await m.answer(t("welcome",l),reply_markup=main_menu(l,is_admin_user(m.from_user)))

@dp.message(F.text.in_({"Язык","Til"}))
async def change_lang(m): clear(m.from_user.id);await m.answer("Выберите язык / Tilni tanlang:",reply_markup=language_keyboard())

# ---------- CUSTOMER ----------
@dp.message(F.text.in_({"Заказать технику","Texnika buyurtma qilish"}))
async def order_start(m):
    l=await lang(m.from_user.id);states[m.from_user.id]={"flow":"customer","step":"category","lang":l}
    await m.answer(t("choose_equipment",l),reply_markup=equipment_categories(l,"customer"))

@dp.callback_query(F.data.startswith("customer_cat:"))
async def customer_cat(c):
    uid=c.from_user.id;l=await lang(uid);cat=c.data.split(":",1)[1]
    states[uid]={"flow":"customer","step":"spec","spec_index":0,"lang":l,"category":cat,"request_specs":{}}
    await c.message.edit_text(t("selected_equipment",l).format(category=esc(cat))+"\n\n"+label_for_prompt(cat,0,l),reply_markup=spec_keyboard(cat,schema(cat)[0][0],l))
    await c.answer()

def label_for_prompt(cat,idx,l):
    key,label,unit=schema(cat)[idx]
    return f"{label_for(key,l)}\nВыберите требуемое значение ({unit})." if l=="ru" else f"{label_for(key,l)}\nKerakli qiymatni tanlang ({unit})."

@dp.callback_query(F.data.startswith("owner_spec:"))
async def owner_spec(c):
    uid=c.from_user.id
    l=await lang(uid)
    s=states.get(uid)
    try:
        if not s or s.get("flow")!="owner":
            await c.answer(t("session_expired",l),show_alert=True)
            return
        parts=c.data.split(":",2)
        if len(parts)!=3:
            await c.answer("Invalid selection",show_alert=True)
            return
        key,val=parts[1],parts[2]
        s.setdefault("specs",{}).setdefault("values",{})[key]=float(val)
        idx=s.get("spec_index",0)+1
        if idx < len(schema(s["category"])):
            s["spec_index"]=idx
            await c.message.edit_text(
                label_for_prompt(s["category"],idx,l),
                reply_markup=spec_keyboard(s["category"],schema(s["category"])[idx][0],l,"owner")
            )
        else:
            s["step"]="price"
            await c.message.edit_text(t("enter_price",l),reply_markup=cancel_keyboard(l))
        await c.answer()
    except Exception as e:
        print("owner_spec error:",repr(e))
        await c.answer("Не удалось выбрать значение. Попробуйте ещё раз.",show_alert=True)

@dp.callback_query(F.data.startswith("owner_specother:"))
async def owner_spec_other(c):
    uid=c.from_user.id;l=await lang(uid);s=states.get(uid)
    if not s:return
    key=c.data.split(":")[1];s["pending_key"]=key;s["step"]="spec_manual"
    await c.message.edit_text((label_for(key,l)+"\nВведите точное значение.") if l=="ru" else (label_for(key,l)+"\nAniq qiymatni kiriting."),reply_markup=cancel_keyboard(l));await c.answer()

@dp.callback_query(F.data.startswith("customer_spec:"))
async def customer_spec(c):
    uid=c.from_user.id
    l=await lang(uid)
    s=states.get(uid)
    try:
        if not s or s.get("flow")!="customer":
            await c.answer(t("session_expired",l),show_alert=True)
            return
        parts=c.data.split(":",2)
        if len(parts)!=3:
            await c.answer("Invalid selection",show_alert=True)
            return
        key,val=parts[1],parts[2]
        s.setdefault("request_specs",{})[key]=float(val)
        idx=s.get("spec_index",0)+1
        if idx < len(schema(s["category"])):
            s["spec_index"]=idx
            await c.message.edit_text(
                label_for_prompt(s["category"],idx,l),
                reply_markup=spec_keyboard(s["category"],schema(s["category"])[idx][0],l)
            )
        else:
            s["step"]="date"
            # edit_message_text accepts only InlineKeyboardMarkup.
            # The Mini App launch button is a ReplyKeyboardMarkup, so send it
            # as a new message instead of passing it to edit_text().
            await c.message.edit_text(t("choose_date", l))
            await c.message.answer(t("choose_date", l), reply_markup=date_entry_keyboard(l))
        await c.answer()
    except Exception as e:
        print("customer_spec error:",repr(e))
        await c.answer("Не удалось выбрать значение. Попробуйте ещё раз.",show_alert=True)

@dp.callback_query(F.data.startswith("customer_specother:"))
async def customer_spec_other(c):
    uid=c.from_user.id;l=await lang(uid);s=states.get(uid)
    if not s: return
    key=c.data.split(":")[1];s["pending_key"]=key;s["step"]="spec_manual"
    await c.message.edit_text(f"{label_for(key,l)}\nВведите точное значение.",reply_markup=cancel_keyboard(l));await c.answer()

@dp.callback_query(F.data=="open_calendar")
async def open_calendar(c):
    uid=c.from_user.id;l=await lang(uid);s=states.get(uid)
    if not s or s.get("flow")!="customer": return
    await c.message.edit_text(t("choose_date",l),reply_markup=calendar_keyboard(l))
    await c.answer()

@dp.callback_query(F.data.startswith("calnav:"))
async def calendar_nav(c):
    _,y,m=c.data.split(":");l=await lang(c.from_user.id)
    await c.message.edit_reply_markup(reply_markup=calendar_keyboard(l,int(y),int(m)))
    await c.answer()

@dp.callback_query(F.data=="noop")
async def noop(c): await c.answer()

@dp.callback_query(F.data.startswith("datepick:"))
async def pick_date(c):
    uid=c.from_user.id;l=await lang(uid);s=states.get(uid)
    if not s:return
    from datetime import date, timedelta
    chosen=date.fromisoformat(c.data.split(":",1)[1]);today=date.today()
    if chosen < today or chosen > today+timedelta(days=1):
        await c.answer("Можно выбрать только сегодня или завтра." if l=="ru" else "Faqat bugun yoki ertani tanlash mumkin.",show_alert=True);return
    s["date"]=chosen.isoformat();s["step"]="time"
    await c.message.edit_text(t("choose_time",l),reply_markup=time_entry_keyboard(l))
    await c.answer()

@dp.callback_query(F.data=="open_time")
async def open_time(c):
    uid=c.from_user.id;l=await lang(uid);s=states.get(uid)
    if not s or s.get("flow")!="customer":return
    await c.message.edit_text(t("choose_time",l),reply_markup=time_picker_keyboard(l))
    await c.answer()

@dp.callback_query(F.data.startswith("timepick:"))
async def pick_time(c):
    uid=c.from_user.id;l=await lang(uid);s=states.get(uid)
    if not s:return
    s["time"]=c.data.split(":",1)[1];s["step"]="location"
    await c.message.edit_text(t("enter_location",l))
    await c.message.answer(t("enter_location",l),reply_markup=location_keyboard(l))
    await c.answer()

@dp.message(F.web_app_data)
async def receive_webapp_data(m):
    uid = m.from_user.id
    s = states.get(uid)
    l = await lang(uid)
    try:
        payload = json.loads(m.web_app_data.data)
    except Exception:
        await m.answer("Не удалось получить выбор. Откройте ещё раз.")
        return
    kind, value = payload.get("type"), payload.get("value")
    if not s or s.get("flow") != "customer":
        await m.answer("Сессия заказа истекла. Начните заказ заново.", reply_markup=ReplyKeyboardRemove())
        return
    if kind == "date" and s.get("step") == "date":
        from datetime import date, timedelta
        try:
            chosen=date.fromisoformat(value); today=date.today()
            if chosen < today or chosen > today+timedelta(days=1):
                await m.answer("Можно выбрать только сегодня или завтра." if l=="ru" else "Faqat bugun yoki ertani tanlash mumkin.")
                return
        except Exception:
            await m.answer("Некорректная дата." if l=="ru" else "Noto'g'ri sana.")
            return
        s["date"] = value
        s["step"] = "time"
        await m.answer(t("choose_time", l), reply_markup=time_entry_keyboard(l))
        return
    if kind == "time" and s.get("step") == "time":
        s["time"] = value
        s["step"] = "location"
        await m.answer(t("enter_location", l), reply_markup=location_keyboard(l))
        return
    await m.answer("Выбор уже обработан или устарел.", reply_markup=ReplyKeyboardRemove())

@dp.message(F.location)
async def receive_location(m):
    uid=m.from_user.id;s=states.get(uid)
    if not s or s.get("flow")!="customer" or s.get("step")!="location": return
    l=s["lang"];s["latitude"]=m.location.latitude;s["longitude"]=m.location.longitude;s["location"]="GPS";s["step"]="payment"
    await m.answer(t("location_received",l));await m.answer(t("choose_payment",l),reply_markup=payment_keyboard(l))

@dp.callback_query(F.data.startswith("payment:"))
async def choose_payment(c):
    uid=c.from_user.id;l=await lang(uid);s=states.get(uid)
    if not s or s.get("flow")!="customer" or s.get("step")!="payment":
        await c.answer(t("session_expired",l),show_alert=True);return
    method=c.data.split(":",1)[1]
    if method not in ("card","cash"): await c.answer();return
    s["payment_method"]=method
    await finalize_customer_order(uid);await c.answer()

# ---------- OWNER ----------
@dp.message(F.text.in_({"Я владелец техники","Men texnika egasiman"}))
async def owner_start(m):
    uid=m.from_user.id;l=await lang(uid);await set_role(uid,"owner");clear(uid);await m.answer(t("owner_intro",l),reply_markup=owner_menu(l,is_admin_user(m.from_user)))

@dp.message(F.text.in_({"Моя карта","Mening kartam"}))
async def owner_card(m):
    uid=m.from_user.id;l=await lang(uid);u=await get_user(uid);clear(uid)
    if u and u["card_number"]:
        await m.answer(t("owner_card_title",l).format(card=esc(decrypt_card(u["card_number"]) or "—")),reply_markup=owner_menu(l,is_admin_user(m.from_user)))
    else:
        states[uid]={"flow":"owner","step":"card","lang":l}
        await m.answer(t("enter_owner_card",l),reply_markup=cancel_keyboard(l))

@dp.message(F.text.in_({"Добавить технику","Texnika qo'shish"}))
async def add_start(m):
    uid=m.from_user.id;l=await lang(uid);u=await get_user(uid)
    if not (u and u["card_number"]):
        states[uid]={"flow":"owner","step":"card","lang":l}
        await m.answer(t("enter_owner_card",l),reply_markup=cancel_keyboard(l))
        return
    states[uid]={"flow":"owner","step":"category","lang":l}
    await m.answer(t("owner_choose",l),reply_markup=equipment_categories(l,"owner"))

@dp.callback_query(F.data.startswith("owner_cat:"))
async def owner_cat(c):
    uid=c.from_user.id;l=await lang(uid);cat=c.data.split(":",1)[1]
    states[uid]={"flow":"owner","step":"brand","lang":l,"category":cat,"specs":{"values":{}}}
    await c.message.edit_text(t("enter_brand",l),reply_markup=cancel_keyboard(l));await c.answer()

@dp.message(F.text.in_({"Моя техника","Mening texnikam"}))
async def my_equipment(m):
    uid=m.from_user.id;l=await lang(uid);clear(uid)
    await m.answer("<b>Моя техника</b>\n\nОткройте красивую карточку гаража со всей вашей техникой и прошлыми работами." if l=="ru" else "<b>Mening texnikam</b>\n\nTexnikalaringiz va ishlaringizni ko'ring.",reply_markup=owner_web_menu(l,uid))

@dp.message(F.text.in_({"Мои заказы","Buyurtmalar"}))
async def owner_orders(m):
    uid=m.from_user.id;l=await lang(uid);clear(uid);orders=await get_owner_orders(uid)
    text=t("my_orders_title",l)
    if not orders:text+=t("no_orders",l)
    for o in orders[:20]:text+=t("order_list_item",l).format(id=o["id"],category=o["category"],status=o["status"],date_time=o["date_time"])
    await m.answer(text,reply_markup=owner_menu(l,is_admin_user(m.from_user)))

@dp.callback_query(F.data.startswith("owner_accept:"))
async def owner_accept(c):
    uid=c.from_user.id;l=await lang(uid);oid=int(c.data.split(":")[1]);o=await get_order(oid)
    if not o or o["status"]!="searching":await c.answer(t("order_taken",l),show_alert=True);return
    if await owner_has_unpaid_commission(uid):
        await c.answer(t("owner_payment_blocked",l),show_alert=True);return
    if o["payment_method"]=="card" and not decrypt_card(await get_owner_card(uid)):
        await c.answer(t("owner_card_required",l),show_alert=True);return
    order_date=str(o["date_time"])[:10]
    if await owner_is_busy(uid,order_date):await c.answer(t("owner_busy",l),show_alert=True);return
    req=json.loads(o["request_specs"] or "{}")
    eq=[e for e in await get_available_equipment(o["category"]) if e["owner_id"]==uid and matches(req,e)]
    if not eq:await c.answer(t("owner_busy",l),show_alert=True);return
    if not await accept_order(oid,uid,eq[0]["id"],eq[0]["price_per_hour"]):await c.answer(t("order_taken",l),show_alert=True);return
    e=eq[0];await c.message.edit_reply_markup(reply_markup=None);await c.message.answer(t("order_accepted_owner",l).format(id=oid),reply_markup=start_work_keyboard(oid,"owner",l))
    cl=await lang(o["customer_id"]);owner_u=await get_user(uid)
    await bot.send_message(o["customer_id"],t("customer_accepted",cl).format(id=oid,category=esc(o["category"]),specs=format_specs(o["category"],parse_specs(e),cl),brand=esc(e["brand"]),plate=esc(e["plate_number"]),price=e["price_per_hour"],owner_phone=owner_u["phone_number"]),reply_markup=start_work_keyboard(oid,"customer",cl))
    await c.answer()

@dp.callback_query(F.data.startswith("owner_decline:"))
async def owner_decline(c): await c.message.edit_reply_markup(reply_markup=None);await c.answer()

# ---------- WORK START / TIMER / COMPLETION ----------
async def timer_loop(order_id):
    try:
        while True:
            o=await get_order(order_id)
            if not o or o["status"]!="in_progress" or not o["work_started_at"]: return
            seconds=elapsed_seconds(o["work_started_at"])
            amount=calc_amount(o["price"],seconds)
            for uid,info in list(timer_messages.get(order_id,{}).items()):
                l=await lang(uid)
                try:
                    await bot.edit_message_text(
                        chat_id=uid,message_id=info["message_id"],
                        text=t("timer_live",l).format(id=order_id,elapsed=format_elapsed(seconds),price=o["price"],amount=amount),
                        reply_markup=completion_keyboard(order_id,info["role"],l)
                    )
                except Exception:
                    pass
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        return

async def notify_timer_start(order_id):
    o=await get_order(order_id)
    if not o:return
    timer_messages[order_id]={}
    for uid,role in ((o["owner_id"],"owner"),(o["customer_id"],"customer")):
        if uid:
            l=await lang(uid)
            try:
                msg=await bot.send_message(uid,t("work_started",l).format(id=order_id,price=o["price"]),reply_markup=completion_keyboard(order_id,role,l))
                timer_messages[order_id][uid]={"message_id":msg.message_id,"role":role}
            except: pass
    task=timer_tasks.get(order_id)
    if task and not task.done(): task.cancel()
    timer_tasks[order_id]=asyncio.create_task(timer_loop(order_id))

@dp.callback_query(F.data.startswith("start_work:"))
async def start_work(c):
    _,role,oid=c.data.split(":");oid=int(oid);uid=c.from_user.id;l=await lang(uid);o=await get_order(oid)
    if not o or o["status"]!="active":await c.answer(t("session_expired",l),show_alert=True);return
    if role=="owner" and o["owner_id"]!=uid:await c.answer("Нет доступа.",show_alert=True);return
    if role=="customer" and o["customer_id"]!=uid:await c.answer("Нет доступа.",show_alert=True);return
    try:
        scheduled=datetime.strptime(str(o["date_time"]),"%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Tashkent"))
        if datetime.now(ZoneInfo("Asia/Tashkent")) < scheduled:
            await c.answer("Начать работу можно только после назначенных даты и времени." if l=="ru" else "Ishni faqat belgilangan sana va vaqtdan keyin boshlash mumkin.",show_alert=True);return
    except Exception:
        pass
    result=await mark_started(oid,uid,role)
    await c.message.edit_reply_markup(reply_markup=None)
    if result["started"]:
        await notify_timer_start(oid)
    else:
        other=o["customer_id"] if role=="owner" else o["owner_id"]
        ol=await lang(other)
        try:
            await bot.send_message(other,t("start_wait",ol).format(id=oid),reply_markup=start_work_keyboard(oid,"customer" if role=="owner" else "owner",ol))
        except: pass
        await c.message.answer(t("start_confirmed",l).format(id=oid))
    await c.answer()

@dp.callback_query(F.data.startswith("complete:"))
async def complete(c):
    _,role,oid=c.data.split(":");oid=int(oid);uid=c.from_user.id;l=await lang(uid);o=await get_order(oid)
    if not o or o["status"] not in ("in_progress","awaiting_completion"):await c.answer(t("session_expired",l),show_alert=True);return
    if role=="owner" and o["owner_id"]!=uid:await c.answer("Нет доступа.",show_alert=True);return
    if role=="customer" and o["customer_id"]!=uid:await c.answer("Нет доступа.",show_alert=True);return
    result=await mark_completed(oid,uid,role)
    await c.message.edit_reply_markup(reply_markup=None)
    if not result:return
    if result["completed"]:
        task=timer_tasks.pop(oid,None)
        if task and not task.done(): task.cancel()
        timer_messages.pop(oid,None)
        o=await get_order(oid)
        seconds=elapsed_seconds(o["work_started_at"])
        amount=calc_amount(o["price"],seconds)
        commission=round(amount*COMMISSION_RATE,2)
        await set_payment_and_amount(oid,o["payment_method"] or "card",amount,commission)
        o=await get_order(oid)
        elapsed=format_elapsed(seconds)
        for recipient,rl in [(o["owner_id"],await lang(o["owner_id"])),(o["customer_id"],await lang(o["customer_id"]))]:
            try:
                await bot.send_message(recipient,t("work_finished",rl).format(id=oid,elapsed=elapsed,price=o["price"],amount=amount,commission=commission))
            except: pass
        # Payment must be confirmed by both sides before the owner can settle the 5% commission.
        cl=await lang(o["customer_id"]);ol=await lang(o["owner_id"])
        card=decrypt_card(await get_owner_card(o["owner_id"]))
        if o["payment_method"]=="card":
            if card:
                await bot.send_message(o["customer_id"],t("customer_payment_card",cl).format(id=oid,amount=amount,card=esc(card)),reply_markup=payment_confirm_customer_keyboard(oid,cl))
            else:
                await bot.send_message(o["customer_id"],t("customer_payment_missing_card",cl).format(id=oid))
        else:
            await bot.send_message(o["customer_id"],t("customer_payment_cash",cl).format(id=oid,amount=amount),reply_markup=payment_confirm_customer_keyboard(oid,cl))
        await bot.send_message(o["owner_id"],t("owner_waiting_payment",ol).format(id=oid,amount=amount))
    else:
        await c.message.answer(t("completion_wait",l))
        other=o["customer_id"] if role=="owner" else o["owner_id"];ol=await lang(other)
        key="complete_customer" if role=="owner" else "complete_owner"
        try:await bot.send_message(other,t(key,ol),reply_markup=completion_keyboard(oid,"customer" if role=="owner" else "owner",ol))
        except:pass
    await c.answer()

# ---------- PAYMENT CONFIRMATION ----------
@dp.callback_query(F.data.startswith("admin_payment_ok:"))
async def admin_payment_ok(c):
    if not is_admin_user(c.from_user):return
    oid=int(c.data.split(":")[1]);o=await get_order(oid)
    if not o or not o["customer_payment_confirmed"]:
        await c.answer("Платёж уже обработан.",show_alert=True);return
    await admin_confirm_customer_payment(oid,True);await c.message.edit_reply_markup(reply_markup=None)
    ol=await lang(o["owner_id"]);await bot.send_message(o["owner_id"],t("owner_confirm_payment",ol).format(id=oid,amount=o["final_amount"]),reply_markup=payment_confirm_owner_keyboard(oid,ol));await c.answer("Оплата подтверждена")
@dp.callback_query(F.data.startswith("admin_payment_no:"))
async def admin_payment_no(c):
    if not is_admin_user(c.from_user):return
    oid=int(c.data.split(":")[1]);o=await get_order(oid)
    if not o:return
    await admin_confirm_customer_payment(oid,False);await c.message.edit_reply_markup(reply_markup=None)
    cl=await lang(o["customer_id"]);await bot.send_message(o["customer_id"],t("customer_payment_rejected",cl).format(id=oid,amount=o["final_amount"]),reply_markup=payment_confirm_customer_keyboard(oid,cl));await c.answer("Оплата отклонена")
@dp.callback_query(F.data.startswith("payment_customer:"))
async def customer_payment_confirm(c):
    uid=c.from_user.id;l=await lang(uid);oid=int(c.data.split(":")[1]);o=await get_order(oid)
    if not o or o["customer_id"]!=uid or o["status"]!="completed" or o["payment_status"] not in ("unpaid","customer_confirmed"):
        await c.answer(t("payment_unavailable",l),show_alert=True);return
    if not await mark_customer_payment(oid):
        await c.answer(t("payment_unavailable",l),show_alert=True);return
    await c.message.edit_reply_markup(reply_markup=None)
    await notify_admins(t("admin_customer_payment", "ru").format(id=oid,amount=o["final_amount"],customer=o["customer_id"],method=o["payment_method"]), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить оплату",callback_data=f"admin_payment_ok:{oid}"),InlineKeyboardButton(text="❌ Отклонить",callback_data=f"admin_payment_no:{oid}")]]))
    await c.message.answer(t("customer_payment_sent",l))
    await c.answer()

@dp.callback_query(F.data.startswith("payment_owner:"))
async def owner_payment_confirm(c):
    uid=c.from_user.id;l=await lang(uid);oid=int(c.data.split(":")[1]);o=await get_order(oid)
    if not o or o["owner_id"]!=uid or not o["customer_payment_confirmed"] or o["payment_status"]!="customer_confirmed":
        await c.answer(t("payment_unavailable",l),show_alert=True);return
    if not await mark_owner_payment_received(oid,uid):
        await c.answer(t("payment_unavailable",l),show_alert=True);return
    await c.message.edit_reply_markup(reply_markup=None)
    o=await get_order(oid)
    commission=o["commission"]
    await c.message.answer(t("owner_commission_due",l).format(id=oid,commission=commission,recipient=esc(COMMISSION_RECIPIENT_NAME or "SpecTech"),card=esc(COMMISSION_CARD_NUMBER)),reply_markup=commission_submit_keyboard(oid,l))
    cl=await lang(o["customer_id"])
    await bot.send_message(o["customer_id"],t("customer_payment_confirmed",cl).format(id=oid))
    await c.answer()

@dp.callback_query(F.data.startswith("commission_submit:"))
async def commission_submit(c):
    uid=c.from_user.id;l=await lang(uid);oid=int(c.data.split(":")[1]);o=await get_order(oid)
    if not o or o["owner_id"]!=uid or o["payment_status"]!="paid_confirmed" or o["commission_paid"]:
        await c.answer(t("commission_unavailable",l),show_alert=True);return
    if not COMMISSION_CARD_NUMBER:
        await c.answer("Карта сервиса пока не настроена администратором.",show_alert=True);return
    if not await submit_commission_payment(oid,uid):
        await c.answer(t("commission_unavailable",l),show_alert=True);return
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(t("commission_wait_admin",l))
    await notify_admins(t("admin_commission", "ru").format(id=oid,owner=uid,commission=o["commission"],card=esc(COMMISSION_CARD_NUMBER)), admin_commission_keyboard(oid))
    await c.answer()

@dp.callback_query(F.data.startswith("admin_commission_ok:"))
async def admin_commission_ok(c):
    if not is_admin_user(c.from_user):return
    oid=int(c.data.split(":")[1]);o=await get_order(oid)
    if not o or not o["commission_payment_submitted"]:
        await c.answer("Платёж уже обработан.",show_alert=True);return
    await mark_commission_paid(oid,None);await c.message.edit_reply_markup(reply_markup=None)
    ol=await lang(o["owner_id"]);await bot.send_message(o["owner_id"],t("commission_paid_ok",ol));await c.answer("Комиссия подтверждена")

@dp.callback_query(F.data.startswith("admin_commission_no:"))
async def admin_commission_no(c):
    if not is_admin_user(c.from_user):return
    oid=int(c.data.split(":")[1]);o=await get_order(oid)
    if not o:return
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET commission_payment_submitted=0 WHERE id=?",(oid,));await db.commit()
    await c.message.edit_reply_markup(reply_markup=None);ol=await lang(o["owner_id"]);await bot.send_message(o["owner_id"],t("commission_rejected",ol));await c.answer("Отклонено")

# ---------- ADMIN ----------
@dp.message(F.text=="Админ-панель")
async def admin_panel(m):
    if not is_admin_user(m.from_user):return
    url=os.getenv("MINIAPP_URL","").rstrip("/")+"/admin"
    await m.answer("<b>Админ-панель SpecTech</b>\n\nУправление проверками, оплатами, активными работами и техникой.",reply_markup=admin_web_menu("ru",m.from_user.id))

@dp.callback_query(F.data.startswith("admin_eq_"))
async def admin_verify(c):
    if not is_admin_user(c.from_user):return
    action,eid=c.data.split(":");e=await get_equipment(int(eid));approved=action=="admin_eq_ok"
    await verify_equipment(int(eid),approved);l=await lang(e["owner_id"])
    await bot.send_message(e["owner_id"],t("equipment_approved_owner" if approved else "equipment_rejected_owner",l).format(id=eid))
    await c.message.edit_reply_markup(reply_markup=None);await c.answer()

# ---------- GENERAL ----------
@dp.callback_query(F.data=="flow_cancel")
async def flow_cancel(c):
    uid=c.from_user.id;l=await lang(uid);clear(uid);await c.message.edit_text(t("flow_cancelled",l));await c.message.answer(t("welcome",l),reply_markup=main_menu(l,is_admin_user(c.from_user)));await c.answer()

async def finalize_customer_order(uid):
    s=states.get(uid)
    if not s:return
    l=s["lang"];s["step"]="confirm"
    specs=format_specs(s["category"],s["request_specs"],l)
    pay=t("payment_card",l) if s.get("payment_method")=="card" else t("payment_cash",l)
    await bot.send_message(uid,t("confirm",l).format(
        category=esc(s["category"]),specs=specs,date=esc(s["date"]),time=esc(s["time"]),payment=pay
    ),reply_markup=confirm_keyboard(l,"order"))

@dp.message(F.text.in_({"Отменить","Bekor qilish"}))
async def text_cancel(m):
    if m.from_user.id in states:
        l=await lang(m.from_user.id);clear(m.from_user.id)
        await m.answer(t("flow_cancelled",l),reply_markup=main_menu(l,is_admin_user(m.from_user)))

@dp.message()
async def flow(m:Message):
    uid=m.from_user.id;s=states.get(uid)
    if not s:return
    l=s["lang"];v=(m.text or "").strip();step=s["step"]

    if s["flow"]=="customer":
        if step=="spec_manual":
            x=num(v)
            if not x or x<=0:await m.answer("Введите положительное число." if l=="ru" else "Musbat son kiriting.");return
            s["request_specs"][s["pending_key"]]=x;idx=s["spec_index"]+1
            if idx<len(schema(s["category"])):
                s["spec_index"]=idx;await m.answer(label_for_prompt(s["category"],idx,l),reply_markup=spec_keyboard(s["category"],schema(s["category"])[idx][0],l))
            else:s["step"]="date";await m.answer(t("choose_date",l),reply_markup=date_entry_keyboard(l))
        return

    if s["flow"]=="owner":
        if step=="card":
            digits=re.sub(r"\D", "", v)
            if len(digits) < 12 or len(digits) > 19:
                await m.answer(t("card_error",l));return
            await set_card_number(uid,encrypt_card(digits))
            s["step"]="category"
            await m.answer(t("owner_choose",l),reply_markup=equipment_categories(l,"owner"));return
        if step=="brand":
            s["brand"]=v;s["step"]="plate";await m.answer(t("enter_plate",l),reply_markup=cancel_keyboard(l));return
        if step=="plate":
            s["plate"]=v;s["step"]="year";await m.answer(t("enter_year",l),reply_markup=cancel_keyboard(l));return
        if step=="year":
            x=num(v)
            if not x or x<1950 or x>2100:await m.answer(t("year_error",l));return
            s["year"]=int(x);s["step"]="spec";s["spec_index"]=0
            await m.answer(label_for_prompt(s["category"],0,l),reply_markup=spec_keyboard(s["category"],schema(s["category"])[0][0],l,"owner"));return
        if step=="spec_manual":
            x=num(v)
            if not x or x<=0:await m.answer("Введите положительное число." if l=="ru" else "Musbat son kiriting.");return
            s["specs"]["values"][s["pending_key"]]=x;idx=s["spec_index"]+1
            if idx<len(schema(s["category"])):
                s["spec_index"]=idx;await m.answer(label_for_prompt(s["category"],idx,l),reply_markup=spec_keyboard(s["category"],schema(s["category"])[idx][0],l,"owner"))
            else:s["step"]="price";await m.answer(t("enter_price",l),reply_markup=cancel_keyboard(l))
            return
        if step=="price":
            x=num(v)
            if not x or x<=0:await m.answer(t("price_error",l));return
            s["price"]=x;s["step"]="equipment_confirm"
            await m.answer(f"<b>{esc(s['category'])}</b>\n{format_specs(s['category'],s['specs']['values'],l)}\nЦена: {x}",reply_markup=confirm_keyboard(l,"equipment"))
            return

@dp.callback_query(F.data=="order_confirm")
async def order_confirm(c):
    uid=c.from_user.id;l=await lang(uid);s=states.get(uid)
    if not s or s.get("step")!="confirm":await c.answer(t("session_expired",l),show_alert=True);return
    oid=await create_order(uid,s["category"],s["location"],s["latitude"],s["longitude"],f"{s['date']} {s['time']}",0,"",s["request_specs"],s.get("payment_method","card"))
    clear(uid);await c.message.edit_text(t("order_created",l).format(id=oid,details=format_specs(s["category"],s["request_specs"],l)))
    n=await notify_matches(oid)
    if not n:await c.message.answer(t("no_match",l).format(id=oid))
    await c.message.answer(t("welcome",l),reply_markup=main_menu(l,is_admin_user(c.from_user)));await c.answer()

@dp.callback_query(F.data=="equipment_confirm")
async def equipment_confirm(c):
    uid=c.from_user.id;l=await lang(uid);s=states.get(uid)
    if not s or s.get("flow")!="owner":await c.answer(t("session_expired",l),show_alert=True);return
    eid=await add_equipment(uid,s["category"],s["brand"],s["plate"],s["year"],"",s["price"],json.dumps(s["specs"],ensure_ascii=False));clear(uid)
    await c.message.edit_text(t("equipment_added",l).format(id=eid));await c.message.answer(t("welcome",l),reply_markup=owner_menu(l,is_admin_user(c.from_user)))
    await notify_admins(t("admin_equipment","ru").format(id=eid,category=esc(s["category"]),brand=esc(s["brand"]),plate=esc(s["plate"]),owner=uid,specs=format_specs(s["category"],s["specs"]["values"],"ru"),price=s["price"]),admin_equipment_keyboard(eid))

@dp.message(F.text.in_({"Мои заказы","Buyurtmalarim"}))
async def customer_orders(m):
    uid=m.from_user.id;l=await lang(uid);clear(uid)
    u=await get_user(uid)
    if u and u["role"]=="owner":
        await m.answer("<b>Мои работы</b>\n\nЗдесь будут ваши завершённые работы, время, стоимость и комиссия." if l=="ru" else "<b>Mening ishlarim</b>\n\nBu yerda tugallangan ishlar, vaqt, narx va komissiya ko‘rsatiladi.",reply_markup=owner_web_menu(l,uid))
    else:
        await m.answer("<b>История заказов</b>\n\nЗдесь будут все выполненные работы, длительность, стоимость и техника." if l=="ru" else "<b>Buyurtmalar tarixi</b>\n\nBarcha ishlar, vaqt va narxlar shu yerda.",reply_markup=customer_history_button(l,uid))

@dp.message(F.text.in_({"Поддержка","Yordam"}))
async def support(m):
    uid=m.from_user.id;l=await lang(uid);clear(uid)
    handle=SUPPORT_USERNAME.lstrip('@')
    if handle:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=("💬 Открыть поддержку" if l=="ru" else "💬 Yordamni ochish"),url=f"https://t.me/{handle}")]])
        await m.answer(("Поддержка: @"+esc(handle)) if l=="ru" else ("Yordam: @"+esc(handle)),reply_markup=kb)
    else:
        await m.answer("Поддержка пока не настроена.",reply_markup=main_menu(l,is_admin_user(m.from_user)))

async def main():
    await init_db();print("SpecTech Bot started")
    from aiohttp import web
    app=web.Application();setup_web(app)
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,"0.0.0.0",int(os.getenv("PORT", os.getenv("WEB_PORT","8080"))));await site.start()
    await dp.start_polling(bot)
if __name__=="__main__":asyncio.run(main())
