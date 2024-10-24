from datetime import datetime, timedelta
from colorama import init, Fore
from curl_cffi import CurlMime
from typing import Literal
from time import sleep
from enum import Enum

import stealth_requests as requests
import threading
import logging
import shutil
import base64
import json
import os
import re

init(autoreset=True)
yl = Fore.YELLOW

print_lock = threading.Lock()


def sync_print(*args, **kwargs):
    with print_lock:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"{yl}[{timestamp}]", *args, **kwargs)


class Speed(Enum):
    DEFAULT = 0
    QUALITY = -2
    TURBO = 2


class IdeogramWrapper:
    BASE_URL = "https://ideogram.ai/api/images"

    def __init__(
            self,
            session_cookie_token,
            prompt,
            reference_image: bytes = None,
            weight: int = 50,
            style="AUTO",
            user_id="-xnquyqCVSFOYTomOeUchbw",
            channel_id="LbF4xfurTryl5MUEZ73bDw",
            output_dir="images",
            speed=Speed.QUALITY.value,
            negative_prompt="",
            image_part: int = 0,
            enable_logging=False,
            in_memory=False,
            proxy=None,
            max_saves: Literal[1, 2, 3, 4] = 0):

        if not session_cookie_token:
            raise ValueError("Session cookie token is not defined.")
        if not prompt:
            raise ValueError("Prompt is not defined.")

        self.user_id = user_id
        self.channel_id = channel_id
        self.session_cookie_token = session_cookie_token
        self.prompt = prompt
        self.reference_image = reference_image
        self.weight = weight
        self.style = style
        self.speed = speed
        self.negative_prompt = negative_prompt
        self.output_dir = output_dir
        self.enable_logging = enable_logging
        self.in_memory = in_memory
        self.downloaded_images = []
        self.proxy = proxy
        self.image_part = image_part
        self.max_saves = max_saves

        if self.enable_logging:
            logging.basicConfig(format='[%(asctime)s] [%(levelname)s]: %(message)s',
                                level=logging.INFO, datefmt='%H:%M:%S')
            logging.info("IdeogramWrapper initialized.")

    def request_with_retries(self, method, url, headers, cookies, payload=None, retries=5, delay=2):
        attempt = 0
        response = None  # Initialize response to None
        while attempt < retries:
            try:
                if method.upper() == 'POST':
                    response = requests.post(url, headers=headers, cookies=cookies, json=payload, proxies=self.proxy)
                elif method.upper() == 'GET':
                    response = requests.get(url, headers=headers, cookies=cookies, params=payload, proxies=self.proxy)
                else:
                    raise ValueError("Unsupported method. Use 'POST' or 'GET'.")

                if response:
                    response.raise_for_status()
                    return response

            except Exception as e:
                message = None
                if response and response.content:
                    try:
                        message = response.json().get('message')
                    except ValueError:
                        message = response.text

                if attempt < retries:
                    if message and 'wait_time' in message:
                        message_data = json.loads(message)
                        delay = message_data.get('time_until_next_generation', delay)
                    else:
                        attempt += 1

                    if delay == 0:
                        raise e

                    if self.enable_logging:
                        logging.info(f"Retrying in {delay} seconds...")
                        sync_print(f"Retrying in {delay} seconds...")

                    sleep(delay)
                else:
                    if self.enable_logging:
                        logging.error(f"Failed after {retries} attempts. Reason: {message}")
                    raise Exception(f"Error: {e}. Reason: {message}")

    def fetch_generation_metadata(self, request_id):
        url = f"{self.BASE_URL}/retrieve_metadata_request_id/{request_id}"
        headers, cookies = self.get_request_params()

        try:
            response = self.request_with_retries("GET", url, headers, cookies, retries=10, delay=5)
            data = response.json()
            if data.get("resolution") == 1024:
                if self.enable_logging:
                    logging.info("Receiving image data...")
                    sync_print(f"Receiving image data...")
                return data

            percentage = data.get('completion_percentage')
            if self.enable_logging and int(percentage) != 99:
                logging.info(f"Completion percent: {percentage}")
                sync_print(f"Completion percent: {percentage}")

        except Exception as e:
            if self.enable_logging:
                logging.error(f"An error occurred: {e}")
                sync_print(f"An error occurred: {e}")
            raise e

    def create(self):
        url = f"{self.BASE_URL}/sample"
        headers, cookies = self.get_request_params()

        payload = {
            "prompt": self.prompt,
            "user_id": self.user_id,
            "private": True,
            "model_version": "V_1_5",
            "use_autoprompt_option": "ON",
            "negative_prompt": self.negative_prompt,
            "sampling_speed": self.speed,
            "style_expert": self.style,
            "resolution": {
                "width": 1080,
                "height": 1920
            }
        }

        try:
            if self.reference_image:
                ref_url = f"https://ideogram.ai/api/uploads/upload"

                with open(self.reference_image, "rb") as img_file:
                    image_data = img_file.read()

                # Create multipart form data
                mp = CurlMime()
                mp.addpart(
                    name="file",
                    content_type="image/png",
                    filename="image.png",
                    data=image_data
                )
                upload_headers = {'Accept': '*/*', 'Content-Type': 'multipart/form-data', 'User-Agent': 'Mozilla/5.0'}

                attempt = 0
                retries = 5

                while attempt < retries:
                    try:
                        r = requests.post(ref_url, headers=upload_headers, cookies=cookies, multipart=mp,
                                          proxies=self.proxy, timeout=60)
                        r.raise_for_status()

                        image_id = r.json().get('id')
                        parent_payload = {
                            "image_id": image_id,
                            "weight": self.weight,
                            "type": "VARIATION"
                        }
                        payload.update({"parent": parent_payload})

                        break
                    except Exception as e:
                        if self.enable_logging:
                            logging.warning(f"Reference error: {str(e)} - {attempt + 1}/{retries}")
                            sync_print(f"Timeout occurred (curl error 28), attempt {attempt + 1}/{retries}")
                        if attempt < retries - 1:
                            sleep(1)
                        else:
                            if self.enable_logging:
                                logging.error(f"Reference upload failed after {retries} retries due to timeout.")
                                sync_print(f"Reference upload failed after {retries} retries due to timeout.")
                            raise e
                    attempt += 1

                mp.close()

            response = self.request_with_retries("POST", url, headers, cookies, payload, retries=10, delay=5)
            request_id = response.json().get("request_id")
            if self.enable_logging:
                logging.info("Generation request sent. Waiting for response...")
                sync_print(f"Generation request sent. Waiting for response...")
            self.make_get_request(request_id)
        except Exception as e:
            if self.enable_logging:
                logging.error(f"An error occurred: {e}")
                sync_print(f"An error occurred: {e}")
            raise e

    def make_get_request(self, request_id):
        end_time = datetime.now() + timedelta(minutes=5)

        while datetime.now() < end_time:
            image_data = self.fetch_generation_metadata(request_id)
            if image_data:
                self.download_images(image_data.get("responses", []))
                return

            sleep(5)

    def download_images(self, responses):
        headers, cookies = self.get_request_params()

        for i, response in enumerate(responses):
            image_url = f"{self.BASE_URL}/direct/{response['response_id']}"
            if self.in_memory:
                image_data = self.download_image_in_memory(image_url, headers, cookies)
                if image_data:
                    self.downloaded_images.append(image_data)
            else:
                file_path = self.download_image_to_disk(image_url, headers, cookies, i)
                if file_path:
                    self.downloaded_images.append(file_path)

        if self.downloaded_images and self.enable_logging:
            logging.info(f"Successfully downloaded {len(self.downloaded_images)} images.")
            sync_print(f"Successfully downloaded {len(self.downloaded_images)} images.")

    def download_image_to_disk(self, image_url, headers, cookies, index):
        os.makedirs(self.output_dir, exist_ok=True)
        file_path = os.path.join(self.output_dir, f'image_{self.image_part}_{index}.png')

        if index >= self.max_saves:
            return None

        try:
            response = self.request_with_retries("GET", image_url, headers, cookies, retries=10, delay=5)
            response.raise_for_status()

            with open(file_path, "wb") as f:
                f.write(response.content)
            return file_path
        except Exception as e:
            if self.enable_logging:
                logging.error(f"An error occurred while downloading to disk: {e}")
                sync_print(f"An error occurred while downloading to disk: {e}")
            raise e

    def download_image_in_memory(self, image_url, headers, cookies):
        if self.image_part > self.max_saves:
            return None

        try:
            response = self.request_with_retries("GET", image_url, headers, cookies, retries=10, delay=5)
            response.raise_for_status()
            return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            if self.enable_logging:
                logging.error(f"An error occurred while downloading in memory: {e}")
                sync_print(f"An error occurred while downloading in memory: {e}")
            raise e

    def get_request_params(self):
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        cookies = {
            "session_cookie": self.session_cookie_token
        }
        return headers, cookies
