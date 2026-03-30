import base64
import hashlib
import json
import logging
import os
import secrets
import time
from argparse import ArgumentParser, Namespace
from ssl import CERT_NONE as SSL_CERT_NONE
from threading import Event
from typing import Any, Literal, TypedDict
from urllib.parse import quote, urlencode

try:
    import paho.mqtt.client as mqtt
    import requests
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    from dotenv import load_dotenv
    from paho.mqtt.enums import CallbackAPIVersion
except ImportError as e:
    missing_package = str(e).split("'")[1]
    print(f"Fehlendes Paket: {missing_package}. Bitte installiere alle Pakete mit 'pip install -r requirements.txt' und versuche es erneut.") # fmt: skip
    exit(-1)

############################################[Constants]#############################################
load_dotenv()

DEVICE_KEY = os.environ.get("DEVICE_KEY", "")
PRODUCT_KEY = os.environ.get("PRODUCT_KEY", "")
EMAIL = os.environ.get("EMAIL", "")
PASSWORD = os.environ.get("PASSWORD", "")

TOKENS_FILE = os.environ.get("TOKENS_FILE", "tokens.json")


###########################################[Custom Types]###########################################
class Tokens(TypedDict):
    access_token: str
    access_token_expiration_time: int
    refresh_token: str
    refresh_token_expiration_time: int


# OFF = 0W, NORMAL = 620W, FAST = 1600W, SLOW = 390W
type ChargeLevel = Literal["OFF", "NORMAL", "FAST", "SLOW"]


#########################################[Global Variables]#########################################
logger = logging.getLogger()

message_event = Event()
received_payload: str | None = None

WS_PUB_TOPIC = f"q/1/d/qd{PRODUCT_KEY}{DEVICE_KEY}/bus"


##########################################[Helper Methods]##########################################
def get_args() -> Namespace:
    parser = ArgumentParser(
        description="Sunbooster Akku Werte auslesen oder schreiben."
    )

    output_choices = [0, 100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800] # fmt: skip
    charge_choices = ["off", "normal", "fast", "slow"]

    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "-c",
        "--charge",
        type=str.lower,
        choices=charge_choices,
        help="Einspeisemodus",
    )
    group.add_argument(
        "-o",
        "--output",
        type=int,
        choices=output_choices,
        help="Ladewert als Integer (0 für aus oder 100W-800W in 50er Schritten)",
    )

    parser.add_argument(
        "-r",
        "--read",
        action="store_true",
        help="Ließt alle Werte vom Sunbooster Akku aus",
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Zeige genauere Informationen an"
    )

    parser.add_argument(
        "-d", "--debug", action="store_true", help="Zeige Debugging Informationen an"
    )

    args = parser.parse_args()

    if args.charge is None and args.output is None and args.read == False:
        parser.print_usage()
        exit(-1)

    return args


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


def login(email: str, password: str) -> Tokens:
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
        raise Exception(f"Falsches Passwort oder anderer Fehler:\n{o}")

    return {
        "access_token": o["data"]["accessToken"]["token"],
        "access_token_expiration_time": o["data"]["accessToken"]["expirationTime"],
        "refresh_token": o["data"]["refreshToken"]["token"],
        "refresh_token_expiration_time": o["data"]["refreshToken"]["expirationTime"],
    }


def request_access_token(refresh_token: str) -> Tokens:
    url = "https://iot-api.acceleronix.io/v2/enduser/enduserapi/refreshToken"
    payload = urlencode({"refreshToken": refresh_token}, quote_via=quote)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    o = requests.put(url, data=payload, headers=headers).json()

    return {
        "access_token": o["data"]["accessToken"]["token"],
        "access_token_expiration_time": o["data"]["accessToken"]["expirationTime"],
        "refresh_token": o["data"]["refreshToken"]["token"],
        "refresh_token_expiration_time": o["data"]["refreshToken"]["expirationTime"],
    }


