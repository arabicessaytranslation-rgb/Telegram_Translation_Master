import os
import re
import json
import datetime
import smtplib
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from difflib import SequenceMatcher

import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ==========================================
# 1. إعدادات النظام الأساسية
# ==========================================
TELEGRAM_BOT_TOKEN = "8833047165:AAGUQYdoagBjyGzznLrwhZzXFfldZX7J32Y"
ALLOWED_USERS = [747904641]

SENDER_EMAIL = "arabicessaytranslation@gmail.com"
SENDER_PASSWORD = "dgvk rvdg sexp hyed"
TEAM_RECIPIENTS = [
    "arabicessaytranslation@gmail.com",
    "ameermam.sa@gmail.com",
    "mohammedd9644@gmail.com",
    "keepcomingback.29@gmail.com",
    "ahmad2075533@gmail.com"
]

ROOT_TRANSLATION_FOLDER_ID = "1x-0O_GQfdYtMFRREBlpO9l5kRw2toA-j"
SHEET_ID = "1405qDECZXQ2rYfGfVVFDMCfrXleDBwhFKZc8RgB6MG0"
TRACKER_HEADERS = ["المترجم", "المدقق", "المسجل", "عنوان المقال", "رابط المقال", "السنة والشهر للعدد"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly"
]

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

# ==========================================
# 2. مصادقة جوجل ودوال درايف (من كود Streamlit)
# ==========================================
def get_google_services():
    # قراءة توكن المستخدم من متغيرات البيئة لتجاوز مشكلة مساحة الـ Service Account
    token_str = os.environ.get('GCP_OAUTH_TOKEN')
    if not token_str:
        raise Exception("لم يتم العثور على GCP_OAUTH_TOKEN في متغيرات البيئة.")
    
    creds_dict = json.loads(token_str)
    creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)
    
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    docs_service = build('docs', 'v1', credentials=creds, cache_discovery=False)
    return gc, drive_service, docs_service

def extract_folder_id(url):
    match = re.search(r'folders/([a-zA-Z0-9_-]+)', url)
    return match.group(1) if match else None

def strip_copy_prefix(name):
    pattern = r'^(?:(?:copy\b(?:\s*\(\d+\)|\s+\d+)?\s+of\s*)|(?:نسخة\b(?:\s*\(\d+\)|\s+\d+)?\s+من\s*)|(?:copy\s*[:\-])\s*)+'
    return re.sub(pattern, '', name, flags=re.IGNORECASE).strip()

def clean_article_title(raw_title):
    title = strip_copy_prefix(raw_title)
    title = re.sub(r'\.(docx|doc|gdoc|pdf)$', '', title, flags=re.IGNORECASE)
    title = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF\s]', ' ', title)
    return re.sub(r'\s+', ' ', title).strip().lower()

def extract_article_number(title):
    match = re.search(r'^\s*(\d+)\s*[\.\-_]', title)
    if match:
        return int(match.group(1))
    nums = re.findall(r'\b\d+\b', title)
    return int(nums[0]) if nums else 9999

def compute_title_similarity(t1, t2):
    c1, c2 = clean_article_title(t1), clean_article_title(t2)
    if not c1 or not c2: return 0.0
    if c1 == c2: return 1.0
    if c1 in c2 or c2 in c1: return max(0.85, SequenceMatcher(None, c1, c2).ratio())
    return SequenceMatcher(None, c1, c2).ratio()

def list_subfolders(drive_service, parent_id):
    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = drive_service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, pageSize=100).execute()
    return res.get('files', [])

def list_files_in_folder(drive_service, folder_id):
    query = f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
    res = drive_service.files().list(q=query, fields="files(id, name, mimeType)", supportsAllDrives=True, pageSize=100).execute()
    return res.get('files', [])

def get_or_create_folder(drive_service, parent_id, folder_name):
    metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    created = drive_service.files().create(body=metadata, fields='id', supportsAllDrives=True).execute()
    return created.get('id')

def count_words(docs_service, document_id):
    try:
        doc = docs_service.documents().get(documentId=document_id).execute()
        text = "".join([
            p.get('textRun', {}).get('content', '')
            for e in doc.get('body', {}).get('content', []) if 'paragraph' in e
            for p in e.get('paragraph', {}).get('elements', []) if 'textRun' in p
        ])
        return len(re.findall(r'\b\w+\b', text))
    except Exception:
        return 0

