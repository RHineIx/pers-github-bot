# In bot/telegram_log_handler.py
import logging
import traceback
import telebot # We use the synchronous version here for simplicity in a logging handler.

class TelegramLogHandler(logging.Handler):
    """
    A custom logging handler that sends log records to a specified Telegram channel.
    It's designed to notify the owner of critical errors in the bot.
    """
    def __init__(self, token: str, channel_id: str):
        super().__init__()
        self.token = token
        self.channel_id = channel_id
        # Initialize a synchronous bot instance for sending log messages.
        self.bot = telebot.TeleBot(token)

    def emit(self, record: logging.LogRecord):
        """
        This method is called for every log record.
        It formats the message and sends it to the Telegram channel.
        """
        # Format the log record into a string.
        log_entry = self.format(record)
        
        # Prepare a clean message for Telegram.
        # HTML for better formatting.
        message = f"<b>⭕ ERROR ⭕</b>\n\n"
        message += f"<pre>{log_entry}</pre>"
        
        # Truncate the message if it's too long for Telegram.
        if len(message) > 4096:
            message = message[:4090] + "\n..."

        try:
            # Send the formatted log message.
            self.bot.send_message(
                self.channel_id,
                message,
                parse_mode='HTML'
            )
        except Exception as e:
            # If sending the log fails, print the error to the console.
            # This avoids an infinite loop of logging errors.
            print(f"FATAL: Could not send log to Telegram channel: {e}")
            print(f"Original Log Message: {log_entry}")