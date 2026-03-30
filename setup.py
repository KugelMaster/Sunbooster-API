import base64
import hashlib
import secrets
from getpass import getpass
from pathlib import Path

try:
    import requests
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
except ImportError as e:
    missing_package = str(e).split("'")[1]
    print(f"Fehlendes Paket: {missing_package}. Bitte installiere alle Pakete mit 'pip install -r requirements.txt' und versuche es erneut.") # fmt: skip
    exit(-1)


def user_approved(question: str) -> bool:
    while (i := input(question).lower()) not in ["y", "n"]:
        pass

    return i == "y"


def getRandom() -> str:
    result = ""

    for _ in range(16):
        choice = secrets.randbelow(3)

        if choice == 0:
            result += str(secrets.randbelow(10))
        elif choice == 1:
            result += chr(secrets.randbelow(25) + 65)
        else:
            result += chr(secrets.randbelow(25) + 97)

    return result


def aes_encrypt_base64(password_plain: str, random: str) -> str:
    md5_hash = hashlib.md5(random.encode()).hexdigest().upper()[8:24]

    key_bytes = md5_hash.encode("utf-8")
    iv_bytes = (md5_hash[8:16] + md5_hash[0:8]).encode("utf-8")

    cipher = AES.new(key_bytes, AES.MODE_CBC, iv=iv_bytes)  # type: ignore

    padded = pad(password_plain.encode("utf-8"), AES.block_size)

    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode("utf-8")


def login(email: str, password: str) -> dict[str, str]:
    DOMAIN_SECRET = "8px7ztwB8Khi3iax97VVhufBCSv6QT4oCimou1Dyrkkv"
    USER_DOMAIN = "E.DM.1209906967672817.3"
    url = "https://iot-api.acceleronix.io/v2/enduser/enduserapi/emailPwdLogin"

    random = getRandom()
    pwd = aes_encrypt_base64(password, random)
    signature = hashlib.sha256(
        (email + pwd + random + DOMAIN_SECRET).encode("utf-8")
    ).hexdigest()

    payload = {
        "random": random,
        "signature": signature,
        "userDomain": USER_DOMAIN,
        "pwd": pwd,
        "email": email,
    }

    o = requests.post(url, data=payload).json()

    if o.get("code", -1) != 200:
        return {}

    return {
        "access_token": o["data"]["accessToken"]["token"],
        "access_token_expiration_time": o["data"]["accessToken"]["expirationTime"],
        "refresh_token": o["data"]["refreshToken"]["token"],
        "refresh_token_expiration_time": o["data"]["refreshToken"]["expirationTime"],
    }


def fetch_device_list(access_token: str):
    url = "https://iot-api.acceleronix.io/v2/binding/enduserapi/userDeviceList"
    headers = {"authorization": access_token}

    o = requests.get(url, headers=headers).json()

    if o.get("code", 200) != 200:
        print(f"Error: {o.get('msg', 'Unknown error')}")
        return

    return [
        {
            "productName": i.get("productName"),
            "deviceName": i.get("deviceName"),
            "firstItemName": i.get("firstItemName"),
            "productKey": i.get("productKey"),
            "deviceKey": i.get("deviceKey"),
        }
        for i in o.get("data", {}).get("list", [])
    ]


def interactively_get_env_file() -> Path | None:
    env_file = Path.cwd() / ".env"

    print(f"Die Datei mit allen wichtigen Informationen (Geräteschlüssel, Passwörter, etc.) wird hier erstellt: '{env_file}'") # fmt: skip

    if env_file.exists():
        if not user_approved(f"Diese Datei gibt es bereits. Möchtest du sie überschreiben? (y/n) "): # fmt: skip
            print("Abgebrochen.")
            return None
        print("Datei wird überschrieben")

    return env_file


def interactive_login() -> tuple[str, str, str]:
    try:
        while True:
            email = input("Gib deine E-Mail von deinem Sunbooster Account ein: ")
            password = getpass("Gib dein Passwort von deinem Sunbooster Account ein: ")

            access_token = login(email, password).get("access_token")

            if access_token is not None:
                return email, password, access_token

            print("Falsche Anmeldedaten. Versuche es erneut!")
    except KeyboardInterrupt:
        exit(0)


def select_device(access_token: str) -> tuple[str, str, str] | None:
    device_list = fetch_device_list(access_token)

    if device_list is None:
        print("Ein Fehler ist aufgetreten.")
        return

    for device in device_list:
        print("-----------------------------------------------------")
        print(f"Produktname: {device['productName']}")
        print(f"Gerätename: {device['deviceName']}")
        print(f"First Item Name: {device['firstItemName']}")
        print(f"(Product Key: {device['productKey']})")
        print(f"(Device Key: {device['deviceKey']})")
        print()
        if user_approved("Ist das hier die Powerstation Grid? (y/n) "):
            name = f"{device['productName']} ({device['deviceName']})"
            productKey = device["productKey"]
            deviceKey = device["deviceKey"]

            return name, productKey, deviceKey


def select_device_interactively(access_token: str) -> tuple[str, str, str]:
    device_info = select_device(access_token)
    print("-----------------------------------------------------")

    if device_info is None:
        print("Kein Gerät ausgewählt. Beendet.")
        exit(0)

    print(f"Ausgewähltes Gerät: {device_info[0]}")
    return device_info


def main() -> None:
    env_file = interactively_get_env_file()

    if env_file is None:
        return

    email, password, access_token = interactive_login()
    name, productKey, deviceKey = select_device_interactively(access_token)

    content_string = (
        f"# Login Daten\n"
        f"EMAIL={email}\n"
        f"PASSWORD={password}\n"
        f"\n"
        f"# Gerät Informationen\n"
        f"DEVICE_NAME={name}\n"
        f"PRODUCT_KEY={productKey}\n"
        f"DEVICE_KEY={deviceKey}\n"
    )

    with env_file.open("w", encoding="utf-8") as f:
        f.write(content_string)

    print("Alle Daten erfolgreich abgespeichert! Du kannst nun das 'sunbooster.py' Skript verwenden.") # fmt: skip


if __name__ == "__main__":
    main()
