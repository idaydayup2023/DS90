#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提示词配置模块

集中管理所有翻译相关的提示词定义，便于修改和调整。
"""

from typing import List, Dict, Optional


class PromptTemplates:
    """提示词模板类"""
    
    # 基础翻译提示词
    BASE_TRANSLATION_PROMPT = "你是一名专业影视字幕翻译员，请将以下内容翻译为目标语言。要求忠实原意、流畅自然、符合字幕规范。"
    
    # 简明翻译提示词
    CONCISE_TRANSLATION_PROMPT = "请简明翻译，无需赘述背景和规则。"
    
    # 双语翻译提示词模板
    DUAL_LANGUAGE_PROMPT_TEMPLATE = """请将以下{source_lang}文本同时翻译成中文和英文。要求：
1. 中文翻译要自然流畅，符合中文表达习惯
2. 英文翻译要准确地道，符合英文表达习惯
3. 保持原文的语气和情感
4. 只返回翻译结果，不要添加任何解释

原文：{text}

请按以下格式返回：
中文：[中文翻译]
英文：[英文翻译]"""
    
    # 统一的类型特定指导（适用于影片类型和场景类型）
    TYPE_SPECIFIC_GUIDES = {
        "action": "动作场面描述要简洁有力，突出紧张感",
        "comedy": "保持幽默感，注意文化差异，适当本土化",
        "drama": "情感表达要细腻，注重人物内心描写",
        "horror": "营造恐怖氛围，用词要有张力",
        "romance": "情感表达要温馨浪漫，用词优美",
        "thriller": "保持悬疑紧张感，节奏要紧凑",
        "sci-fi": "科幻术语要准确，保持未来感",
        "fantasy": "奇幻元素要有想象力，保持神秘感",
        "superhero": "超能力描述要生动，保持奇幻与现实平衡；准确翻译专业术语如TP(telepathy心灵感应)、TK(telekinesis心灵传动)等缩写；注意区分超能力机构、实验项目等专有名词",
        "crime": "犯罪术语要专业，保持严肃感",
        "documentary": "用词要客观准确，保持纪实感",
        "animation": "语言要生动活泼，适合目标观众",
        "family": "用词要温馨正面，适合全家观看",
        "adventure": "冒险精神要突出，用词要有激情",
        "mystery": "保持神秘感，不要过早透露关键信息",
        "war": "战争场面要有震撼力，情感要深沉",
        "western": "保持西部风情，用词要有时代感",
        "musical": "音乐相关术语要准确，保持艺术感",
        "sport": "体育术语要专业，保持竞技感",
        "biography": "人物描写要真实，保持敬重感",
        "history": "历史背景要准确，用词要有厚重感",
        "medical": "医疗术语要专业准确，保持专业感",
        "legal": "法律术语要严谨，保持权威感",
        "political": "政治术语要准确，保持中立感",
        "military": "军事术语要专业，保持严肃感",
        "tech": "技术术语要准确，保持专业感",
    }
    
    # 缩写处理指导
    ABBREVIATION_GUIDE = "准确识别专业缩写，注意区分同形缩写的不同含义，避免与人名混淆"
    
    # 注释：TYPE_SPECIFIC_GUIDES 已经在上面定义，不需要重复引用
    
    # 场景类型关键词映射
    SCENE_TYPE_KEYWORDS = {
        "action": ["fight", "chase", "explosion", "gun", "battle", "attack", "weapon", "combat", "shoot", "bomb", "punch", "kick", "blast", "fire", "bullet", "sword", "knife", "missile", "grenade", "assassin", "warrior", "martial", "ambush", "raid"],
        "comedy": ["funny", "laugh", "joke", "humor", "comedy", "hilarious", "amusing", "witty", "prank", "silly", "ridiculous", "gag", "parody", "sarcasm", "clown", "comedian", "sitcom", "slapstick", "satire", "irony", "giggle", "chuckle"],
        "drama": ["family", "life", "emotion", "relationship", "society", "human", "story", "feeling", "cry", "tears", "struggle", "conflict", "tragedy", "sorrow", "grief", "pain", "suffering", "divorce", "argument", "regret", "reconciliation", "forgiveness", "betrayal", "sacrifice"],
        "horror": ["scary", "fear", "ghost", "monster", "nightmare", "terror", "scream", "blood", "death", "kill", "murder", "evil", "demon", "zombie", "vampire", "witch", "curse", "haunted", "creepy", "spine", "chill", "dark", "shadow", "grave"],
        "romance": ["love", "heart", "kiss", "romantic", "date", "couple", "wedding", "marriage", "boyfriend", "girlfriend", "husband", "wife", "valentine", "flower", "sweet", "tender", "passion", "affection", "intimate", "soul", "forever", "together", "beautiful", "gorgeous"],
        "thriller": ["suspense", "mystery", "danger", "chase", "escape", "hide", "secret", "conspiracy", "betrayal", "trap", "hunt", "pursue", "follow", "watch", "spy", "agent", "mission", "target", "eliminate", "survive", "threat", "risk", "edge", "tension"],
        "sci-fi": ["space", "alien", "robot", "future", "technology", "science", "experiment", "laboratory", "computer", "artificial", "intelligence", "machine", "cyber", "virtual", "digital", "quantum", "genetic", "clone", "mutation", "evolution", "planet", "galaxy", "universe", "dimension"],
        "hospital": ["doctor", "nurse", "patient", "hospital", "medical", "surgery", "operation", "medicine", "treatment", "diagnosis", "emergency", "ambulance", "clinic", "ward", "injection", "prescription", "therapy", "recovery", "health", "disease", "illness", "symptom", "cure", "heal"],
        "school": ["student", "teacher", "school", "class", "lesson", "homework", "exam", "test", "grade", "study", "learn", "education", "university", "college", "campus", "library", "textbook", "professor", "lecture", "assignment", "graduation", "degree", "scholarship", "dormitory"],
        "military": ["soldier", "army", "war", "battle", "fight", "weapon", "gun", "tank", "missile", "bomb", "military", "commander", "officer", "sergeant", "captain", "general", "base", "camp", "mission", "operation", "strategy", "tactics", "enemy", "ally"],
        "superhero": ["hero", "power", "super", "ability", "strength", "speed", "fly", "save", "rescue", "villain", "evil", "justice", "protect", "defend", "cape", "mask", "costume", "secret", "identity", "mission", "world", "city", "people", "innocent", "telepathy", "telekinesis", "psychic", "mental", "mind", "tk", "tp", "institute", "experiment", "subject", "test", "recruit", "enhanced", "gifted", "special", "phenomenon"],
        "space": ["space", "planet", "star", "galaxy", "universe", "earth", "moon", "sun", "rocket", "spacecraft", "astronaut", "orbit", "gravity", "atmosphere", "alien", "cosmic", "solar", "lunar", "satellite", "mission", "exploration", "discovery", "void", "infinity"],
        "fantasy": ["magic", "wizard", "witch", "spell", "potion", "dragon", "fairy", "elf", "dwarf", "kingdom", "castle", "sword", "quest", "adventure", "treasure", "legend", "myth", "enchanted", "mystical", "supernatural", "creature", "beast", "prophecy", "destiny"],
        "crime": ["police", "detective", "crime", "criminal", "thief", "robbery", "murder", "investigation", "evidence", "suspect", "arrest", "prison", "jail", "court", "judge", "lawyer", "trial", "guilty", "innocent", "witness", "victim", "case", "law", "justice"],
        "documentary": ["documentary", "real", "true", "fact", "history", "research", "study", "interview", "expert", "scientist", "professor", "analysis", "data", "evidence", "proof", "investigation", "discovery", "nature", "wildlife", "environment", "culture", "society", "people", "world"],
        "war": ["war", "battle", "soldier", "army", "fight", "enemy", "ally", "victory", "defeat", "peace", "conflict", "invasion", "defense", "attack", "strategy", "tactics", "commander", "general", "troops", "casualties", "sacrifice", "honor", "courage", "bravery"],
        "western": ["cowboy", "sheriff", "outlaw", "horse", "ranch", "desert", "saloon", "gun", "duel", "frontier", "wild", "west", "town", "gold", "mine", "train", "robbery", "bandit", "justice", "law", "order", "settlement", "pioneer", "cattle"],
        "musical": ["music", "song", "sing", "dance", "musical", "theater", "stage", "performance", "artist", "musician", "singer", "dancer", "orchestra", "band", "instrument", "melody", "rhythm", "harmony", "lyrics", "chorus", "verse", "concert", "show", "audience"],
        "sport": ["sport", "game", "team", "player", "coach", "match", "competition", "championship", "victory", "defeat", "win", "lose", "score", "goal", "point", "training", "practice", "athlete", "fitness", "exercise", "stadium", "field", "court", "track"],
        "biography": ["life", "born", "childhood", "family", "career", "achievement", "success", "failure", "struggle", "dream", "ambition", "talent", "skill", "experience", "memory", "past", "present", "future", "legacy", "influence", "impact", "contribution", "history", "story"],
        "history": ["history", "historical", "past", "ancient", "century", "year", "era", "period", "empire", "kingdom", "civilization", "culture", "tradition", "heritage", "ancestor", "generation", "event", "revolution", "discovery", "invention", "progress", "development", "change", "evolution"],
        "medical": ["medical", "health", "disease", "illness", "treatment", "cure", "medicine", "drug", "therapy", "surgery", "operation", "diagnosis", "symptom", "patient", "doctor", "nurse", "hospital", "clinic", "emergency", "recovery", "healing", "prevention", "research", "science"],
        "legal": ["legal", "law", "court", "judge", "lawyer", "attorney", "trial", "case", "evidence", "witness", "testimony", "verdict", "guilty", "innocent", "justice", "rights", "constitution", "contract", "agreement", "dispute", "settlement", "appeal", "prosecution", "defense"],
        "political": ["political", "politics", "government", "president", "minister", "senator", "congress", "parliament", "election", "vote", "campaign", "party", "policy", "law", "reform", "democracy", "republic", "citizen", "public", "nation", "country", "state", "power", "authority"]
    }
    
    # 语言检测关键词
    LANGUAGE_DETECTION_KEYWORDS = {
        'spanish': [
            r'\b(el|la|los|las|un|una|de|del|en|con|por|para|que|es|son|está|están|tiene|tienen|muy|más|pero|como|cuando|donde|porque|también|siempre|nunca|todo|todos|nada|algo|alguien|nadie|aquí|allí|ahora|después|antes|durante|desde|hasta|entre|sobre|bajo|dentro|fuera|cerca|lejos|grande|pequeño|bueno|malo|nuevo|viejo|joven|mayor|mejor|peor|mucho|poco|bastante|demasiado|sí|no|tal|vez|quizás|seguro|cierto|verdad|mentira|amor|vida|muerte|tiempo|día|noche|casa|trabajo|dinero|agua|comida|familia|amigo|hermano|hermana|padre|madre|hijo|hija|hombre|mujer|niño|niña|gente|persona|mundo|país|ciudad|calle|coche|tren|avión|barco|libro|película|música|canción|color|blanco|negro|rojo|azul|verde|amarillo|naranja|rosa|morado|gris|marrón)\b',
            r'\b(hola|adiós|gracias|por favor|perdón|disculpe|buenos días|buenas tardes|buenas noches|hasta luego|hasta mañana|nos vemos|cuánto cuesta|dónde está|cómo estás|me llamo|mucho gusto|encantado|de nada|lo siento|no entiendo|habla más despacio|repita por favor|no hablo español|habla inglés|ayuda|emergencia|policía|hospital|médico|farmacia|hotel|restaurante|banco|supermercado|estación|aeropuerto|taxi|autobús|metro|izquierda|derecha|todo recto|arriba|abajo|entrada|salida|abierto|cerrado|caliente|frío|grande|pequeño|caro|barato|rápido|lento|fácil|difícil|cerca|lejos|aquí|allí|ahora|después|mañana|ayer|hoy|semana|mes|año|lunes|martes|miércoles|jueves|viernes|sábado|domingo|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b'
        ],
        'french': [
            r'\b(le|la|les|un|une|de|du|des|en|dans|sur|avec|pour|par|que|qui|est|sont|être|avoir|faire|aller|venir|voir|savoir|pouvoir|vouloir|devoir|dire|donner|prendre|mettre|partir|sortir|entrer|monter|descendre|rester|devenir|très|plus|moins|bien|mal|bon|mauvais|grand|petit|nouveau|vieux|jeune|beau|joli|noir|blanc|rouge|bleu|vert|jaune|orange|rose|violet|gris|marron|oui|non|peut-être|toujours|jamais|souvent|parfois|maintenant|hier|demain|aujourd\'hui|temps|jour|nuit|matin|midi|soir|semaine|mois|année|maison|travail|argent|eau|nourriture|famille|ami|frère|sœur|père|mère|fils|fille|homme|femme|enfant|gens|personne|monde|pays|ville|rue|voiture|train|avion|bateau|livre|film|musique|chanson|couleur)\b',
            r'\b(bonjour|bonsoir|salut|au revoir|à bientôt|merci|s\'il vous plaît|excusez-moi|pardon|comment allez-vous|ça va|je m\'appelle|enchanté|de rien|je suis désolé|je ne comprends pas|parlez plus lentement|répétez s\'il vous plaît|je ne parle pas français|parlez-vous anglais|aide|urgence|police|hôpital|médecin|pharmacie|hôtel|restaurant|banque|supermarché|gare|aéroport|taxi|bus|métro|gauche|droite|tout droit|en haut|en bas|entrée|sortie|ouvert|fermé|chaud|froid|grand|petit|cher|pas cher|rapide|lent|facile|difficile|près|loin|ici|là|maintenant|après|demain|hier|aujourd\'hui|semaine|mois|année|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\b'
        ],
        'german': [
            r'\b(der|die|das|ein|eine|und|oder|aber|denn|wenn|weil|dass|mit|von|zu|in|an|auf|für|durch|über|unter|vor|nach|bei|seit|bis|ohne|gegen|um|ich|du|er|sie|es|wir|ihr|sie|mein|dein|sein|ihr|unser|euer|dieser|diese|dieses|jener|jene|jenes|welcher|welche|welches|alle|einige|viele|wenige|mehr|weniger|gut|schlecht|groß|klein|neu|alt|jung|schön|hässlich|schwarz|weiß|rot|blau|grün|gelb|orange|rosa|lila|grau|braun|ja|nein|vielleicht|immer|nie|oft|manchmal|jetzt|gestern|morgen|heute|Zeit|Tag|Nacht|Morgen|Mittag|Abend|Woche|Monat|Jahr|Haus|Arbeit|Geld|Wasser|Essen|Familie|Freund|Bruder|Schwester|Vater|Mutter|Sohn|Tochter|Mann|Frau|Kind|Leute|Person|Welt|Land|Stadt|Straße|Auto|Zug|Flugzeug|Schiff|Buch|Film|Musik|Lied|Farbe)\b',
            r'\b(hallo|auf wiedersehen|tschüss|danke|bitte|entschuldigung|wie geht es ihnen|mir geht es gut|ich heiße|freut mich|bitte schön|es tut mir leid|ich verstehe nicht|sprechen sie langsamer|wiederholen sie bitte|ich spreche kein deutsch|sprechen sie englisch|hilfe|notfall|polizei|krankenhaus|arzt|apotheke|hotel|restaurant|bank|supermarkt|bahnhof|flughafen|taxi|bus|u-bahn|links|rechts|geradeaus|oben|unten|eingang|ausgang|offen|geschlossen|heiß|kalt|groß|klein|teuer|billig|schnell|langsam|einfach|schwierig|nah|weit|hier|dort|jetzt|später|morgen|gestern|heute|woche|monat|jahr|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\b'
        ],
        'italian': [
            r'\b(il|la|lo|gli|le|un|una|di|da|in|con|su|per|tra|fra|che|chi|cosa|dove|quando|come|perché|quanto|quale|essere|avere|fare|dire|andare|stare|dare|sapere|vedere|dovere|potere|volere|venire|uscire|partire|entrare|salire|scendere|rimanere|diventare|molto|più|meno|bene|male|buono|cattivo|grande|piccolo|nuovo|vecchio|giovane|bello|brutto|nero|bianco|rosso|blu|verde|giallo|arancione|rosa|viola|grigio|marrone|sì|no|forse|sempre|mai|spesso|qualche volta|ora|ieri|domani|oggi|tempo|giorno|notte|mattina|mezzogiorno|sera|settimana|mese|anno|casa|lavoro|soldi|acqua|cibo|famiglia|amico|fratello|sorella|padre|madre|figlio|figlia|uomo|donna|bambino|gente|persona|mondo|paese|città|strada|macchina|treno|aereo|nave|libro|film|musica|canzone|colore)\b',
            r'\b(ciao|arrivederci|grazie|prego|scusi|come sta|sto bene|mi chiamo|piacere|prego|mi dispiace|non capisco|parli più lentamente|ripeta per favore|non parlo italiano|parla inglese|aiuto|emergenza|polizia|ospedale|medico|farmacia|hotel|ristorante|banca|supermercato|stazione|aeroporto|taxi|autobus|metropolitana|sinistra|destra|dritto|sopra|sotto|entrata|uscita|aperto|chiuso|caldo|freddo|grande|piccolo|caro|economico|veloce|lento|facile|difficile|vicino|lontano|qui|lì|ora|dopo|domani|ieri|oggi|settimana|mese|anno|lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica|gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\b'
        ],
        'portuguese': [
            r'\b(o|a|os|as|um|uma|de|da|do|das|dos|em|na|no|nas|nos|com|por|para|que|é|são|está|estão|tem|têm|muito|mais|menos|bem|mal|bom|mau|grande|pequeno|novo|velho|jovem|bonito|feio|preto|branco|vermelho|azul|verde|amarelo|laranja|rosa|roxo|cinza|marrom|sim|não|talvez|sempre|nunca|muitas vezes|às vezes|agora|ontem|amanhã|hoje|tempo|dia|noite|manhã|meio-dia|tarde|semana|mês|ano|casa|trabalho|dinheiro|água|comida|família|amigo|irmão|irmã|pai|mãe|filho|filha|homem|mulher|criança|pessoas|pessoa|mundo|país|cidade|rua|carro|trem|avião|barco|livro|filme|música|canção|cor)\b',
            r'\b(olá|tchau|obrigado|obrigada|por favor|desculpe|como está|estou bem|meu nome é|prazer|de nada|sinto muito|não entendo|fale mais devagar|repita por favor|não falo português|fala inglês|ajuda|emergência|polícia|hospital|médico|farmácia|hotel|restaurante|banco|supermercado|estação|aeroporto|táxi|ônibus|metrô|esquerda|direita|em frente|em cima|embaixo|entrada|saída|aberto|fechado|quente|frio|grande|pequeno|caro|barato|rápido|devagar|fácil|difícil|perto|longe|aqui|ali|agora|depois|amanhã|ontem|hoje|semana|mês|ano|segunda|terça|quarta|quinta|sexta|sábado|domingo|janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b'
        ],
        'turkish': [
            r'\b(bir|bu|şu|o|ben|sen|biz|siz|onlar|ve|veya|ama|çünkü|için|ile|den|dan|de|da|te|ta|ye|ya|re|ra|le|la|ne|na|me|ma|se|sa|ke|ka|ge|ga|çok|daha|en|iyi|kötü|büyük|küçük|yeni|eski|genç|güzel|çirkin|siyah|beyaz|kırmızı|mavi|yeşil|sarı|turuncu|pembe|mor|gri|kahverengi|evet|hayır|belki|her zaman|hiç|sık sık|bazen|şimdi|dün|yarın|bugün|zaman|gün|gece|sabah|öğle|akşam|hafta|ay|yıl|ev|iş|para|su|yemek|aile|arkadaş|kardeş|baba|anne|oğul|kız|adam|kadın|çocuk|insanlar|kişi|dünya|ülke|şehir|sokak|araba|tren|uçak|gemi|kitap|film|müzik|şarkı|renk)\b',
            r'\b(merhaba|hoşça kal|teşekkürler|lütfen|özür dilerim|nasılsınız|iyiyim|benim adım|memnun oldum|rica ederim|üzgünüm|anlamıyorum|daha yavaş konuşun|tekrar edin lütfen|türkçe bilmiyorum|ingilizce biliyor musunuz|yardım|acil durum|polis|hastane|doktor|eczane|otel|restoran|banka|süpermarket|istasyon|havaalanı|taksi|otobüs|metro|sol|sağ|düz|yukarı|aşağı|giriş|çıkış|açık|kapalı|sıcak|soğuk|büyük|küçük|pahalı|ucuz|hızlı|yavaş|kolay|zor|yakın|uzak|burada|orada|şimdi|sonra|yarın|dün|bugün|hafta|ay|yıl|pazartesi|salı|çarşamba|perşembe|cuma|cumartesi|pazar|ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\b'
        ],
        'english': [
            r'\b(the|a|an|and|or|but|if|when|where|why|how|what|who|which|that|this|these|those|some|any|all|no|not|very|more|most|good|bad|big|small|new|old|young|beautiful|ugly|black|white|red|blue|green|yellow|orange|pink|purple|gray|brown|yes|no|maybe|always|never|often|sometimes|now|yesterday|tomorrow|today|time|day|night|morning|noon|evening|week|month|year|house|work|money|water|food|family|friend|brother|sister|father|mother|son|daughter|man|woman|child|people|person|world|country|city|street|car|train|plane|ship|book|movie|music|song|color)\b',
            r'\b(hello|goodbye|thank|please|sorry|excuse|how are you|i am fine|my name is|nice to meet you|you are welcome|i am sorry|i do not understand|speak slowly|repeat please|i do not speak english|do you speak|help|emergency|police|hospital|doctor|pharmacy|hotel|restaurant|bank|supermarket|station|airport|taxi|bus|subway|left|right|straight|up|down|entrance|exit|open|closed|hot|cold|big|small|expensive|cheap|fast|slow|easy|difficult|near|far|here|there|now|later|tomorrow|yesterday|today|week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)\b'
        ]
    }
    
    @classmethod
    def get_dual_language_prompt(cls, source_lang: str, text: str) -> str:
        """获取双语翻译提示词"""
        return cls.DUAL_LANGUAGE_PROMPT_TEMPLATE.format(
            source_lang=source_lang,
            text=text
        )
    
    @classmethod
    def get_genre_guide(cls, genres: List[str]) -> str:
        """获取影片类型特定指导"""
        if not genres:
            return ""
        
        guides = []
        for genre in genres:
            genre_lower = genre.lower()
            if genre_lower in cls.GENRE_SPECIFIC_GUIDES:
                guides.append(cls.GENRE_SPECIFIC_GUIDES[genre_lower])
        
        if guides:
            return f"类型特定指导：{'; '.join(guides)}"
        
        return ""
    
    # 音乐翻译提示词模板
    MUSIC_TRANSLATION_PROMPT_TEMPLATE = """请将以下字幕歌词翻译成简洁自然的中文，严格遵守：
