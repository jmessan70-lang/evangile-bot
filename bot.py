#!/usr/bin/env python3
"""Bot de contenus catholiques quotidiens.

Programmes :
    python bot.py matin   # prière du matin, lectures, évangile commenté, rosaire, pensée
    python bot.py midi    # Angélus (+ chemin de croix le mardi et le vendredi)
    python bot.py soir    # actualités de l'Église
    python bot.py nuit    # prière du soir
Blocs seuls : priere_matin lectures commentaire rosaire pensee angelus
              chemin_de_croix actus priere_soir   (+ date AAAA-MM-JJ en option)

Variables d'environnement :
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID    (envoi Telegram)
    WHATSAPP_PHONE, WHATSAPP_APIKEY     (CallMeBot, optionnel)
    ANTHROPIC_API_KEY                   (pour l'évangile commenté)
    CLAUDE_MODEL                        (optionnel, défaut claude-sonnet-5-5)
Sans variables d'envoi, le texte est seulement affiché.
"""
import html
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date
from functools import lru_cache

import requests

ZONE = "france"
API_AELF = "https://api.aelf.org/v1/messes/{d}/{zone}"

# Flux d'actualités : (nom, url). Ajoute ou retire des lignes librement.
# Seuls le titre et le lien sont repris (pas le texte des articles).
FLUX = [
    ("Vatican News", "https://www.vaticannews.va/fr.rss.xml"),
    # ("Aleteia", "https://fr.aleteia.org/feed/"),  # à vérifier avant d'activer
]

# Pensées : (texte, auteur). Bible : traduction Louis Segond (domaine public).
PENSEES = [
    ("Je puis tout par celui qui me fortifie.", "Philippiens 4, 13"),
    ("L'Éternel est mon berger : je ne manquerai de rien.", "Psaume 23, 1"),
    ("Venez à moi, vous tous qui êtes fatigués et chargés, et je vous donnerai du repos.", "Matthieu 11, 28"),
    ("Je vous laisse la paix, je vous donne ma paix.", "Jean 14, 27"),
    ("Confie-toi en l'Éternel de tout ton cœur, et ne t'appuie pas sur ta sagesse.", "Proverbes 3, 5"),
    ("Dieu est amour.", "1 Jean 4, 8"),
    ("Tu nous as faits pour toi, Seigneur, et notre cœur est sans repos tant qu'il ne repose pas en toi.", "Saint Augustin, Confessions I, 1"),
    ("Aime, et fais ce que tu veux.", "Saint Augustin, Homélies sur la 1re lettre de saint Jean"),
    ("N'ayez pas peur !", "Saint Jean-Paul II, 22 octobre 1978"),
    ("Je veux passer mon ciel à faire du bien sur la terre.", "Sainte Thérèse de Lisieux"),
    ("Le cœur a ses raisons que la raison ne connaît point.", "Blaise Pascal, Pensées"),
    ("Fortifie-toi et prends courage ! Ne t'effraie point, car l'Éternel, ton Dieu, est avec toi.", "Josué 1, 9"),
]

PATER = (
    "Notre Père, qui es aux cieux, que ton nom soit sanctifié, que ton règne vienne, "
    "que ta volonté soit faite sur la terre comme au ciel.\n"
    "Donne-nous aujourd'hui notre pain de ce jour. Pardonne-nous nos offenses, "
    "comme nous pardonnons aussi à ceux qui nous ont offensés. "
    "Et ne nous laisse pas entrer en tentation, mais délivre-nous du Mal. Amen."
)
AVE = (
    "Je vous salue, Marie, pleine de grâce ; le Seigneur est avec vous. "
    "Vous êtes bénie entre toutes les femmes, et Jésus, le fruit de vos entrailles, est béni.\n"
    "Sainte Marie, Mère de Dieu, priez pour nous, pauvres pécheurs, "
    "maintenant et à l'heure de notre mort. Amen."
)
GLOIRE = (
    "Gloire au Père, et au Fils, et au Saint-Esprit, comme il était au commencement, "
    "maintenant et toujours, et dans les siècles des siècles. Amen."
)

