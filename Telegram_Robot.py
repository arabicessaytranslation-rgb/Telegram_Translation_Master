import os
import re
import requests
import smtplib
import threading
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# --- الإعدادات الأساسية ---
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

# ⚠️ ضع هنا رابط الـ Web App الذي حصلت عليه من Google Apps Script
GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbzFdgnidkbay1WUOTj9fOUrveSuZe_RUnh9jL4cqHt8ljExBPAVTIs2vcAPuwqPcIJS/exec"
GAS_SECRET_KEY = "123456789"

SHEET_ID = "1405qDECZXQ2rYfGfVVFDMCfrXleDBwhFKZc8RgB6MG0"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

def extract_folder_id(url):
    match = re.search(r'folders/([a-zA-Z0-9_-]+)', url)
    return match.group(1) if match else None

# --- إرسال الإيميل بنفس تصميم Streamlit ---
def send_notification_email(records, edition_label):
    sheet_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
    total_articles = len(records)
    total_words = sum([r.get('words', 0) for r in records])

    msg = MIMEMultipart("alternative")
    msg['Subject'] = f"📢 تحديث: مقالات عدد ({edition_label}) جاهزة للعمل"
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(TEAM_RECIPIENTS)

    rows_html = ""
    for idx, r in enumerate(records, 1):
        bg = "#f8fafc" if idx % 2 == 0 else "#ffffff"
        rows_html += f"""
        <tr style="background-color: {bg}; border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 10px; text-align: center; color: #64748b; font-weight: bold;">{idx}</td>
          <td style="padding: 10px; text-align: right; color: #1e293b; font-weight: 500;">{r['name']}</td>
          <td style="padding: 10px; text-align: center; color: #0f172a; font-weight: bold;">{r['words']}</td>
          <td style="padding: 10px; text-align: center;">
            <a href="{r['url']}" style="background-color: #0284c7; color: #ffffff; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-size: 13px; font-weight: bold;">افتح المقال</a>
          </td>
        </tr>
        """
    
    html = f"""<html dir="rtl"><body style="font-family: Arial, sans-serif; background-color: #f1f5f9; padding: 25px;"><div style="max-width: 680px; margin: auto; background-color: #ffffff; border-radius: 8px; overflow: hidden;"><div style="background-color: #0f172a; padding: 20px; text-align: center; color: #ffffff;"><h2>إصدار المقالات الجديد: {edition_label}</h2></div><div style="padding: 24px;"><div style="display: flex; gap: 10px; margin-bottom: 20px; text-align: center;"><div style="flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px;"><span style="color: #64748b;">المقالات</span><div style="font-size: 20px; font-weight: bold;">{total_articles}</div></div><div style="flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px;"><span style="color: #64748b;">الكلمات</span><div style="font-size: 20px; font-weight: bold; color: #0284c7;">{total_words:,}</div></div></div><div style="text-align: center; margin-bottom: 25px;"><a href="{sheet_link}" style="background-color: #16a34a; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">📋 فتح جدول المتابعة لتوزيع المهام</a></div><table style="width: 100%; border-collapse: collapse;"><thead><tr style="background-color: #f1f5f9; border-bottom: 2px solid #cbd5e1;"><th style="padding: 10px;">#</th><th style="padding: 10px; text-align: right;">العنوان</th><th style="padding: 10px;">الكلمات</th><th style="padding: 10px;">المستند</th></tr></thead><tbody>{rows_html}</tbody></table></div></div></body></html>"""
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)