def get_access_token(email: str, password: str) -> str:
    current_time = int(time.time()) - 60  # Toleranz von 1min

    # Versuche, Tokens aus der Datei zu laden
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, "r") as f:
                tokens: Tokens = json.load(f)

            if tokens.get("access_token_expiration_time", 0) > current_time:
                if tokens.get("refresh_token_expiration_time", 0) > current_time:
                    logger.info("Access Token geladen")
                    return tokens["access_token"]

                new_tokens = request_access_token(tokens["refresh_token"])
                with open(TOKENS_FILE, "w") as f:
                    json.dump(new_tokens, f, indent=2)
                logger.info("Neuen Access Token erstellt, weil der alte abgelaufen ist")
                return new_tokens["access_token"]
            logger.info("Refresh Token ist abgelaufen...")

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Fehler beim Laden der Tokens aus {TOKENS_FILE}: {e}")
    else:
        logger.debug("Token Datei existiert nicht, versuche Login mit Anmeldedaten...")

    # Wenn Datei nicht existiert, Parsing-Fehler oder Tokens abgelaufen: Neu anmelden
    try:
        logger.info("Versuche, neu anzumelden...")
        tokens = login(email, password)
        with open(TOKENS_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
        logger.info("Access Token erstellt")
        return tokens["access_token"]
    except Exception as e:
        logger.error(f"Login fehlgeschlagen: {e}")

        raise Exception(
            "Alle Authentifizierungsversuche sind fehlgeschlagen. Bitte überprüfe deine Anmeldedaten oder Netzwerkverbindung."
        )


def get_sunbooster_attributes(access_token: str) -> dict[str, str]:
    url = f"https://iot-api.acceleronix.io/v2/binding/enduserapi/getDeviceBusinessAttributes?dk={DEVICE_KEY}&pk={PRODUCT_KEY}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "authorization": access_token,
    }

    o = requests.get(url, headers=headers).json()

    if "data" not in o:
        raise Exception(
            f"The server returned an invalid object. Maybe invalid access token?\nServer message: {o['msg']}"
        )

    infos: list[dict[str, str]] = o["data"]["customizeTslInfo"]

    # return {f"{p['name']} ({p['resourceCode']})": p["resourceValce"] for p in infos}
    return {p["resourceCode"]: p["resourceValce"] for p in infos}


def on_ws_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None: # fmt: skip
    logger.debug(f"Connected with reason code {reason_code}")

    if reason_code != 0:
        raise ConnectionError(f"Server raised a reason code {reason_code}")

    client.subscribe(f"q/2/d/qd{PRODUCT_KEY}{DEVICE_KEY}/bus")
    client.subscribe(f"q/2/d/qd{PRODUCT_KEY}{DEVICE_KEY}/ack_")


def on_ws_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    global received_payload
    logger.debug(f"Received: {msg.payload}")

    received_payload = msg.payload.decode()
    message_event.set()


def setup_mqtt_ws(access_token: str) -> mqtt.Client:
    WS_PATH = "/ws/v2"
    WS_CLIENT_ID = f"qu_E19725_{int(time.time()*1000)}"

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=WS_CLIENT_ID,
        transport="websockets",
    )

    client.ws_set_options(path=WS_PATH)
    client.tls_set(cert_reqs=SSL_CERT_NONE)  # type: ignore
    client.username_pw_set(username="", password=access_token)

    client.on_connect = on_ws_connect
    client.on_message = on_ws_message

    return client


def interpret_response(success_message: str) -> None:
    try:
        received_payload_json = json.loads(received_payload or "{}")
        success = received_payload_json.get("status", False) == "succ"

        if success:
            logger.info(success_message)
        elif "device offline" in received_payload_json.get("msg", ""):
            logger.error("Fehler: Das Gerät ist offline!")
        else:
            logger.error(
                f"Fehler beim Senden des Aufladen-Befehls. Server Nachricht: '{received_payload_json.get('msg', 'Unbekannter Fehler')}'"
            )

    except json.JSONDecodeError:
        logger.error(f"Failed to decode received payload: {received_payload}")