ANGELUS = (
    "L'ange du Seigneur apporta l'annonce à Marie.\n_Et elle conçut du Saint-Esprit._\n\n"
    f"{AVE}\n\n"
    "Voici la servante du Seigneur.\n_Qu'il me soit fait selon votre parole._\n\n"
    f"{AVE}\n\n"
    "Et le Verbe s'est fait chair.\n_Et il a habité parmi nous._\n\n"
    f"{AVE}\n\n"
    "Priez pour nous, sainte Mère de Dieu.\n_Afin que nous soyons rendus dignes des promesses du Christ._\n\n"
    "Prions : Que ta grâce, Seigneur notre Dieu, se répande en nos cœurs : par le message "
    "de l'ange, tu nous as fait connaître l'incarnation de ton Fils bien-aimé ; conduis-nous, "
    "par sa passion et par sa croix, jusqu'à la gloire de la résurrection. "
    "Par Jésus, le Christ, notre Seigneur. Amen."
)

MYSTERES = {
    "joyeux": ["L'Annonciation", "La Visitation", "La Nativité",
               "La Présentation de Jésus au Temple", "Le Recouvrement de Jésus au Temple"],
    "lumineux": ["Le Baptême de Jésus", "Les noces de Cana", "L'annonce du Royaume",
                 "La Transfiguration", "L'institution de l'Eucharistie"],
    "douloureux": ["L'agonie à Gethsémani", "La flagellation", "Le couronnement d'épines",
                   "Le portement de la Croix", "La crucifixion"],
    "glorieux": ["La Résurrection", "L'Ascension", "La Pentecôte",
                 "L'Assomption de Marie", "Le couronnement de Marie"],
}
# 0 = lundi ... 6 = dimanche
MYSTERES_PAR_JOUR = ["joyeux", "douloureux", "glorieux", "lumineux",
                     "douloureux", "joyeux", "glorieux"]

PRIERE_MATIN = (
    "Au nom du Père, et du Fils, et du Saint-Esprit. Amen.\n\n"
    "Seigneur, merci pour cette nuit et pour ce jour qui commence. Je te confie ma journée : "
    "mes projets, mes rencontres, mes fatigues et mes joies. Garde-moi dans ta paix, "
    "donne-moi un cœur attentif aux autres et fidèle à ta volonté.\n\n"
    "Divin Cœur de Jésus, je t'offre, par le Cœur immaculé de Marie, les prières, les œuvres "
    "et les souffrances de cette journée, en réparation de nos péchés et pour tous ceux "
    "qui ont besoin de ta miséricorde. Amen.\n\n"
    "Ange de Dieu, qui es mon gardien et à qui la bonté divine m'a confié, "
    "éclaire-moi, garde-moi, dirige-moi et gouverne-moi. Amen."
)

EXAMEN = (
    "1. De quoi veux-je remercier Dieu aujourd'hui ?\n"
    "2. Où ai-je manqué d'amour envers Dieu, envers les autres, envers moi-même ?\n"
    "3. Qu'est-ce que je veux lui confier pour demain ?"
)
CONTRITION = (
    "Mon Dieu, j'ai un très grand regret de vous avoir offensé, parce que vous êtes infiniment bon "
    "et que le péché vous déplaît. Je prends la ferme résolution, avec le secours de votre sainte grâce, "
    "de ne plus vous offenser et de faire pénitence. Amen."
)
SALVE = (
    "Salut, ô Reine, Mère de miséricorde, notre vie, notre douceur et notre espérance, salut ! "
    "Enfants d'Ève, exilés, nous crions vers vous ; vers vous nous soupirons, gémissant et pleurant "
    "dans cette vallée de larmes. Ô vous, notre avocate, tournez vers nous vos regards miséricordieux, "
    "et, après cet exil, montrez-nous Jésus, le fruit béni de vos entrailles, "
    "ô clémente, ô charitable, ô douce Vierge Marie."
)
PRIERE_SOIR = (
    "Au nom du Père, et du Fils, et du Saint-Esprit. Amen.\n\n"
    "Je me mets en présence de Dieu et je relis ma journée.\n\n"
    f"{EXAMEN}\n\n*Acte de contrition*\n{CONTRITION}\n\n*Salve Regina*\n{SALVE}\n\n"
    "Seigneur, accorde-nous une nuit paisible. Que ta bénédiction nous garde. Amen."
)

