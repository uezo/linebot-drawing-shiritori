from contextlib import asynccontextmanager
import aiohttp
from linebot import AsyncLineBotApi, WebhookParser
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.models import TextSendMessage, ImageSendMessage
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from openai import AsyncClient

OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
SYSTEM_CONTENT = """あなたは私としりとりをしています。以下の条件に基づいて応答してください。

* ユーザー送ってきた画像は、ユーザーのターンの単語です。
* その画像に写っているものを認識します。画像は写真ではなくユーザーによるドローイングの場合もあります。たとえば寿司が写っていれば、ユーザーのターンの単語は「寿司」です。
* 次に、あなたのターンの単語を考えます。たとえばユーザーのターンの単語が「寿司」であれば、その読みは「スシ」であり、読みの末尾は「シ」です。そのため、あなたの単語は「シカ」や「シロネコ」になります。
* あなたのターンの単語だけを応答します。たとえば「シカ」や「シロネコ」だけを応答します。検討過程やその他の文言を入れることは許されません。
* ユーザーのターンの単語を応答することは厳禁です。たとえばコーヒーの画像を見せられて「コーヒー」と回答することは許されません。

例

user: スシ
assistant: シカ
user: カイ
assistant: イカ
user: カラス
assistant: スミレ

以上です。ユーザーの送ってきた画像がよく分からなくても、ベストを尽くしてください。間違っても問題ありません。自信を持ってプレイしましょう！
"""

# OpenAI
openai_client = AsyncClient(api_key=OPENAI_API_KEY)

# Tokens
YOUR_CHANNEL_ACCESS_TOKEN = "YOUR_CHANNEL_ACCESS_TOKEN"
YOUR_CHANNEL_SECRET = "YOUR_CHANNEL_SECRET"

# LINE Messagin API resources
session = aiohttp.ClientSession()
client = AiohttpAsyncHttpClient(session)
line_api = AsyncLineBotApi(
    channel_access_token=YOUR_CHANNEL_ACCESS_TOKEN,
    async_http_client=client
)
parser = WebhookParser(channel_secret=YOUR_CHANNEL_SECRET)

# Preparing FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await session.close()

app = FastAPI(lifespan=lifespan)
app.mount("/images", StaticFiles(directory="images"), name="images")

# Handler for events from LINE
async def handle_events(events):
    for ev in events:
        if ev.message.type == "image":
            # Get and save image
            image_stream = await line_api.get_message_content(ev.message.id)
            with open(f"./images/{ev.message.id}.png", "wb") as f:
                async for chunk in image_stream.iter_content():
                    f.write(chunk)

            # Talk with ChatGPT with image
            chatgpt_resp = await openai_client.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=[
                    {
                        "role": "system", "content": SYSTEM_CONTENT
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "これは私のターンの画像です。あなたのターンの単語を考えてください。"},
                            {"type": "image_url", "image_url": f"https://YOUR_DOMAIN/images/{ev.message.id}.png"}
                        ]
                    }
                ]
            )

            # Translate to english to get better response from DALL-E 3
            assistant_word = chatgpt_resp.choices[0].message.content
            print(assistant_word)
            translated_resp = await openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": f"「{assistant_word}」を英語に翻訳してください。翻訳した単語だけを応答してください。"}]
            )
            assistant_word_en = translated_resp.choices[0].message.content
            print(assistant_word_en)

            # Generate image with DALL-E 3
            dalle_resp = await openai_client.images.generate(
                prompt=f"{assistant_word_en}. Quick and simple drawing with a bold pen."
            )
            print(dalle_resp.data[0].url)

            # Send image
            await line_api.reply_message(
                ev.reply_token,
                ImageSendMessage(
                    original_content_url=dalle_resp.data[0].url,
                    preview_image_url=dalle_resp.data[0].url
                )
            )

        else:
            await line_api.reply_message(
                ev.reply_token,
                TextSendMessage(
                    text="画像を送ってね"
                )
            )

# WebHook request handler
@app.post("/linebot")
async def handle_request(request: Request, background_tasks: BackgroundTasks):
    events = parser.parse(
        (await request.body()).decode("utf-8"),
        request.headers.get("X-Line-Signature", "")
    )
    background_tasks.add_task(handle_events, events=events)
    return "ok"
