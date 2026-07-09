# 🎙️Blog to Podcast Agent 

A modern, AI-powered Streamlit web application that seamlessly transforms any blog post or article into an engaging, AI-narrated audio podcast. 

Built with **Streamlit**, **Agno Agents**, **Google Gemini**, **Firecrawl**, and **ElevenLabs**.

* <b>Author:</b> @aniketpotabatti
* <b>Created:</b> Aug 2025

---
## Video Overview

https://github.com/user-attachments/assets/9fee086b-707b-4d90-a420-8e59f9e65689

---
## ✨ Features

- **Sleek UI/UX:** A premium, fully responsive dark-themed glassmorphism interface.
- **Intelligent Web Scraping:** Uses Firecrawl to accurately extract content from any blog or article URL.
- **Smart Summarization:** Leverages Google Gemini via an Agno Agent to digest the article into a conversational, podcast-ready script (under 2,000 characters).
- **Ultra-Realistic Voice Synthesis:** Uses ElevenLabs' cutting-edge TTS models to generate a high-quality audio podcast.
- **Listen & Download:** Instantly play the generated podcast in your browser or download it as an `.mp3` file.

---

## 🛠️ Technology Stack

- **[Streamlit](https://streamlit.io/):** For building the interactive front-end web application.
- **[Agno](https://github.com/agno-agi/agno):** Agent orchestration framework.
- **[Google Gemini (2.5 Flash)](https://aistudio.google.com/):** Large Language Model used for natural language processing and podcast script generation.
- **[Firecrawl](https://www.firecrawl.dev/):** Intelligent web scraping tool to extract clean text from URLs.
- **[ElevenLabs](https://elevenlabs.io/):** Best-in-class AI voice generator for Text-to-Speech synthesis.

---

## 🚀 Getting Started

### Prerequisites

Ensure you have Python 3.9+ installed. You will also need API keys for the following services:
1. **Google Gemini API Key**
2. **Firecrawl API Key**
3. **ElevenLabs API Key** *(Note: Ensure your ElevenLabs API key has `text_to_speech` permissions enabled on your account tier)*

### Installation

1. **Clone or download this repository** and navigate to the project directory:
   ```bash
   cd "Blog to Podcasts agent"
   ```

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS/Linux
   source .venv/bin/activate
   ```

3. **Install the required dependencies**:
   *(Assuming requirements are saved in a `requirements.txt` file)*
   ```bash
   pip install -r requirements.txt
   ```
   *Core dependencies typically include:* `streamlit`, `agno`, `google-genai`, `firecrawl-py`, `elevenlabs`.

### Running the App

1. Start the Streamlit server:
   ```bash
   streamlit run blog_to_podcasts_agent.py
   ```
2. The application will open in your default web browser (typically at `http://localhost:8501`).
3. Enter your API keys in the left sidebar.
4. Paste a blog URL into the main input field.
5. Click **"✨ Generate Podcast"** and wait for the magic to happen!

---

## ⚠️ Troubleshooting

- **ElevenLabs API Error / Missing Permissions:** 
  If you encounter an error stating `missing_permissions` or `401 Unauthorized` during the Voice Synthesis step, ensure that your ElevenLabs API key has Text-to-Speech enabled. You may need to generate a new key from your [ElevenLabs Dashboard](https://elevenlabs.io/app/settings/api-keys).
- **Scraping Failures:**
  Some websites have strict anti-bot protections. If Firecrawl fails to scrape a page, try a different blog or ensure the URL is publicly accessible without a login or paywall.

---

## 📄 License

This project is licensed under the MIT License.
