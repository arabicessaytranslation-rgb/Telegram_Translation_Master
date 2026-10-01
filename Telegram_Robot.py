import os
import re
import datetime
import smtplib
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ==========================================
# 0. تهيئة ملف الـ JSON أماناً من متغيرات البيئة على Render
# ==========================================
if not os.path.exists('service_account.json'):
    json_data = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if json_data:
        with open('service_account.json', 'w', encoding='utf-8') as f:
            f.write(json_data)

# ==========================================
# 1. إعدادات النظام الأساسية
# ==========================================
TELEGRAM_BOT_TOKEN = "8833047165:AAGUQYdoagBjyGzznLrwhZzXFfldZX7J32Y"

# القائمة البيضاء: أضف رقم الـ ID الخاص بك هنا (مسموح له فقط باستخدام البوت)
ALLOWED_USERS = [747904641]

# إعدادات البريد الإلكتروني والإشعارات
SENDER_EMAIL = "arabicessaytranslation@gmail.com"
SENDER_PASSWORD = "dgvk rvdg sexp hyed"
TEAM_RECIPIENTS = [
    "arabicessaytranslation@gmail.com",
    "ameermam.sa@gmail.com",
    "mohammedd9644@gmail.com",
    "keepcomingback.29@gmail.com",
    "ahmad2075533@gmail.com"
]

# معرفات المجلدات والملفات على جوجل درايف
ROOT_TRANSLATION_FOLDER_ID = "1x-0O_GQfdYtMFRREBlpO9l5kRw2toA-j"
SHEET_ID = "1405qDECZXQ2rYfGfVVFDMCfrXleDBwhFKZc8RgB6MG0"
TRACKER_HEADERS = ["المترجم", "المدقق", "المسجل", "عنوان المقال", "رابط المقال", "السنة والشهر للعدد"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly"
]