STATIONS = [
    ("Jésus est condamné à mort", "Innocent, il accepte l'injustice. Garde-nous de juger et de condamner trop vite."),
    ("Jésus est chargé de sa croix", "Il prend sur lui le poids de nos péchés. Apprends-nous à porter nos croix avec confiance."),
    ("Jésus tombe pour la première fois", "Il connaît la fatigue et la faiblesse. Relève-nous quand nous tombons."),
    ("Jésus rencontre sa Mère", "Marie souffre avec son Fils sans le quitter. Donne-nous de rester fidèles dans l'épreuve."),
    ("Simon de Cyrène aide Jésus à porter sa croix", "Un passant devient disciple. Rends-nous attentifs à ceux qui portent un lourd fardeau."),
    ("Véronique essuie le visage de Jésus", "Un geste simple, un grand amour. Que nous sachions consoler par de petits gestes."),
    ("Jésus tombe pour la deuxième fois", "Chute après chute, il continue d'avancer. Donne-nous la persévérance."),
    ("Jésus console les femmes de Jérusalem", "Même épuisé, il pense aux autres. Ouvre nos cœurs à la conversion."),
    ("Jésus tombe pour la troisième fois", "Au bout de ses forces, il avance encore. Soutiens ceux qui n'en peuvent plus."),
    ("Jésus est dépouillé de ses vêtements", "Il est privé de tout, livré à la honte. Rends-nous proches des humiliés et des pauvres."),
    ("Jésus est cloué sur la croix", "Ses mains s'ouvrent pour nous. Pardonne-nous, comme il pardonne."),
    ("Jésus meurt sur la croix", "Il donne sa vie par amour. Que sa mort nous ouvre à la vie."),
    ("Jésus est descendu de la croix", "Marie reçoit son Fils dans ses bras. Console les familles en deuil."),
    ("Jésus est mis au tombeau", "Le silence du tombeau précède la lumière de Pâques. Garde-nous dans l'espérance."),
]

SYSTEME_COMMENTAIRE = (
    "Tu rédiges un court commentaire de l'évangile du jour pour une chaîne catholique francophone. "
    "Reste fidèle à l'enseignement de l'Église catholique (Écriture, Tradition, Catéchisme). "
    "N'invente aucune citation, aucun fait historique incertain, et ne prends pas position sur des "
    "sujets politiques. Style simple, chaleureux, sans jargon. Pas de titre, pas de markdown. "
    "Environ 150 à 200 mots, en trois temps : le contexte ou le sens du passage, ce qu'il dit "
    "de Dieu, une invitation concrète pour aujourd'hui. Termine par une question à méditer."
)


# ---------------------------------------------------------------- utilitaires
def nettoyer(texte_html: str) -> str:
    """Transforme le HTML en texte brut lisible."""
    t = re.sub(r"<br\s*/?>", "\n", texte_html or "")
    t = re.sub(r"</p>", "\n\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def decouper(message: str, taille: int = 1500) -> list[str]:
    """Coupe un long message en morceaux, aux sauts de ligne."""
    morceaux, courant = [], ""
    for ligne in message.split("\n"):
        if len(courant) + len(ligne) + 1 > taille and courant:
            morceaux.append(courant.strip())
            courant = ""
        courant += ligne + "\n"
    if courant.strip():
        morceaux.append(courant.strip())
    return morceaux


# -------------------------------------------------------------------- envoi
def envoyer_telegram(message: str) -> None:
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    for morceau in decouper(message, 3500):
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": morceau},
            timeout=20,
        ).raise_for_status()
    print("-> Telegram : envoyé.")