def send_charge_cmd(client: mqtt.Client, level: ChargeLevel) -> None:
    CHARGE_DATA_WORD = "AA AA 00 09 69 00 42 00 13 00 DA 00 "

    idx = ["OFF", "NORMAL", "FAST", "SLOW"].index(level)
    data_word_raw = CHARGE_DATA_WORD + f"0{idx}"
    payload = bytes.fromhex(data_word_raw)

    client.publish(WS_PUB_TOPIC, payload)
    logger.debug(f"Sent '{data_word_raw}' to topic '{WS_PUB_TOPIC}'")

    if message_event.wait(timeout=10):
        interpret_response(
            f"Der Befehl für das Aufladen des Akkus mit dem Modus '{level}' wurde erfolgreich gesendet."
            if level != "OFF"
            else "Der Befehl für das Ausschalten des Aufladens des Akkus wurde erfolgreich gesendet."
        )

    else:
        logger.error("Fehler beim Senden des Aufladen-Befehls")
    message_event.clear()


def send_output_cmd(client: mqtt.Client, watt: int) -> None:
    OUTPUT_DATA_WORD = "AA AA 00 09 69 00 43 00 13 01 0A 00 "

    level = [0, 100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800].index(watt) # fmt: skip

    hex_val = format(level, "x")
    data_word_raw = OUTPUT_DATA_WORD + f"0{hex_val}"
    payload = bytes.fromhex(data_word_raw)

    client.publish(WS_PUB_TOPIC, payload)
    logger.debug(f"Sent '{data_word_raw}' to topic '{WS_PUB_TOPIC}'")

    if message_event.wait(timeout=10):
        interpret_response(
            f"Der Befehl für das Einspeisen des Akkus mit {watt}W wurde erfolgreich gesendet."
            if watt != 0
            else "Der Befehl für das Beenden des Einspeisens des Akkus wurde erfolgreich gesendet."
        )

    else:
        logger.error("Fehler beim Senden des Einspeisen-Befehls!")
    message_event.clear()


###########################################[Main Method]############################################
def main() -> None:
    WS_BROKER = "iot-south.acceleronix.io"
    WS_PORT = 8443

    # Logger konfigurieren
    logging.basicConfig(format="%(levelname)s: %(message)s")

    # Überprüfen, ob alle notwendigen Konstanten gesetzt sind
    if not all([DEVICE_KEY, PRODUCT_KEY, EMAIL, PASSWORD]):
        logger.error("Bitte setze DEVICE_KEY, PRODUCT_KEY, EMAIL und PASSWORD in der .env Datei oder als Umgebungsvariablen. Du kannst 'python setup.py' einmal ausführen, um Hilfe beim Einrichten zu erhalten.") # fmt: skip
        exit(-1)

    # Argumente aus der Kommandozeile parsen
    args = get_args()

    # Log-Level basierend auf den Argumenten setzen
    if args.debug:
        logger.setLevel(logging.DEBUG)
    elif args.verbose:
        logger.setLevel(logging.INFO)

    # Access Token laden
    access_token = get_access_token(EMAIL, PASSWORD)

    # Attribute des Sunbooster Akkus abrufen und ggf. ausgeben
    attrs = get_sunbooster_attributes(access_token)
    battery_percentage = int(attrs.get("batteryPercentage", "0"))

    if args.read:
        print(json.dumps(attrs, indent=2, ensure_ascii=False))

    if args.charge is None and args.output is None:
        return

    client = setup_mqtt_ws(access_token)

    client.connect(WS_BROKER, WS_PORT, keepalive=60)
    client.loop_start()

    try:
        if args.charge is not None:
            if battery_percentage < 100:
                send_charge_cmd(client, level=args.charge.upper())
            else:
                logger.error("Der Befehl zum Aufladen des Akkus wird nicht gesendet, weil der Akku bereits voll ist.") # fmt: skip

        if args.output is not None:
            if battery_percentage <= 15 and battery_percentage > 10:
                logger.warning(f"Der Akku hat nur noch {battery_percentage}% Ladung.")
            if battery_percentage > 10:
                send_output_cmd(client, watt=args.output)
            else:
                logger.error("Der Befehl zum Einspeisen des Akkus wird nicht gesendet, weil der Akku weniger als 10% Ladung hat.") # fmt: skip

    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
