"""Add power_level (0-10) to every NPC story card in the One Piece scenario JSON.

Calibration anchors (feat-based, current manga canon — Egghead/Elbaf arc):
  10 = Imu only (apex of the world, controls everything)
   9 = Yonko (Shanks/Kaido/BigMom/BB/Luffy-G5), Admirals (Akainu/Kizaru/Aokiji),
       legendary peers (Whitebeard/Roger/Xebec/Garp/Sengoku/Dragon/Rayleigh),
       Five Elders, Sabo (Revolutionary Chief), Cross Guild Mihawk-tier
   8 = Top Yonko commanders proven (Marco, Katakuri), Shichibukai elite who can
       contest above (Doflamingo, Hancock, Magellan, Crocodile, Kuma),
       Worst Gen who took down Yonko (Law, Kid), post-Wano Zoro & Sanji
       (defeated King/Queen), Ace, Shiryu (defeated Magellan), Shamrock (Holy
       Knights leader, Shanks's twin), Seraphim (Lunarian + Pacifista tech),
       Zunesha (massive but immobile)
   7 = Sea Kings (combat anchor), strong Yonko commanders (Cracker/Smoothie/
       Oven/Perospero/Queen-tier), top CP0 (post-skip Lucci, Stussy), top
       Tobiroppo (Who's Who, Black Maria, Sasaki), top Vice-Admirals (Smoker,
       Vergo), Doflamingo executives (Trebol/Pica/Diamante), Revolutionary
       Commanders (Karasu/Morley/Lindbergh/Belo Betty), Ivankov, Mink Dukes
       (Sulong), Elbaf giant warriors (Dorry/Brogy), Loki (hyped Elbaf prince,
       feats unproven), Jinbe (Knight of the Sea), Don Chinjao (broke
       continents prime), Hyogoro (AdvCoA), Enel (Goro Goro Logia), Burgess,
       Gunko (Holy Knight, lost to Sanji), Kyros (legendary gladiator),
       Vista/Jozu (Whitebeard top div)
   6 = Vice-Admirals average, mid Worst Gen (Bonney/Hawkins/Apoo/Bege/Urouge),
       Pacifistas (PX-series, Saturn-Pacifista), Atlas (Vegapunk satellite),
       Numbers (failed giants), Akazaya samurai (Kin'emon/Raizo/etc), Mink
       officers (Carrot/Pedro), CP0 mid (Maha/Joseph/Guernica), Page One,
       mid Charlotte family, Caesar, Cavendish/Bartolomeo, Hajrudin
   5 = Strawhat support (Nami/Usopp/Chopper/Robin/Franky/Brook), CP9 mid
       (Blueno/Kalifa/Fukurou/Kumadori/Kaku), Marine Captains, Hody Jones,
       Tashigi, Wyper, Senor Pink, Daz Bonez (Mr.1), Mont Blanc Cricket
   4 = Weak captains (Buggy/Don Krieg/Kuro), Bellamy, Caribou, Baroque officers
       (Mr.3/4/5), Skypiea priests (Ohm/Gedatsu/Yama), Perona/Absalom,
       Doflamingo execs lower (Sugar/Lao G/Baby 5/Violet), NFP captains, Tom,
       Vegapunk himself (frail), Monet, Demaro Black (impostor)
   3 = Average pirate / Alabasta officers, Wapol, Paulie, scientist satellites
       Edison/Pythagoras, Yakuza minor, Rebecca, Victoria Cindry, Orochi
   2 = Crocus, Doctor Kureha, Lola, Hogback, Spandam, Momonosuke (kid),
       King Riku, Mjosgard, Madame Shyarly, Miss Monday
   1 = Civilians with grit / kids — Iceburg, Kokoro, Camie, Conis, Vivi,
       Cobra, Tama, Hiyori, Makino, Tenryuubito (no skills), Bariete
   0 = Pure non-combatants (Toto, Eyelashes, Chimney) and concept cards
       (Devil Fruits / Kairouseki / Caramachuchos)
"""