def envoyer_whatsapp(message: str) -> None:
    phone, apikey = os.getenv("WHATSAPP_PHONE"), os.getenv("WHATSAPP_APIKEY")
    if not (phone and apikey):
        return
    for morceau in decouper(message):
        requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": phone, "text": morceau, "apikey": apikey},
            timeout=30,
        ).raise_for_status()
        time.sleep(3)
    print("-> WhatsApp : envoyé.")


def envoyer(message: str) -> None:
    envoyer_whatsapp(message)
    envoyer_telegram(message)


# ------------------------------------------------------------------- blocs
@lru_cache(maxsize=4)
def messe(jour_iso: str) -> dict:
    r = requests.get(API_AELF.format(d=jour_iso, zone=ZONE), timeout=20)
    r.raise_for_status()
    messes = r.json().get("messes") or []
    if not messes:
        raise RuntimeError("Aucune messe trouvée pour cette date.")
    return r.json()


def extraire(jour: date) -> tuple[dict, dict | None, dict]:
    data = messe(jour.isoformat())
    lectures = data["messes"][0].get("lectures", [])
    trouver = lambda t: next((x for x in lectures if x.get("type") == t), None)
    evangile = trouver("evangile")
    if not evangile:
        raise RuntimeError("Évangile introuvable dans la réponse de l'API.")
    return evangile, trouver("lecture_1"), data


def bloc_lectures(jour: date) -> str:
    evangile, premiere, data = extraire(jour)
    titre = data.get("informations", {}).get("jour_liturgique_nom") or jour.isoformat()
    lignes = [f"✝️ *{titre}*", f"_{jour.isoformat()}_", ""]
    if premiere:
        lignes += [
            f"📖 *{nettoyer(premiere.get('titre', 'Première lecture'))}*",
            f"_{premiere.get('ref', '')}_",
            nettoyer(premiere.get("contenu", "")),
            "",
        ]
    lignes += ["🕊️ *Évangile*", f"_{evangile.get('ref', '')}_"]
    if evangile.get("intro_lue"):
        lignes.append(nettoyer(evangile["intro_lue"]))
    lignes += [nettoyer(evangile.get("contenu", "")), "",
               "_Source : AELF – traduction liturgique_"]
    return "\n".join(lignes)


def bloc_commentaire(jour: date) -> str:
    cle = os.getenv("ANTHROPIC_API_KEY")
    if not cle:
        raise RuntimeError("ANTHROPIC_API_KEY manquante (secret à ajouter).")
    evangile, _, _ = extraire(jour)
    texte = nettoyer(evangile.get("contenu", ""))
    ref = evangile.get("ref", "")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": cle, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={
            "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
            "max_tokens": 700,
            "system": SYSTEME_COMMENTAIRE,
            "messages": [{"role": "user",
                          "content": f"Évangile du jour ({ref}) :\n\n{texte}"}],
        },
        timeout=60,
    )
    r.raise_for_status()
    com = "".join(b.get("text", "") for b in r.json().get("content", [])
                  if b.get("type") == "text").strip()
    if not com:
        raise RuntimeError("Commentaire vide.")
    return (f"🕯️ *Évangile commenté* ({ref})\n\n{com}\n\n"
            "_⚠️ Commentaire généré par IA : à relire avant publication._")


def bloc_priere_matin(jour: date) -> str:
    return f"🌅 *Prière du matin*\n\n{PRIERE_MATIN}"


def bloc_priere_soir(jour: date) -> str:
    return f"🌙 *Prière du soir*\n\n{PRIERE_SOIR}"


def bloc_chemin_de_croix(jour: date) -> str:
    lignes = [
        "✝️ *Chemin de croix*", "",
        "À chaque station :",
        "_Nous t'adorons, ô Christ, et nous te bénissons._",
        "_Car par ta sainte Croix, tu as racheté le monde._", "",
    ]
    for i, (titre, reflexion) in enumerate(STATIONS, 1):
        lignes += [f"*{i}ᵉ station : {titre}*", reflexion, ""]
    lignes += [
        "Après chaque station, on peut dire : 1 Notre Père, 1 Je vous salue Marie, 1 Gloire au Père.", "",
        "Prions : Seigneur Jésus, par ta croix tu as vaincu la mort. Donne-nous de te suivre "
        "sur le chemin de l'amour, jusqu'à la joie de la Résurrection. Amen.",
    ]
    return "\n".join(lignes)