- 只输出纯中文翻译
- 保留原有的音乐符号（如 ♪♫♬♩）和括号格式
- 不要添加任何解释、注释、角色说明或段落标题
- 不要输出"翻译"、"结果"等标记
待翻译内容：{text}"""
    
    # 简单翻译提示词模板
    SIMPLE_TRANSLATION_PROMPT_TEMPLATE = "只输出中文翻译：{text}"
    
    # 简单双语翻译提示词模板
    SIMPLE_DUAL_TRANSLATION_PROMPT_TEMPLATE = """请将以下内容翻译成中文和英文双语字幕：

{text}

双语字幕："""
    
    # 批量翻译提示词模板
    BATCH_TRANSLATION_PROMPT_TEMPLATE = """请将以下编号的字幕翻译为{target_language}，保持编号格式，每行一个翻译结果：

{batch_text}

要求：
1. 保持原有编号格式
2. 翻译要简洁准确
3. 符合字幕规范
4. 每行对应一个翻译结果"""

    @staticmethod
    def get_music_translation_prompt(text: str) -> str:
        """获取音乐翻译提示词"""
        return PromptTemplates.MUSIC_TRANSLATION_PROMPT_TEMPLATE.format(text=text)
    
    @staticmethod
    def get_simple_translation_prompt(text: str) -> str:
        """获取简单翻译提示词"""
        return PromptTemplates.SIMPLE_TRANSLATION_PROMPT_TEMPLATE.format(text=text)
    
    @staticmethod
    def get_simple_dual_translation_prompt(text: str) -> str:
        """获取简单双语翻译提示词"""
        return PromptTemplates.SIMPLE_DUAL_TRANSLATION_PROMPT_TEMPLATE.format(text=text)
    
    @staticmethod
    def get_batch_translation_prompt(target_language: str, batch_text: str) -> str:
        """获取批量翻译提示词"""
        return PromptTemplates.BATCH_TRANSLATION_PROMPT_TEMPLATE.format(
            target_language=target_language, 
            batch_text=batch_text
        )

    @staticmethod
    def get_language_detection_keywords():
        """获取语言检测关键词"""
        return PromptTemplates.LANGUAGE_DETECTION_KEYWORDS

    @classmethod
    def get_type_specific_guide(cls, types: List[str]) -> str:
        """获取类型特定的翻译指导"""
        if not types:
            return ""
        
        guides = []
        for type_name in types:
            type_lower = type_name.lower()
            if type_lower in cls.TYPE_SPECIFIC_GUIDES:
                guides.append(cls.TYPE_SPECIFIC_GUIDES[type_lower])
        
        if guides:
            return f"类型特定指导：{'; '.join(guides)}"
        return ""
    
    @classmethod
    def build_translation_prompt(
        cls,
        preprocessed_text: str,
        movie_context=None,
        scene_types: Optional[List[str]] = None,
        abbreviation_rules: Optional[str] = None,
        extra_rules: Optional[List[str]] = None,
        batch_mode: bool = False
    ) -> str:
        """构建翻译提示词"""
        prompt_parts = []
        
        # 基础通用提示词
        prompt_parts.append(cls.BASE_TRANSLATION_PROMPT)
        
        # 统一的类型适配模块
        all_types = []
        
        # 收集影片类型
        if movie_context and hasattr(movie_context, "genre") and movie_context.genre:
            if isinstance(movie_context.genre, list):
                all_types.extend(movie_context.genre)
                prompt_parts.append(f"影片类型：{', '.join(movie_context.genre)}")
            else:
                all_types.append(movie_context.genre)
                prompt_parts.append(f"影片类型：{movie_context.genre}")
        
        # 收集场景类型
        if scene_types:
            all_types.extend(scene_types)
            prompt_parts.append(f"场景类型：{', '.join(scene_types)}")
        
        # 添加统一的类型特定翻译指导
        if all_types:
            type_guide = cls.get_type_specific_guide(all_types)
            if type_guide:
                prompt_parts.append(type_guide)
        
        # 缩写/术语处理规则
        if abbreviation_rules:
            prompt_parts.append(f"缩写与术语处理规则：{abbreviation_rules}")
        
        # 内容长度与批量优化
        if batch_mode or (preprocessed_text and len(preprocessed_text) < 40):
            prompt_parts.append(cls.CONCISE_TRANSLATION_PROMPT)
        
        # 特殊内容处理
        if extra_rules:
            prompt_parts.extend(extra_rules)
        
        # 待翻译内容
        prompt_parts.append(f"待翻译内容：{preprocessed_text}")
        
        return "\n".join(prompt_parts)