# --- محادثات تيليجرام ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS: return
    await update.message.reply_text("أهلاً بك يا مدير 🫡\nأرسل لي **رابط مجلد Google Drive** للمنسق.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS: return
    url = update.message.text.strip()
    if not extract_folder_id(url):
        await update.message.reply_text("⚠️ الرابط غير صحيح.")
        return

    context.user_data.clear()
    context.user_data['sourceUrl'] = url

    current_year = datetime.datetime.now().year
    keyboard = [[InlineKeyboardButton(str(y), callback_data=f"year_{y}")] for y in range(current_year - 1, current_year + 3)]
    await update.message.reply_text("📅 **خطوة 1:** اختر سنة الإصدار:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("year_"):
        context.user_data['year'] = int(data.split("_")[1])
        keyboard = [
            [InlineKeyboardButton(MONTHS[i], callback_data=f"month_{i+1}"), InlineKeyboardButton(MONTHS[i+1], callback_data=f"month_{i+2}")]
            for i in range(0, 12, 2)
        ]
        await query.edit_message_text(f"✅ السنة: {context.user_data['year']}\n\n🗓 **خطوة 2:** اختر شهر الإصدار:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("month_"):
        month_num = int(data.split("_")[1])
        month_name = MONTHS[month_num - 1]
        context.user_data['month_num'] = month_num
        context.user_data['month_name'] = month_name
        
        await query.edit_message_text("⏳ جاري الفحص في خوادم جوجل... الرجاء الانتظار.")
        
        # التواصل مع GAS لفحص المجلد
        payload = {
            "secret": GAS_SECRET_KEY, "action": "check",
            "sourceUrl": context.user_data['sourceUrl'], "year": context.user_data['year'],
            "monthName": month_name, "monthNum": month_num
        }
        
        try:
            res = requests.post(GAS_WEBAPP_URL, json=payload).json()
            if "error" in res:
                await query.edit_message_text(f"❌ خطأ من جوجل: {res['error']}")
                return
                
            context.user_data['targetFolderId'] = res.get('targetFolderId')
            context.user_data['newFiles'] = res.get('newFiles', [])
            context.user_data['sourceFiles'] = res.get('sourceFiles', [])
            
            report = f"📊 **نتيجة الفحص:**\n• ملفات المنسق: {len(res['sourceFiles'])}\n"
            if res['targetFolderId']: report += "📁 المجلد المستهدف موجود مسبقاً.\n"
            if res.get('similarPairs'): report += f"⚠️ تنبيه: تم رصد ({len(res['similarPairs'])}) ملف مشابه مسبقاً.\n"
            
            keyboard = []
            if res['newFiles']: keyboard.append([InlineKeyboardButton(f"✅ نسخ الجديد فقط ({len(res['newFiles'])})", callback_data="action_new")])
            if res['sourceFiles']: keyboard.append([InlineKeyboardButton(f"⚡ نسخ الكل ({len(res['sourceFiles'])})", callback_data="action_all")])
            keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="action_cancel")])
            
            await query.edit_message_text(report, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في الاتصال: {e}")

    elif data.startswith("action_"):
        action = data.split("_")[1]
        if action == "cancel":
            await query.edit_message_text("❌ تم الإلغاء.")
            return
            
        await query.edit_message_text("⏳ جاري النقل، التحويل، والتحديث في الخلفية... لا تقاطع العملية.")
        
        files_to_transfer = context.user_data['newFiles'] if action == "new" else context.user_data['sourceFiles']
        
        payload = {
            "secret": GAS_SECRET_KEY, "action": "transfer",
            "filesToTransfer": files_to_transfer,
            "targetFolderId": context.user_data.get('targetFolderId'),
            "year": context.user_data['year'], "monthName": context.user_data['month_name'], "monthNum": context.user_data['month_num']
        }
        
        try:
            res = requests.post(GAS_WEBAPP_URL, json=payload).json()
            if "error" in res:
                await query.edit_message_text(f"❌ خطأ من جوجل: {res['error']}")
                return
            
            # إرسال الإيميل بواسطة البايثون (لتجاوز حدود إيميلات جوجل)
            send_notification_email(res['emailData'], res['editionLabel'])
            await query.edit_message_text(f"🎉 **تمت العملية بنجاح!**\nتم معالجة الملفات وتحديث الجدول وإرسال الإيميل.")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ أثناء المعالجة: {e}")

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
    print("🤖 Bot is running with GAS backend...")
    app.run_polling()

if __name__ == '__main__':
    main()
