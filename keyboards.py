from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import os, hmac, hashlib, time
from datetime import date,timedelta

def language_keyboard(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🇷🇺 Русский',callback_data='lang:ru'),InlineKeyboardButton(text="🇺🇿 O'zbekcha",callback_data='lang:uz')]])
def phone_keyboard(lang='ru'):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='📱 Отправить номер телефона' if lang=='ru' else '📱 Telefon raqamini yuborish',request_contact=True)]],resize_keyboard=True,one_time_keyboard=True)
def _web_token(uid, ttl=3600):
    exp=int(time.time())+ttl
    payload=f'{int(uid)}.{exp}'
    sig=hmac.new(os.getenv('BOT_TOKEN','').encode(),payload.encode(),hashlib.sha256).hexdigest()
    return f'{payload}.{sig}'

def _web_url(path, uid=None):
    base=os.getenv('MINIAPP_URL','').rstrip('/')
    if uid is None:
        return base+path
    return f'{base}{path}?auth={_web_token(uid)}'

def webapp_button(text,url): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=text,web_app=WebAppInfo(url=url))]],resize_keyboard=True,one_time_keyboard=True)
def main_menu(lang='ru',is_admin=False):
    rows=[[KeyboardButton(text='Заказать технику' if lang=='ru' else 'Texnika buyurtma qilish')],[KeyboardButton(text='Я владелец техники' if lang=='ru' else 'Men texnika egasiman')],[KeyboardButton(text='Мои заказы' if lang=='ru' else 'Buyurtmalarim'),KeyboardButton(text='Поддержка' if lang=='ru' else 'Yordam')],[KeyboardButton(text='Язык' if lang=='ru' else 'Til')]]
    if is_admin: rows.append([KeyboardButton(text='Админ-панель')])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True)
def owner_menu(lang='ru',is_admin=False):
    rows=[[KeyboardButton(text='Добавить технику' if lang=='ru' else "Texnika qo'shish"),KeyboardButton(text='Моя техника' if lang=='ru' else 'Mening texnikam')],[KeyboardButton(text='Моя карта' if lang=='ru' else 'Mening kartam'),KeyboardButton(text='Мои заказы' if lang=='ru' else 'Buyurtmalar')],[KeyboardButton(text='Поддержка' if lang=='ru' else 'Yordam'),KeyboardButton(text='Язык' if lang=='ru' else 'Til')]]
    if is_admin: rows.append([KeyboardButton(text='Админ-панель')])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True)
def admin_web_menu(lang='ru',uid=None):
    url=_web_url('/admin',uid)
    return webapp_button('🛡 Админ-панель',url)
def owner_web_menu(lang='ru',uid=None):
    url=_web_url('/owner',uid)
    return webapp_button('🚜 Моя техника',url)
def customer_history_button(lang='ru',uid=None):
    url=_web_url('/history',uid)
    return webapp_button('📋 Мои заказы' if lang=='ru' else '📋 Buyurtmalarim',url)
def equipment_categories(lang='ru',prefix='customer'):
    names=['Бетономиксер','Автобетононасос','Самосвал','Манипулятор','Экскаватор','Автокран'] if lang=='ru' else ['Beton aralashtirgich','Avtobeton nasosi','Samosval','Manipulyator','Ekskavator','Avtokran']
    b=InlineKeyboardBuilder()
    for display,canonical in zip(names,['Бетономиксер','Автобетононасос','Самосвал','Манипулятор','Экскаватор','Автокран']):b.button(text=display,callback_data=f'{prefix}_cat:{canonical}')
    b.adjust(2);return b.as_markup()
def cancel_keyboard(lang):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Bekor qilish' if lang=='uz' else 'Отменить',callback_data='flow_cancel')]])
def confirm_keyboard(lang,kind):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Tasdiqlash' if lang=='uz' else 'Подтвердить',callback_data=f'{kind}_confirm'),InlineKeyboardButton(text='Отmenit' if lang=='uz' else 'Отменить',callback_data='flow_cancel')]])
def date_entry_keyboard(lang):return webapp_button('📅 Tanlash' if lang=='uz' else '📅 Выбрать дату',os.getenv('MINIAPP_URL','').rstrip('/')+'/?mode=date')
def time_entry_keyboard(lang):return webapp_button('🕐 Tanlash' if lang=='uz' else '🕐 Выбрать время',os.getenv('MINIAPP_URL','').rstrip('/')+'/?mode=time')
def calendar_keyboard(lang,year=None,month=None):
    today=date.today();tomorrow=today+timedelta(days=1);year=year or today.year;month=month or today.month;first=date(year,month,1);import calendar
    b=InlineKeyboardBuilder();b.row(InlineKeyboardButton(text=f'{month:02d}.{year}',callback_data='noop'))
    for n in (['Пн','Вт','Ср','Чт','Пт','Сб','Вс'] if lang=='ru' else ['Du','Se','Ch','Pa','Ju','Sh','Ya']):b.button(text=n,callback_data='noop')
    b.adjust(7)
    for _ in range(first.weekday()):b.button(text=' ',callback_data='noop')
    for d in range(1,calendar.monthrange(year,month)[1]+1):
        x=date(year,month,d);b.button(text=str(d) if x in (today,tomorrow) else '·',callback_data=f'datepick:{x.isoformat()}' if x in (today,tomorrow) else 'noop')
    b.adjust(7);b.row(InlineKeyboardButton(text='✕',callback_data='flow_cancel'));return b.as_markup()
