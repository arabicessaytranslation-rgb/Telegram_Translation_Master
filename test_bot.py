from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ضع هنا التوكن الذي أعطاه لك BotFather
TELEGRAM_BOT_TOKEN = "8833047165:AAGUQYdoagBjyGzznLrwhZzXFfldZX7J32Y"

# ضع هنا رقم الـ ID الخاص بك الذي أخذته من userinfobot
MY_USER_ID = 747904641  # استبدل هذا الرقم برقمك الحقيقي

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # فحص الأمان (هل أنت المدير أم شخص غريب؟)
    if user_id != MY_USER_ID:
        await update.message.reply_text("عذراً، هذا البوت مخصص لمدير المشروع فقط.")
        return
        
    await update.message.reply_text("أهلاً بك يا مدير! البوت يعمل بنجاح وجاهز لأوامرك 🫡")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    
    print("البوت يعمل الآن وينتظر إشارتك...")
    app.run_polling()

if __name__ == '__main__':
    main()
