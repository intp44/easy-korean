"""1단계: 사진 준비

사진을 AI에게 보내기 좋은 모양으로 다듬습니다.
- 아이폰 HEIC 사진을 JPG로 바꿉니다.
- 옆으로 누운 사진을 바로 세웁니다 (사진에 저장된 회전 정보 사용).
- 너무 큰 사진은 줄입니다.
모든 작업은 메모리 안에서만 하고, 파일로 저장하지 않습니다.
"""

import base64
import io
import math

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}

# claude-sonnet-5가 한 장에서 읽을 수 있는 최대 크기입니다. 이보다 크면 AI 쪽에서 어차피 줄입니다.
MAX_LONG_SIDE = 2576
MAX_PIXELS = 3_750_000
# API가 받는 사진 한 장의 최대 용량(5MB)보다 조금 작게 잡습니다.
MAX_BASE64_BYTES = 4_500_000


class ImageError(Exception):
    """사진을 준비하지 못했을 때 쓰는 오류입니다. 메시지는 사용자에게 그대로 보여줍니다."""


def prepare_image(path, data=None):
    """사진 파일을 읽어 (형식, base64 글자) 묶음으로 돌려줍니다.
    data에 사진 내용(바이트)을 주면 파일을 읽지 않고 메모리에 있는 사진을 씁니다. 이때 path는 확장자 확인에만 씁니다."""
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ImageError(
            f"지원하지 않는 파일 형식입니다: {path.suffix or '(확장자 없음)'}\n"
            "jpg, jpeg, png, heic 사진이나 txt 파일을 넣어 주세요."
        )

    try:
        with Image.open(io.BytesIO(data) if data is not None else path) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
    except (UnidentifiedImageError, OSError):
        raise ImageError(
            "사진을 열 수 없습니다.\n"
            "파일이 사진이 아니거나, 파일이 망가졌을 수 있습니다. 사진을 다시 찍거나 다시 저장해 주세요."
        )

    image = _to_rgb(image)
    image = _shrink(image)
    return "image/jpeg", _encode_jpeg(image)


def _to_rgb(image):
    """투명 배경(PNG)은 흰 배경으로 채우고, 색 형식을 JPG에 맞게 바꿉니다."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        return background
    return image.convert("RGB")


def _shrink(image):
    """긴 변이 2576px, 전체 크기가 375만 화소를 넘지 않게 줄입니다."""
    width, height = image.size
    scale = min(
        1.0,
        MAX_LONG_SIDE / max(width, height),
        math.sqrt(MAX_PIXELS / (width * height)),
    )
    if scale < 1.0:
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size, Image.LANCZOS)
    return image


def _encode_jpeg(image):
    """JPG로 바꾼 뒤 base64 글자로 만듭니다. 용량이 크면 화질을 조금씩 낮춥니다."""
    for quality in (90, 80, 70, 60):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        data = base64.standard_b64encode(buffer.getvalue()).decode("ascii")
        if len(data) <= MAX_BASE64_BYTES:
            return data
    raise ImageError("사진 용량이 너무 큽니다. 사진을 조금 작게 줄여서 다시 넣어 주세요.")
