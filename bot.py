from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from PIL import Image, ImageDraw, ImageFont
import sqlite3
from io import BytesIO
import os

# Get the bot token from environment variables
TOKEN = os.getenv("BOT_TOKEN")
app = ApplicationBuilder().token(TOKEN).build()

# Database setup
conn = sqlite3.connect("votes.db", check_same_thread=False)
cursor = conn.cursor()

# Create tables
cursor.execute("""
CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE,
    username TEXT,
    name TEXT,
    vote_count INTEGER DEFAULT 0
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    username TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS channel (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER
)
""")
conn.commit()

# Function to create a banner
def create_banner(name, username):
    # Create a blank image with a white background
    img = Image.new("RGB", (600, 300), color="white")
    draw = ImageDraw.Draw(img)

    # Load a font
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except IOError:
        font = ImageFont.load_default()

    # Add text to the image
    draw.text((50, 50), f"Name: {name}", fill="black", font=font)
    draw.text((50, 120), f"Username: @{username}", fill="black", font=font)

    # Save the image to a BytesIO object
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return img_byte_arr

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Create inline keyboard
    keyboard = [[InlineKeyboardButton("Help", callback_data="help")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send welcome message with inline button
    await update.message.reply_text(
        "Welcome to the Voting Bot! 🎉\n\nUse the button below for help:",
        reply_markup=reply_markup
    )

# Help button callback
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "help":
        await query.message.edit_text(
            "Here's how to use the bot:\n\n"
            "1. Use /votep to participate in voting.\n"
            "2. Use the 'Vote' button under a participant's banner to vote.\n"
            "3. Admins can use /votef <username> <vote_count> to edit vote counts."
        )

# Set channel command
async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Usage: /setchannel <channel_id>")
        return

    channel_id = context.args[0]
    bot = context.bot

    try:
        chat = await bot.get_chat(channel_id)
        if chat.type != "channel":
            await update.message.reply_text("The provided ID is not a channel.")
            return

        admins = await bot.get_chat_administrators(channel_id)
        bot_id = (await bot.get_me()).id
        if not any(admin.user.id == bot_id for admin in admins):
            await update.message.reply_text("The bot must be an admin in the channel.")
            return

        # Save the channel ID
        cursor.execute("DELETE FROM channel")
        cursor.execute("INSERT INTO channel (channel_id) VALUES (?)", (channel_id,))
        conn.commit()
        await update.message.reply_text(f"Channel set to {channel_id} and verified.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}. Please check the channel ID and ensure the bot is added as an admin.")

# Register participant and create banner
async def handle_participant_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text or "@" not in text:
        await update.message.reply_text("Invalid format. Please send: Name @username")
        return

    name, username = text.split("@", 1)
    username = username.strip()

    # Create a banner
    banner = create_banner(name, username)

    # Save participant details to the database
    user = update.effective_user
    cursor.execute("INSERT OR IGNORE INTO votes (user_id, username, name) VALUES (?, ?, ?)", 
                   (user.id, username, name))
    conn.commit()

    # Inline keyboard with Vote button
    keyboard = [[InlineKeyboardButton("Vote", callback_data=f"vote_{user.id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the banner with the Vote button
    await update.message.reply_photo(
        photo=banner, 
        caption=f"Participant: {name} (@{username})",
        reply_markup=reply_markup
    )

# Handle voting via inline button
async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("vote_"):
        return

    participant_user_id = int(data.split("_")[1])
    voter = query.from_user

    cursor.execute("SELECT channel_id FROM channel")
    channel = cursor.fetchone()
    if not channel:
        await query.message.reply_text("Channel not set. Please contact an admin.")
        return

    channel_id = channel[0]
    bot = context.bot

    try:
        chat_member = await bot.get_chat_member(channel_id, voter.id)
        if chat_member.status not in ["member", "administrator", "creator"]:
            await query.message.reply_text("You must join the channel to vote.")
            return
    except Exception as e:
        await query.message.reply_text(f"Error: {e}. Please check if the bot is added to the channel.")
        return

    # Increment vote count
    cursor.execute("UPDATE votes SET vote_count = vote_count + 1 WHERE user_id = ?", (participant_user_id,))
    conn.commit()

    # Fetch updated vote count
    cursor.execute("SELECT vote_count FROM votes WHERE user_id = ?", (participant_user_id,))
    vote_count = cursor.fetchone()[0]

    # Update message caption with updated vote count
    await query.message.edit_caption(
        caption=f"Vote registered! 🎉\n\nCurrent vote count: {vote_count}"
    )

# Admin command to edit votes
async def votef(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /votef <username> <vote_count>")
        return

    user = update.effective_user
    cursor.execute("SELECT * FROM admins WHERE user_id = ?", (user.id,))
    if not cursor.fetchone():
        await update.message.reply_text("You are not authorized to use this command.")
        return

    username = context.args[0]
    vote_count = int(context.args[1])

    cursor.execute("UPDATE votes SET vote_count = ? WHERE username = ?", (vote_count, username))
    conn.commit()
    await update.message.reply_text(f"Vote count for @{username} updated to {vote_count}.")

# Handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("setchannel", set_channel))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_participant_details))
app.add_handler(CallbackQueryHandler(vote_callback))
app.add_handler(CommandHandler("votef", votef))

# Run the bot
print("Bot is running...")
app.run_polling()
