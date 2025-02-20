import io
import logging
import uuid
import asyncio
import os
import urllib3

import requests
import time
import json
import uvicorn
import nest_asyncio
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# https://urllib3.readthedocs.io/en/latest/advanced-usage.html#tls-warnings
urllib3.disable_warnings()

dp = Dispatcher()
router = Router()
dp.include_router(router)
app = FastAPI()

gif_cache_file = "gif_cache.json"
gif_cache = {}


def load_cache():
    global gif_cache
    if os.path.exists(gif_cache_file):
        try:
            with open(gif_cache_file, "r", encoding="UTF-8") as f:
                gif_cache = json.load(f)
        except Exception as e:
            logging.error(f"Failed to load cache: {e}")


def save_cache():
    try:
        with open(gif_cache_file, "w", encoding="UTF-8") as f:
            json.dump(gif_cache, f)
    except Exception as e:
        logging.error(f"Failed to save cache: {e}")


class BurningTextError(Exception):
    pass


class BurningTextAPIError(BurningTextError):
    def __init__(self, status_code: int):
        super().__init__(f"BurningText API responded with status code {status_code}")
        self.status_code = status_code


class BurningTextTimeoutError(BurningTextError):
    def __init__(self):
        super().__init__("Request to BurningText API timed out")


class BurningTextRequestError(BurningTextError):
    def __init__(self, message: str):
        super().__init__(f"BurningText request failed: {message}")


def generate_burning_text_video(text: str) -> io.BytesIO:
    params = {
        "Integer13": "on",
        "Integer12": "on",
        "Integer9": 0,
        "BackgroundColor_color": "#FFFFFF",
        "Boolean1": "on",
        "Integer1": 15,
        "Color1_color": "#FF0000",
        "FontSize": 70,
        "LogoID": 4,
        "Text": text
    }
    
    try:
        response = requests.post("https://cooltext.com/PostChange", params=params, timeout=10)

        if response.status_code != 200:
            raise BurningTextAPIError(response.status_code)

        data = response.json()
        gif_url = data.get("renderLocation")
        if not gif_url:
            raise BurningTextError("Missing \"renderLocation\" in API response")

        gif_cache[gif_url] = time.time()
        save_cache()

        gif_response = requests.get(gif_url, verify=False, timeout=10)
        gif_bytes = io.BytesIO(gif_response.content)
        gif_bytes.seek(0)

        return gif_bytes
    except requests.Timeout:
        raise BurningTextTimeoutError()
    except requests.RequestException as e:
        raise BurningTextRequestError(str(e))


@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Send me some text, and I will generate a burning logo for you!")


@router.message()
async def handle_message(message: types.Message):
    if message.text:
        text = message.text
        try:
            gif_bytes = generate_burning_text_video(text)
            gif_bytes.name = f"{uuid.uuid4().hex}.gif"

            file = BufferedInputFile(gif_bytes.read(), filename=gif_bytes.name)
            await message.reply_animation(file)
        except BurningTextTimeoutError:
            await message.reply("The request timed out. Please try again later.")
        except BurningTextAPIError as e:
            await message.reply(f"API error: {e.status_code}")
        except BurningTextRequestError as e:
            await message.reply(f"Request failed: {str(e)}")
        except BurningTextError as e:
            await message.reply(f"Error: {str(e)}")
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            await message.reply(f"An unexpected error occurred: {str(e)}")


@app.get("/")
async def root():
    one_hour_ago = time.time() - 3600
    recent_gifs = [url for url, timestamp in gif_cache.items() if timestamp > one_hour_ago]
    return Response(content=json.dumps({
        "latest_gifs": recent_gifs,
        "total_gifs": len(gif_cache),
        "active_gifs": len(recent_gifs)
    }), media_type="application/json")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("favicon.ico")


async def main():
    load_cache()
    token = os.getenv("API_TOKEN")
    bot = Bot(token=token)
    loop = asyncio.get_running_loop()
    loop.create_task(dp.start_polling(bot))
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
