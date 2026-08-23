import os, json, hmac, hashlib, urllib.parse, time
from pathlib import Path
from aiohttp import web
from aiogram import Bot
from database import *
from texts import t

BASE=Path(__file__).parent
BOT_TOKEN=os.getenv('BOT_TOKEN','')
web_bot=Bot(BOT_TOKEN) if BOT_TOKEN else None
_raw_admins=os.getenv('ADMIN_IDS','')
ADMIN_IDS={int(x.strip()) for x in _raw_admins.split(',') if x.strip().isdigit()}
ADMIN_USERNAMES={x.strip().lstrip('@').lower() for x in _raw_admins.split(',') if x.strip() and not x.strip().isdigit()}

def validate_init_user(raw):
    if not raw or not BOT_TOKEN:return None
    try:
        data=dict(urllib.parse.parse_qsl(raw,keep_blank_values=True)); received=data.pop('hash',None)
        if not received:return None
        check='\n'.join(f'{k}={data[k]}' for k in sorted(data))
        secret=hmac.new(b'WebAppData',BOT_TOKEN.encode(),hashlib.sha256).digest()
        expected=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,received):return None
        user=json.loads(data.get('user','{}'))
        return int(user['id']), str(user.get('username') or '').lstrip('@').lower()
    except Exception:return None

def validate_init_data(raw):
    result=validate_init_user(raw)
    return result[0] if result else None

def validate_web_token(token):
    if not token or not BOT_TOKEN:return None
    try:
        uid_s, exp_s, sig = token.split('.', 2)
        uid, exp = int(uid_s), int(exp_s)
        if exp < int(time.time()): return None
        payload=f'{uid}.{exp}'
        expected=hmac.new(BOT_TOKEN.encode(),payload.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,sig): return None
        return uid
    except Exception:
        return None

async def auth(request):
    token=request.headers.get('X-SpecTech-Auth','') or request.query.get('auth','')
    uid=validate_web_token(token)
    if uid:return uid
    uid=validate_init_data(request.headers.get('X-Telegram-Init-Data',''))
    if not uid:return None
    return uid

async def admin_auth(request):
    uid=validate_web_token(request.headers.get('X-SpecTech-Auth','') or request.query.get('auth',''))
    if uid:
        u=await get_user(uid)
        username=str(u['username'] or '').lstrip('@').lower() if u else ''
        if uid in ADMIN_IDS or username in ADMIN_USERNAMES or (u and u['role']=='admin'):
            return uid
        return None
    raw=request.headers.get('X-Telegram-Init-Data','')
    result=validate_init_user(raw)
    if not result:return None
    uid, username=result

    # Allow configured admins by numeric Telegram ID or username,
    # even if the database role has not been upgraded yet.
    if uid in ADMIN_IDS or username in ADMIN_USERNAMES:return uid

    u=await get_user(uid)
    if not u:return None
    if u['role']=='admin':return uid
    return None

def rowdict(r):return dict(r) if r else None
async def json_auth(request, fn):
    uid=await auth(request)
    if not uid:return web.json_response({'error':'unauthorized'},status=401)
    return await fn(uid)

async def admin_pending(request):
    uid=await admin_auth(request)
    if not uid:return web.json_response({'error':'forbidden'},status=403)
    try:
        return web.json_response({'equipment':[rowdict(x) for x in await get_pending_equipment()], 'commission':[rowdict(x) for x in await get_pending_commission_payments()], 'payments':[rowdict(x) for x in await get_pending_customer_payments()]})
    except Exception as ex:
        print('admin_pending error:', repr(ex))
        return web.json_response({'error':'server_error','detail':str(ex)}, status=500)
async def admin_active(request):
    uid=await admin_auth(request)
    if not uid:return web.json_response({'error':'forbidden'},status=403)
    return web.json_response({'orders':[rowdict(x) for x in await get_active_orders()]})
async def admin_equipment(request):
    uid=await admin_auth(request)
    if not uid:return web.json_response({'error':'forbidden'},status=403)
    return web.json_response({'equipment':[rowdict(x) for x in await get_verified_equipment()]})