# ==========================================
# 2. دوال معالجة جوجل درايف والملفات
# ==========================================
def get_google_services():
    # قراءة بيانات الاعتماد من ملف الـ JSON
    creds = service_account.Credentials.from_service_account_file(
        'service_account.json', scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    drive_svc = build('drive', 'v3', credentials=creds, cache_discovery=False)
    docs_svc = build('docs', 'v1', credentials=creds, cache_discovery=False)
    return gc, drive_svc, docs_svc

def extract_folder_id(url):
    match = re.search(r'folders/([a-zA-Z0-9_-]+)', url)
    return match.group(1) if match else None

def strip_copy_prefix(name):
    pattern = r'^(?:(?:copy\b(?:\s*\(\d+\)|\s+\d+)?\s+of\s*)|(?:نسخة\b(?:\s*\(\d+\)|\s+\d+)?\s+من\s*)|(?:copy\s*[:\-])\s*)+'
    return re.sub(pattern, '', name, flags=re.IGNORECASE).strip()

def get_or_create_folder(drive_svc, parent_id, folder_name):
    metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    created = drive_svc.files().create(body=metadata, fields='id', supportsAllDrives=True).execute()
    return created.get('id')

def list_files_in_folder(drive_svc, folder_id):
    query = f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
    res = drive_svc.files().list(q=query, fields="files(id, name, mimeType)", supportsAllDrives=True, pageSize=100).execute()
    return res.get('files', [])

def count_words(docs_svc, document_id):
    try:
        doc = docs_svc.documents().get(documentId=document_id).execute()
        text = "".join([
            p.get('textRun', {}).get('content', '')
            for e in doc.get('body', {}).get('content', []) if 'paragraph' in e
            for p in e.get('paragraph', {}).get('elements', []) if 'textRun' in p
        ])
        return len(re.findall(r'\b\w+\b', text))
    except Exception:
        return 0

def process_transfer(files_to_transfer, dst_folder_id, month_label):
    gc, drive_svc, docs_svc = get_google_services()
    records = []

    for f in files_to_transfer:
        clean_name = strip_copy_prefix(f['name'])
        copy_meta = {'name': clean_name, 'parents': [dst_folder_id]}

        # تحويل ملفات الوورد إلى Google Docs تلقائياً أثناء النسخ
        if f.get('mimeType') in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/msword']:
            copy_meta['mimeType'] = 'application/vnd.google-apps.document'

        copied = drive_svc.files().copy(fileId=f['id'], body=copy_meta, fields="id", supportsAllDrives=True).execute()
        doc_id = copied['id']
        records.append({
            "name": clean_name,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
            "words": count_words(docs_svc, doc_id)
        })

    update_tracker(gc, records, month_label)
    send_email(records, month_label)
    return records

def update_tracker(gc, records, month_label):
    sheet = gc.open_by_key(SHEET_ID).worksheet("Translation_Tracker")
    sheet.clear()
    sheet.update(range_name='A1:F1', values=[TRACKER_HEADERS], value_input_option='USER_ENTERED')

    rows = []
    for r in records:
        rows.append(["", "", "", r["name"], f'=HYPERLINK("{r["url"]}", "افتح المقال")', month_label])

    if rows:
        sheet.update(range_name=f'A2:F{len(rows)+1}', values=rows, value_input_option='USER_ENTERED')

def send_email(records, title):
    msg = MIMEMultipart()
    msg['Subject'] = f"📢 تم إنجاز ونقل المهام: {title}"
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(TEAM_RECIPIENTS)

    html = f"<h2 dir='rtl'>ملخص نقل الملفات: {title}</h2><ul dir='rtl'>"
    for r in records:
        html += f"<li><b>{r['name']}</b> ({r['words']} كلمة) - <a href='{r['url']}'>الرابط</a></li>"
    html += "</ul>"

    msg.attach(MIMEText(html, 'html', 'utf-8'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)

# ==========================================
# 3. توجيهات وأوامر تيليجرام
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        await update.message.reply_text("عذراً، هذا البوت مخصص لمدير المشروع فقط.")
        return
    await update.message.reply_text(
        "أهلاً بك يا مدير 🫡\n"
        "أرسل لي الآن **رابط مجلد Google Drive** الخاص بالمنسق لأقوم بفحصه وتجهيزه."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return

    url = update.message.text.strip()
    folder_id = extract_folder_id(url)
    if not folder_id:
        await update.message.reply_text("⚠️ الرابط غير صحيح، يرجى إرسال رابط مجلد Google Drive صالح.")
        return

    context.user_data['pending_folder_id'] = folder_id

    try:
        _, drive_svc, _ = get_google_services()
        files = list_files_in_folder(drive_svc, folder_id)
        if not files:
            await update.message.reply_text("⚠️ المجلد فارغ ولا يحتوي على ملفات.")
            return

        keyboard = [
            [InlineKeyboardButton("✅ تأكيد النقل، التحويل، والتحديث", callback_data="confirm_transfer")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_transfer")]
        ]
        await update.message.reply_text(
            f"📊 تم فحص المجلد بنجاح!\n• عدد الملفات المكتشفة: {len(files)}\n\nهل تريد تنفيذ العملية الآن؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في الاتصال بجوجل درايف: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_transfer":
        await query.edit_message_text("❌ تم الإلغاء.")
        return

    if query.data == "confirm_transfer":
        folder_id = context.user_data.get('pending_folder_id')
        if not folder_id:
            await query.edit_message_text("⚠️ انتهت الجلسة، أرسل الرابط من جديد.")
            return

        await query.edit_message_text("⏳ جاري نسخ الملفات، التحويل، وتحديث السجل وإرسال البريد...")

        try:
            _, drive_svc, _ = get_google_services()
            files = list_files_in_folder(drive_svc, folder_id)

            now = datetime.datetime.now()
            year_label = f"{now.year} Edition"
            month_label = f"{now.month:02d} - {now.strftime('%B')} {now.year}"

            year_folder_id = get_or_create_folder(drive_svc, ROOT_TRANSLATION_FOLDER_ID, year_label)
            dst_folder_id = get_or_create_folder(drive_svc, year_folder_id, month_label)

            records = process_transfer(files, dst_folder_id, month_label)

            await query.edit_message_text(
                f"🎉 تمت العملية بنجاح!\n"
                f"• تم معالجة {len(records)} ملفاً.\n"
                f"• تم تحديث جدول المتابعة والإيميلات."
            )
        except Exception as e:
            await query.edit_message_text(f"❌ حدث خطأ أثناء المعالجة: {e}")

# ==========================================
# 4. تشغيل خادم الويب الوهمي والبوت معاً
# ==========================================
def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    class SimpleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive and running!")
    server = HTTPServer(('', port), SimpleHandler)
    server.serve_forever()

def main():
    # تشغيل خادم الويب في الخلفية للتوافق مع متطلبات Render
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("🤖 Production Bot is running on Render...")
    app.run_polling()

if __name__ == '__main__':
    main()