def bloc_pensee(jour: date) -> str:
    texte, auteur = PENSEES[jour.toordinal() % len(PENSEES)]
    return f"💡 *Pensée du jour*\n\n« {texte} »\n— _{auteur}_"


def bloc_angelus(jour: date) -> str:
    return f"🔔 *Angélus de midi*\n\n{ANGELUS}"


def bloc_rosaire(jour: date) -> str:
    serie = MYSTERES_PAR_JOUR[jour.weekday()]
    mysteres = "\n".join(f"{i}. {m}" for i, m in enumerate(MYSTERES[serie], 1))
    return (
        f"📿 *Rosaire – mystères {serie}*\n\n{mysteres}\n\n"
        "Pour chaque mystère : 1 Notre Père, 10 Je vous salue Marie, 1 Gloire au Père.\n\n"
        f"*Notre Père*\n{PATER}\n\n*Je vous salue Marie*\n{AVE}\n\n*Gloire au Père*\n{GLOIRE}"
    )


def lire_flux(url: str, n: int = 3) -> list[tuple[str, str]]:
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    sortie = []
    for item in ET.fromstring(r.content).iter("item"):
        titre = html.unescape((item.findtext("title") or "").strip())
        lien = (item.findtext("link") or "").strip()
        if titre and lien:
            sortie.append((titre, lien))
        if len(sortie) >= n:
            break
    return sortie


def bloc_actus(jour: date) -> str:
    lignes = ["📰 *Actualité de l'Église*", ""]
    total = 0
    for nom, url in FLUX:
        try:
            articles = lire_flux(url)
        except Exception as e:
            print(f"[actus] flux « {nom} » ignoré : {e}", file=sys.stderr)
            continue
        if articles:
            lignes.append(f"_{nom}_")
            for titre, lien in articles:
                lignes.append(f"• {titre}\n{lien}")
                total += 1
            lignes.append("")
    if not total:
        raise RuntimeError("Aucun article récupéré.")
    return "\n".join(lignes).strip()


BLOCS = {
    "priere_matin": bloc_priere_matin,
    "lectures": bloc_lectures,
    "commentaire": bloc_commentaire,
    "rosaire": bloc_rosaire,
    "pensee": bloc_pensee,
    "angelus": bloc_angelus,
    "chemin_de_croix": bloc_chemin_de_croix,
    "actus": bloc_actus,
    "priere_soir": bloc_priere_soir,
}


def programme(nom: str, jour: date) -> list[str]:
    """Liste des blocs à envoyer pour un programme (ou un bloc seul)."""
    if nom == "matin":
        return ["priere_matin", "lectures", "commentaire", "rosaire", "pensee"]
    if nom == "midi":
        blocs = ["angelus"]
        if jour.weekday() in (1, 4):  # mardi et vendredi
            blocs.append("chemin_de_croix")
        return blocs
    if nom == "soir":
        return ["actus"]
    if nom == "nuit":
        return ["priere_soir"]
    return [nom]


def main() -> None:
    args = sys.argv[1:]
    nom = args[0] if args else "matin"
    jour = date.fromisoformat(args[1]) if len(args) > 1 else date.today()
    blocs = programme(nom, jour)
    if any(b not in BLOCS for b in blocs):
        sys.exit(f"Inconnu : {nom}. Choix : {', '.join(['matin', 'midi', 'soir', 'nuit'] + list(BLOCS))}")

    erreurs = 0
    for b in blocs:  # une erreur dans un bloc n'empêche pas les autres
        try:
            message = BLOCS[b](jour)
            print(message, "\n" + "-" * 40)
            envoyer(message)
        except Exception as e:
            erreurs += 1
            print(f"[{b}] erreur : {e}", file=sys.stderr)
    sys.exit(1 if erreurs else 0)


if __name__ == "__main__":
    main()