def compare_file_lists(source_files, dest_files, similarity_threshold=0.75):
    similar_pairs, new_files = [], []
    for s_file in source_files:
        clean_s_name = strip_copy_prefix(s_file['name'])
        best_dest_match, max_sim = None, 0.0
        for d_file in dest_files:
            clean_d_name = strip_copy_prefix(d_file['name'])
            sim = compute_title_similarity(clean_s_name, clean_d_name)
            if sim > max_sim:
                max_sim, best_dest_match = sim, d_file
        if max_sim >= similarity_threshold and best_dest_match:
            similar_pairs.append({"source_name": s_file['name'], "clean_name": clean_s_name})
        else:
            new_files.append({"id": s_file['id'], "name": s_file['name'], "clean_name": clean_s_name, "mimeType": s_file.get('mimeType', '')})
    return similar_pairs, new_files

# ==========================================
# 3. تحديث الإكسل وإرسال الإيميل (HTML)
# ==========================================
def reset_and_populate_tracker(gc, sheet_id, year, month_name, month_num, records):
    sheet = gc.open_by_key(sheet_id).worksheet("Translation_Tracker")
    sheet.clear()
    sheet.update(range_name='A1:F1', values=[TRACKER_HEADERS], value_input_option='USER_ENTERED')
    
    if not records: return 0
    
    sorted_records = sorted(records, key=lambda x: extract_article_number(x["clean_name"]))
    edition_label = f"{month_num:02d} - {month_name} {year}"
    
    rows_payload = [["", "", "", r["clean_name"], f'=HYPERLINK("{r["doc_url"]}", "افتح المقال")', edition_label] for r in sorted_records]
    sheet.update(range_name=f'A2:F{len(rows_payload)+1}', values=rows_payload, value_input_option='USER_ENTERED')
    return len(rows_payload)

def send_monthly_notification_email(table_data, edition_label, sheet_id):
    sheet_link = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    total_articles = len(table_data) - 1
    total_words = sum([r[1] for r in table_data[1:] if isinstance(r[1], int)])

    msg = MIMEMultipart("alternative")
    msg['Subject'] = f"📢 تحديث: مقالات عدد ({edition_label}) جاهزة للعمل"
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(TEAM_RECIPIENTS)

    rows_html = ""
    for idx, row in enumerate(table_data[1:], 1):
        bg = "#f8fafc" if idx % 2 == 0 else "#ffffff"
        rows_html += f"""
        <tr style="background-color: {bg}; border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 10px; text-align: center; color: #64748b; font-weight: bold;">{idx}</td>
          <td style="padding: 10px; text-align: right; color: #1e293b; font-weight: 500;">{row[0]}</td>
          <td style="padding: 10px; text-align: center; color: #0f172a; font-weight: bold;">{row[1]}</td>
          <td style="padding: 10px; text-align: center;">
            <a href="{row[2]}" style="background-color: #0284c7; color: #ffffff; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-size: 13px; font-weight: bold;">افتح المقال</a>
          </td>
        </tr>
        """
    html = f"""<html dir="rtl"><body style="font-family: Arial, sans-serif; background-color: #f1f5f9; padding: 25px;"><div style="max-width: 680px; margin: auto; background-color: #ffffff; border-radius: 8px; overflow: hidden;"><div style="background-color: #0f172a; padding: 20px; text-align: center; color: #ffffff;"><h2>إصدار المقالات الجديد: {edition_label}</h2></div><div style="padding: 24px;"><div style="display: flex; gap: 10px; margin-bottom: 20px; text-align: center;"><div style="flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px;"><span style="color: #64748b;">المقالات</span><div style="font-size: 20px; font-weight: bold;">{total_articles}</div></div><div style="flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px;"><span style="color: #64748b;">الكلمات</span><div style="font-size: 20px; font-weight: bold; color: #0284c7;">{total_words:,}</div></div></div><div style="text-align: center; margin-bottom: 25px;"><a href="{sheet_link}" style="background-color: #16a34a; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">📋 فتح جدول المتابعة لتوزيع المهام</a></div><table style="width: 100%; border-collapse: collapse;"><thead><tr style="background-color: #f1f5f9; border-bottom: 2px solid #cbd5e1;"><th style="padding: 10px;">#</th><th style="padding: 10px; text-align: right;">العنوان</th><th style="padding: 10px;">الكلمات</th><th style="padding: 10px;">المستند</th></tr></thead><tbody>{rows_html}</tbody></table></div></div></body></html>"""
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)

