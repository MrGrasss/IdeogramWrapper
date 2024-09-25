from datetime import datetime, timedelta
from time import sleep
from enum import Enum

import requests
import logging
import shutil
import base64
import os
import re


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
            user_id="-xnquyqCVSFOYTomOeUchbw",
            channel_id="LbF4xfurTryl5MUEZ73bDw",
            output_dir="images",
            speed=Speed.QUALITY.value,
            negative_prompt="",
            enable_logging=False,
            in_memory=True):

        if not session_cookie_token:
            raise ValueError("Session cookie token is not defined.")
        if not prompt:
            raise ValueError("Prompt is not defined.")

        self.user_id = user_id
        self.channel_id = channel_id
        self.session_cookie_token = session_cookie_token
        self.prompt = prompt
        self.speed = speed
        self.negative_prompt = negative_prompt
        self.output_dir = output_dir
        self.enable_logging = enable_logging
        self.in_memory = in_memory
        self.downloaded_images = []

        if self.enable_logging:
            logging.basicConfig(format='[%(asctime)s] [%(levelname)s]: %(message)s',
                                level=logging.INFO, datefmt='%H:%M:%S')
            logging.info("IdeogramWrapper initialized.")

    def fetch_generation_metadata(self, request_id):
        url = f"{self.BASE_URL}/retrieve_metadata_request_id/{request_id}"
        headers, cookies = self.get_request_params()

        try:
            response = requests.get(url, headers=headers, cookies=cookies)
            response.raise_for_status()

            data = response.json()
            if data.get("resolution") == 1024:
                if self.enable_logging:
                    logging.info("Receiving image data...")
                return data
        except requests.RequestException as e:
            logging.error(f"An error occurred: {e}")
        return None

    def inference(self):
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
            "style_expert": "AUTO",
            "resolution": {
                "width": 736,
                "height": 1312
            }
        }

        try:
            response = requests.post(url, headers=headers, cookies=cookies, json=payload)
            response.raise_for_status()

            request_id = response.json().get("request_id")
            if self.enable_logging:
                logging.info("Generation request sent. Waiting for response...")
            self.make_get_request(request_id)
        except requests.RequestException as e:
            logging.error(f"An error occurred: {e}")

    def make_get_request(self, request_id):
        end_time = datetime.now() + timedelta(minutes=5)

        while datetime.now() < end_time:
            image_data = self.fetch_generation_metadata(request_id)
            if image_data:
                self.download_images(image_data.get("responses", []))
                return
            sleep(1)

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

    def download_image_to_disk(self, image_url, headers, cookies, index):
        os.makedirs(self.output_dir, exist_ok=True)

        sanitized_prompt = re.sub(r'[^\w\s\'-]', '', self.prompt).replace(' ', '_')
        file_path = os.path.join(self.output_dir, f"{sanitized_prompt}_{index}.jpeg")

        try:
            response = requests.get(image_url, headers=headers, cookies=cookies, stream=True)
            response.raise_for_status()

            with open(file_path, "wb") as f:
                shutil.copyfileobj(response.raw, f)
            return file_path
        except requests.RequestException as e:
            logging.error(f"An error occurred while downloading to disk: {e}")
        return None

    def download_image_in_memory(self, image_url, headers, cookies):
        try:
            response = requests.get(image_url, headers=headers, cookies=cookies, stream=True)
            response.raise_for_status()
            return base64.b64encode(response.content).decode('utf-8')
        except requests.RequestException as e:
            logging.error(f"An error occurred while downloading in memory: {e}")
        return None

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