import json
import sys

PATH = r"C:\Users\iury2\OneDrive\Desktop\open-source-projects\project-lunar\scenario_clone_op\one_piece_adventures_lunar.pt-br.json"

POWER_MAP = {
    # === 10 — apex of the world ===
    "Imu": 10,

    # === 9 — Yonko / Admirals / legendary peers (proven world-shaker feats) ===
    "Akainu": 9,                    # Fleet Admiral, killed Ace, Marineford victor
    "Kizaru": 9,                    # Admiral, light Logia
    "Aokiji": 9,                    # Ex-Admiral, fought Akainu 10 days
    "Edward Newgate": 9,            # WSM prime, peer of Roger
    "Charlotte Linlin": 9,          # Yonko (defeated by Law+Kid duo, not solo)
    "Kaido": 9,                     # "Strongest Creature", defeated by G5 Luffy
    "Shanks": 9,                    # Yonko, AdvCoC mastery, scarred Blackbeard
    "Blackbeard": 9,                # Yonko, two Devil Fruits, defeated Whitebeard old
    "Garp": 9,                      # "Hero of the Marines", cornered Roger
    "Sengoku": 9,                   # Ex-FA, Hito Hito Buddha
    "Monkey D. Dragon": 9,          # Most-wanted criminal, Revolutionary leader
    "Rocks D. Xebec": 9,            # Legendary captain, surpassed Whitebeard
    "Monkey D. Luffy": 9,           # Gear 5 Sun God Nika, defeated Kaido
    "Sabo": 9,                      # Revolutionary Chief of Staff, Mera Mera, "Pyro"
    "Silvers Rayleigh": 9,          # Dark King, Roger's first mate
    "Cinco Anciões": 9,             # Five Elders (true forms revealed in Egghead)
    "Quatro Yonko": 9,              # Concept card

    # === 8 — Top Yonko commanders / Shichibukai elite / Wano-arc apex Strawhats ===
    "Marco": 8,                     # 1st div Whitebeard Phoenix, held off Akainu
    "Charlotte Katakuri": 8,        # Apex Sweet Commander, drew vs Luffy SBM
    "Boa Hancock": 8,               # Empress, AdvCoC mastery
    "Bartholomew Kuma": 8,          # Pacifista prototype, awakened Paw-Paw
    "Magellan": 8,                  # Chief Warden, defeated Blackbeard pirates initially
    "Donquixote Doflamingo": 8,     # Awakened String, AdvCoC, Yonko-rival prep
    "Crocodile": 8,                 # Cross Guild executive, Sand Logia
    "Roronoa Zoro": 8,              # Defeated King (Calamity), AdvCoC, Enma
    "Sanji": 8,                     # Defeated Queen (Calamity), Germa exoskeleton, Ifrit Jambe
    "Trafalgar Law": 8,             # Defeated Big Mom (with Kid), awakened Op-Op
    "Eustass Kid": 8,               # Defeated Big Mom (with Law), awakened magnet
    "Portgas D. Ace": 8,            # 2nd div Whitebeard, Mera Mera Logia
    "Shiryu": 8,                    # Defeated Magellan, Suke Suke (Invisible) fruit
    "Figarland Shamrock": 8,        # Holy Knights leader, Shanks's twin (unproven extended feats)
    "Seraphim S-Bear": 8,           # Lunarian + child + Pacifista tech
    "Seraphim S-Snake": 8,
    "Seraphim S-Hawk": 8,
    "Serafim S-Shark": 8,
    "Zunesha": 8,                   # Ancient elephant, sank Jack's fleet with one swing

    # === 7 — Sea-King tier / strong commanders / top CP0 / Tobiroppo / unproven hyped ===
    "Loki": 7,                      # Hyped Elbaf prince, unproven feats; well below Yonko
    "Jinbe": 7,                     # Knight of the Sea, defeated Who's Who in Wano
    "Vista": 7,                     # 5th div Whitebeard, briefly dueled Mihawk
    "Jozu": 7,                      # 3rd div Whitebeard, fought Aokiji
    "Vergo": 7,                     # CP0 Vice-Admiral, full-body AdvCoA
    "Smoker": 7,                    # Post-skip VAdm, Smoke Logia + Haki
    "Charlotte Smoothie": 7,        # Sweet Commander
    "Charlotte Cracker": 7,         # Sweet Commander, Bis-Bis biscuit armor
    "Charlotte Oven": 7,            # Sweet Commander, Heat Heat
    "Charlotte Perospero": 7,       # Eldest, Pero-Pero candy
    "Rob Lucci": 7,                 # Post-skip CP0, awakened Cat-Cat Leopard
    "Stussy": 7,                    # Lunarian Vampire Bat-Bat, dual CP0/Rocks agent
    "Jesus Burgess": 7,             # BB pirate champion, Power-Power
    "X Drake": 7,                   # Tobiroppo, Allosaurus Ancient Zoan
    "Killer": 7,                    # Massacre Soldier, AdvCoO awakening
    "Don Chinjao": 7,               # Happo Navy patriarch, broke continent in prime
    "Hyogoro": 7,                   # Yakuza patriarch, full-body AdvCoA
    "Inuarashi": 7,                 # Mink Duke, Sulong, Tot Musica swordsman
    "Nekomamushi": 7,               # Mink Duke, Sulong
    "Dorry": 7,                     # Elbaf giant warrior, century-long duel with Brogy
    "Brogy": 7,                     # Elbaf giant warrior
    "Trebol": 7,                    # Doflamingo top exec, Sticky Sticky
    "Diamante": 7,                  # Doflamingo top exec, Flag-Flag
    "Pica": 7,                      # Doflamingo top exec, Stone-Stone Logia-like
    "Kyros": 7,                     # Legendary one-legged gladiator, decapitated Doflamingo
    "Gecko Moria": 7,               # Ex-Shichibukai, Shadow-Shadow
    "Oars": 7,                      # Continent Puller's descendant
    "Enel": 7,                      # Goro-Goro Logia, Mantra (Observation Haki)
    "Karasu": 7,                    # Revolutionary Commander
    "Morley": 7,                    # Revolutionary Commander, Earth-Earth giant
    "Lindbergh": 7,                 # Revolutionary Commander, mink scientist
    "Belo Betty": 7,                # Revolutionary Commander, rallying flag
    "Shaka": 7,                     # Vegapunk satellite, calm/wise, Voice of All Things
    "Ulti": 7,                      # Tobiroppo, Pachycephalosaurus
    "Who’s Who": 7,                 # Tobiroppo, Saber-tooth, ex-CP9
    "Black Maria": 7,               # Tobiroppo, Spider Rosamygale
    "Sasaki": 7,                    # Tobiroppo, Triceratops
    "Saturn": 7,                    # Pacifista version (per scenario description)
    "Gunko": 7,                     # Holy Knight, lost to Sanji (so < Sanji's 8)
    "Guernica": 7,                  # CP0 elite, sent for Luffy at Wano
    "Ivankov": 7,                   # Hormone-Hormone, fought Magellan with Inazuma
    "Os Sete Corsários do Mar": 7,  # Concept (collective ranges)

    # === 6 — Vice-Admirals avg / mid Worst Gen / strong officers / Numbers / Akazaya ===
    "Jewelry Bonney": 6,
    "Basil Hawkins": 6,
    "Scratchmen Apoo": 6,
    "Capone “Gang” Bege": 6,
    "Urouge": 6,
    "Atlas": 6,                     # Vegapunk satellite (Violence)
    "Page One": 6,                  # Tobiroppo, Spinosaurus (lower)
    "Charlotte Daifuku": 6,
    "Charlotte Mont-d’Or": 6,
    "Charlotte Pudding": 6,         # Three-eyed, awakened Memory-Memory
    "Streusen": 6,                  # Big Mom Pirates Cook, Cook-Cook
    "Pell": 6,                      # Falcon-Falcon
    "Chaka": 6,                     # Jackal-Jackal
    "Boa Sandersonia": 6,           # Snake-Snake Anaconda
    "Boa Marigold": 6,              # Snake-Snake King Cobra
    "Bon Clay": 6,                  # Mane-Mane + Okama Kenpo
    "Hannyabal": 6,                 # Vice Warden Impel Down
    "Inazuma": 6,                   # Choki-Choki, Revolutionary
    "Cavendish": 6,                 # Hakuba personality
    "Bartolomeo": 6,                # Bari-Bari Barrier
    "Sai": 6,                       # Happo Navy, killing fist
    "Hajrudin": 6,                  # Giant boxer, ex-New Giant Pirates
    "Kin’emon": 6,                  # Fox-Fox Mythical Zoan
    "Ashura Doji": 6,
    "Raizo": 6,
    "Kawamatsu": 6,
    "Kikunojo": 6,
    "Denjiro": 6,
    "Izo": 6,                       # Whitebeard 16th div
    "Carrot": 6,                    # Sulong rabbit mink
    "Pedro": 6,                     # Jaguar mink, Nox Pirates captain
    "Shakuyaku": 6,                 # Ex-Empress of Amazon Lily
    "Caesar Clown": 6,              # Gas-Gas Logia, scientist
    "Daz Bonez": 6,                 # Mr. 1, Dice-Dice steel body
    "Maha": 6,                      # CP0 agent
    "Joseph": 6,                    # CP0 agent
    "Hacha": 6,                     # Numbers (failed Oars-clone giants)
    "Goki": 6,
    "Jaki": 6,
    "Nangi": 6,
    "Fuga": 6,
    "Zanki": 6,
    "Mont Blanc Cricket": 6,        # Ex-pirate captain Saruyama Alliance
    "Soku": 6,                      # Vice-Admiral Egghead
    "Kaku": 6,                      # CP0, Giraffe Zoan
    "Jabra": 6,                     # CP9, Wolf-Wolf
    "Sentomaru": 6,                 # Pacifista commander, AdvCoA
    "PX-1": 6,                      # Pacifista
    "King Neptune": 6,              # Trident, ancient knowledge
    "King Elizabello II": 6,        # King's Punch (single-shot)

    # === 5 — Strawhat support / mid CP9 / Marine Captains / ex-rivals ===
    "Nami": 5,                      # Zeus thunder cloud + Sorcery Clima Tact
    "Usopp": 5,                     # Awakened Observation Haki, Pop Greens
    "Tony Tony Chopper": 5,         # Monster Point (unstable)
    "Nico Robin": 5,                # Demonio Fleur
    "Franky": 5,                    # General Franky cyborg suit
    "Brook": 5,                     # Soul King ice slashes
    "Wyper": 5,                     # Skypiea warrior, Reject Dial
    "Ohm": 5,                       # Skypiea priest, cloud sword
    "Blueno": 5,                    # CP9, Door-Door
    "Kalifa": 5,                    # CP9, Bubble-Bubble
    "Fukurou": 5,                   # CP9, Iron-Body specialist
    "Kumadori": 5,                  # CP9, Hair-Hair Life Return
    "Charlotte Brûlée": 5,          # Mirror-Mirror utility
    "Senor Pink": 5,                # Swim-Swim through ground
    "Gladius": 5,                   # Pop-Pop swelling
    "Wanda": 5,                     # Mink officer
    "Lilith": 5,                    # Vegapunk satellite (Evil)
    "York": 5,                      # Vegapunk satellite (Greed/traitor)
    "Doc Q": 5,                     # BB pirate, sickness fruit
    "Van Augur": 5,                 # BB pirate sniper, Wapu-Wapu (Warp)
    "Sadi": 5,                      # Impel Down chief jailer
    "T-Bone": 5,                    # Marine Captain
    "Hody Jones": 5,                # Energy Steroid Fishman
    "Fukaboshi": 5,                 # Fishman prince, trident
    "Miss Doublefinger": 5,         # Spike-Spike officer agent
    "Hatchan": 5,                   # Six-sword octopus fishman
    "Arlong": 5,                    # Saw fishman captain, ex-Sun Pirates
    "Ideo": 5,                      # Boxer giant
    "Orlumbus": 5,                  # Yonta Maria fleet admiral
    "Tashigi": 5,                   # Marine officer, Shigure
    "Monet": 5,                     # Snow Logia (weak Logia)
    "Brownbeard": 5,                # Centaur captain
    "Madame Shyarly": 5,            # Mermaid seer (downgrade from prediction-only)
    "Momousagi": 5,                 # Marine officer Egghead

    # === 4 — Weak captains / officer-tier / strong soldiers / Vegapunk himself ===
    "Vegapunk": 4,                  # Stella himself, frail genius
    "Edison": 4,                    # Vegapunk satellite (Inventiveness)
    "Pythagoras": 4,                # Vegapunk satellite (Wisdom, weakest combatant)
    "Demaro Black": 4,              # Impostor Luffy, no real powers
    "Kuro": 4,                      # Cat Claws, Shakushi technique
    "Don Krieg": 4,                 # Heavy armor + arsenal, no fruit
    "Bellamy": 4,                   # Spring-Spring (was rookie)
    "Sarquiss": 4,
    "Masira": 4,                    # Diving captain
    "Shoujou": 4,                   # Diving captain
    "Mr. 5": 4,                     # Bomb-Bomb
    "Miss Valentine": 4,            # Weight-Weight
    "Mr. 3": 4,                     # Wax-Wax
    "Mr. 4": 4,                     # Slow Slow gunner
    "Lassoo": 4,                    # Dog-Gun ZF
    "Dalton": 4,                    # Bison-Bison
    "Gan Fall": 4,                  # Old God of Skypiea
    "Gedatsu": 4,                   # Skypiea priest, Marsh cloud
    "Yama": 4,                      # Skypiea commander
    "Tom": 4,                       # Giant fishman shipwright
    "Perona": 4,                    # Negative Hollow ghost girl
    "Absalom": 4,                   # Lion zoan, invisibility
    "Duval": 4,                     # Bison rider, post-makeover
    "Ryuboshi": 4,                  # Fishman prince
    "Manboshi": 4,                  # Fishman prince
    "Vander Decken IX": 4,          # Mark-Mark thrower
    "Dosun": 4,                     # NFP officer
    "Ikaros Much": 4,               # NFP squid
    "Zeo": 4,                       # NFP swirl
    "Daruma": 4,                    # NFP cookie cutter
    "Yeti Cool Brothers": 4,        # Bounty hunter duo
    "Sugar": 4,                     # Hobby-Hobby (utility powerhouse, frail)
    "Lao G": 4,                     # Aged martial artist
    "Baby 5": 4,                    # Weapon-Weapon
    "Violet": 4,                    # Glare-Glare seer
    "Caribou": 4,                   # Marsh-Marsh Logia (cowardly)
    "Buggy": 4,                     # Chop-Chop (personally weak despite Yonko status)
    "Buffalo": 4,                   # Spin-Spin
    "Onimaru": 4,                   # Yokai/raccoon-dog spirit
    "Hammond": 4,                   # NFP, Hammerhead karate
    "Funkfreed": 4,                 # Elephant-elephant sword
    "Família Franky": 4,            # Water 7 gang
    "Kurozumi Orochi": 4,           # Yamata-no-Orochi (multi-headed)

    # === 3 — Average pirate / Alabasta officers / Yakuza minor / specialists ===
    "Alvida": 3,                    # Slip-Slip
    "Igaram": 3,                    # Alabasta royal guard captain
    "Mr. 9": 3,
    "Miss Goldenweek": 3,           # Color-Trap (subtle utility)
    "Wapol": 3,                     # Munch-Munch
    "Miss Merry Christmas": 3,      # Mole-Mole
    "Curly Dadan": 3,               # Mountain bandit boss
    "Paulie": 3,                    # Rope master shipwright
    "Satori": 3,                    # Skypiea priest, ball Mantra
    "Rebecca": 3,                   # Gladiator princess (mostly defensive)
    "Victoria Cindry": 3,           # Reanimated zombie
    "Gloriosa": 3,                  # Elder of Amazon Lily
    "Omasa": 3,                     # Yakuza minor
    "Tsunagoro": 3,
    "Yatappe": 3,
    "Chujo": 3,
    "Shirahoshi": 3,                # Personally a child; potential as Poseidon is unused
    "Spandam": 3,                   # Has Funkfreed, but personally cowardly

    # === 2 — Specialists with little combat / royals / scientists ===
    "Crocus": 2,                    # Doctor of Twin Cape
    "Laboon": 2,                    # Juvenile island whale
    "Miss Monday": 2,               # Strength-Strength
    "Doctor Kureha": 2,             # Genius doctor
    "Kureha": 2,                    # Same character (duplicate entry)
    "Lola": 2,                      # Princess pirate
    "King Riku": 2,                 # Pacifist former king
    "Donquixote Mjosgard": 2,       # Reformed Tenryuubito
    "Dr. Hogback": 2,               # Mad scientist
    "Momonosuke": 2,                # Young dragon (kid mind)

    # === 1 — Civilians with grit / kids / royals without combat ===
    "Iceburg": 1,                   # Mayor / shipwright
    "Kokoro": 1,                    # Mermaid station-master
    "Camie": 1,                     # Octopus mermaid
    "Conis": 1,                     # Skypiea civilian
    "Pagaya": 1,                    # Skypiea civilian
    "Makino": 1,                    # Bartender of Foosha
    "King Cobra": 1,                # Alabasta peace king
    "Koza": 1,                      # Rebel leader (civilian fighter)
    "Nefertari Vivi": 1,            # Princess (with Slingshot)
    "Nefertari Cobra": 1,           # Same family — peace king
    "Kozuki Hiyori": 1,             # Kozuki princess
    "Tama": 1,                      # Kibi-Kibi child (utility, no combat)
    "Bariete": 1,                   # Mink bell-ringer
    "Kumashi": 1,                   # Hogback creation
    "Saint Charlos": 1,             # Tenryuubito (no skills, just slaver)
    "Saint Shalria": 1,             # Tenryuubito

    # === 0 — Pure non-combatants / animals / props / concepts ===
    "Toto": 0,                      # Alabasta well-builder
    "Eyelashes": 0,                 # Camel
    "Chimney": 0,                   # Little girl
    "Fruta do Diabo Paramecia": 0,  # Concept
    "Frutas do Diabo Zoan": 0,      # Concept
    "Frutas do Diabo Logia": 0,     # Concept
    "Frutas do Diabo": 0,           # Concept
    "Algemas de Kairouseki": 0,     # Item concept
    "Caramachuchos": 0,             # Den Den Mushi (snail telephones)
}


def main():
    with open(PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    npcs = [c for c in data["story_cards"] if c.get("card_type") == "NPC"]
    missing = []
    for card in npcs:
        name = card["name"]
        if name in POWER_MAP:
            card.setdefault("content", {})["power_level"] = POWER_MAP[name]
        else:
            missing.append(name)
            card.setdefault("content", {})["power_level"] = 3  # safe default

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Report
    ranked = sorted(
        [(c["name"], c["content"]["power_level"]) for c in npcs],
        key=lambda x: (-x[1], x[0]),
    )
    print(f"Updated {len(npcs)} NPCs. {len(missing)} not in map (defaulted to 3).")
    if missing:
        print("\nMissing from map:")
        for n in missing:
            print(f"  - {n}")
    print("\nRanking (strongest -> weakest):")
    for name, p in ranked:
        print(f"  {p:2d}  {name}")


if __name__ == "__main__":
    main()