def execute_article_transfer(files_to_transfer, dest_folder_id, year, month_name, month_num):
    gc, drive_service, docs_service = get_google_services()
    new_records = []
    email_table_data = [["عنوان المقال", "عدد الكلمات", "رابط المستند"]]
    edition_label = f"{month_num:02d} - {month_name} {year}"

    for f_info in files_to_transfer:
        clean_name = f_info['clean_name']
        copy_meta = {'name': clean_name, 'parents': [dest_folder_id]}
        
        # Auto-convert Word files
        if f_info.get('mimeType') in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/msword']:
            copy_meta['mimeType'] = 'application/vnd.google-apps.document'

        copied = drive_service.files().copy(fileId=f_info['id'], body=copy_meta, fields="id", supportsAllDrives=True).execute()
        doc_id = copied['id']
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        word_count = count_words(docs_service, doc_id)

        record = {"clean_name": clean_name, "word_count": word_count, "doc_url": doc_url, "file_id": doc_id}
        new_records.append(record)
        email_table_data.append([clean_name, word_count, doc_url])

    # Update sheet for ALL files in destination (old + newly copied)
    all_dest_files = list_files_in_folder(drive_service, dest_folder_id)
    cached_records = {r["file_id"]: r for r in new_records}
    final_sheet_records = []
    
    for f in all_dest_files:
        f_id = f['id']
        if f_id in cached_records:
            final_sheet_records.append(cached_records[f_id])
        else:
            f_clean = strip_copy_prefix(f['name'])
            f_url = f"https://docs.google.com/document/d/{f_id}/edit"
            f_words = count_words(docs_service, f_id)
            final_sheet_records.append({"clean_name": f_clean, "word_count": f_words, "doc_url": f_url, "file_id": f_id})

    reset_and_populate_tracker(gc, SHEET_ID, year, month_name, month_num, final_sheet_records)
    send_monthly_notification_email(email_table_data, edition_label, SHEET_ID)
    return new_records

