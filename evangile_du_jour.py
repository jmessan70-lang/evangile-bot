#!/usr/bin/env python3
"""Récupère l'évangile du jour (AELF) et le formate pour WhatsApp.

Usage :
    pip install requests
    python evangile_du_jour.py            # aujourd'hui
    python evangile_du_jour.py 2026-11-01 # une date précise

Envoi sur ton WhatsApp via CallMeBot : définis les variables d'environnement
    WHATSAPP_PHONE  (ex. 33612345678, format international sans + ni espaces)
    WHATSAPP_APIKEY (clé reçue de CallMeBot après activation)
Option : envoi vers Telegram avec TELEGRAM_TOKEN et TELEGRAM_CHAT_ID.
"""
import html
import os
import re
import sys
import time
from datetime import date

import requests

ZONE = "france"
API = "https://api.aelf.org/v1/messes/{d}/{zone}"


def nettoyer(texte_html: str) -> str:
    """Transforme le HTML AELF en texte brut lisible."""
    t = re.sub(r"<br\s*/?>", "\n", texte_html or "")
    t = re.sub(r"</p>", "\n\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def recuperer(jour: str) -> dict:
    r = requests.get(API.format(d=jour, zone=ZONE), timeout=20)
    r.raise_for_status()
    return r.json()


def trouver(lectures: list, type_: str) -> dict | None:
    return next((l for l in lectures if l.get("type") == type_), None)


def formater(data: dict, jour: str) -> str:
    infos = data.get("informations", {})
    messes = data.get("messes") or []
    if not messes:
        raise RuntimeError("Aucune messe trouvée pour cette date.")
    lectures = messes[0].get("lectures", [])

    evangile = trouver(lectures, "evangile")
    premiere = trouver(lectures, "lecture_1")
    if not evangile:
        raise RuntimeError("Évangile introuvable dans la réponse de l'API.")

    titre_jour = infos.get("jour_liturgique_nom") or jour
    lignes = [f"✝️ *{titre_jour}*", f"_{jour}_", ""]

    if premiere:
        lignes += [
            f"📖 *{nettoyer(premiere.get('titre', 'Première lecture'))}*",
            f"_{premiere.get('ref', '')}_",
            nettoyer(premiere.get("contenu", "")),
            "",
        ]

    lignes += [
        "🕊️ *Évangile*",
        f"_{evangile.get('ref', '')}_",
    ]
    if evangile.get("intro_lue"):
        lignes.append(nettoyer(evangile["intro_lue"]))
    lignes += [nettoyer(evangile.get("contenu", "")), ""]

    lignes += [
        "🙏 _Que la Parole du jour nous accompagne._",
        "_Source : AELF – traduction liturgique_",
    ]
    return "\n".join(lignes)


def decouper(message: str, taille: int = 1500) -> list[str]:
    """Coupe le message en morceaux, aux sauts de ligne."""
    morceaux, courant = [], ""
    for ligne in message.split("\n"):
        if len(courant) + len(ligne) + 1 > taille and courant:
            morceaux.append(courant.strip())
            courant = ""
        courant += ligne + "\n"
    if courant.strip():
        morceaux.append(courant.strip())
    return morceaux


def envoyer_whatsapp(message: str) -> None:
    phone = os.getenv("WHATSAPP_PHONE")
    apikey = os.getenv("WHATSAPP_APIKEY")
    if not (phone and apikey):
        return
    for i, morceau in enumerate(decouper(message), 1):
        r = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": phone, "text": morceau, "apikey": apikey},
            timeout=30,
        )
        r.raise_for_status()
        print(f"WhatsApp : partie {i} envoyée.")
        time.sleep(3)  # évite de saturer le service


def envoyer_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message},
        timeout=20,
    ).raise_for_status()
    print("Envoyé sur Telegram pour validation.")


def main() -> None:
    jour = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    message = formater(recuperer(jour), jour)

    chemin = f"evangile_{jour}.txt"
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(message)

    print(message)
    print(f"\n--- Sauvegardé dans {chemin} ---")
    envoyer_whatsapp(message)
    envoyer_telegram(message)


if __name__ == "__main__":
    main()
