import os
import requests
import aiohttp
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

async def upload_to_yadisk(db, project_name, telegram_id, file_bytes, filename):
    token = os.getenv("YADISK_TOKEN")
    headers = {"Authorization": f"OAuth {token}"}

    common_root = "Отчёты"
    safe_proj = project_name.replace(" ", "_").replace("/", "_")
    date_folder = datetime.now().date().isoformat()

    user = await db.users.find_one({"telegram_id": str(telegram_id)})
    surname = user["surname"].replace(" ", "_") if user and "surname" in user else str(telegram_id)

    last_folder = f"{common_root}/{safe_proj}/{date_folder}/{surname}"

    async with aiohttp.ClientSession() as session:
        for path in [
            common_root,
            f"{common_root}/{safe_proj}",
            f"{common_root}/{safe_proj}/{date_folder}",
            last_folder
        ]:
            await session.put(
                "https://cloud-api.yandex.net/v1/disk/resources",
                headers=headers,
                params={"path": path}
            )

        async with session.get(
            "https://cloud-api.yandex.net/v1/disk/resources/upload",
            headers=headers,
            params={"path": f"{last_folder}/{filename}", "overwrite": "true"}
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            upload_url = data["href"]

        async with session.put(upload_url, data=file_bytes):
            pass

    return last_folder

def finalize_report(last_folder: str) -> str | None:
    if not last_folder:
        return None
    token = os.getenv("YADISK_TOKEN")
    headers = {"Authorization": f"OAuth {token}"}
    base_url = "https://cloud-api.yandex.net/v1/disk/resources"

    requests.put(
        f"{base_url}/publish",
        headers=headers,
        params={"path": last_folder}
    ).raise_for_status()

    info_resp = requests.get(
        base_url,
        headers=headers,
        params={"path": last_folder, "fields": "public_url"}
    )
    info_resp.raise_for_status()
    return info_resp.json().get("public_url")