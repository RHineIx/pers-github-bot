# Personal AI-Powered GitHub Stars Bot

A sophisticated, asynchronous Telegram bot designed to be your personal GitHub assistant.  
It actively monitors your starred repositories and delivers intelligent, media-rich notifications to your chosen destinations, turning your star list into a powerful, curated feed of information.

---

## ✨ Key Features

### 🤖 AI-Powered Summaries

Utilizes the Google Gemini Pro AI to read and summarize `README.md` files, providing you with a smart, concise description of what each project does, its purpose, and its key features.

### 🖼️ Smart Visual Previews

Intelligently extracts and selects the top 1–3 best preview images or GIFs from a repository's README and delivers them as a rich media album with every notification.

### 🔔 Advanced Notification Control

- **Digest Mode**: Switch between instant notifications for every new star, or receive a clean **Daily** or **Weekly** digest of all your new stars at a scheduled time.
- **Pause & Resume**: Temporarily pause and resume all notifications with simple commands, perfect for when you're on a _"starring spree"_.
- **Custom Interval**: Full control over the monitoring frequency, from minutes to hours.

### 🔒 Completely Private & Secure

- **Owner-Only**: Designed for a single user, the bot is hard-coded to only respond to its configured owner's User ID.
- **Secure Token Storage**: Your GitHub and AI API keys are stored securely.

### 🚀 High-Performance Backend

- **E-Tag Caching**: Implements an advanced E-Tag-based caching system to drastically reduce GitHub API usage and improve performance.
- **Fully Asynchronous**: Built from the ground up using `asyncio` and `pyTelegramBotAPI` (async) for high efficiency.

---

## 🚀 Available Commands

### Core Controls

```text
/start           - Shows the welcome message and command list.
/help            - Shows the command list.
/status          - Checks the bot's current status, GitHub account, API limits, and configured settings.
```

### Token Management

```text
/settoken <TOKEN>     - Securely saves your GitHub Personal Access Token. This is required.
/removetoken          - Deletes your stored GitHub token.
```

### Monitoring & Notification Settings

```text
/pause                - Temporarily pauses the monitoring service.
/resume               - Resumes the monitoring service.
/setinterval <secs>   - Sets the monitoring check interval (minimum 60 seconds).
/digest <daily|weekly|off>
                      - Sets the notification mode:
                          daily  => Receive digest daily
                          weekly => Receive digest weekly
                          off    => Receive instant notifications (default)
```

### Destination Management

```text
/add_dest [ID]        - Adds a notification destination. If no ID is provided, it adds your private chat (DM).
/remove_dest <ID|me>  - Removes a destination. Use 'me' to remove your private chat.
/list_dests           - Lists all currently configured notification destinations.
```

### Inline Mode

You can use the bot in any chat to quickly look up repositories or users:

```text
@YourBotUsername .repo owner/repo   - Get a rich, AI-summarized preview of any repository.
@YourBotUsername .user username     - Get a profile summary for any GitHub user.
```

---

## 🛠️ Setup & Installation

### Requirements

- Python 3.9+
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Your personal Telegram User ID from a bot like [@userinfobot](https://t.me/userinfobot)
- A Gemini API Key from [Google AI Studio](https://aistudio.google.com/app/apikey)

### Installation

**Clone the repository:**

```bash
git clone <your-repo-url>
cd <your-repo-folder>
```

**Install the required dependencies:**

```bash
pip install -r requirements.txt
```

**Create a `.env` file** in the root directory and fill it with your credentials:

```env
# Required
BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
OWNER_USER_ID="123456789"
GEMINI_API_KEY="AIzaSy...your_gemini_key"

# Optional: Change the AI model if needed
# GEMINI_MODEL_NAME="gemini-1.5-pro-latest"
```

### Running the Bot

```bash
python main.py
```

---

> Have suggestions or want to contribute? Feel free to open issues or pull requests!