# ==========================================
# 4. محادثات وتفاعلات تيليجرام
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS: return
    await update.message.reply_text("أهلاً بك يا مدير 🫡\nأرسل لي **رابط مجلد Google Drive** للمنسق لنبدأ الإصدار الشهري.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS: return
    url = update.message.text.strip()
    folder_id = extract_folder_id(url)
    
    if not folder_id:
        await update.message.reply_text("⚠️ الرابط غير صحيح.")
        return

    context.user_data.clear()
    context.user_data['source_folder_id'] = folder_id

    # عرض أزرار السنة
    current_year = datetime.datetime.now().year
    keyboard = [[InlineKeyboardButton(str(y), callback_data=f"year_{y}")] for y in range(current_year - 1, current_year + 3)]
    await update.message.reply_text("📅 **خطوة 1:** اختر سنة الإصدار:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- Step 2: اختيار الشهر ---
    if data.startswith("year_"):
        context.user_data['year'] = int(data.split("_")[1])
        keyboard = [
            [InlineKeyboardButton(MONTHS[i], callback_data=f"month_{i+1}"), InlineKeyboardButton(MONTHS[i+1], callback_data=f"month_{i+2}")]
            for i in range(0, 12, 2)
        ]
        await query.edit_message_text(f"✅ تم اختيار السنة: {context.user_data['year']}\n\n🗓 **خطوة 2:** اختر شهر الإصدار:", reply_markup=InlineKeyboardMarkup(keyboard))

    # --- Step 3: فحص الملفات والتشابه ---
    elif data.startswith("month_"):
        month_num = int(data.split("_")[1])
        month_name = MONTHS[month_num - 1]
        year = context.user_data['year']
        source_id = context.user_data['source_folder_id']
        
        context.user_data['month_num'] = month_num
        context.user_data['month_name'] = month_name
        
        await query.edit_message_text("⏳ جاري فحص الملفات ومطابقة العناوين... الرجاء الانتظار.")
        
        try:
            gc, drive_svc, docs_svc = get_google_services()
            source_files = list_files_in_folder(drive_svc, source_id)
            
            # البحث عن المجلد الوجهة
            year_folders = list_subfolders(drive_svc, ROOT_TRANSLATION_FOLDER_ID)
            matched_year = next((f for f in year_folders if str(year) in f['name']), None)
            
            dest_files = []
            target_month_folder = None
            if matched_year:
                m_folders = list_subfolders(drive_svc, matched_year['id'])
                for f in m_folders:
                    nums = re.findall(r'\b\d{1,2}\b', f['name'])
                    if month_name.lower() in f['name'].lower() or str(month_num) in nums or f"{month_num:02d}" in nums:
                        target_month_folder = f
                        dest_files = list_files_in_folder(drive_svc, f['id'])
                        break
            
            similar_pairs, new_files = compare_file_lists(source_files, dest_files)
            
            # حفظ النتائج في الجلسة للخطوة القادمة
            context.user_data['new_files'] = new_files
            context.user_data['source_files'] = [dict(f, clean_name=strip_copy_prefix(f['name'])) for f in source_files]
            context.user_data['target_m_id'] = target_month_folder['id'] if target_month_folder else None
            
            report = f"📊 **نتيجة الفحص (إصدار {month_num:02d}-{year}):**\n"
            report += f"• عدد الملفات في مجلد المنسق: {len(source_files)}\n"
            if target_month_folder:
                report += f"📁 المجلد المستهدف موجود مسبقاً وفيه {len(dest_files)} ملف.\n"
            
            if similar_pairs:
                report += f"\n⚠️ **تنبيه:** تم العثور على ({len(similar_pairs)}) ملفات مشابهة/مكررة.\n"
            
            keyboard = []
            if new_files:
                keyboard.append([InlineKeyboardButton(f"✅ نسخ الجديد فقط ({len(new_files)} ملف)", callback_data="action_new")])
            if source_files:
                keyboard.append([InlineKeyboardButton(f"⚡ نسخ كافة الملفات ({len(source_files)} ملف)", callback_data="action_all")])
            keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="action_cancel")])
            
            await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(keyboard))
            
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ أثناء الفحص: {e}")

    # --- Step 4: التنفيذ بناءً على قرارك ---
    elif data.startswith("action_"):
        action = data.split("_")[1]
        if action == "cancel":
            await query.edit_message_text("❌ تم الإلغاء بنجاح.")
            return
            
        await query.edit_message_text("⏳ جاري النسخ، التحويل لـ Docs، حساب الكلمات، تحديث الجدول وإرسال الإيميل...")
        
        try:
            files_to_transfer = context.user_data['new_files'] if action == "new" else context.user_data['source_files']
            year = context.user_data['year']
            month_name = context.user_data['month_name']
            month_num = context.user_data['month_num']
            
            gc, drive_svc, _ = get_google_services()
            
            # تجهيز المجلد الوجهة إذا لم يكن موجوداً
            target_m_id = context.user_data['target_m_id']
            if not target_m_id:
                year_folders = list_subfolders(drive_svc, ROOT_TRANSLATION_FOLDER_ID)
                matched_year = next((f for f in year_folders if str(year) in f['name']), None)
                year_id = matched_year['id'] if matched_year else get_or_create_folder(drive_svc, ROOT_TRANSLATION_FOLDER_ID, f"{year} Edition")
                target_m_id = get_or_create_folder(drive_svc, year_id, f"{month_num:02d} - {month_name} {year}")

            execute_article_transfer(files_to_transfer, target_m_id, year, month_name, month_num)
            
            await query.edit_message_text(f"🎉 **تمت العملية بنجاح!**\nتم نسخ ومعالجة ({len(files_to_transfer)}) مقال، وتحديث الجدول وإرسال البريد للفريق.")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ أثناء التنفيذ: {e}")

# ==========================================
# 5. تشغيل المنظومة (Render Ready)
# ==========================================
def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    class SimpleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")
    server = HTTPServer(('', port), SimpleHandler)
    server.serve_forever()

def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("🤖 Streamlit-Logic Bot is running on Render...")
    app.run_polling()

if __name__ == '__main__':
    main()