def time_picker_keyboard(lang):
    b=InlineKeyboardBuilder()
    for h in range(7,23):
        for minute in (0,30):
            if h==22 and minute==30:continue
            b.button(text=f'{h:02d}:{minute:02d}',callback_data=f'timepick:{h:02d}:{minute:02d}')
    b.adjust(4);b.row(InlineKeyboardButton(text='✕',callback_data='flow_cancel'));return b.as_markup()
def spec_keyboard(category,key,lang,prefix='customer'):
    presets={'Бетономиксер':{'drum_volume':[5,7,8,9,10,12]},'Автобетононасос':{'boom_length':[24,28,32,36,40,42,45]},'Самосвал':{'body_volume':[10,15,20,25,30]},'Манипулятор':{'lift_capacity':[1,3,5,8,10,15],'reach':[4,6,8,10,12]},'Экскаватор':{'bucket_volume':[0.3,0.6,0.9,1.2,1.5,2]},'Автокран':{'lift_capacity':[10,16,25,30,40,50,70],'boom_length':[20,25,30,35,40,50]}}
    units={'drum_volume':'м³','boom_length':'м','body_volume':'м³','lift_capacity':'т','reach':'м','bucket_volume':'м³'};b=InlineKeyboardBuilder()
    for v in presets.get(category,{}).get(key,[]):b.button(text=f'{v} {units[key]}',callback_data=f'{prefix}_spec:{key}:{v}')
    b.button(text='Другое' if lang=='ru' else 'Boshqa',callback_data=f'{prefix}_specother:{key}');b.adjust(3);return b.as_markup()
def location_keyboard(lang):return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='📍 Геолокация' if lang=='ru' else '📍 Geolokatsiya',request_location=True)]],resize_keyboard=True,one_time_keyboard=True)
def owner_order_keyboard(order_id,lang):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Принять' if lang=='ru' else 'Qabul qilish',callback_data=f'owner_accept:{order_id}'),InlineKeyboardButton(text='Отказаться' if lang=='ru' else 'Rad etish',callback_data=f'owner_decline:{order_id}')]])
def payment_keyboard(lang):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💳 Карта' if lang=='ru' else '💳 Karta',callback_data='payment:card'),InlineKeyboardButton(text='💵 Наличные' if lang=='ru' else '💵 Naqd',callback_data='payment:cash')],[InlineKeyboardButton(text='✕ Отменить' if lang=='ru' else '✕ Bekor qilish',callback_data='flow_cancel')]])
def start_work_keyboard(order_id,role,lang):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='▶️ Начать работу' if lang=='ru' else '▶️ Ishni boshlash',callback_data=f'start_work:{role}:{order_id}')]])
def completion_keyboard(order_id,role,lang):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='⏹ Завершить объект' if lang=='ru' else '⏹ Obyektni tugatish',callback_data=f'complete:{role}:{order_id}')]])
def admin_equipment_keyboard(eid):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Одобрить',callback_data=f'admin_eq_ok:{eid}'),InlineKeyboardButton(text='Отклонить',callback_data=f'admin_eq_no:{eid}')]])
def payment_confirm_customer_keyboard(order_id,lang='ru'):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Я оплатил' if lang=='ru' else "✅ To'ladim",callback_data=f'payment_customer:{order_id}')]])
def payment_confirm_owner_keyboard(order_id,lang='ru'):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Получил оплату' if lang=='ru' else "✅ To'lovni oldim",callback_data=f'payment_owner:{order_id}')]])
def commission_submit_keyboard(order_id,lang='ru'):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💳 Я оплатил комиссию' if lang=='ru' else "💳 Komissiyani to'ladim",callback_data=f'commission_submit:{order_id}')]])
def admin_commission_keyboard(order_id):return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Подтвердить оплату',callback_data=f'admin_commission_ok:{order_id}'),InlineKeyboardButton(text='❌ Отклонить',callback_data=f'admin_commission_no:{order_id}')]])