async def admin_eq_status(request):
    uid=await admin_auth(request)
    if not uid:return web.json_response({'error':'forbidden'},status=403)
    eid=int(request.match_info['eid']); data=await request.json(); action=data.get('action')
    e=await get_equipment(eid)
    if not e:return web.json_response({'error':'not found'},status=404)
    if action=='approve':
        await verify_equipment(eid,True)
        if web_bot and e['owner_id']:
            try:
                u=await get_user(e['owner_id']); l=(u['language'] or 'ru') if u else 'ru'
                await web_bot.send_message(e['owner_id'], t('equipment_approved',l).format(id=eid))
            except Exception as ex: print('equipment approve notify error:',ex)
    elif action=='freeze':
        await set_equipment_status(eid,'frozen')
    elif action=='unfreeze':
        await set_equipment_status(eid,'available')
    elif action=='delete':
        await delete_equipment(eid)
        if web_bot and e['owner_id']:
            try:
                u=await get_user(e['owner_id']); l=(u['language'] or 'ru') if u else 'ru'
                await web_bot.send_message(e['owner_id'], t('equipment_rejected',l).format(id=eid))
            except Exception as ex: print('equipment delete notify error:',ex)
    else:return web.json_response({'error':'bad action'},status=400)
    return web.json_response({'ok':True})
async def admin_commission(request):
    uid=await admin_auth(request)
    if not uid:return web.json_response({'error':'forbidden'},status=403)
    oid=int(request.match_info['oid']);data=await request.json();ok=data.get('approved',False);o=await get_order(oid)
    if not o:return web.json_response({'error':'not found'},status=404)
    if ok:
        res=await mark_commission_paid(oid,None)
        if res and web_bot:
            ol=(await get_user(o['owner_id']))['language'] or 'ru'
            await web_bot.send_message(o['owner_id'],t('commission_paid_ok',ol))
    else:
        # Keep driver blocked and remove submitted flag so admin can see it was rejected.
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as db: await db.execute('UPDATE orders SET commission_payment_submitted=0 WHERE id=?',(oid,)); await db.commit()
        res=True
        if web_bot:
            ol=(await get_user(o['owner_id']))['language'] or 'ru'
            await web_bot.send_message(o['owner_id'],t('commission_rejected',ol))
    return web.json_response({'ok':bool(res),'approved':ok})
async def admin_payment(request):
    uid=await admin_auth(request)
    if not uid:return web.json_response({'error':'forbidden'},status=403)
    oid=int(request.match_info['oid']);data=await request.json();ok=bool(data.get('approved'));o=await get_order(oid)
    if not o:return web.json_response({'error':'not found'},status=404)
    res=await admin_confirm_customer_payment(oid,ok)
    if res and web_bot:
        if ok:
            ol=(await get_user(o['owner_id']))['language'] or 'ru'
            await web_bot.send_message(o['owner_id'],t('owner_confirm_payment',ol).format(id=oid,amount=o['final_amount']))
        else:
            cl=(await get_user(o['customer_id']))['language'] or 'ru'
            await web_bot.send_message(o['customer_id'],t('customer_payment_rejected',cl).format(id=oid,amount=o['final_amount']))
    return web.json_response({'ok':bool(res),'approved':ok})
async def owner_data(request):
    return await json_auth(request, lambda uid: owner_payload(uid))
async def owner_payload(uid):
    return web.json_response({'equipment':[rowdict(x) for x in await get_owner_equipment(uid)],'orders':[rowdict(x) for x in await get_owner_orders(uid)],'user':rowdict(await get_user(uid))})
async def history_data(request):
    return await json_auth(request, lambda uid: history_payload(uid))
async def history_payload(uid):
    u=await get_user(uid)
    role=(u['role'] if u else '')
    orders=await get_owner_orders(uid) if role=='owner' else await get_customer_orders(uid)
    return web.json_response({'role':role,'orders':[rowdict(x) for x in orders]})

async def serve(name):
    return web.FileResponse(BASE/'webapp'/name)

async def health(request):
    return web.json_response({'ok': True, 'service': 'spectech'})

def setup_web(app):
    app.router.add_get('/health',health)
    app.router.add_get('/admin',lambda r:serve('admin.html'))
    app.router.add_get('/owner',lambda r:serve('owner.html'))
    app.router.add_get('/history',lambda r:serve('history.html'))
    app.router.add_get('/api/admin/pending',admin_pending)
    app.router.add_get('/api/admin/active',admin_active)
    app.router.add_get('/api/admin/equipment',admin_equipment)
    app.router.add_post('/api/admin/equipment/{eid}/status',admin_eq_status)
    app.router.add_post('/api/admin/commission/{oid}',admin_commission)
    app.router.add_post('/api/admin/payment/{oid}',admin_payment)
    app.router.add_get('/api/owner',owner_data)
    app.router.add_get('/api/history',history_data)
    app.router.add_static('/webapp/',BASE/'webapp',show_index=False)
    return app
